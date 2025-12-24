"""
Pytest configuration and fixtures for ZTWIM Test Framework.

This file contains all the fixtures needed to test ZTWIM/SPIRE components
on OpenShift clusters.

ZTWIM Operator Installation (manual):
    export APP_DOMAIN=apps.$(oc get dns cluster -o jsonpath='{ .spec.baseDomain }')
    export JWT_ISSUER_ENDPOINT=oidc-discovery.${APP_DOMAIN}
    export CLUSTER_NAME=test01
    
    # Then apply operator manifests...

Usage:
    pytest tests/ --kubeconfig=/path/to/kubeconfig
    
    Or set KUBECONFIG environment variable:
    export KUBECONFIG=/path/to/kubeconfig
    pytest tests/

HTML Reports:
    Reports are automatically generated in test-reports/ directory
    with timestamp: test-report-YYYY-MM-DD_HH-MM-SS.html
    
    The report includes:
    - Test results (pass/fail/skip)
    - Code coverage summary
    - Detailed logs
"""

import os
import uuid
from datetime import datetime
from typing import Generator, Optional

import pytest

from src.ocp_client.client import OCPClient
from src.ocp_client.spire_crds import (
    OperatorInstaller,
    ZTWIMManager,
    SpireServerManager,
    SpireAgentManager,
    SpiffeCSIDriverManager,
    SpireOIDCDiscoveryManager,
    ZTWIMStackDeployer,
    ZTWIMInstallationVerifier,
    ZTWIMFullInstaller,
)
from src.utils.config import get_settings, set_kubeconfig
from src.utils.logger import get_logger, log_test_start, log_test_end

logger = get_logger("fixtures")


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    import shutil
    
    # Set KUBECONFIG from command line option if provided
    kubeconfig = config.getoption("--kubeconfig", default=None)
    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig
        logger.info(f"Using kubeconfig from CLI: {kubeconfig}")
    
    # Create timestamped directory for this test run
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_report_dir = os.path.join(os.path.dirname(__file__), "test-reports")
    run_report_dir = os.path.join(base_report_dir, timestamp)
    os.makedirs(run_report_dir, exist_ok=True)
    
    # Set paths for this run
    report_path = os.path.join(run_report_dir, "test-report.html")
    coverage_dir = os.path.join(run_report_dir, "coverage")
    
    # Set the HTML report path dynamically
    config.option.htmlpath = report_path
    
    # Set custom CSS for better styling
    css_path = os.path.join(os.path.dirname(__file__), "assets", "pytest-html-style.css")
    if os.path.exists(css_path):
        config.option.css = [css_path]
    
    # Store paths for coverage report
    config._report_timestamp = timestamp
    config._run_report_dir = run_report_dir
    config._coverage_dir = coverage_dir
    config._base_report_dir = base_report_dir
    
    # Update coverage report path (override pyproject.toml setting)
    if hasattr(config.option, 'cov_report'):
        # Find and update HTML report path
        new_cov_reports = {}
        for report_type, path in (config.option.cov_report or {}).items():
            if report_type == 'html':
                new_cov_reports['html'] = coverage_dir
            else:
                new_cov_reports[report_type] = path
        config.option.cov_report = new_cov_reports
    
    # Create 'latest' symlink
    latest_symlink = os.path.join(base_report_dir, "latest")
    if os.path.exists(latest_symlink) or os.path.islink(latest_symlink):
        os.remove(latest_symlink)
    try:
        os.symlink(timestamp, latest_symlink, target_is_directory=True)
    except OSError:
        pass  # Symlinks might not work on all systems
    
    # =========================================================================
    # Keep only 5 latest reports - cleanup old ones
    # =========================================================================
    MAX_REPORTS = 5
    try:
        # Get all timestamped directories (exclude 'latest' symlink)
        all_dirs = []
        for entry in os.listdir(base_report_dir):
            entry_path = os.path.join(base_report_dir, entry)
            # Skip 'latest' symlink and non-directories
            if entry == "latest" or os.path.islink(entry_path):
                continue
            if os.path.isdir(entry_path):
                # Validate timestamp format (YYYY-MM-DD_HH-MM-SS)
                try:
                    datetime.strptime(entry, "%Y-%m-%d_%H-%M-%S")
                    all_dirs.append(entry)
                except ValueError:
                    pass  # Not a timestamped directory
        
        # Sort by timestamp (newest first)
        all_dirs.sort(reverse=True)
        
        # Delete old reports beyond MAX_REPORTS
        if len(all_dirs) > MAX_REPORTS:
            dirs_to_delete = all_dirs[MAX_REPORTS:]
            for old_dir in dirs_to_delete:
                old_path = os.path.join(base_report_dir, old_dir)
                logger.debug(f"Removing old report: {old_dir}")
                shutil.rmtree(old_path, ignore_errors=True)
            logger.info(f"🧹 Cleaned up {len(dirs_to_delete)} old report(s), keeping latest {MAX_REPORTS}")
    except Exception as e:
        logger.debug(f"Could not cleanup old reports: {e}")
    
    logger.info(f"")
    logger.info(f"📁 Report directory: {run_report_dir}")
    logger.info(f"   ├── test-report.html")
    logger.info(f"   └── coverage/")
    logger.info(f"")


