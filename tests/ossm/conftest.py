"""
OSSM + SPIRE integration test fixtures for single-cluster testing.

Validates the spire.adoc guide flow with PR #120 (auto-generated SDS config).
The ZTWIM operator with PR #120 eliminates CREATE_ONLY_MODE, manual SDS
ConfigMap patching, and create-only annotations entirely.

Required:
    - ZTWIM operator installed (operator-only) or bare cluster (bootstrap)
    - Framework installs Sail Operator + IstioCNI + Istio CR with SPIRE config

Usage:
    # Operator pre-installed (ZTWIM with PR #120):
    pytest tests/ossm/ -v --deployment-mode=operator-only --keep-deployed

    # Bare cluster (install everything):
    pytest tests/ossm/ -v --deployment-mode=bootstrap --keep-deployed
"""

import ast
import base64
import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

import pytest
from kubernetes.client import ApiException

from src.utils.config import get_settings

for _logger_name, _level in get_settings().logging.suppressed_loggers.items():
    logging.getLogger(_logger_name).setLevel(getattr(logging, _level.upper(), logging.WARNING))

from src.ocp_client.client import OCPClient
from src.ocp_client.spire_crds import (
    OperatorInstaller,
    ZTWIMStackDeployer,
    ZTWIMInstallationVerifier,
    ZTWIMFullInstaller,
)
from src.utils.config import set_kubeconfig
from src.utils.logger import get_logger, log_test_end, log_test_start
from src.utils.polling import wait_until
from src.utils.test_reporting import ReportManager
from src.utils.ztwim_setup import ZTWIMSetupOrchestrator

logger = get_logger("ossm.fixtures")
report_manager = ReportManager(
    workspace_dir=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    keep_latest=5,
)

SAIL_OPERATOR_NAMESPACE = "openshift-operators"
SAIL_SUBSCRIPTION_NAME = "sailoperator"
SAIL_PACKAGE_NAME = "sailoperator"
SAIL_CATALOG_SOURCE = "community-operators"
SAIL_CHANNEL = "stable"
SAIL_VERSION = "v1.30-latest"
OLM_SUBSCRIPTION_API = "operators.coreos.com/v1alpha1"


@dataclass(frozen=True)
class OSSMScenarioConfig:
    """Runtime OSSM scenario configuration."""

    ossm_namespace: str
    cni_namespace: str
    spiffe_audience: str
    httpbin_image: str
    curl_image: str
    ztwim_client_image: str
    sail_version: str = SAIL_VERSION


# =============================================================================
# CLI Options
# =============================================================================


def pytest_addoption(parser):
    """Add base and OSSM-specific CLI options."""
    parser.addoption("--kubeconfig", action="store", default=None, help="Path to kubeconfig file")
    parser.addoption(
        "--operator-namespace",
        action="store",
        default="zero-trust-workload-identity-manager",
        help="Namespace where ZTWIM operator is installed",
    )
    parser.addoption("--skip-cleanup", action="store_true", default=False, help="Skip cleanup")
    parser.addoption(
        "--deployment-mode",
        action="store",
        choices=["operator-only", "bootstrap"],
        default="operator-only",
        help="operator-only=operator must be present; bootstrap=install from scratch",
    )
    parser.addoption("--app-domain", action="store", default=None, help="OpenShift apps domain")
    parser.addoption("--cluster-name", action="store", default="test01", help="ZTWIM cluster name")
    parser.addoption(
        "--operator-timeout", action="store", type=int, default=300,
        help="Timeout for operator installation (seconds)",
    )
    parser.addoption(
        "--component-timeout", action="store", type=int, default=120,
        help="Timeout per component verification (seconds)",
    )
    parser.addoption(
        "--keep-deployed", "--keep-ztwim", dest="keep_deployed",
        action="store_true", default=False, help="Keep everything deployed after tests",
    )
    parser.addoption(
        "--cleanup-only-mode", "--cleanup-only", dest="cleanup_only_mode",
        action="store_true", default=False, help="Run cleanup and skip tests",
    )

    parser.addoption(
        "--use-existing-deployment", "--skip-install", dest="use_existing_deployment",
        action="store_true", default=False,
        help="(deprecated) Use --deployment-mode=operator-only instead",
    )
    parser.addoption(
        "--bootstrap-clusters", "--install-operator", dest="bootstrap_clusters",
        action="store_true", default=False,
        help="(deprecated) Use --deployment-mode=bootstrap instead",
    )

    group = parser.getgroup("ossm", "OSSM + SPIRE integration options")
    group.addoption(
        "--ossm-namespace", action="store", default="istio-system",
        help="Namespace where Istiod is deployed (default: istio-system)",
    )
    group.addoption(
        "--ossm-cni-namespace", action="store", default="istio-cni",
        help="Namespace for IstioCNI DaemonSet (default: istio-cni)",
    )
    group.addoption(
        "--spiffe-audience", action="store", default="sky-computing-demo",
        help="SPIFFE audience annotation for workloads",
    )
    group.addoption(
        "--ossm-timeout", action="store", type=int, default=300,
        help="Timeout for OSSM operations (seconds)",
    )
    group.addoption(
        "--httpbin-image", action="store",
        default="docker.io/mccutchen/go-httpbin:v2.15.0",
        help="Container image for httpbin workload",
    )
    group.addoption(
        "--curl-image", action="store",
        default="curlimages/curl:8.16.0",
        help="Container image for curl client workload",
    )
    group.addoption(
        "--ztwim-client-image", action="store",
        default="ghcr.io/spiffe/spire-agent:1.5.1",
        help="Container image for ZTWIM verification client",
    )
    group.addoption(
        "--skip-gateway-tests", action="store_true", default=False,
        help="Skip ingress gateway tests",
    )
    group.addoption(
        "--sail-channel", action="store", default=SAIL_CHANNEL,
        help="Sail Operator OLM channel (default: stable)",
    )
    group.addoption(
        "--sail-version", action="store", default=SAIL_VERSION,
        help=f"Istio/IstioCNI version for Sail CRs (default: {SAIL_VERSION})",
    )


