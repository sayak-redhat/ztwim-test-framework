"""
Federation test fixtures for multi-cluster SPIRE federation testing.

These fixtures provide a secondary OCP client and utilities for managing
the two-cluster federation workflow (https_spiffe profile).

Both clusters are expected to have the ZTWIM operator installed.
The SPIRE stack (operands) will be auto-deployed if not already present.

Required environment variables or CLI options:
    REMOTE_KUBECONFIG: Path to the kubeconfig for the remote (second) cluster
    REMOTE_APP_DOMAIN: (optional) Remote cluster's apps domain (auto-detected)

Usage:
    # Operator pre-installed on both clusters, operands auto-deployed:
    pytest tests/federation/ -v \
        --deployment-mode=operator-only \
        --remote-kubeconfig=/path/to/remote/kubeconfig

    # Bare clusters (install operator + operands):
    pytest tests/federation/ -v \
        --remote-kubeconfig=/path/to/remote/kubeconfig \
        --deployment-mode=bootstrap --keep-deployed
"""

import logging
import os
import json
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Any, Generator, Optional

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
from src.utils.polling import wait_until, PollConfig, DynamicPoller
from src.utils.test_reporting import ReportManager
from src.utils.ztwim_setup import ZTWIMSetupOrchestrator
from src.helpers.ossm import OSSMHelper, OSSMScenarioConfig
from src.helpers.ossm_federation import OSSMFederationHelper

logger = get_logger("federation.fixtures")
report_manager = ReportManager(
    workspace_dir=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    keep_latest=5,
)

FEDERATION_ROUTE_NAME = "spire-server-federation"
SPIRE_SERVER_POD_LABEL = "app.kubernetes.io/name=spire-server"
SPIFFE_API_VERSION = "spire.spiffe.io/v1alpha1"
ZTWIM_API_VERSION = "operator.openshift.io/v1alpha1"
SPIRE_CLASS_NAME = "zero-trust-workload-identity-manager-spire"


@dataclass(frozen=True)
class FederationScenarioConfig:
    """
    Runtime federation scenario configuration.

    This object centralizes tunables so tests can run against multiple
    federation configurations without changing test code.
    """

    profile: str
    managed_route: bool
    mtls_server_image: str
    mtls_client_image: str
    spiffe_helper_image: str

    def endpoint_spiffe_id(self, trust_domain: str) -> str:
        return f"spiffe://{trust_domain}/spire/server"

    def bundle_endpoint_url(self, app_domain: str) -> str:
        return f"https://federation.{app_domain}"


def pytest_addoption(parser):
    """Add base and federation-specific CLI options."""
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
        help=(
            "Cluster lifecycle mode: operator-only=operator must be present, "
            "deploy/repair operands; bootstrap=install operator+operands"
        ),
    )
    parser.addoption(
        "--use-existing-deployment",
        "--skip-install",
        dest="use_existing_deployment",
        action="store_true",
        default=False,
        help=(
            "Deprecated and no longer supported "
            "(legacy alias: --skip-install)"
        ),
    )
    parser.addoption("--app-domain", action="store", default=None, help="OpenShift apps domain")
    parser.addoption("--cluster-name", action="store", default="test01", help="ZTWIM cluster name")
    parser.addoption(
        "--operator-timeout",
        action="store",
        type=int,
        default=300,
        help="Timeout for operator installation (seconds)",
    )
    parser.addoption(
        "--component-timeout",
        action="store",
        type=int,
        default=120,
        help="Timeout per component verification (seconds)",
    )
    parser.addoption(
        "--keep-deployed",
        "--keep-ztwim",
        dest="keep_deployed",
        action="store_true",
        default=False,
        help="Keep operator/operands deployed after tests (legacy alias: --keep-ztwim)",
    )
    parser.addoption(
        "--cleanup-only-mode",
        "--cleanup-only",
        dest="cleanup_only_mode",
        action="store_true",
        default=False,
        help="Run cleanup and skip tests (legacy alias: --cleanup-only)",
    )

    group = parser.getgroup("federation", "SPIRE Federation options")
    group.addoption(
        "--remote-kubeconfig",
        action="store",
        default=None,
        help="Path to kubeconfig for the remote (second) cluster",
    )
    group.addoption(
        "--remote-app-domain",
        action="store",
        default=None,
        help="Remote cluster's apps domain (auto-detected if not set)",
    )
    group.addoption(
        "--federation-profile",
        action="store",
        default="https_spiffe",
        help="Federation bundle endpoint profile (default: https_spiffe)",
    )
    group.addoption(
        "--federation-managed-route",
        action="store",
        default="true",
        choices=["true", "false"],
        help="Whether SpireServer federation uses managedRoute (true/false)",
    )
    group.addoption(
        "--mtls-server-image",
        action="store",
        default="registry.access.redhat.com/ubi9/ubi:latest",
        help="Container image for mTLS server workload",
    )
    group.addoption(
        "--mtls-client-image",
        action="store",
        default="registry.access.redhat.com/ubi9/ubi:latest",
        help="Container image for mTLS client workload",
    )
    group.addoption(
        "--spiffe-helper-image",
        action="store",
        default="ghcr.io/spiffe/spiffe-helper:0.8.0",
        help="Container image for spiffe-helper sidecar",
    )
    group.addoption(
        "--bootstrap-clusters",
        "--install-operator",
        dest="bootstrap_clusters",
        action="store_true",
        default=False,
        help=(
            "Install operator and operands on both clusters if needed "
            "(legacy alias: --install-operator)"
        ),
    )
    group.addoption(
        "--federation-timeout",
        action="store",
        type=int,
        default=300,
        help="Timeout for federation operations (seconds)",
    )
    group.addoption(
        "--mtls-timeout",
        action="store",
        type=int,
        default=240,
        help="Timeout for mTLS workload readiness (seconds)",
    )

    ossm_group = parser.getgroup("ossm_federation", "OSSM cross-cluster federation options")
    ossm_group.addoption(
        "--ossm-namespace", action="store", default="istio-system",
        help="Namespace where Istiod is deployed",
    )
    ossm_group.addoption(
        "--ossm-cni-namespace", action="store", default="istio-cni",
        help="Namespace for IstioCNI DaemonSet",
    )
    ossm_group.addoption(
        "--ossm-timeout", action="store", type=int, default=300,
        help="Timeout for OSSM operations (seconds)",
    )
    ossm_group.addoption(
        "--sail-channel", action="store", default="stable",
        help="Sail Operator OLM channel",
    )
    ossm_group.addoption(
        "--sail-version", action="store", default="v1.30-latest",
        help="Istio/IstioCNI version for Sail CRs",
    )
    ossm_group.addoption(
        "--workload-namespace", action="store", default="sample",
        help="Namespace for federation workloads",
    )
    ossm_group.addoption(
        "--nofed-namespace", action="store", default="nofed",
        help="Namespace for negative-test workloads (no federatesWith)",
    )
    ossm_group.addoption(
        "--local-cluster-name", action="store", default="cluster-a",
        help="Cluster A name for multi-cluster config",
    )
    ossm_group.addoption(
        "--remote-cluster-name", action="store", default="cluster-b",
        help="Cluster B name for multi-cluster config",
    )


