"""OpenShift client module for ZTWIM Test Framework."""

from .client import OCPClient, get_ocp_client
from .spire_crds import (
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

__all__ = [
    "OCPClient",
    "get_ocp_client",
    "OperatorInstaller",
    "ZTWIMManager",
    "SpireServerManager",
    "SpireAgentManager",
    "SpiffeCSIDriverManager",
    "SpireOIDCDiscoveryManager",
    "ZTWIMStackDeployer",
    "ZTWIMInstallationVerifier",
    "ZTWIMFullInstaller",
]