def pytest_html_report_title(report):
    """Customize HTML report title."""
    report.title = "ZTWIM Operator Tests - OpenShift"


@pytest.hookimpl(optionalhook=True)
def pytest_metadata(metadata):
    """Customize metadata in HTML report Environment section."""
    # Clear default metadata (Python, Platform, Packages, Plugins)
    metadata.clear()
    
    # Try to get OpenShift version from cluster
    try:
        from kubernetes import client, config as k8s_config
        
        # Load kubeconfig
        kubeconfig = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config"))
        k8s_config.load_kube_config(config_file=kubeconfig)
        
        # Get cluster version from OpenShift ClusterVersion resource
        custom_api = client.CustomObjectsApi()
        cluster_version = custom_api.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="clusterversions",
            name="version"
        )
        
        # Extract version info
        ocp_version = cluster_version.get("status", {}).get("desired", {}).get("version", "Unknown")
        
        # Add OpenShift version to metadata (no cluster ID for cleaner report)
        metadata["OpenShift Version"] = ocp_version
        
        logger.info(f"Detected OpenShift version: {ocp_version}")
        
    except Exception as e:
        logger.warning(f"Could not detect OpenShift version: {e}")
        metadata["OpenShift Version"] = "Not detected (check KUBECONFIG)"


def pytest_html_results_summary(prefix, summary, postfix):
    """Add custom summary to HTML report with coverage data."""
    from datetime import datetime
    
    # Header section - simple white background with dark text for visibility
    prefix.extend([
        '<div style="margin: 20px 0; padding: 24px; background: #FFFFFF; border-radius: 8px; border-left: 5px solid #CC0000; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">',
        '<h2 style="margin: 0 0 8px 0; color: #000000; font-size: 24px; font-weight: bold;">🔐 ZTWIM Operator Test Results</h2>',
        '<p style="margin: 0; color: #333333; font-size: 14px;">Zero Trust Workload Identity Manager - OpenShift Operator Validation</p>',
        f'<p style="margin: 8px 0 0 0; color: #666666; font-size: 12px;">📅 Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
        '</div>',
    ])
    
    # Try to add coverage summary
    try:
        from coverage import Coverage
        from io import StringIO
        
        cov = Coverage()
        cov.load()
        
        # Get coverage data
        output = StringIO()
        total = cov.report(file=output)
        
        # Create detailed coverage summary HTML
        if total is not None:
            coverage_color = "#3E8635" if total >= 80 else "#F0AB00" if total >= 50 else "#C9190B"
            status_text = "Excellent" if total >= 80 else "Good" if total >= 50 else "Needs Improvement"
            
            prefix.extend([
                '<div style="margin: 20px 0; padding: 20px; background: #FFFFFF; border-radius: 8px; border: 1px solid #CCCCCC;">',
                '<h3 style="margin: 0 0 12px 0; color: #000000; font-size: 18px; font-weight: bold;">📊 Code Coverage Summary</h3>',
                
                # Simple progress bar
                '<div style="width: 100%; height: 24px; background: #EEEEEE; border-radius: 4px; overflow: hidden; margin-bottom: 12px;">',
                f'<div style="width: {total:.1f}%; height: 100%; background: {coverage_color}; display: flex; align-items: center; justify-content: center;">',
                f'<span style="color: #FFFFFF; font-weight: bold; font-size: 12px;">{total:.1f}%</span>',
                '</div>',
                '</div>',
                
                # Simple stats
                '<table style="width: 100%; border-collapse: collapse;">',
                '<tr>',
                f'<td style="padding: 10px; text-align: center; border: 1px solid #DDDDDD; background: #F9F9F9;"><strong style="font-size: 24px; color: {coverage_color};">{total:.1f}%</strong><br/><span style="color: #666666; font-size: 11px;">COVERAGE</span></td>',
                f'<td style="padding: 10px; text-align: center; border: 1px solid #DDDDDD; background: #F9F9F9;"><strong style="font-size: 16px; color: {coverage_color};">{status_text}</strong><br/><span style="color: #666666; font-size: 11px;">STATUS</span></td>',
                '</tr>',
                '</table>',
                
                # Link
                '<p style="margin: 12px 0 0 0; font-size: 12px;">',
                '📁 <a href="coverage/index.html" style="color: #0066CC;">View detailed coverage report →</a>',
                '</p>',
                '</div>',
            ])
    except Exception:
        # Coverage not available
        prefix.extend([
            '<div style="margin: 20px 0; padding: 16px; background: #FFF3CD; border-radius: 8px; border-left: 4px solid #F0AB00;">',
            '<p style="margin: 0; color: #856404;">⚠️ Coverage data not available. Run with --cov to enable.</p>',
            '</div>',
        ])
    


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Enhance test reports with additional metadata."""
    outcome = yield
    report = outcome.get_result()
    
    # Add extra info to the report
    report.description = str(item.function.__doc__) if item.function.__doc__ else ""
    
    # Add markers as tags
    markers = [marker.name for marker in item.iter_markers()]
    if markers:
        report.markers = ", ".join(markers)


def pytest_sessionfinish(session, exitstatus):
    """Generate combined report after session finishes."""
    run_report_dir = getattr(session.config, '_run_report_dir', None)
    base_report_dir = getattr(session.config, '_base_report_dir', None)
    coverage_dir = getattr(session.config, '_coverage_dir', None)
    
    if not run_report_dir or not base_report_dir:
        return
    
    # Generate HTML coverage report to the timestamped directory
    if coverage_dir:
        try:
            from coverage import Coverage
            cov = Coverage()
            cov.load()
            os.makedirs(coverage_dir, exist_ok=True)
            cov.html_report(directory=coverage_dir, title="ZTWIM Test Framework - Coverage Report")
            logger.info(f"📊 Coverage HTML report generated: {coverage_dir}")
        except Exception as e:
            logger.warning(f"Could not generate coverage HTML report: {e}")
    
    # Create 'latest' symlink pointing to this run
    latest_link = os.path.join(base_report_dir, "latest")
    try:
        # Remove existing symlink if present
        if os.path.islink(latest_link):
            os.unlink(latest_link)
        elif os.path.exists(latest_link):
            import shutil
            shutil.rmtree(latest_link)
        
        # Create relative symlink
        run_dir_name = os.path.basename(run_report_dir)
        os.symlink(run_dir_name, latest_link)
        
    except Exception as e:
        logger.debug(f"Could not create 'latest' symlink: {e}")
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 TEST REPORTS GENERATED")
    logger.info("=" * 60)
    logger.info(f"")
    logger.info(f"📁 {run_report_dir}/")
    logger.info(f"   ├── test-report.html    ← Test results (pass/fail)")
    logger.info(f"   └── coverage/index.html ← Code coverage details")
    logger.info(f"")
    logger.info(f"🔗 Quick access: {latest_link}/test-report.html")
    logger.info("=" * 60)


# ============================================================================
# Pytest Hooks and Configuration
# ============================================================================

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--kubeconfig",
        action="store",
        default=None,
        help="Path to kubeconfig file"
    )
    parser.addoption(
        "--operator-namespace",
        action="store",
        default="zero-trust-workload-identity-manager",
        help="Namespace where ZTWIM operator is installed"
    )
    parser.addoption(
        "--skip-cleanup",
        action="store_true",
        default=False,
        help="Skip cleanup of test resources after tests"
    )
    parser.addoption(
        "--skip-install",
        action="store_true",
        default=False,
        help="Skip ZTWIM installation (assumes already deployed)"
    )
    parser.addoption(
        "--app-domain",
        action="store",
        default=None,
        help="OpenShift apps domain (auto-detected if not set)"
    )
    parser.addoption(
        "--cluster-name",
        action="store",
        default="test01",
        help="ZTWIM cluster name"
    )
    parser.addoption(
        "--operator-timeout",
        action="store",
        type=int,
        default=300,
        help="Timeout for operator installation (seconds)"
    )
    parser.addoption(
        "--component-timeout",
        action="store",
        type=int,
        default=120,
        help="Timeout per component verification (seconds)"
    )
    parser.addoption(
        "--keep-ztwim",
        action="store_true",
        default=False,
        help="Keep ZTWIM installed after tests (default: cleanup after tests)"
    )
    parser.addoption(
        "--cleanup-ztwim",
        action="store_true",
        default=False,
        help="[DEPRECATED] Cleanup is now default. Use --keep-ztwim to skip cleanup."
    )
    parser.addoption(
        "--cleanup-only",
        action="store_true",
        default=False,
        help="Only run cleanup (uninstall ZTWIM), skip all tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers."""
    for item in items:
        # Add component markers based on file path
        if "spire_server" in str(item.fspath):
            item.add_marker(pytest.mark.spire_server)
        elif "spire_agent" in str(item.fspath):
            item.add_marker(pytest.mark.spire_agent)
        elif "oidc_discovery" in str(item.fspath):
            item.add_marker(pytest.mark.oidc_discovery)
        elif "workload_identity" in str(item.fspath):
            item.add_marker(pytest.mark.workload_identity)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Log test start."""
    log_test_start(item.name)


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    """Log test end."""
    passed = item.rep_call.passed if hasattr(item, 'rep_call') else True
    log_test_end(item.name, passed)


# ============================================================================
# Session-scoped Fixtures (Created once per test session)
# ============================================================================

@pytest.fixture(scope="session")
def kubeconfig_path(request) -> str:
    """
    Get kubeconfig path and set as environment variable.
    
    Priority:
    1. --kubeconfig CLI argument
    2. KUBECONFIG environment variable
    3. ~/.kube/config default
    """
    cli_kubeconfig = request.config.getoption("--kubeconfig")
    kubeconfig = set_kubeconfig(cli_kubeconfig)
    logger.info(f"Using kubeconfig: {kubeconfig}")
    return kubeconfig


@pytest.fixture(scope="session")
def ocp_client(kubeconfig_path) -> OCPClient:
    """Create an OpenShift client for the test session."""
    client = OCPClient(kubeconfig_path)
    
    try:
        cluster_info = client.get_cluster_info()
        logger.info(f"Connected to cluster: {cluster_info['git_version']}")
        
        if client.is_openshift():
            logger.info("Cluster type: OpenShift")
        else:
            logger.info("Cluster type: Kubernetes")
    except Exception as e:
        logger.error(f"Failed to connect to cluster: {e}")
        raise
    
    return client


@pytest.fixture(scope="session")
def settings():
    """Get framework settings."""
    return get_settings()


# ============================================================================
# ZTWIM Auto-Installation Fixture (Runs BEFORE all tests)
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def ztwim_setup(request, ocp_client, settings):
    """
    Automatically install and verify ZTWIM stack before running tests.
    
    This fixture runs ONCE at the start of the test session and:
    1. Creates the operator namespace
    2. Installs the operator (OperatorGroup + Subscription)
    3. Waits for operator to be ready
    4. Creates all operand CRs (ZeroTrustWorkloadIdentityManager, SpireServer, etc.)
    5. Verifies all components are ready
    
    Use --skip-install to skip installation if ZTWIM is already deployed.
    Use --cleanup-only to only run cleanup without tests.
    """
    cleanup_only = request.config.getoption("--cleanup-only")
    skip_install = request.config.getoption("--skip-install")
    
    # Handle --cleanup-only mode: just cleanup and skip all tests
    if cleanup_only:
        logger.info("")
        logger.info("🧹 CLEANUP-ONLY MODE - Uninstalling ZTWIM stack...")
        logger.info("")
        
        try:
            installer = ZTWIMFullInstaller(ocp_client)
            installer.uninstall_all(timeout=180)
            logger.info("✅ ZTWIM cleanup complete")
        except Exception as e:
            logger.warning(f"Cleanup encountered issues: {e}")
            # Try force delete namespace as fallback
            try:
                logger.info("Attempting force delete of namespace...")
                ocp_client.delete_namespace(
                    "zero-trust-workload-identity-manager", 
                    wait=True, 
                    timeout=120
                )
                logger.info("✅ Namespace force deleted")
            except Exception as e2:
                logger.error(f"Force delete also failed: {e2}")
                logger.error("Manual cleanup may be required:")
                logger.error("  oc delete ns zero-trust-workload-identity-manager --force --grace-period=0")
        
        pytest.skip("Cleanup-only mode: skipping all tests")
        yield
        return
    
    if skip_install:
        logger.info("Skipping ZTWIM installation (--skip-install flag set)")
        logger.info("Assuming ZTWIM stack is already deployed")
        
        # Still verify the installation
        verifier = ZTWIMInstallationVerifier(ocp_client)
        try:
            verifier.verify_all(timeout_per_component=60)
            logger.info("✅ Existing ZTWIM installation verified")
        except Exception as e:
            pytest.fail(f"ZTWIM verification failed. Is it deployed? Error: {e}")
        
        yield
        return
    
    # Get configuration
    app_domain = request.config.getoption("--app-domain") or os.environ.get("APP_DOMAIN")
    cluster_name = request.config.getoption("--cluster-name") or os.environ.get("CLUSTER_NAME", "test01")
    operator_timeout = request.config.getoption("--operator-timeout")
    component_timeout = request.config.getoption("--component-timeout")
    
    installer = ZTWIMFullInstaller(ocp_client)
    
    try:
        results = installer.install_and_verify(
            app_domain=app_domain,
            cluster_name=cluster_name,
            skip_if_exists=True,
            operator_timeout=operator_timeout,
            component_timeout=component_timeout,
        )
        
        logger.info("✅ ZTWIM setup complete - ready to run tests")
        
    except Exception as e:
        pytest.fail(f"ZTWIM installation/verification failed: {e}")
    
    yield
    
    # Cleanup after tests (DEFAULT: always cleanup, use --keep-ztwim to skip)
    keep_ztwim = request.config.getoption("--keep-ztwim")
    if keep_ztwim:
        logger.info("")
        logger.info("⏭️  Skipping ZTWIM cleanup (--keep-ztwim flag set)")
        logger.info("   ZTWIM stack remains deployed for next run")
    else:
        logger.info("")
        logger.info("🧹 Cleaning up ZTWIM stack after tests...")
        try:
            installer = ZTWIMFullInstaller(ocp_client)
            installer.uninstall_all(timeout=180)
            logger.info("✅ ZTWIM cleanup complete - cluster is clean")
        except Exception as e:
            logger.warning(f"Cleanup failed (non-fatal): {e}")
            logger.warning("You may need to manually cleanup:")
            logger.warning("  oc delete ns zero-trust-workload-identity-manager")


@pytest.fixture(scope="session")
def operator_namespace(request) -> str:
    """Get the ZTWIM operator namespace."""
    return request.config.getoption("--operator-namespace")


@pytest.fixture(scope="session")
def app_domain(request, ocp_client) -> str:
    """
    Get the OpenShift apps domain.
    
    Auto-detected from cluster DNS if not provided.
    """
    cli_domain = request.config.getoption("--app-domain")
    if cli_domain:
        return cli_domain
    
    # Check environment variable
    if os.environ.get("APP_DOMAIN"):
        return os.environ["APP_DOMAIN"]
    
    # Auto-detect from cluster
    try:
        dns = ocp_client.custom_objects.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="dnses",
            name="cluster"
        )
        base_domain = dns.get("spec", {}).get("baseDomain", "")
        domain = f"apps.{base_domain}"
        logger.info(f"Auto-detected APP_DOMAIN: {domain}")
        return domain
    except Exception as e:
        pytest.fail(f"Could not determine APP_DOMAIN: {e}")


@pytest.fixture(scope="session")
def jwt_issuer_endpoint(app_domain) -> str:
    """Get JWT issuer endpoint."""
    if os.environ.get("JWT_ISSUER_ENDPOINT"):
        return os.environ["JWT_ISSUER_ENDPOINT"]
    return f"oidc-discovery.{app_domain}"


@pytest.fixture(scope="session")
def cluster_name(request) -> str:
    """Get ZTWIM cluster name."""
    if os.environ.get("CLUSTER_NAME"):
        return os.environ["CLUSTER_NAME"]
    return request.config.getoption("--cluster-name")


@pytest.fixture(scope="session")
def skip_cleanup(request) -> bool:
    """Check if cleanup should be skipped."""
    return request.config.getoption("--skip-cleanup")


# ============================================================================
# CRD Manager Fixtures (Session-scoped)
# ============================================================================

@pytest.fixture(scope="session")
def operator_installer(ocp_client) -> OperatorInstaller:
    """Get operator installer helper."""
    return OperatorInstaller(ocp_client)


@pytest.fixture(scope="session")
def ztwim_manager(ocp_client) -> ZTWIMManager:
    """Get ZeroTrustWorkloadIdentityManager CRD manager."""
    return ZTWIMManager(ocp_client)


@pytest.fixture(scope="session")
def spire_server_manager(ocp_client) -> SpireServerManager:
    """Get SpireServer CRD manager."""
    return SpireServerManager(ocp_client)


@pytest.fixture(scope="session")
def spire_agent_manager(ocp_client) -> SpireAgentManager:
    """Get SpireAgent CRD manager."""
    return SpireAgentManager(ocp_client)


@pytest.fixture(scope="session")
def csi_driver_manager(ocp_client) -> SpiffeCSIDriverManager:
    """Get SpiffeCSIDriver CRD manager."""
    return SpiffeCSIDriverManager(ocp_client)


@pytest.fixture(scope="session")
def oidc_manager(ocp_client) -> SpireOIDCDiscoveryManager:
    """Get SpireOIDCDiscoveryProvider CRD manager."""
    return SpireOIDCDiscoveryManager(ocp_client)


@pytest.fixture(scope="session")
def stack_deployer(ocp_client) -> ZTWIMStackDeployer:
    """Get ZTWIM stack deployer helper."""
    return ZTWIMStackDeployer(ocp_client)


# ============================================================================
# Module-scoped Fixtures (Created once per test module)
# ============================================================================

@pytest.fixture(scope="module")
def test_namespace(ocp_client, settings, skip_cleanup) -> Generator[str, None, None]:
    """
    Create a test namespace for workload tests.
    
    The namespace is automatically cleaned up after tests unless --skip-cleanup is set.
    """
    prefix = settings.openshift.test_namespace_prefix
    unique_id = str(uuid.uuid4())[:8]
    namespace = f"{prefix}-{unique_id}"
    
    logger.info(f"Creating test namespace: {namespace}")
    ocp_client.create_namespace(
        name=namespace,
        labels={
            "app.kubernetes.io/managed-by": "ztwim-test-framework",
            "ztwim-test/session-id": unique_id,
        }
    )
    
    yield namespace
    
    if not skip_cleanup:
        logger.info(f"Cleaning up test namespace: {namespace}")
        try:
            ocp_client.delete_namespace(namespace, wait=True, timeout=100)
        except Exception as e:
            logger.warning(f"Failed to cleanup namespace {namespace}: {e}")
    else:
        logger.info(f"Skipping cleanup of namespace: {namespace}")


@pytest.fixture(scope="module")
def ztwim_cr(ztwim_manager) -> dict:
    """
    Get the existing ZeroTrustWorkloadIdentityManager CR.
    
    Assumes the operator and ZTWIM CR are already deployed.
    """
    try:
        return ztwim_manager.get("cluster")
    except Exception as e:
        pytest.fail(
            f"ZeroTrustWorkloadIdentityManager 'cluster' not found. "
            f"Please deploy ZTWIM stack first. Error: {e}"
        )


@pytest.fixture(scope="module")
def spire_server(spire_server_manager) -> dict:
    """
    Get the existing SpireServer CR.
    
    Assumes SpireServer is already deployed.
    """
    try:
        return spire_server_manager.get("cluster")
    except Exception as e:
        pytest.fail(
            f"SpireServer 'cluster' not found. "
            f"Please deploy ZTWIM stack first. Error: {e}"
        )


@pytest.fixture(scope="module")
def spire_agent(spire_agent_manager) -> dict:
    """
    Get the existing SpireAgent CR.
    
    Assumes SpireAgent is already deployed.
    """
    try:
        return spire_agent_manager.get("cluster")
    except Exception as e:
        pytest.fail(
            f"SpireAgent 'cluster' not found. "
            f"Please deploy ZTWIM stack first. Error: {e}"
        )


@pytest.fixture(scope="module")
def spiffe_csi_driver(csi_driver_manager) -> dict:
    """
    Get the existing SpiffeCSIDriver CR.
    
    Assumes SpiffeCSIDriver is already deployed.
    """
    try:
        return csi_driver_manager.get("cluster")
    except Exception as e:
        pytest.fail(
            f"SpiffeCSIDriver 'cluster' not found. "
            f"Please deploy ZTWIM stack first. Error: {e}"
        )


@pytest.fixture(scope="module")
def oidc_provider(oidc_manager) -> dict:
    """
    Get the existing SpireOIDCDiscoveryProvider CR.
    
    Assumes SpireOIDCDiscoveryProvider is already deployed.
    """
    try:
        return oidc_manager.get("cluster")
    except Exception as e:
        pytest.fail(
            f"SpireOIDCDiscoveryProvider 'cluster' not found. "
            f"Please deploy ZTWIM stack first. Error: {e}"
        )


# ============================================================================
# Function-scoped Fixtures (Created for each test)
# ============================================================================

@pytest.fixture
def unique_name() -> str:
    """Generate a unique name for test resources."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_labels() -> dict:
    """Standard labels for test resources."""
    return {
        "app.kubernetes.io/managed-by": "ztwim-test-framework",
        "ztwim-test/type": "test-resource",
    }