# =============================================================================
# Report hooks and common test hooks
# =============================================================================


def pytest_configure(config):
    """Configure HTML reporting and kubeconfig."""
    kubeconfig = config.getoption("--kubeconfig", default=None)
    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig
        logger.info(f"Using kubeconfig from CLI: {kubeconfig}")
    report_manager.configure(config)


def pytest_html_report_title(report):
    """Customize HTML report title."""
    report.title = "ZTWIM Federation Tests - OpenShift"


@pytest.hookimpl(optionalhook=True)
def pytest_metadata(metadata):
    """Show OpenShift version in HTML report metadata."""
    metadata.clear()
    try:
        from kubernetes import client, config as k8s_config

        kubeconfig = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config"))
        k8s_config.load_kube_config(config_file=kubeconfig)
        custom_api = client.CustomObjectsApi()
        cluster_version = custom_api.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="clusterversions",
            name="version",
        )
        ocp_version = cluster_version.get("status", {}).get("desired", {}).get(
            "version", "Unknown"
        )
        metadata["OpenShift Version"] = ocp_version
    except Exception as exc:
        logger.warning(f"Could not detect OpenShift version: {exc}")
        metadata["OpenShift Version"] = "Not detected (check KUBECONFIG)"


def pytest_html_results_summary(prefix, summary, postfix):
    """Add short federation-focused summary block."""
    from datetime import datetime

    prefix.extend(
        [
            '<div style="margin: 20px 0; padding: 24px; background: #FFFFFF; border-radius: 8px; border-left: 5px solid #CC0000;">',
            '<h2 style="margin: 0 0 8px 0; color: #000000; font-size: 24px; font-weight: bold;">🔐 ZTWIM Federation Test Results</h2>',
            '<p style="margin: 0; color: #333333; font-size: 14px;">SPIRE federation validation across clusters</p>',
            f'<p style="margin: 8px 0 0 0; color: #666666; font-size: 12px;">📅 Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
            "</div>",
        ]
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach description and markers to test report rows."""
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__) if item.function.__doc__ else ""
    markers = [marker.name for marker in item.iter_markers()]
    if markers:
        report.markers = ", ".join(markers)


def pytest_sessionfinish(session, exitstatus):
    """Finalize report paths and summary output."""
    report_manager.finalize(session.config)


def pytest_collection_modifyitems(config, items):
    """Ensure federation marker on federation test files."""
    for item in items:
        if "federation" in str(item.fspath):
            item.add_marker(pytest.mark.federation)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Log test start."""
    log_test_start(item.name)


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    """Log test end."""
    passed = item.rep_call.passed if hasattr(item, "rep_call") else True
    log_test_end(item.name, passed)


# =============================================================================
# Core local-cluster fixtures
# =============================================================================


@pytest.fixture(scope="session")
def kubeconfig_path(request) -> str:
    """Resolve kubeconfig from CLI/env/default."""
    cli_kubeconfig = request.config.getoption("--kubeconfig")
    kubeconfig = set_kubeconfig(cli_kubeconfig)
    logger.info(f"Using kubeconfig: {kubeconfig}")
    return kubeconfig


@pytest.fixture(scope="session")
def ocp_client(kubeconfig_path) -> OCPClient:
    """Create OpenShift client for local cluster."""
    client = OCPClient(kubeconfig_path)
    try:
        cluster_info = client.get_cluster_info()
        logger.info(f"Connected to cluster: {cluster_info['git_version']}")
        logger.info("Cluster type: OpenShift" if client.is_openshift() else "Cluster type: Kubernetes")
    except Exception as exc:
        logger.error(f"Failed to connect to cluster: {exc}")
        raise
    return client


@pytest.fixture(scope="session", autouse=True)
def ztwim_setup(request, ocp_client):
    """Run session setup/teardown orchestration for local cluster."""
    orchestrator = ZTWIMSetupOrchestrator(ocp_client)
    options = orchestrator.from_pytest_request(request)
    orchestrator.run_setup(options)
    yield
    orchestrator.run_teardown(options)


@pytest.fixture(scope="session")
def operator_namespace(request) -> str:
    """ZTWIM operator namespace."""
    return request.config.getoption("--operator-namespace")


@pytest.fixture(scope="session")
def app_domain(request, ocp_client) -> str:
    """Resolve local cluster app domain."""
    cli_domain = request.config.getoption("--app-domain")
    if cli_domain:
        return cli_domain
    if os.environ.get("APP_DOMAIN"):
        return os.environ["APP_DOMAIN"]
    try:
        dns = ocp_client.custom_objects.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="dnses",
            name="cluster",
        )
        base_domain = dns.get("spec", {}).get("baseDomain", "")
        domain = f"apps.{base_domain}"
        logger.info(f"Auto-detected APP_DOMAIN: {domain}")
        return domain
    except Exception as exc:
        pytest.fail(f"Failed to determine APP_DOMAIN: {exc}")


@pytest.fixture(scope="session")
def skip_cleanup(request) -> bool:
    """Whether cleanup should be skipped."""
    return request.config.getoption("--skip-cleanup")


# =============================================================================
# Remote Cluster Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def remote_kubeconfig(request) -> str:
    """
    Get the remote cluster kubeconfig path.

    Priority:
    1. --remote-kubeconfig CLI arg
    2. REMOTE_KUBECONFIG environment variable
    """
    cli_path = request.config.getoption("--remote-kubeconfig", default=None)
    env_path = os.environ.get("REMOTE_KUBECONFIG")

    kubeconfig = cli_path or env_path
    if not kubeconfig:
        pytest.skip(
            "Remote kubeconfig not provided. "
            "Set --remote-kubeconfig or REMOTE_KUBECONFIG env var."
        )

    if not os.path.isfile(kubeconfig):
        pytest.fail(f"Remote kubeconfig not found: {kubeconfig}")

    logger.info(f"Using remote kubeconfig: {kubeconfig}")
    return kubeconfig


@pytest.fixture(scope="module")
def remote_ocp_client(remote_kubeconfig) -> OCPClient:
    """Create an OCP client connected to the remote cluster."""
    client = OCPClient(remote_kubeconfig)

    try:
        cluster_info = client.get_cluster_info()
        logger.info(f"Connected to remote cluster: {cluster_info['git_version']}")
    except Exception as e:
        pytest.fail(f"Failed to connect to remote cluster: {e}")

    return client