# =============================================================================
# Report hooks and test hooks
# =============================================================================


def pytest_configure(config):
    """Configure HTML reporting and kubeconfig."""
    kubeconfig = config.getoption("--kubeconfig", default=None)
    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig
        logger.info(f"Using kubeconfig from CLI: {kubeconfig}")
    report_manager.configure(config)


def pytest_html_report_title(report):
    report.title = "ZTWIM OSSM+SPIRE Integration Tests - OpenShift"


@pytest.hookimpl(optionalhook=True)
def pytest_metadata(metadata):
    metadata.clear()
    try:
        from kubernetes import client, config as k8s_config
        kubeconfig = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config"))
        k8s_config.load_kube_config(config_file=kubeconfig)
        custom_api = client.CustomObjectsApi()
        cv = custom_api.get_cluster_custom_object(
            group="config.openshift.io", version="v1", plural="clusterversions", name="version",
        )
        metadata["OpenShift Version"] = cv.get("status", {}).get("desired", {}).get("version", "Unknown")
    except Exception as exc:
        logger.warning(f"Could not detect OpenShift version: {exc}")
        metadata["OpenShift Version"] = "Not detected"


def pytest_html_results_summary(prefix, summary, postfix):
    from datetime import datetime
    prefix.extend([
        '<div style="margin: 20px 0; padding: 24px; background: #FFFFFF; border-radius: 8px; border-left: 5px solid #CC0000;">',
        '<h2 style="margin: 0 0 8px 0; color: #000000; font-size: 24px;">ZTWIM OSSM+SPIRE Test Results</h2>',
        '<p style="margin: 0; color: #333333; font-size: 14px;">Single-cluster OSSM integration with SPIRE (PR #120)</p>',
        f'<p style="margin: 8px 0 0 0; color: #666666; font-size: 12px;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
        "</div>",
    ])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__) if item.function.__doc__ else ""
    markers = [marker.name for marker in item.iter_markers()]
    if markers:
        report.markers = ", ".join(markers)


def pytest_sessionfinish(session, exitstatus):
    report_manager.finalize(session.config)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "ossm" in str(item.fspath):
            item.add_marker(pytest.mark.ossm)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    log_test_start(item.name)


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    passed = item.rep_call.passed if hasattr(item, "rep_call") else True
    log_test_end(item.name, passed)


# =============================================================================
# Core session-scoped fixtures
# =============================================================================


@pytest.fixture(scope="session")
def kubeconfig_path(request) -> str:
    cli_kubeconfig = request.config.getoption("--kubeconfig")
    kubeconfig = set_kubeconfig(cli_kubeconfig)
    logger.info(f"Using kubeconfig: {kubeconfig}")
    return kubeconfig


@pytest.fixture(scope="session")
def ocp_client(kubeconfig_path) -> OCPClient:
    client = OCPClient(kubeconfig_path)
    try:
        cluster_info = client.get_cluster_info()
        logger.info(f"Connected to cluster: {cluster_info['git_version']}")
    except Exception as exc:
        logger.error(f"Failed to connect to cluster: {exc}")
        raise
    return client


@pytest.fixture(scope="session", autouse=True)
def ztwim_setup(request, ocp_client):
    """Session setup/teardown for ZTWIM/SPIRE stack."""
    orchestrator = ZTWIMSetupOrchestrator(ocp_client)
    options = orchestrator.from_pytest_request(request)
    orchestrator.run_setup(options)
    yield
    orchestrator.run_teardown(options)


@pytest.fixture(scope="session")
def operator_namespace(request) -> str:
    return request.config.getoption("--operator-namespace")


@pytest.fixture(scope="session")
def app_domain(request, ocp_client) -> str:
    cli_domain = request.config.getoption("--app-domain")
    if cli_domain:
        return cli_domain
    if os.environ.get("APP_DOMAIN"):
        return os.environ["APP_DOMAIN"]
    try:
        dns = ocp_client.custom_objects.get_cluster_custom_object(
            group="config.openshift.io", version="v1", plural="dnses", name="cluster",
        )
        base_domain = dns.get("spec", {}).get("baseDomain", "")
        domain = f"apps.{base_domain}"
        logger.info(f"Auto-detected APP_DOMAIN: {domain}")
        return domain
    except Exception as exc:
        pytest.fail(f"Failed to determine APP_DOMAIN: {exc}")


