#!/usr/bin/env python3
"""
Standalone ZTWIM Installation Script for CI/CD.

This script installs and verifies the ZTWIM stack without running tests.
Useful for CI pipelines that want to separate setup from test execution.

Usage:
    # Install with auto-detected settings
    python scripts/install_ztwim.py

    # Install with custom settings
    python scripts/install_ztwim.py --app-domain apps.example.com --cluster-name prod

    # Skip if already installed
    python scripts/install_ztwim.py --skip-if-exists

Environment Variables:
    KUBECONFIG - Path to kubeconfigFile (required)
    APP_DOMAIN - OpenShift apps domain (optional, auto-detected)
    JWT_ISSUER_ENDPOINT - JWT issuer endpoint (optional, auto-derived)
    CLUSTER_NAME - ZTWIM cluster name (optional, default: test01)

Exit Codes:
    0 - Installation successful
    1 - Installation failed
    2 - Configuration error
"""

import argparse
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.ocp_client.client import OCPClient
from src.ocp_client.spire_crds import ZTWIMFullInstaller
from src.utils.logger import get_logger

logger = get_logger("install_ztwim")


def main():
    parser = argparse.ArgumentParser(
        description="Install and verify ZTWIM stack on OpenShift",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG"),
        help="Path to kubeconfig file (default: $KUBECONFIG)"
    )
    parser.add_argument(
        "--app-domain",
        default=os.environ.get("APP_DOMAIN"),
        help="OpenShift apps domain (auto-detected if not set)"
    )
    parser.add_argument(
        "--cluster-name",
        default=os.environ.get("CLUSTER_NAME", "test01"),
        help="ZTWIM cluster name (default: test01)"
    )
    parser.add_argument(
        "--catalog-name",
        default="redhat-operators",
        help="OLM catalog source (default: redhat-operators)"
    )
    parser.add_argument(
        "--channel",
        default="stable-v1",
        help="OLM subscription channel (default: stable-v1)"
    )
    parser.add_argument(
        "--operator-timeout",
        type=int,
        default=300,
        help="Timeout for operator installation in seconds (default: 300)"
    )
    parser.add_argument(
        "--component-timeout",
        type=int,
        default=120,
        help="Timeout per component verification in seconds (default: 120)"
    )
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        help="Skip installation if ZTWIM is already deployed"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing installation, don't install"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Validate kubeconfig
    if not args.kubeconfig:
        logger.error("KUBECONFIG is required. Set via --kubeconfig or $KUBECONFIG")
        sys.exit(2)
    
    if not os.path.exists(args.kubeconfig):
        logger.error(f"Kubeconfig file not found: {args.kubeconfig}")
        sys.exit(2)
    
    # Set environment variable for consistency
    os.environ["KUBECONFIG"] = args.kubeconfig
    
    try:
        logger.info("=" * 60)
        logger.info("ZTWIM Installation Script")
        logger.info("=" * 60)
        logger.info(f"KUBECONFIG: {args.kubeconfig}")
        logger.info(f"APP_DOMAIN: {args.app_domain or 'auto-detect'}")
        logger.info(f"CLUSTER_NAME: {args.cluster_name}")
        logger.info(f"CATALOG: {args.catalog_name}")
        logger.info(f"CHANNEL: {args.channel}")
        logger.info("")
        
        # Create client
        client = OCPClient(args.kubeconfig)
        
        # Verify cluster connection
        cluster_info = client.get_cluster_info()
        logger.info(f"Connected to cluster: {cluster_info['git_version']}")
        
        # Create installer
        installer = ZTWIMFullInstaller(client)
        
        if args.verify_only:
            # Only verify
            logger.info("Verification-only mode")
            from src.ocp_client.spire_crds import ZTWIMInstallationVerifier
            verifier = ZTWIMInstallationVerifier(client)
            verifier.verify_all(timeout_per_component=args.component_timeout)
            logger.info("✅ Verification passed")
        else:
            # Full installation
            results = installer.install_and_verify(
                app_domain=args.app_domain,
                cluster_name=args.cluster_name,
                catalog_name=args.catalog_name,
                channel=args.channel,
                skip_if_exists=args.skip_if_exists,
                operator_timeout=args.operator_timeout,
                component_timeout=args.component_timeout,
            )
            
            logger.info("")
            logger.info("Installation Results:")
            logger.info(f"  Operator Installed: {results['operator_installed']}")
            logger.info(f"  Operator Ready: {results['operator_ready']}")
            logger.info(f"  Operands Deployed: {results['operands_deployed']}")
            logger.info(f"  Verification Passed: {results['verification_passed']}")
            logger.info(f"  APP_DOMAIN: {results.get('app_domain', 'N/A')}")
            logger.info(f"  CLUSTER_NAME: {results.get('cluster_name', 'N/A')}")
        
        logger.info("")
        logger.info("✅ ZTWIM installation complete - ready for testing")
        sys.exit(0)
        
    except TimeoutError as e:
        logger.error(f"Installation timed out: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