@pytest.fixture(scope="module")
def remote_app_domain(request, remote_ocp_client) -> str:
    """Get the remote cluster's apps domain."""
    cli_domain = request.config.getoption("--remote-app-domain", default=None)
    if cli_domain:
        return cli_domain

    env_domain = os.environ.get("REMOTE_APP_DOMAIN")
    if env_domain:
        return env_domain

    try:
        dns = remote_ocp_client.custom_objects.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="dnses",
            name="cluster",
        )
        base_domain = dns.get("spec", {}).get("baseDomain", "")
        domain = f"apps.{base_domain}"
        logger.info(f"Auto-detected remote APP_DOMAIN: {domain}")
        return domain
    except Exception as e:
        pytest.fail(f"Could not determine remote APP_DOMAIN: {e}")


@pytest.fixture(scope="module")
def local_app_domain(app_domain) -> str:
    """Alias for the local cluster's apps domain (from root conftest)."""
    return app_domain


# =============================================================================
# Auto-Deploy Operator + SPIRE Stack on Both Clusters
# =============================================================================


def _resolve_deployment_mode(request) -> str:
    """Resolve effective deployment mode, honoring legacy aliases."""
    mode = request.config.getoption("deployment_mode")
    use_existing = request.config.getoption("use_existing_deployment")
    bootstrap = request.config.getoption("bootstrap_clusters")

    if use_existing:
        pytest.fail(
            "--use-existing-deployment / --skip-install is no longer supported. "
            "Use --deployment-mode=operator-only or --deployment-mode=bootstrap."
        )
    if bootstrap:
        return "bootstrap"
    return mode


@pytest.fixture(scope="module", autouse=True)
def ensure_spire_stack_deployed(
    request, ocp_client, remote_ocp_client, local_app_domain, remote_app_domain
):
    """
    Ensure the ZTWIM operator and SPIRE stack are deployed on both clusters.

    Supports two modes:

    1. --deployment-mode=operator-only (default): Requires operator to be
       pre-installed and ready, then auto-deploys/repairs operands.

    2. --deployment-mode=bootstrap: Clusters are completely bare.
       Installs the operator and deploys operands on both clusters.
    """
    deployment_mode = _resolve_deployment_mode(request)
    keep_deployed = request.config.getoption("keep_deployed")
    cleanup_only = request.config.getoption("cleanup_only_mode")

    # ── Cleanup-only mode: wipe everything and skip tests ──────────────────
    if cleanup_only:
        logger.info("")
        logger.info("=" * 60)
        logger.info("CLEANUP-ONLY MODE: Removing ALL resources on both clusters")
        logger.info("=" * 60)

        _cleanup_federation_resources(ocp_client, "local")
        _cleanup_federation_resources(remote_ocp_client, "remote")
        _cleanup_test_namespaces(ocp_client, remote_ocp_client)

        if deployment_mode == "bootstrap":
            _full_uninstall(ocp_client, "local")
            _full_uninstall(remote_ocp_client, "remote")
        else:
            _cleanup_operands(ocp_client, "local")
            _cleanup_operands(remote_ocp_client, "remote")

        logger.info("")
        logger.info("=" * 60)
        logger.info("CLEANUP COMPLETE - clusters are ready for a fresh test run")
        logger.info("=" * 60)
        pytest.skip("Cleanup-only mode: all resources removed, skipping tests")

    # ── Mode 2: Full install (operator + operands from bare cluster) ─────────
    if deployment_mode == "bootstrap":
        logger.info("")
        logger.info("=" * 60)
        logger.info("FULL INSTALL: OPERATOR + OPERANDS ON BOTH CLUSTERS")
        logger.info("=" * 60)

        _install_operator_if_needed(ocp_client, "local")
        _install_operator_if_needed(remote_ocp_client, "remote")
    else:
        logger.info("")
        logger.info("=" * 60)
        logger.info("OPERATOR-ONLY MODE: VALIDATE OPERATOR ON BOTH CLUSTERS")
        logger.info("=" * 60)
        _require_operator_ready(ocp_client, "local")
        _require_operator_ready(remote_ocp_client, "remote")

    # ── Mode 1 & 2: Deploy operands ─────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("DEPLOYING SPIRE STACK (OPERANDS) ON BOTH CLUSTERS")
    logger.info("=" * 60)

    _deploy_stack_if_needed(ocp_client, local_app_domain, "local", "cluster1")
    _deploy_stack_if_needed(remote_ocp_client, remote_app_domain, "remote", "cluster2")

    logger.info("")
    logger.info("SPIRE stack ready on both clusters")
    logger.info("=" * 60)

    yield

    # ── Teardown ────────────────────────────────────────────────────────────
    if keep_deployed:
        logger.info("Keeping ZTWIM deployed (--keep-deployed set)")
        return

    if deployment_mode == "bootstrap":
        logger.info("Uninstalling operator + operands on both clusters")
        _full_uninstall(ocp_client, "local")
        _full_uninstall(remote_ocp_client, "remote")
    else:
        logger.info("Cleaning up operands on both clusters (use --keep-deployed to skip)")
        _cleanup_operands(ocp_client, "local")
        _cleanup_operands(remote_ocp_client, "remote")


def _install_operator_if_needed(client: OCPClient, cluster_label: str):
    """Install the ZTWIM operator via OLM if not already installed."""
    installer = OperatorInstaller(client)

    try:
        pods = client.get_pods(
            namespace=installer.OPERATOR_NAMESPACE,
            label_selector="name=zero-trust-workload-identity-manager",
        )
        if pods and any(
            p.get("status", {}).get("phase") == "Running" for p in pods
        ):
            logger.info(f"[{cluster_label}] Operator already installed and running")
            return
    except Exception:
        pass

    logger.info(f"[{cluster_label}] Installing ZTWIM operator via OLM...")
    try:
        installer.install()
        installer.wait_for_operator_ready(timeout=300)
        logger.info(f"[{cluster_label}] Operator installed successfully")
    except Exception as e:
        pytest.fail(f"[{cluster_label}] Operator installation failed: {e}")


def _require_operator_ready(client: OCPClient, cluster_label: str):
    """Require existing operator installation and ready controller pod."""
    installer = OperatorInstaller(client)
    if not installer.is_installed():
        pytest.fail(
            f"[{cluster_label}] ZTWIM operator is not installed. "
            "Use --deployment-mode=bootstrap to install it."
        )
    try:
        installer.wait_for_operator_ready(timeout=300)
        logger.info(f"[{cluster_label}] Operator is present and ready")
    except Exception as e:
        pytest.fail(f"[{cluster_label}] Operator is installed but not ready: {e}")


