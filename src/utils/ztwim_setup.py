"""
ZTWIM setup orchestration utilities.

Uses a strategy-style approach to keep fixture logic in `conftest.py` small and
separate install/verify/cleanup behaviors.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import pytest

from src.ocp_client.client import OCPClient
from src.ocp_client.spire_crds import (
    OperatorInstaller,
    ZTWIMFullInstaller,
    ZTWIMInstallationVerifier,
    ZTWIMStackDeployer,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SetupOptions:
    """Normalized setup options pulled from pytest config/env."""

    cleanup_only_mode: bool
    deployment_mode: str
    keep_deployed: bool
    app_domain: str | None
    cluster_name: str
    operator_timeout: int
    component_timeout: int


class SetupStrategy(Protocol):
    """Strategy interface for session setup behavior."""

    def execute(self, options: SetupOptions, ocp_client: OCPClient) -> None:
        """Run setup strategy or raise on failure."""


class CleanupOnlyStrategy:
    """Only uninstall ZTWIM and skip test execution."""

    def execute(self, options: SetupOptions, ocp_client: OCPClient) -> None:
        logger.info("")
        logger.info("🧹 CLEANUP-ONLY MODE")
        logger.info(f"   Deployment mode: {options.deployment_mode}")
        logger.info("")

        if options.deployment_mode == "bootstrap":
            try:
                logger.info("Removing operator + operands (bootstrap mode)...")
                ZTWIMFullInstaller(ocp_client).uninstall_all(timeout=180)
                logger.info("✅ ZTWIM cleanup complete")
            except Exception as exc:
                logger.warning(f"Cleanup encountered issues: {exc}")
                try:
                    logger.info("Attempting force delete of namespace...")
                    ocp_client.delete_namespace(
                        "zero-trust-workload-identity-manager", wait=True, timeout=120
                    )
                    logger.info("✅ Namespace force deleted")
                except Exception as fallback_exc:
                    logger.error(f"Force delete also failed: {fallback_exc}")
                    logger.error("Manual cleanup may be required:")
                    logger.error(
                        "  oc delete ns zero-trust-workload-identity-manager "
                        "--force --grace-period=0"
                    )
        else:
            deployer = ZTWIMStackDeployer(ocp_client)
            if deployer.is_deployed():
                logger.info("Removing operands only (operator preserved)...")
                try:
                    deployer.delete_all_operands()
                    logger.info("✅ Operands cleaned up")
                except Exception as exc:
                    logger.warning(f"Operand cleanup encountered issues: {exc}")
            else:
                logger.info("✅ No operands deployed - nothing to clean up")

        pytest.skip("Cleanup-only mode: skipping all tests")


class OperatorOnlyStrategy:
    """Require operator presence, then deploy/verify operands."""

    def execute(self, options: SetupOptions, ocp_client: OCPClient) -> None:
        installer = OperatorInstaller(ocp_client)
        if not installer.is_installed():
            pytest.fail(
                "ZTWIM operator is not installed, but --deployment-mode=operator-only "
                "was requested. Install operator first, or use --deployment-mode=bootstrap."
            )

        logger.info("Operator-only mode: operator must already be installed")
        installer.wait_for_operator_ready(timeout=options.operator_timeout)

        deployer = ZTWIMStackDeployer(ocp_client)
        if deployer.is_deployed():
            logger.info("✅ Operands already deployed")
        else:
            logger.info("Deploying operands (operator-only mode)")
            deployer.deploy_all(
                app_domain=options.app_domain,
                cluster_name=options.cluster_name,
                wait=False,
            )

        verifier = ZTWIMInstallationVerifier(ocp_client)
        try:
            verifier.verify_all(timeout_per_component=options.component_timeout)
            logger.info("✅ Operator + operands verified")
        except Exception as exc:
            pytest.fail(f"ZTWIM verification failed in operator-only mode: {exc}")


class BootstrapInstallAndVerifyStrategy:
    """Install operator+operands (if needed) and verify deployment."""

    def execute(self, options: SetupOptions, ocp_client: OCPClient) -> None:
        installer = ZTWIMFullInstaller(ocp_client)
        try:
            installer.install_and_verify(
                app_domain=options.app_domain,
                cluster_name=options.cluster_name,
                skip_if_exists=True,
                operator_timeout=options.operator_timeout,
                component_timeout=options.component_timeout,
            )
            logger.info("✅ ZTWIM setup complete - ready to run tests")
        except Exception as exc:
            pytest.fail(f"ZTWIM installation/verification failed: {exc}")


class ZTWIMSetupOrchestrator:
    """Select and execute setup strategy based on options."""

    def __init__(self, ocp_client: OCPClient):
        self.ocp_client = ocp_client

    @staticmethod
    def from_pytest_request(request) -> SetupOptions:
        """Build setup options from pytest config and environment."""
        deployment_mode = request.config.getoption("deployment_mode")
        use_existing_deployment = request.config.getoption("use_existing_deployment")
        bootstrap_clusters = request.config.getoption("bootstrap_clusters")
        if use_existing_deployment:
            pytest.fail(
                "--use-existing-deployment / --skip-install is no longer supported. "
                "Use --deployment-mode=operator-only or --deployment-mode=bootstrap."
            )
        if bootstrap_clusters:
            deployment_mode = "bootstrap"
        if deployment_mode not in {"operator-only", "bootstrap"}:
            pytest.fail(
                f"Unsupported deployment mode '{deployment_mode}'. "
                "Use --deployment-mode=operator-only or --deployment-mode=bootstrap."
            )

        return SetupOptions(
            cleanup_only_mode=request.config.getoption("cleanup_only_mode"),
            deployment_mode=deployment_mode,
            keep_deployed=request.config.getoption("keep_deployed"),
            app_domain=request.config.getoption("--app-domain")
            or os.environ.get("APP_DOMAIN"),
            cluster_name=request.config.getoption("--cluster-name")
            or os.environ.get("CLUSTER_NAME", "test01"),
            operator_timeout=request.config.getoption("--operator-timeout"),
            component_timeout=request.config.getoption("--component-timeout"),
        )

    def run_setup(self, options: SetupOptions) -> None:
        """Execute selected setup strategy."""
        if options.cleanup_only_mode:
            strategy: SetupStrategy = CleanupOnlyStrategy()
        elif options.deployment_mode == "operator-only":
            strategy = OperatorOnlyStrategy()
        else:
            strategy = BootstrapInstallAndVerifyStrategy()
        strategy.execute(options, self.ocp_client)

    def run_teardown(self, options: SetupOptions) -> None:
        """Run default teardown behavior, respecting deployment mode."""
        if options.cleanup_only_mode:
            return

        if options.keep_deployed:
            logger.info("")
            logger.info("⏭️  Skipping ZTWIM cleanup (--keep-deployed flag set)")
            logger.info("   ZTWIM stack remains deployed for next run")
            return

        logger.info("")
        try:
            if options.deployment_mode == "bootstrap":
                logger.info("🧹 Cleaning up operator + operands (bootstrap mode)...")
                ZTWIMFullInstaller(self.ocp_client).uninstall_all(timeout=180)
                logger.info("✅ ZTWIM cleanup complete")
            else:
                deployer = ZTWIMStackDeployer(self.ocp_client)
                if deployer.is_deployed():
                    logger.info("🧹 Cleaning up operands (operator preserved)...")
                    deployer.delete_all_operands()
                    logger.info("✅ Operands cleaned up")
                else:
                    logger.info("✅ No operands deployed - nothing to clean up")
        except Exception as exc:
            logger.warning(f"Cleanup failed (non-fatal): {exc}")
            logger.warning("You may need to manually cleanup:")
            logger.warning("  oc delete ns zero-trust-workload-identity-manager")
