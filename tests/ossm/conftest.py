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

import logging
import os
from typing import Dict

import pytest
from src.utils.config import get_settings

for _logger_name, _level in get_settings().logging.suppressed_loggers.items():
    logging.getLogger(_logger_name).setLevel(getattr(logging, _level.upper(), logging.WARNING))

from src.ocp_client.client import OCPClient
from src.utils.config import set_kubeconfig
from src.utils.logger import get_logger, log_test_end, log_test_start
from src.utils.test_reporting import ReportManager
from src.utils.ztwim_setup import ZTWIMSetupOrchestrator

from src.helpers.ossm import (
    OSSMHelper,
    OSSMScenarioConfig,
    SAIL_OPERATOR_NAMESPACE,
    SAIL_CHANNEL,
    SAIL_VERSION,
)

logger = get_logger("ossm.fixtures")
report_manager = ReportManager(
    workspace_dir=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    keep_latest=5,
)


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