def _deploy_stack_if_needed(
    client: OCPClient, app_domain: str, cluster_label: str, cluster_name: str
):
    """Deploy SPIRE stack (operands) on a cluster if not already present."""
    deployer = ZTWIMStackDeployer(client)

    if deployer.is_deployed():
        verifier = ZTWIMInstallationVerifier(client)
        try:
            verifier.verify_all(timeout_per_component=60)
            logger.info(f"[{cluster_label}] SPIRE stack already deployed and healthy")
            return
        except Exception:
            logger.info(f"[{cluster_label}] SPIRE stack partially deployed, redeploying...")
    else:
        logger.info(f"[{cluster_label}] No operands found, deploying SPIRE stack...")

    deployer = ZTWIMStackDeployer(client)
    try:
        deployer.deploy_all(
            app_domain=app_domain,
            cluster_name=cluster_name,
            wait=True,
            timeout=600,
        )
        logger.info(f"[{cluster_label}] SPIRE stack deployed successfully")
    except Exception as e:
        pytest.fail(
            f"[{cluster_label}] Failed to deploy SPIRE stack: {e}\n"
            "Ensure the ZTWIM operator is installed and ready, "
            "or use --deployment-mode=bootstrap."
        )


def _verify_stack(client: OCPClient, cluster_label: str):
    """Verify SPIRE stack is healthy on a cluster."""
    verifier = ZTWIMInstallationVerifier(client)
    try:
        verifier.verify_all(timeout_per_component=60)
        logger.info(f"[{cluster_label}] SPIRE stack verified healthy")
    except Exception as e:
        pytest.fail(
            f"[{cluster_label}] SPIRE stack verification failed: {e}\n"
            "Ensure ZTWIM is deployed, or use --deployment-mode=bootstrap."
        )


def _cleanup_operands(client: OCPClient, cluster_label: str):
    """Remove operand CRs from a cluster (keeps operator installed)."""
    deployer = ZTWIMStackDeployer(client)
    try:
        deployer.delete_all_operands()
        logger.info(f"[{cluster_label}] Operands cleaned up")
    except Exception as e:
        logger.warning(f"[{cluster_label}] Operand cleanup failed: {e}")


def _full_uninstall(client: OCPClient, cluster_label: str):
    """Uninstall operator + operands completely from a cluster."""
    try:
        installer = ZTWIMFullInstaller(client)
        installer.uninstall_all(timeout=180)
        logger.info(f"[{cluster_label}] Full uninstall complete")
    except Exception as e:
        logger.warning(f"[{cluster_label}] Full uninstall failed: {e}")


def _cleanup_federation_resources(client: OCPClient, cluster_label: str):
    """Delete all cluster-scoped federation resources (CFDTs, ClusterSPIFFEIDs)."""
    logger.info(f"[{cluster_label}] Cleaning up federation resources...")

    # Delete all ClusterFederatedTrustDomains
    try:
        cfdt_resource = client.get_crd_resource(
            "spire.spiffe.io/v1alpha1", "ClusterFederatedTrustDomain"
        )
        cfdts = cfdt_resource.get()
        for item in cfdts.get("items", []):
            name = item["metadata"]["name"]
            try:
                cfdt_resource.delete(name=name)
                logger.info(f"[{cluster_label}] Deleted CFDT: {name}")
            except Exception as e:
                logger.debug(f"[{cluster_label}] Failed to delete CFDT {name}: {e}")
    except Exception as e:
        logger.debug(f"[{cluster_label}] No CFDTs to clean or CRD not found: {e}")

    # Delete all ClusterSPIFFEIDs
    try:
        spiffeid_resource = client.get_crd_resource(
            "spire.spiffe.io/v1alpha1", "ClusterSPIFFEID"
        )
        spiffeids = spiffeid_resource.get()
        for item in spiffeids.get("items", []):
            name = item["metadata"]["name"]
            try:
                spiffeid_resource.delete(name=name)
                logger.info(f"[{cluster_label}] Deleted ClusterSPIFFEID: {name}")
            except Exception as e:
                logger.debug(
                    f"[{cluster_label}] Failed to delete ClusterSPIFFEID {name}: {e}"
                )
    except Exception as e:
        logger.debug(f"[{cluster_label}] No ClusterSPIFFEIDs to clean or CRD not found: {e}")

    logger.info(f"[{cluster_label}] Federation resources cleaned")


def _cleanup_test_namespaces(local_client: OCPClient, remote_client: OCPClient):
    """Delete any leftover federation test namespaces on both clusters."""
    logger.info("Cleaning up leftover test namespaces...")

    ns_prefix = "ztwim-test"
    for client, label in [(local_client, "local"), (remote_client, "remote")]:
        try:
            namespaces = client.core_v1.list_namespace(
                label_selector="purpose=ztwim-federation-test"
            )
            for ns in namespaces.items:
                name = ns.metadata.name
                try:
                    client.delete_namespace(name, wait=False)
                    logger.info(f"[{label}] Deleted test namespace: {name}")
                except Exception as e:
                    logger.debug(f"[{label}] Failed to delete namespace {name}: {e}")
        except Exception:
            pass

        # Also clean namespaces matching the prefix pattern
        try:
            all_ns = client.core_v1.list_namespace()
            for ns in all_ns.items:
                if ns.metadata.name.startswith(ns_prefix):
                    try:
                        client.delete_namespace(ns.metadata.name, wait=False)
                        logger.info(f"[{label}] Deleted test namespace: {ns.metadata.name}")
                    except Exception as e:
                        logger.debug(
                            f"[{label}] Failed to delete namespace {ns.metadata.name}: {e}"
                        )
        except Exception:
            pass

    logger.info("Test namespace cleanup done")


@pytest.fixture(scope="module")
def federation_timeout(request) -> int:
    """Get federation operation timeout."""
    return request.config.getoption("--federation-timeout", default=300)


@pytest.fixture(scope="module")
def mtls_timeout(request) -> int:
    """Get mTLS workload readiness timeout."""
    return request.config.getoption("--mtls-timeout", default=240)


@pytest.fixture(scope="module")
def federation_config(request) -> FederationScenarioConfig:
    """Build the federation scenario config from CLI options."""
    return FederationScenarioConfig(
        profile=request.config.getoption("--federation-profile", default="https_spiffe"),
        managed_route=(
            request.config.getoption("--federation-managed-route", default="true").lower()
            == "true"
        ),
        mtls_server_image=request.config.getoption(
            "--mtls-server-image", default="registry.access.redhat.com/ubi9/ubi:latest"
        ),
        mtls_client_image=request.config.getoption(
            "--mtls-client-image", default="registry.access.redhat.com/ubi9/ubi:latest"
        ),
        spiffe_helper_image=request.config.getoption(
            "--spiffe-helper-image", default="ghcr.io/spiffe/spiffe-helper:0.8.0"
        ),
    )