@pytest.fixture(scope="session")
def skip_cleanup(request) -> bool:
    return request.config.getoption("--skip-cleanup")


# =============================================================================
# OSSM module-scoped fixtures
# =============================================================================


@pytest.fixture(scope="module")
def ossm_namespace(request) -> str:
    return request.config.getoption("--ossm-namespace")


@pytest.fixture(scope="module")
def cni_namespace(request) -> str:
    return request.config.getoption("--ossm-cni-namespace")


@pytest.fixture(scope="module")
def trust_domain(app_domain) -> str:
    return app_domain


@pytest.fixture(scope="module")
def ossm_timeout(request) -> int:
    return request.config.getoption("--ossm-timeout")


@pytest.fixture(scope="module")
def ossm_config(request) -> OSSMScenarioConfig:
    return OSSMScenarioConfig(
        ossm_namespace=request.config.getoption("--ossm-namespace"),
        cni_namespace=request.config.getoption("--ossm-cni-namespace"),
        spiffe_audience=request.config.getoption("--spiffe-audience"),
        httpbin_image=request.config.getoption("--httpbin-image"),
        curl_image=request.config.getoption("--curl-image"),
        ztwim_client_image=request.config.getoption("--ztwim-client-image"),
        sail_version=request.config.getoption("--sail-version"),
    )


@pytest.fixture(scope="module")
def ossm_helper(ocp_client, operator_namespace, ossm_config) -> "OSSMHelper":
    return OSSMHelper(
        client=ocp_client,
        operator_namespace=operator_namespace,
        ossm_namespace=ossm_config.ossm_namespace,
        cni_namespace=ossm_config.cni_namespace,
        config=ossm_config,
    )


# =============================================================================
# Auto-deploy: Sail Operator + IstioCNI + Istio CR
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def ensure_ossm_stack_deployed(
    request, ocp_client, app_domain, operator_namespace, ossm_config, ossm_timeout,
):
    """
    Install Sail Operator + deploy IstioCNI + Istio CR with SPIRE config.
    Framework handles the FULL Sail stack regardless of deployment mode.
    """
    keep_deployed = request.config.getoption("keep_deployed")
    cleanup_only = request.config.getoption("cleanup_only_mode")
    sail_channel = request.config.getoption("--sail-channel")

    helper = OSSMHelper(
        client=ocp_client,
        operator_namespace=operator_namespace,
        ossm_namespace=ossm_config.ossm_namespace,
        cni_namespace=ossm_config.cni_namespace,
        config=ossm_config,
    )

    if cleanup_only:
        logger.info("")
        logger.info("=" * 60)
        logger.info("CLEANUP-ONLY MODE: Removing OSSM resources")
        logger.info("=" * 60)
        helper.delete_istio_cr()
        helper.delete_istio_cni()
        _cleanup_ossm_test_namespaces(ocp_client)
        helper.uninstall_sail_operator()
        logger.info("OSSM cleanup complete")
        pytest.skip("Cleanup-only mode: OSSM resources removed, skipping tests")

    logger.info("")
    logger.info("=" * 60)
    logger.info("DEPLOYING OSSM STACK (Sail Operator + IstioCNI + Istio CR)")
    logger.info("=" * 60)

    if not helper.is_sail_operator_installed():
        logger.info("Sail Operator not found, installing via OLM...")
        helper.install_sail_operator(channel=sail_channel, timeout=ossm_timeout)
    else:
        logger.info("Sail Operator already installed")
    helper.wait_for_sail_operator_ready(timeout=ossm_timeout)

    if not helper.is_istio_cni_deployed():
        logger.info("Deploying IstioCNI CR...")
        helper.deploy_istio_cni(timeout=ossm_timeout)
    else:
        logger.info("IstioCNI already deployed")
    helper.wait_for_istio_cni_ready(timeout=ossm_timeout)

    trust_domain = app_domain
    if not helper.is_istio_deployed():
        logger.info("Deploying Istio CR with SPIRE config...")
        helper.deploy_istio_cr(trust_domain=trust_domain, timeout=ossm_timeout)
    else:
        logger.info("Istio CR already deployed, patching with SPIRE config...")
        helper.deploy_istio_cr(trust_domain=trust_domain, timeout=ossm_timeout)
    helper.wait_for_istiod_ready(timeout=ossm_timeout)

    logger.info("")
    logger.info("OSSM stack ready")
    logger.info("=" * 60)

    yield

    if keep_deployed:
        logger.info("Keeping OSSM deployed (--keep-deployed set)")
        return

    logger.info("Cleaning up OSSM stack...")
    helper.delete_istio_cr()
    helper.delete_istio_cni()
    _cleanup_ossm_test_namespaces(ocp_client)
    helper.uninstall_sail_operator()