@pytest.fixture
def wait_timeout(settings) -> int:
    """Get default wait timeout from settings."""
    return settings.testing.default_timeout


@pytest.fixture
def poll_interval(settings) -> int:
    """Get default poll interval from settings."""
    return settings.testing.poll_interval


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def create_test_workload(ocp_client, test_namespace):
    """
    Factory fixture to create test workloads.
    
    Usage in tests:
        def test_something(create_test_workload):
            pod = create_test_workload(name="my-pod", labels={"app": "test"})
    """
    created_pods = []
    
    def _create_workload(
        name: str,
        labels: dict,
        image: str = "registry.access.redhat.com/ubi9/ubi-minimal:latest",
        command: list = None,
        with_spiffe_csi: bool = False
    ):
        """Create a test pod, optionally with SPIFFE CSI volume."""
        from kubernetes import client
        
        volumes = []
        volume_mounts = []
        
        if with_spiffe_csi:
            volumes.append(
                client.V1Volume(
                    name="spiffe-workload-api",
                    csi=client.V1CSIVolumeSource(
                        driver="csi.spiffe.io",
                        read_only=True,
                    )
                )
            )
            volume_mounts.append(
                client.V1VolumeMount(
                    name="spiffe-workload-api",
                    mount_path="/spiffe-workload-api",
                    read_only=True,
                )
            )
        
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=test_namespace,
                labels=labels,
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="test-container",
                        image=image,
                        command=command or ["sleep", "3600"],
                        volume_mounts=volume_mounts if volume_mounts else None,
                    )
                ],
                volumes=volumes if volumes else None,
                restart_policy="Never",
            )
        )
        
        created = ocp_client.core_v1.create_namespaced_pod(
            namespace=test_namespace,
            body=pod
        )
        created_pods.append((name, test_namespace))
        logger.info(f"Created test pod: {name} in {test_namespace}")
        
        return created.to_dict()
    
    yield _create_workload
    
    # Cleanup
    for pod_name, ns in created_pods:
        try:
            ocp_client.core_v1.delete_namespaced_pod(name=pod_name, namespace=ns)
            logger.info(f"Cleaned up test pod: {pod_name}")
        except Exception:
            pass