# =============================================================================
# Federation Helper Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def federation_helper(
    ocp_client, remote_ocp_client, operator_namespace, federation_config
) -> "FederationHelper":
    """Provide a FederationHelper for managing federation operations."""
    return FederationHelper(
        local_client=ocp_client,
        remote_client=remote_ocp_client,
        namespace=operator_namespace,
        scenario_config=federation_config,
    )


class FederationHelper:
    """
    Encapsulates SPIRE federation operations across two clusters.

    Provides methods for:
    - Enabling federation on SpireServer
    - Fetching trust bundles
    - Creating ClusterFederatedTrustDomain resources
    - Verifying bundle synchronization
    - Deploying and managing mTLS workloads
    """

    def __init__(
        self,
        local_client: OCPClient,
        remote_client: OCPClient,
        namespace: str,
        scenario_config: FederationScenarioConfig,
    ):
        self.local = local_client
        self.remote = remote_client
        self.namespace = namespace
        self.config = scenario_config
        self._spire_server_bin: Dict[int, str] = {}
        self._poller = DynamicPoller(
            PollConfig(
                initial_delay=2.0,
                min_interval=5.0,
                max_interval=20.0,
                backoff_factor=1.3,
                timeout=300.0,
            )
        )

    def enable_federation_on_spire_server(
        self,
        client: OCPClient,
        remote_trust_domain: str,
        remote_app_domain: str,
        local_bundle_profile: Optional[str] = None,
        remote_bundle_profile: Optional[str] = None,
        endpoint_spiffe_id: Optional[str] = None,
        https_web_secret_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Patch the SpireServer CR to enable federation with the remote cluster."""
        local_profile = local_bundle_profile or self.config.profile
        remote_profile = remote_bundle_profile or self.config.profile
        spiffe_id = endpoint_spiffe_id or self.config.endpoint_spiffe_id(remote_trust_domain)

        bundle_endpoint: Dict[str, Any] = {"profile": local_profile}
        if local_profile == "https_web" and https_web_secret_ref:
            bundle_endpoint["httpsWeb"] = {
                "servingCert": {
                    "externalSecretRef": https_web_secret_ref,
                    "fileSyncInterval": 86400,
                }
            }

        federates_with: Dict[str, Any] = {
            "trustDomain": remote_trust_domain,
            "bundleEndpointUrl": self.config.bundle_endpoint_url(remote_app_domain),
            "bundleEndpointProfile": remote_profile,
        }
        if remote_profile == "https_spiffe":
            federates_with["endpointSpiffeId"] = spiffe_id

        federation_spec = {
            "spec": {
                "federation": {
                    "bundleEndpoint": bundle_endpoint,
                    "managedRoute": str(self.config.managed_route).lower(),
                    "federatesWith": [federates_with],
                }
            }
        }

        result = client.patch_custom_resource(
            api_version=ZTWIM_API_VERSION,
            kind="SpireServer",
            name="cluster",
            namespace="",
            body=federation_spec,
        )
        logger.info(
            f"Enabled federation on SpireServer (remote: {remote_trust_domain})"
        )
        return result

    def wait_for_federation_route(
        self, client: OCPClient, timeout: int = 120
    ) -> Dict[str, Any]:
        """Wait for the federation route to be created and admitted."""

        def _check():
            route = client.get_route(FEDERATION_ROUTE_NAME, self.namespace)
            if route:
                ingress = route.get("status", {}).get("ingress", [])
                if ingress:
                    return route
            return None

        result = wait_until(
            _check,
            message="Federation route ready",
            timeout=timeout,
            interval=5,
        )
        if not result.success:
            raise TimeoutError(
                f"Federation route not ready within {timeout}s"
            )
        return result.value

    def get_federation_endpoint(self, client: OCPClient) -> str:
        """Get the federation bundle endpoint URL from the cluster's route."""
        route = client.get_route(FEDERATION_ROUTE_NAME, self.namespace)
        if not route:
            raise RuntimeError("Federation route not found")
        host = route["spec"]["host"]
        return f"https://{host}"

    _SPIRE_SERVER_BIN_CANDIDATES = [
        "/spire-server",               # Red Hat productized image
        "/opt/spire/bin/spire-server",  # Upstream open-source image
    ]

    def _get_spire_server_bin(self, client: OCPClient) -> str:
        """Auto-detect the spire-server binary path inside the container.

        Tries known candidate paths, caches per client so the probe runs once.
        """
        cache_key = id(client)
        if cache_key in self._spire_server_bin:
            return self._spire_server_bin[cache_key]

        pods = client.get_pods(
            namespace=self.namespace, label_selector=SPIRE_SERVER_POD_LABEL
        )
        if not pods:
            raise RuntimeError("No spire-server pods found")

        pod_name = pods[0]["metadata"]["name"]
        for candidate in self._SPIRE_SERVER_BIN_CANDIDATES:
            try:
                output = client.exec_in_pod(
                    name=pod_name,
                    namespace=self.namespace,
                    command=[candidate, "--help"],
                    container="spire-server",
                )
                if "not found" not in (output or ""):
                    logger.info(f"Detected spire-server binary: {candidate}")
                    self._spire_server_bin[cache_key] = candidate
                    return candidate
            except Exception:
                continue

        fallback = self._SPIRE_SERVER_BIN_CANDIDATES[0]
        logger.warning(
            f"Could not detect spire-server binary, falling back to {fallback}"
        )
        self._spire_server_bin[cache_key] = fallback
        return fallback

    def fetch_trust_bundle_via_exec(self, client: OCPClient) -> str:
        """
        Fetch the trust bundle by exec'ing into spire-server pod.

        Uses the SPIRE server CLI to show the bundle in JWKS format.
        Retries automatically on transient errors (container not found, etc.)
        using settings from config/settings.yaml -> polling.exec_retry.

        The kubernetes stream() may return a Python dict repr (single quotes)
        instead of raw JSON. This method normalizes the output to valid JSON.
        """
        pods = client.get_pods(
            namespace=self.namespace, label_selector=SPIRE_SERVER_POD_LABEL
        )
        if not pods:
            raise RuntimeError("No spire-server pods found")

        spire_bin = self._get_spire_server_bin(client)
        pod_name = pods[0]["metadata"]["name"]
        output = client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=self.namespace,
            command=[
                spire_bin,
                "bundle",
                "show",
                "-socketPath",
                "/tmp/spire-server/private/api.sock",
                "-format",
                "spiffe",
            ],
            container="spire-server",
        )
        return self._normalize_json_output(output)

    @staticmethod
    def _normalize_json_output(output: str) -> str:
        """Ensure exec output is valid JSON, handling kubernetes stream quirks."""
        if not output:
            return output
        try:
            json.loads(output)
            return output
        except (json.JSONDecodeError, TypeError):
            pass
        if isinstance(output, dict):
            return json.dumps(output)
        import ast
        try:
            parsed = ast.literal_eval(str(output))
            return json.dumps(parsed)
        except (ValueError, SyntaxError):
            return str(output)

    def list_federated_bundles(self, client: OCPClient) -> str:
        """
        List all federated bundles in the SPIRE server.

        Retries automatically on transient errors (container not found, etc.)
        using settings from config/settings.yaml -> polling.exec_retry.
        """
        pods = client.get_pods(
            namespace=self.namespace, label_selector=SPIRE_SERVER_POD_LABEL
        )
        if not pods:
            raise RuntimeError("No spire-server pods found")

        spire_bin = self._get_spire_server_bin(client)
        pod_name = pods[0]["metadata"]["name"]
        output = client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=self.namespace,
            command=[
                spire_bin,
                "bundle",
                "list",
                "-socketPath",
                "/tmp/spire-server/private/api.sock",
            ],
            container="spire-server",
        )
        return output

    def show_spire_entries(self, client: OCPClient) -> str:
        """
        Show SPIRE registration entries.

        Retries automatically on transient errors (container not found, etc.)
        using settings from config/settings.yaml -> polling.exec_retry.
        """
        pods = client.get_pods(
            namespace=self.namespace, label_selector=SPIRE_SERVER_POD_LABEL
        )
        if not pods:
            raise RuntimeError("No spire-server pods found")

        spire_bin = self._get_spire_server_bin(client)
        pod_name = pods[0]["metadata"]["name"]
        output = client.exec_in_pod_with_retry(
            name=pod_name,
            namespace=self.namespace,
            command=[
                spire_bin,
                "entry",
                "show",
                "-socketPath",
                "/tmp/spire-server/private/api.sock",
            ],
            container="spire-server",
        )
        return output

    def create_cluster_federated_trust_domain(
        self,
        client: OCPClient,
        name: str,
        remote_trust_domain: str,
        remote_app_domain: str,
        trust_bundle_json: str,
        profile_type: Optional[str] = None,
        endpoint_spiffe_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a ClusterFederatedTrustDomain resource."""
        cfdt_profile = profile_type or self.config.profile
        profile_body: Dict[str, Any] = {"type": cfdt_profile}
        if cfdt_profile == "https_spiffe":
            profile_body["endpointSPIFFEID"] = (
                endpoint_spiffe_id or self.config.endpoint_spiffe_id(remote_trust_domain)
            )

        body = {
            "apiVersion": SPIFFE_API_VERSION,
            "kind": "ClusterFederatedTrustDomain",
            "metadata": {"name": name},
            "spec": {
                "trustDomain": remote_trust_domain,
                "bundleEndpointURL": self.config.bundle_endpoint_url(remote_app_domain),
                "bundleEndpointProfile": profile_body,
                "className": SPIRE_CLASS_NAME,
                "trustDomainBundle": trust_bundle_json,
            },
        }

        resource = client.get_crd_resource(SPIFFE_API_VERSION, "ClusterFederatedTrustDomain")
        result = resource.create(body=body)
        logger.info(f"Created ClusterFederatedTrustDomain: {name}")
        return result.to_dict()

    def delete_cluster_federated_trust_domain(
        self, client: OCPClient, name: str
    ) -> None:
        """Delete a ClusterFederatedTrustDomain resource."""
        try:
            resource = client.get_crd_resource(
                SPIFFE_API_VERSION, "ClusterFederatedTrustDomain"
            )
            resource.delete(name=name)
            logger.info(f"Deleted ClusterFederatedTrustDomain: {name}")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"CFDT {name} not found (already deleted or never created)")
            else:
                logger.warning(f"Could not delete CFDT {name}: {e.reason}")
        except Exception as e:
            logger.warning(f"Could not delete CFDT {name}: {e}")

    def create_cluster_spiffe_id(
        self,
        client: OCPClient,
        name: str,
        namespace_match: str,
        pod_label: str,
        federate_with: str,
    ) -> Dict[str, Any]:
        """Create a ClusterSPIFFEID resource for workload identity."""
        body = {
            "apiVersion": SPIFFE_API_VERSION,
            "kind": "ClusterSPIFFEID",
            "metadata": {"name": name},
            "spec": {
                "className": SPIRE_CLASS_NAME,
                "spiffeIDTemplate": (
                    "spiffe://{{ .TrustDomain }}/ns/"
                    "{{ .PodMeta.Namespace }}/sa/{{ .PodSpec.ServiceAccountName }}"
                ),
                "podSelector": {"matchLabels": {"app": pod_label}},
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": namespace_match
                    }
                },
                "federatesWith": [federate_with],
            },
        }

        resource = client.get_crd_resource(SPIFFE_API_VERSION, "ClusterSPIFFEID")
        result = resource.create(body=body)
        logger.info(f"Created ClusterSPIFFEID: {name}")
        return result.to_dict()

    def delete_cluster_spiffe_id(self, client: OCPClient, name: str) -> None:
        """Delete a ClusterSPIFFEID resource."""
        try:
            resource = client.get_crd_resource(SPIFFE_API_VERSION, "ClusterSPIFFEID")
            resource.delete(name=name)
            logger.info(f"Deleted ClusterSPIFFEID: {name}")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"ClusterSPIFFEID {name} not found (already deleted or never created)")
            else:
                logger.warning(f"Could not delete ClusterSPIFFEID {name}: {e.reason}")
        except Exception as e:
            logger.warning(f"Could not delete ClusterSPIFFEID {name}: {e}")

    def deploy_mtls_server(
        self,
        client: OCPClient,
        namespace: str,
        app_domain: str,
    ) -> None:
        """Deploy the mTLS server workload with spiffe-helper sidecar."""
        from kubernetes import client as k8s_client

        sa_body = k8s_client.V1ServiceAccount(
            metadata=k8s_client.V1ObjectMeta(
                name="mtls-server-sa", namespace=namespace
            )
        )
        try:
            client.core_v1.create_namespaced_service_account(
                namespace=namespace, body=sa_body
            )
        except Exception:
            pass

        svc_body = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "mtls-server", "namespace": namespace},
            "spec": {
                "selector": {"app": "mtls-server"},
                "ports": [
                    {"port": 8443, "targetPort": 8443, "name": "https"}
                ],
            },
        }
        try:
            client.core_v1.create_namespaced_service(
                namespace=namespace,
                body=svc_body,
            )
        except Exception:
            pass

        deployment_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "mtls-server", "namespace": namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "mtls-server"}},
                "template": {
                    "metadata": {"labels": {"app": "mtls-server"}},
                    "spec": {
                        "serviceAccountName": "mtls-server-sa",
                        "containers": [
                            {
                                "name": "server",
                                "image": self.config.mtls_server_image,
                                "command": ["/bin/bash", "-c"],
                                "args": [
                                    "dnf install -y openssl &>/dev/null; "
                                    "echo 'Waiting for SVID files...'; "
                                    "while [ ! -f /certs/svid.pem ]; do sleep 5; done; "
                                    "echo 'SVID ready! Starting mTLS server on port 8443...'; "
                                    "while true; do "
                                    "openssl s_server "
                                    "-cert /certs/svid.pem "
                                    "-key /certs/svid_key.pem "
                                    "-CAfile /certs/bundle.pem "
                                    "-Verify 1 -verify_return_error "
                                    "-accept 8443 -www 2>&1; "
                                    "sleep 1; done"
                                ],
                                "ports": [{"containerPort": 8443}],
                                "volumeMounts": [
                                    {
                                        "name": "certs",
                                        "mountPath": "/certs",
                                        "readOnly": True,
                                    }
                                ],
                            },
                            {
                                "name": "spiffe-helper",
                                "image": self.config.spiffe_helper_image,
                                "args": ["-config", "/config/helper.conf"],
                                "volumeMounts": [
                                    {
                                        "name": "spiffe-workload-api",
                                        "mountPath": "/spiffe-workload-api",
                                        "readOnly": True,
                                    },
                                    {"name": "certs", "mountPath": "/certs"},
                                    {
                                        "name": "helper-config",
                                        "mountPath": "/config",
                                    },
                                ],
                            },
                        ],
                        "volumes": [
                            {
                                "name": "spiffe-workload-api",
                                "csi": {
                                    "driver": "csi.spiffe.io",
                                    "readOnly": True,
                                },
                            },
                            {"name": "certs", "emptyDir": {}},
                            {
                                "name": "helper-config",
                                "configMap": {
                                    "name": "spiffe-helper-config"
                                },
                            },
                        ],
                    },
                },
            },
        }

        client.apps_v1.create_namespaced_deployment(
            namespace=namespace, body=deployment_body
        )
        logger.info(f"Deployed mTLS server in {namespace}")

    def deploy_mtls_client(
        self,
        client: OCPClient,
        namespace: str,
    ) -> None:
        """Deploy the mTLS client pod with spiffe-helper sidecar."""
        from kubernetes import client as k8s_client

        sa_body = k8s_client.V1ServiceAccount(
            metadata=k8s_client.V1ObjectMeta(
                name="mtls-client-sa", namespace=namespace
            )
        )
        try:
            client.core_v1.create_namespaced_service_account(
                namespace=namespace, body=sa_body
            )
        except Exception:
            pass

        pod_body = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "mtls-client",
                "namespace": namespace,
                "labels": {"app": "mtls-client"},
            },
            "spec": {
                "serviceAccountName": "mtls-client-sa",
                "containers": [
                    {
                        "name": "client",
                        "image": self.config.mtls_client_image,
                        "command": ["/bin/bash", "-c"],
                        "args": [
                            "dnf install -y openssl &>/dev/null; "
                            "echo 'Waiting for SVID files...'; "
                            "while [ ! -f /certs/svid.pem ]; do sleep 5; done; "
                            "echo 'SVID ready! Client is ready for mTLS testing.'; "
                            "sleep infinity"
                        ],
                        "volumeMounts": [
                            {
                                "name": "certs",
                                "mountPath": "/certs",
                                "readOnly": True,
                            }
                        ],
                    },
                    {
                        "name": "spiffe-helper",
                        "image": self.config.spiffe_helper_image,
                        "args": ["-config", "/config/helper.conf"],
                        "volumeMounts": [
                            {
                                "name": "spiffe-workload-api",
                                "mountPath": "/spiffe-workload-api",
                                "readOnly": True,
                            },
                            {"name": "certs", "mountPath": "/certs"},
                            {
                                "name": "helper-config",
                                "mountPath": "/config",
                            },
                        ],
                    },
                ],
                "volumes": [
                    {
                        "name": "spiffe-workload-api",
                        "csi": {"driver": "csi.spiffe.io", "readOnly": True},
                    },
                    {"name": "certs", "emptyDir": {}},
                    {
                        "name": "helper-config",
                        "configMap": {"name": "spiffe-helper-config"},
                    },
                ],
            },
        }

        client.core_v1.create_namespaced_pod(namespace=namespace, body=pod_body)
        logger.info(f"Deployed mTLS client in {namespace}")

    def create_spiffe_helper_configmap(
        self, client: OCPClient, namespace: str
    ) -> None:
        """Create the spiffe-helper configuration ConfigMap."""
        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "spiffe-helper-config",
                "namespace": namespace,
            },
            "data": {
                "helper.conf": (
                    'agent_address = "/spiffe-workload-api/spire-agent.sock"\n'
                    'cmd = ""\n'
                    'cert_dir = "/certs"\n'
                    'svid_file_name = "svid.pem"\n'
                    'svid_key_file_name = "svid_key.pem"\n'
                    'svid_bundle_file_name = "bundle.pem"\n'
                    'renew_signal = ""\n'
                )
            },
        }
        client.core_v1.create_namespaced_config_map(namespace=namespace, body=body)
        logger.info(f"Created spiffe-helper ConfigMap in {namespace}")

    def create_passthrough_route(
        self,
        client: OCPClient,
        name: str,
        namespace: str,
        service_name: str,
        host: str,
        target_port: str = "https",
    ) -> Dict[str, Any]:
        """Create a TLS passthrough Route."""
        body = {
            "apiVersion": "route.openshift.io/v1",
            "kind": "Route",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "host": host,
                "port": {"targetPort": target_port},
                "tls": {"termination": "passthrough"},
                "to": {
                    "kind": "Service",
                    "name": service_name,
                    "weight": 100,
                },
            },
        }

        resource = client.get_crd_resource("route.openshift.io/v1", "Route")
        result = resource.create(body=body, namespace=namespace)
        logger.info(f"Created passthrough route: {host}")
        return result.to_dict()

    def exec_mtls_connection(
        self,
        client: OCPClient,
        pod_name: str,
        namespace: str,
        server_host: str,
        port: int = 443,
    ) -> str:
        """Execute an mTLS connection from the client pod to the server."""
        output = client.exec_in_pod(
            name=pod_name,
            namespace=namespace,
            command=[
                "openssl",
                "s_client",
                "-connect", f"{server_host}:{port}",
                "-cert", "/certs/svid.pem",
                "-key", "/certs/svid_key.pem",
                "-CAfile", "/certs/bundle.pem",
                "-verify", "1",
                "-brief",
            ],
            container="client",
        )
        return output


# =============================================================================
# Module-scoped setup/teardown fixture
# =============================================================================


@pytest.fixture(scope="module")
def federation_namespaces(
    ocp_client,
    remote_ocp_client,
    skip_cleanup,
) -> Generator[Dict[str, str], None, None]:
    """
    Create namespaces for mTLS server and client workloads.

    Creates:
    - mtls-server namespace on the local cluster
    - mtls-client namespace on the remote cluster

    Cleans up after the module unless --skip-cleanup is set.
    """
    server_ns = f"mtls-server-{uuid.uuid4().hex[:6]}"
    client_ns = f"mtls-client-{uuid.uuid4().hex[:6]}"

    logger.info(f"Creating federation test namespaces: server={server_ns}, client={client_ns}")

    ocp_client.create_namespace(
        name=server_ns,
        labels={
            "app.kubernetes.io/managed-by": "ztwim-test-framework",
            "ztwim-test/type": "federation-server",
        },
    )
    remote_ocp_client.create_namespace(
        name=client_ns,
        labels={
            "app.kubernetes.io/managed-by": "ztwim-test-framework",
            "ztwim-test/type": "federation-client",
        },
    )

    yield {"server": server_ns, "client": client_ns}

    if not skip_cleanup:
        logger.info("Cleaning up federation test namespaces")
        try:
            ocp_client.delete_namespace(server_ns, wait=False)
        except Exception as e:
            logger.warning(f"Failed to delete server namespace: {e}")
        try:
            remote_ocp_client.delete_namespace(client_ns, wait=False)
        except Exception as e:
            logger.warning(f"Failed to delete client namespace: {e}")


# =============================================================================
# OSSM Cross-Cluster Federation Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def local_client(ocp_client) -> OCPClient:
    """Alias for the local cluster client (matches OSSM test convention)."""
    return ocp_client


@pytest.fixture(scope="module")
def remote_client(remote_ocp_client) -> OCPClient:
    """Alias for the remote cluster client (matches OSSM test convention)."""
    return remote_ocp_client


@pytest.fixture(scope="module")
def local_kubeconfig(kubeconfig_path) -> str:
    """Alias for the local kubeconfig path."""
    return kubeconfig_path


@pytest.fixture(scope="module")
def local_trust_domain(local_app_domain) -> str:
    """Trust domain for the local cluster (derived from apps domain)."""
    return local_app_domain


@pytest.fixture(scope="module")
def remote_trust_domain(remote_app_domain) -> str:
    """Trust domain for the remote cluster (derived from apps domain)."""
    return remote_app_domain


@pytest.fixture(scope="module")
def workload_namespace(request) -> str:
    """Namespace for OSSM federation workloads."""
    return request.config.getoption("--workload-namespace")


@pytest.fixture(scope="module")
def nofed_namespace(request) -> str:
    """Namespace for negative-test workloads (no federatesWith)."""
    return request.config.getoption("--nofed-namespace")


@pytest.fixture(scope="module")
def ossm_namespace(request) -> str:
    """Namespace where Istiod is deployed."""
    return request.config.getoption("--ossm-namespace")


@pytest.fixture(scope="module")
def ossm_timeout(request) -> int:
    """Timeout for OSSM operations."""
    return request.config.getoption("--ossm-timeout")


@pytest.fixture(scope="module")
def local_cluster_name(request) -> str:
    """Cluster A name for multi-cluster config."""
    return request.config.getoption("--local-cluster-name")


@pytest.fixture(scope="module")
def remote_cluster_name(request) -> str:
    """Cluster B name for multi-cluster config."""
    return request.config.getoption("--remote-cluster-name")


@pytest.fixture(scope="module")
def local_ossm_helper(
    request, ocp_client, operator_namespace, ossm_namespace,
) -> OSSMHelper:
    """OSSMHelper for the local cluster."""
    cni_ns = request.config.getoption("--ossm-cni-namespace")
    sail_ver = request.config.getoption("--sail-version")
    cfg = OSSMScenarioConfig(ossm_namespace=ossm_namespace, cni_namespace=cni_ns, sail_version=sail_ver)
    return OSSMHelper(
        client=ocp_client,
        operator_namespace=operator_namespace,
        ossm_namespace=ossm_namespace,
        cni_namespace=cni_ns,
        config=cfg,
    )


@pytest.fixture(scope="module")
def remote_ossm_helper(
    request, remote_ocp_client, operator_namespace, ossm_namespace,
) -> OSSMHelper:
    """OSSMHelper for the remote cluster."""
    cni_ns = request.config.getoption("--ossm-cni-namespace")
    sail_ver = request.config.getoption("--sail-version")
    cfg = OSSMScenarioConfig(ossm_namespace=ossm_namespace, cni_namespace=cni_ns, sail_version=sail_ver)
    return OSSMHelper(
        client=remote_ocp_client,
        operator_namespace=operator_namespace,
        ossm_namespace=ossm_namespace,
        cni_namespace=cni_ns,
        config=cfg,
    )


@pytest.fixture(scope="module")
def ossm_federation_helper(
    ocp_client, remote_ocp_client, operator_namespace,
    local_ossm_helper, remote_ossm_helper,
    local_app_domain, remote_app_domain,
    local_trust_domain, remote_trust_domain,
    kubeconfig_path, remote_kubeconfig,
    ossm_namespace, workload_namespace, nofed_namespace,
    local_cluster_name, remote_cluster_name,
) -> OSSMFederationHelper:
    """OSSMFederationHelper for cross-cluster OSSM + SPIRE federation tests."""
    return OSSMFederationHelper(
        local_client=ocp_client,
        remote_client=remote_ocp_client,
        operator_namespace=operator_namespace,
        local_ossm=local_ossm_helper,
        remote_ossm=remote_ossm_helper,
        local_app_domain=local_app_domain,
        remote_app_domain=remote_app_domain,
        local_trust_domain=local_trust_domain,
        remote_trust_domain=remote_trust_domain,
        local_kubeconfig=kubeconfig_path,
        remote_kubeconfig=remote_kubeconfig,
        ossm_namespace=ossm_namespace,
        workload_namespace=workload_namespace,
        nofed_namespace=nofed_namespace,
        local_cluster_name=local_cluster_name,
        remote_cluster_name=remote_cluster_name,
    )