def _cleanup_ossm_test_namespaces(client: OCPClient):
    """Delete leftover OSSM test namespaces."""
    prefixes = ("verify-ossm-", "test-ossm-")
    try:
        all_ns = client.core_v1.list_namespace()
        for ns in all_ns.items:
            name = ns.metadata.name
            if any(name.startswith(p) for p in prefixes):
                try:
                    client.delete_namespace(name, wait=False)
                    logger.info(f"Deleted test namespace: {name}")
                except Exception as e:
                    logger.debug(f"Failed to delete namespace {name}: {e}")
    except Exception:
        pass


# =============================================================================
# OSSMHelper
# =============================================================================


class OSSMHelper:
    """
    Encapsulates OSSM + SPIRE operations for single-cluster testing.

    Manages:
    - Sail Operator lifecycle (install/uninstall via OLM)
    - IstioCNI + Istio CR creation with SPIRE config
    - SDS config verification and destructive operations
    - Workload deployments (ztwim-client, httpbin, curl)
    - mTLS policy application
    - Data plane resilience operations
    """

    def __init__(
        self,
        client: OCPClient,
        operator_namespace: str,
        ossm_namespace: str,
        cni_namespace: str,
        config: OSSMScenarioConfig,
    ):
        self.client = client
        self.operator_namespace = operator_namespace
        self.ossm_namespace = ossm_namespace
        self.cni_namespace = cni_namespace
        self.config = config

    # ── Sail Operator lifecycle ─────────────────────────────────────────

    def is_sail_operator_installed(self) -> bool:
        try:
            resource = self.client.get_crd_resource(OLM_SUBSCRIPTION_API, "Subscription")
            subs = resource.get(namespace=SAIL_OPERATOR_NAMESPACE)
            for item in subs.get("items", []):
                if SAIL_PACKAGE_NAME in item.get("spec", {}).get("name", ""):
                    return True
        except Exception:
            pass
        return False

    def install_sail_operator(self, channel: str = SAIL_CHANNEL, timeout: int = 300) -> None:
        sub_body = {
            "apiVersion": OLM_SUBSCRIPTION_API,
            "kind": "Subscription",
            "metadata": {
                "name": SAIL_SUBSCRIPTION_NAME,
                "namespace": SAIL_OPERATOR_NAMESPACE,
            },
            "spec": {
                "channel": channel,
                "installPlanApproval": "Automatic",
                "name": SAIL_PACKAGE_NAME,
                "source": SAIL_CATALOG_SOURCE,
                "sourceNamespace": "openshift-marketplace",
            },
        }
        try:
            resource = self.client.get_crd_resource(OLM_SUBSCRIPTION_API, "Subscription")
            resource.create(body=sub_body, namespace=SAIL_OPERATOR_NAMESPACE)
            logger.info(f"Created Sail Operator Subscription (channel: {channel})")
        except ApiException as e:
            if e.status == 409:
                logger.info("Sail Operator Subscription already exists")
            else:
                raise

    def wait_for_sail_operator_ready(self, timeout: int = 300) -> None:
        cfg = get_settings().polling.operator

        def _check():
            try:
                csv_resource = self.client.get_crd_resource(OLM_SUBSCRIPTION_API, "ClusterServiceVersion")
                csvs = csv_resource.get(namespace=SAIL_OPERATOR_NAMESPACE)
                for item in csvs.get("items", []):
                    name = item["metadata"]["name"]
                    phase = item.get("status", {}).get("phase", "")
                    if "sail" in name.lower() and phase == "Succeeded":
                        logger.info(f"Sail CSV ready: {name} (phase={phase})")
                        return True
                return False
            except Exception as e:
                logger.warning(f"Sail Operator readiness check failed: {e}")
                return False

        result = wait_until(
            _check,
            message="Sail Operator CSV ready",
            timeout=timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        if not result.success:
            raise TimeoutError(f"Sail Operator not ready within {timeout}s")
        logger.info("Sail Operator is ready")

    def uninstall_sail_operator(self) -> None:
        try:
            resource = self.client.get_crd_resource(OLM_SUBSCRIPTION_API, "Subscription")
            resource.delete(name=SAIL_SUBSCRIPTION_NAME, namespace=SAIL_OPERATOR_NAMESPACE)
            logger.info("Deleted Sail Operator Subscription")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete Sail Operator Subscription: {e.reason}")
        except Exception as e:
            logger.warning(f"Failed to delete Sail Operator Subscription: {e}")

        try:
            csv_resource = self.client.get_crd_resource(OLM_SUBSCRIPTION_API, "ClusterServiceVersion")
            csvs = csv_resource.get(namespace=SAIL_OPERATOR_NAMESPACE)
            for item in csvs.get("items", []):
                name = item["metadata"]["name"]
                if "sail" in name.lower():
                    csv_resource.delete(name=name, namespace=SAIL_OPERATOR_NAMESPACE)
                    logger.info(f"Deleted Sail CSV: {name}")
        except Exception as e:
            logger.debug(f"CSV cleanup: {e}")

    # ── IstioCNI CR lifecycle ───────────────────────────────────────────

    def is_istio_cni_deployed(self) -> bool:
        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "IstioCNI")
            result = resource.get(name="default")
            return result is not None
        except Exception:
            return False

    def deploy_istio_cni(self, timeout: int = 300) -> Dict[str, Any]:
        self.client.create_namespace(name=self.cni_namespace)

        body = {
            "apiVersion": "sailoperator.io/v1",
            "kind": "IstioCNI",
            "metadata": {"name": "default"},
            "spec": {
                "namespace": self.cni_namespace,
                "version": self.config.sail_version,
            },
        }
        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "IstioCNI")
            result = resource.create(body=body)
            logger.info("Created IstioCNI CR")
            return result.to_dict()
        except ApiException as e:
            if e.status == 409:
                logger.info("IstioCNI CR already exists")
                return {}
            raise

    def wait_for_istio_cni_ready(self, timeout: int = 300) -> List[Dict]:
        cfg = get_settings().polling.pod_readiness
        pods = self.client.wait_for_pods_ready(
            namespace=self.cni_namespace,
            label_selector="k8s-app=istio-cni-node",
            expected_count=1,
            timeout=timeout,
        )
        logger.info(f"IstioCNI ready: {len(pods)} pod(s)")
        return pods

    def delete_istio_cni(self) -> None:
        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "IstioCNI")
            resource.delete(name="default")
            logger.info("Deleted IstioCNI CR")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete IstioCNI: {e.reason}")
        except Exception as e:
            logger.debug(f"IstioCNI delete: {e}")

    # ── Istio CR lifecycle ──────────────────────────────────────────────

    def is_istio_deployed(self) -> bool:
        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "Istio")
            result = resource.get(name="default")
            return result is not None
        except Exception:
            return False

    def get_oidc_serving_cert(self) -> str:
        secret = self.client.core_v1.read_namespaced_secret(
            name="oidc-serving-cert", namespace=self.operator_namespace,
        )
        cert_b64 = secret.data.get("tls.crt", "")
        return base64.b64decode(cert_b64).decode("utf-8")

    def deploy_istio_cr(self, trust_domain: str, timeout: int = 300) -> Dict[str, Any]:
        self.client.create_namespace(name=self.ossm_namespace)

        extra_root_ca = self.get_oidc_serving_cert()
        jwt_issuer = f"https://oidc-discovery.{trust_domain}"

        body = {
            "apiVersion": "sailoperator.io/v1",
            "kind": "Istio",
            "metadata": {"name": "default"},
            "spec": {
                "version": self.config.sail_version,
                "namespace": self.ossm_namespace,
                "updateStrategy": {"type": "InPlace"},
                "values": {
                    "pilot": {
                        "jwksResolverExtraRootCA": extra_root_ca,
                        "env": {
                            "PILOT_JWT_ENABLE_REMOTE_JWKS": "true",
                        },
                    },
                    "meshConfig": {
                        "trustDomain": trust_domain,
                        "defaultConfig": {
                            "proxyMetadata": {
                                "WORKLOAD_IDENTITY_SOCKET_FILE": "spire-agent.sock",
                            },
                        },
                    },
                    "sidecarInjectorWebhook": {
                        "templates": {
                            "spire": (
                                "spec:\n"
                                "  initContainers:\n"
                                "  - name: istio-proxy\n"
                                "    volumeMounts:\n"
                                "    - name: workload-socket\n"
                                "      mountPath: /run/secrets/workload-spiffe-uds\n"
                                "      readOnly: true\n"
                                "  volumes:\n"
                                "    - name: workload-socket\n"
                                "      csi:\n"
                                '        driver: "csi.spiffe.io"\n'
                                "        readOnly: true\n"
                            ),
                            "spireGateway": (
                                "spec:\n"
                                "  containers:\n"
                                "  - name: istio-proxy\n"
                                "    volumeMounts:\n"
                                "    - name: workload-socket\n"
                                "      mountPath: /run/secrets/workload-spiffe-uds\n"
                                "      readOnly: true\n"
                                "  volumes:\n"
                                "    - name: workload-socket\n"
                                "      csi:\n"
                                '        driver: "csi.spiffe.io"\n'
                                "        readOnly: true\n"
                            ),
                        },
                    },
                },
            },
        }

        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "Istio")
            try:
                existing = resource.get(name="default")
                result = resource.patch(
                    name="default",
                    body=body,
                    content_type="application/merge-patch+json",
                )
                logger.info("Patched Istio CR with SPIRE config")
                return result.to_dict()
            except ApiException as e:
                if e.status == 404:
                    result = resource.create(body=body)
                    logger.info("Created Istio CR with SPIRE config")
                    return result.to_dict()
                raise
        except Exception as e:
            raise RuntimeError(f"Failed to deploy Istio CR: {e}")

    def wait_for_istiod_ready(self, timeout: int = 300) -> List[Dict]:
        pods = self.client.wait_for_pods_ready(
            namespace=self.ossm_namespace,
            label_selector="app=istiod",
            expected_count=1,
            timeout=timeout,
        )
        logger.info(f"Istiod ready: {pods[0]['metadata']['name']}")
        return pods

    def delete_istio_cr(self) -> None:
        try:
            resource = self.client.get_crd_resource("sailoperator.io/v1", "Istio")
            resource.delete(name="default")
            logger.info("Deleted Istio CR")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete Istio CR: {e.reason}")
        except Exception as e:
            logger.debug(f"Istio CR delete: {e}")

    # ── SDS config verification (PR #120) ───────────────────────────────

    def get_sds_config(self) -> Optional[Dict]:
        cm = self.client.core_v1.read_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace,
        )
        agent_conf_raw = cm.data.get("agent.conf", "")
        agent_conf = json.loads(agent_conf_raw)
        return agent_conf.get("agent", {}).get("sds")

    def delete_sds_from_configmap(self) -> None:
        cm = self.client.core_v1.read_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace,
        )
        agent_conf_raw = cm.data.get("agent.conf", "")
        agent_conf = json.loads(agent_conf_raw)
        if "sds" in agent_conf.get("agent", {}):
            del agent_conf["agent"]["sds"]
        patched = json.dumps(agent_conf)
        body = {"data": {"agent.conf": patched}}
        self.client.core_v1.patch_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace, body=body,
        )
        logger.info("Removed SDS section from spire-agent ConfigMap")

    def delete_spire_agent_configmap(self) -> None:
        self.client.core_v1.delete_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace,
        )
        logger.info("Deleted entire spire-agent ConfigMap")

    def corrupt_sds_config(self, values: Dict[str, str]) -> None:
        cm = self.client.core_v1.read_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace,
        )
        agent_conf_raw = cm.data.get("agent.conf", "")
        agent_conf = json.loads(agent_conf_raw)
        agent_conf.setdefault("agent", {})["sds"] = values
        patched = json.dumps(agent_conf)
        body = {"data": {"agent.conf": patched}}
        self.client.core_v1.patch_namespaced_config_map(
            name="spire-agent", namespace=self.operator_namespace, body=body,
        )
        logger.info(f"Corrupted SDS config to: {values}")

    # ── ZTWIM client verification ───────────────────────────────────────

    def deploy_ztwim_client(self, namespace: str = "default") -> None:
        body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "ztwim-client",
                "namespace": namespace,
                "labels": {"app": "ztwim-client"},
            },
            "spec": {
                "selector": {"matchLabels": {"app": "ztwim-client"}},
                "template": {
                    "metadata": {"labels": {"app": "ztwim-client"}},
                    "spec": {
                        "containers": [{
                            "name": "client",
                            "image": self.config.ztwim_client_image,
                            "command": ["/opt/spire/bin/spire-agent"],
                            "args": [
                                "api", "watch",
                                "-socketPath", "/run/spire/sockets/spire-agent.sock",
                            ],
                            "volumeMounts": [{
                                "mountPath": "/run/spire/sockets",
                                "name": "spiffe-workload-api",
                                "readOnly": True,
                            }],
                        }],
                        "volumes": [{
                            "name": "spiffe-workload-api",
                            "csi": {"driver": "csi.spiffe.io", "readOnly": True},
                        }],
                    },
                },
            },
        }
        self.client.apps_v1.create_namespaced_deployment(namespace=namespace, body=body)
        logger.info(f"Deployed ztwim-client in {namespace}")

    def delete_ztwim_client(self, namespace: str = "default") -> None:
        try:
            self.client.apps_v1.delete_namespaced_deployment(
                name="ztwim-client", namespace=namespace,
            )
            logger.info(f"Deleted ztwim-client from {namespace}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete ztwim-client: {e.reason}")

    def fetch_x509_svid(self, pod_name: str, namespace: str) -> str:
        return self.client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=namespace,
            command=[
                "/opt/spire/bin/spire-agent", "api", "fetch",
                "-socketPath", "/run/spire/sockets/spire-agent.sock",
            ],
            container="client",
        )

    def fetch_jwt_svid(self, pod_name: str, namespace: str, audience: str) -> str:
        return self.client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=namespace,
            command=[
                "/opt/spire/bin/spire-agent", "api", "fetch", "jwt",
                "-audience", audience,
                "-socketPath", "/run/spire/sockets/spire-agent.sock",
            ],
            container="client",
        )

    # ── Istio workload deployment ───────────────────────────────────────

    def deploy_httpbin(
        self,
        namespace: str,
        with_service: bool = False,
        service_account: Optional[str] = None,
    ) -> None:
        sa_name = service_account or "default"

        if service_account:
            from kubernetes import client as k8s_client
            sa_body = k8s_client.V1ServiceAccount(
                metadata=k8s_client.V1ObjectMeta(name=service_account, namespace=namespace)
            )
            try:
                self.client.core_v1.create_namespaced_service_account(
                    namespace=namespace, body=sa_body,
                )
            except ApiException as e:
                if e.status != 409:
                    raise

        if with_service:
            svc_body = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "httpbin", "namespace": namespace, "labels": {"app": "httpbin", "service": "httpbin"}},
                "spec": {
                    "ports": [
                        {"name": "http-ex-spiffe", "port": 443, "targetPort": 8080},
                        {"name": "http", "port": 80, "targetPort": 8080},
                    ],
                    "selector": {"app": "httpbin"},
                },
            }
            try:
                self.client.core_v1.create_namespaced_service(namespace=namespace, body=svc_body)
            except ApiException as e:
                if e.status != 409:
                    raise

        deploy_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "httpbin", "namespace": namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "httpbin", "version": "v1"}},
                "template": {
                    "metadata": {
                        "annotations": {
                            "inject.istio.io/templates": "sidecar,spire",
                            "spiffe.io/audience": self.config.spiffe_audience,
                        },
                        "labels": {"app": "httpbin", "version": "v1"},
                    },
                    "spec": {
                        "serviceAccountName": sa_name,
                        "containers": [{
                            "name": "httpbin",
                            "image": self.config.httpbin_image,
                            "imagePullPolicy": "IfNotPresent",
                            "ports": [{"containerPort": 8080}],
                        }],
                    },
                },
            },
        }

        try:
            self.client.apps_v1.create_namespaced_deployment(namespace=namespace, body=deploy_body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Deployed httpbin in {namespace}")

    def deploy_curl_client(
        self,
        namespace: str,
        service_account: Optional[str] = None,
    ) -> None:
        sa_name = service_account or "default"

        if service_account:
            from kubernetes import client as k8s_client
            sa_body = k8s_client.V1ServiceAccount(
                metadata=k8s_client.V1ObjectMeta(name=service_account, namespace=namespace)
            )
            try:
                self.client.core_v1.create_namespaced_service_account(
                    namespace=namespace, body=sa_body,
                )
            except ApiException as e:
                if e.status != 409:
                    raise

            svc_body = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "curl", "namespace": namespace, "labels": {"app": "curl", "service": "curl"}},
                "spec": {
                    "ports": [{"port": 80, "name": "http"}],
                    "selector": {"app": "curl"},
                },
            }
            try:
                self.client.core_v1.create_namespaced_service(namespace=namespace, body=svc_body)
            except ApiException as e:
                if e.status != 409:
                    raise

        deploy_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "curl", "namespace": namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "curl"}},
                "template": {
                    "metadata": {
                        "annotations": {
                            "inject.istio.io/templates": "sidecar,spire",
                            "spiffe.io/audience": self.config.spiffe_audience,
                        },
                        "labels": {"app": "curl"},
                    },
                    "spec": {
                        "terminationGracePeriodSeconds": 0,
                        "serviceAccountName": sa_name,
                        "containers": [{
                            "name": "curl",
                            "image": self.config.curl_image,
                            "command": ["/bin/sh", "-c", "sleep inf"],
                            "imagePullPolicy": "IfNotPresent",
                        }],
                    },
                },
            },
        }

        try:
            self.client.apps_v1.create_namespaced_deployment(namespace=namespace, body=deploy_body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Deployed curl client in {namespace}")

    # ── mTLS policies ───────────────────────────────────────────────────

    def apply_strict_mtls(self, namespace: str) -> None:
        pa_body = {
            "apiVersion": "security.istio.io/v1beta1",
            "kind": "PeerAuthentication",
            "metadata": {"name": "default", "namespace": namespace},
            "spec": {"mtls": {"mode": "STRICT"}},
        }
        resource = self.client.get_crd_resource("security.istio.io/v1beta1", "PeerAuthentication")
        resource.create(body=pa_body, namespace=namespace)
        logger.info(f"Applied STRICT PeerAuthentication in {namespace}")

    def apply_destination_rules(self, namespace: str, services: List[str]) -> None:
        resource = self.client.get_crd_resource("networking.istio.io/v1", "DestinationRule")
        for svc in services:
            dr_body = {
                "apiVersion": "networking.istio.io/v1",
                "kind": "DestinationRule",
                "metadata": {"name": svc, "namespace": namespace},
                "spec": {
                    "host": svc,
                    "trafficPolicy": {"tls": {"mode": "ISTIO_MUTUAL"}},
                },
            }
            resource.create(body=dr_body, namespace=namespace)
            logger.info(f"Applied ISTIO_MUTUAL DestinationRule for {svc} in {namespace}")

    # ── Destructive operations (resilience tests) ───────────────────────

    def delete_all_spire_agent_pods(self) -> int:
        pods = self.client.get_pods(
            namespace=self.operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
        )
        count = len(pods)
        for pod in pods:
            name = pod["metadata"]["name"]
            self.client.core_v1.delete_namespaced_pod(
                name=name, namespace=self.operator_namespace,
            )
        logger.info(f"Deleted {count} spire-agent pods")
        return count

    def delete_operator_pod(self) -> str:
        pods = self.client.get_pods(
            namespace=self.operator_namespace,
            label_selector="app.kubernetes.io/name=zero-trust-workload-identity-manager",
        )
        if not pods:
            pods = self.client.get_pods(
                namespace=self.operator_namespace,
                label_selector="name=zero-trust-workload-identity-manager",
            )
        if not pods:
            raise RuntimeError("No ZTWIM operator pod found")
        pod_name = pods[0]["metadata"]["name"]
        self.client.core_v1.delete_namespaced_pod(
            name=pod_name, namespace=self.operator_namespace,
        )
        logger.info(f"Deleted ZTWIM operator pod: {pod_name}")
        return pod_name

    def wait_for_spire_agents_recovered(self, expected_count: int, timeout: int = 120) -> List[Dict]:
        return self.client.wait_for_pods_ready(
            namespace=self.operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
            expected_count=expected_count,
            timeout=timeout,
        )

    def wait_for_operator_recovered(self, timeout: int = 120) -> List[Dict]:
        cfg = get_settings().polling.operator

        def _check():
            try:
                pods = self.client.get_pods(
                    namespace=self.operator_namespace,
                    label_selector="app.kubernetes.io/name=zero-trust-workload-identity-manager",
                )
                if not pods:
                    pods = self.client.get_pods(
                        namespace=self.operator_namespace,
                        label_selector="name=zero-trust-workload-identity-manager",
                    )
                running = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
                return running if running else None
            except Exception:
                return None

        result = wait_until(
            _check,
            message="ZTWIM operator pod recovered",
            timeout=timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        if not result.success:
            raise TimeoutError(f"Operator pod not recovered within {timeout}s")
        return result.value

    # ── Ingress gateway ─────────────────────────────────────────────────

    def install_ingress_gateway(self) -> None:
        subprocess.run(
            ["oc", "adm", "policy", "add-scc-to-user", "anyuid",
             f"system:serviceaccount:{self.ossm_namespace}:istio-gateway"],
            check=False, capture_output=True,
        )
        subprocess.run(["helm", "repo", "add", "istio",
                        "https://istio-release.storage.googleapis.com/charts"],
                       check=False, capture_output=True)
        subprocess.run(["helm", "repo", "update"], check=False, capture_output=True)

        result = subprocess.run(
            ["helm", "install", "istio-gateway", "-n", self.ossm_namespace,
             "istio/gateway", "--set-json",
             'podAnnotations={"inject.istio.io/templates":"gateway,spireGateway"}'],
            capture_output=True, text=True,
        )
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(f"Helm install failed: {result.stderr}")
        logger.info("Installed istio-gateway via helm")

    def uninstall_ingress_gateway(self) -> None:
        subprocess.run(
            ["helm", "uninstall", "istio-gateway", "-n", self.ossm_namespace],
            check=False, capture_output=True,
        )
        logger.info("Uninstalled istio-gateway")

    def create_gateway_cr(self, namespace: str, name: str = "httpbin-gateway") -> Dict:
        body = {
            "apiVersion": "networking.istio.io/v1",
            "kind": "Gateway",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "selector": {"istio": "gateway"},
                "servers": [{
                    "port": {"number": 80, "name": "http", "protocol": "HTTP"},
                    "hosts": ["*"],
                }],
            },
        }
        resource = self.client.get_crd_resource("networking.istio.io/v1", "Gateway")
        result = resource.create(body=body, namespace=namespace)
        logger.info(f"Created Gateway {name} in {namespace}")
        return result.to_dict()

    def create_virtual_service(
        self, namespace: str, name: str, gateway: str, destination_host: str, port: int = 80,
    ) -> Dict:
        body = {
            "apiVersion": "networking.istio.io/v1",
            "kind": "VirtualService",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "hosts": ["*"],
                "gateways": [gateway],
                "http": [{"route": [{"destination": {"host": destination_host, "port": {"number": port}}}]}],
            },
        }
        resource = self.client.get_crd_resource("networking.istio.io/v1", "VirtualService")
        result = resource.create(body=body, namespace=namespace)
        logger.info(f"Created VirtualService {name} in {namespace}")
        return result.to_dict()

    # ── Verification helpers ────────────────────────────────────────────

    @staticmethod
    def _parse_exec_json(output: str) -> Any:
        """Parse exec output that may be JSON or Python dict format.

        The kubernetes Python client stream() can return Python repr
        (single-quoted) instead of JSON (double-quoted) for certain
        container types (e.g. native sidecars).
        """
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return ast.literal_eval(output)

    def get_envoy_spiffe_id(self, pod_name: str, namespace: str) -> str:
        output = self.client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=namespace,
            command=["curl", "-s", "localhost:15000/certs"],
            container="istio-proxy",
        )
        certs = self._parse_exec_json(output)
        return certs["certificates"][0]["cert_chain"][0]["subject_alt_names"][0]["uri"]

    def get_envoy_cert_info(self, pod_name: str, namespace: str) -> Dict:
        output = self.client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=namespace,
            command=["curl", "-s", "localhost:15000/certs"],
            container="istio-proxy",
        )
        return self._parse_exec_json(output)

    def exec_curl(
        self, pod_name: str, namespace: str, url: str, extra_args: Optional[List[str]] = None,
    ) -> str:
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url]
        if extra_args:
            cmd.extend(extra_args)
        return self.client.exec_in_pod_with_retry(
            name=pod_name, namespace=namespace, command=cmd, container="curl",
        )

    def get_gateway_addresses(self) -> Dict[str, str]:
        svc = self.client.get_service("istio-gateway", self.ossm_namespace)
        cluster_ip = svc["spec"]["cluster_ip"]
        lb_hostname = ""
        ingress = svc.get("status", {}).get("load_balancer", {}).get("ingress", [])
        if ingress:
            lb_hostname = ingress[0].get("hostname", "") or ingress[0].get("ip", "")
        return {"cluster_ip": cluster_ip, "lb_hostname": lb_hostname}
