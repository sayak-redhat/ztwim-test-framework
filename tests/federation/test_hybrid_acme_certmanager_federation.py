"""
Hybrid federation tests: https_spiffe + https_web (cert-manager ACME, sqlite).

This suite automates the Kubernetes/OpenShift side of:
SPIFFE-ACME-Federation-certmanager-Guide-4.19.md

It validates hybrid trust bootstrap where:
- Local cluster publishes federation bundles with https_spiffe
- Remote cluster publishes federation bundles with https_web using cert-manager
- SPIRE datastore stays default sqlite3 (self-hosted in-cluster)
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator

import pytest
import yaml
from kubernetes.client import ApiException

from src.utils.logger import get_logger
from src.utils.polling import wait_until

logger = get_logger(__name__)

CERT_MANAGER_NS = "cert-manager"
CERT_MANAGER_OPERATOR_NS = "cert-manager-operator"
CRDS_ROOT_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "crds"


@dataclass(frozen=True)
class HybridACMEConfig:
    """Runtime configuration for hybrid ACME federation scenario."""

    letsencrypt_email: str
    cert_secret_name: str
    cert_manager_timeout: int
    install_cert_manager: bool


def _upsert_resource(
    client,
    api_version: str,
    kind: str,
    body: Dict[str, Any],
    namespace: str = "",
) -> Dict[str, Any]:
    """Create resource, patch full body if it already exists."""
    resource = client.get_crd_resource(api_version, kind)
    name = body["metadata"]["name"]
    create_kwargs = {"body": body}
    patch_kwargs = {
        "name": name,
        "body": body,
        "content_type": "application/merge-patch+json",
    }
    if namespace:
        create_kwargs["namespace"] = namespace
        patch_kwargs["namespace"] = namespace

    try:
        result = resource.create(**create_kwargs)
        return result.to_dict()
    except ApiException as exc:
        if exc.status != 409:
            raise
    result = resource.patch(**patch_kwargs)
    return result.to_dict()


def _apply_manifest_file(
    client,
    group: str,
    file_name: str,
    replacements: Dict[str, str],
    namespace_override: str = "",
) -> None:
    """Render and apply one YAML manifest file (supports multi-doc YAML)."""
    manifest_path = CRDS_ROOT_DIR / group / file_name
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest file: {manifest_path}")

    rendered = manifest_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)

    for doc in yaml.safe_load_all(rendered):
        if not doc:
            continue
        api_version = doc["apiVersion"]
        kind = doc["kind"]
        metadata = doc.get("metadata", {})
        namespace = namespace_override or metadata.get("namespace", "")
        _upsert_resource(
            client=client,
            api_version=api_version,
            kind=kind,
            body=doc,
            namespace=namespace,
        )


def _wait_for_cert_manager(remote_ocp_client, timeout: int) -> None:
    """Wait for cert-manager control plane pods to be ready."""
    remote_ocp_client.wait_for_pods_ready(
        namespace=CERT_MANAGER_NS,
        label_selector="app.kubernetes.io/name=cert-manager",
        expected_count=1,
        timeout=timeout,
    )
    remote_ocp_client.wait_for_pods_ready(
        namespace=CERT_MANAGER_NS,
        label_selector="app.kubernetes.io/name=cainjector",
        expected_count=1,
        timeout=timeout,
    )
    remote_ocp_client.wait_for_pods_ready(
        namespace=CERT_MANAGER_NS,
        label_selector="app.kubernetes.io/name=webhook",
        expected_count=1,
        timeout=timeout,
    )


def _ensure_cert_manager(remote_ocp_client, timeout: int, install_if_missing: bool) -> None:
    """Ensure cert-manager is available on the remote cluster."""
    try:
        _wait_for_cert_manager(remote_ocp_client, timeout=60)
        logger.info("cert-manager already ready on remote cluster")
        return
    except Exception:
        if not install_if_missing:
            pytest.fail(
                "cert-manager is not ready on remote cluster. "
                "Set HYBRID_INSTALL_CERT_MANAGER=true to auto-install."
            )

    logger.info("Installing cert-manager operator on remote cluster")
    remote_ocp_client.create_namespace(CERT_MANAGER_OPERATOR_NS)
    replacements = {"CERT_MANAGER_OPERATOR_NAMESPACE": CERT_MANAGER_OPERATOR_NS}
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="operatorgroup.yaml",
        replacements=replacements,
        namespace_override=CERT_MANAGER_OPERATOR_NS,
    )
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="subscription.yaml",
        replacements=replacements,
        namespace_override=CERT_MANAGER_OPERATOR_NS,
    )
    _wait_for_cert_manager(remote_ocp_client, timeout=timeout)


def _wait_for_certificate_ready(client, namespace: str, name: str, timeout: int) -> Dict[str, Any]:
    """Wait until cert-manager Certificate reaches Ready=True."""

    def _check():
        cert = client.get_custom_resource(
            api_version="cert-manager.io/v1",
            kind="Certificate",
            name=name,
            namespace=namespace,
        )
        for cond in cert.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                return cert
        return None

    result = wait_until(
        _check,
        message=f"Certificate {name} ready",
        timeout=timeout,
        interval=10,
    )
    if not result.success:
        raise TimeoutError(f"Certificate {name} was not ready within {timeout}s")
    return result.value


@pytest.fixture(scope="module")
def hybrid_acme_config() -> HybridACMEConfig:
    """Build hybrid ACME scenario config from environment variables."""
    letsencrypt_email = os.environ.get("HYBRID_LETSENCRYPT_EMAIL")
    if not letsencrypt_email:
        pytest.skip(
            "Hybrid ACME scenario not configured. Missing env var: HYBRID_LETSENCRYPT_EMAIL"
        )

    return HybridACMEConfig(
        letsencrypt_email=letsencrypt_email,
        cert_secret_name=os.environ.get("HYBRID_CERT_SECRET_NAME", "spire-server-federation-tls"),
        cert_manager_timeout=int(os.environ.get("HYBRID_CERT_MANAGER_TIMEOUT", "600")),
        install_cert_manager=(
            os.environ.get("HYBRID_INSTALL_CERT_MANAGER", "false").lower() == "true"
        ),
    )


@pytest.fixture(scope="module", autouse=True)
def hybrid_acme_federation_setup(
    hybrid_acme_config: HybridACMEConfig,
    federation_helper,
    ocp_client,
    remote_ocp_client,
    local_app_domain,
    remote_app_domain,
    operator_namespace,
):
    """Configure hybrid federation and cert-manager integration on remote cluster."""
    logger.info("Configuring hybrid federation scenario (https_spiffe + https_web)")

    _ensure_cert_manager(
        remote_ocp_client,
        timeout=hybrid_acme_config.cert_manager_timeout,
        install_if_missing=hybrid_acme_config.install_cert_manager,
    )
    _apply_manifest_file(
        ocp_client,
        group="sqlite",
        file_name="spire-server-sqlite.yaml",
        replacements={},
        namespace_override="",
    )
    _apply_manifest_file(
        remote_ocp_client,
        group="sqlite",
        file_name="spire-server-sqlite.yaml",
        replacements={},
        namespace_override="",
    )

    replacements = {
        "OPERATOR_NAMESPACE": operator_namespace,
        "LETSENCRYPT_EMAIL": hybrid_acme_config.letsencrypt_email,
        "CERT_SECRET_NAME": hybrid_acme_config.cert_secret_name,
        "REMOTE_APP_DOMAIN": remote_app_domain,
    }
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="issuer-letsencrypt.yaml",
        replacements=replacements,
        namespace_override=operator_namespace,
    )
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="certificate-federation.yaml",
        replacements=replacements,
        namespace_override=operator_namespace,
    )
    _wait_for_certificate_ready(
        remote_ocp_client,
        namespace=operator_namespace,
        name=hybrid_acme_config.cert_secret_name,
        timeout=hybrid_acme_config.cert_manager_timeout,
    )
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="router-secret-role.yaml",
        replacements=replacements,
        namespace_override=operator_namespace,
    )
    _apply_manifest_file(
        remote_ocp_client,
        group="cert-manager",
        file_name="router-secret-rolebinding.yaml",
        replacements=replacements,
        namespace_override=operator_namespace,
    )

    federation_helper.enable_federation_on_spire_server(
        client=ocp_client,
        remote_trust_domain=remote_app_domain,
        remote_app_domain=remote_app_domain,
        local_bundle_profile="https_spiffe",
        remote_bundle_profile="https_web",
    )
    federation_helper.enable_federation_on_spire_server(
        client=remote_ocp_client,
        remote_trust_domain=local_app_domain,
        remote_app_domain=local_app_domain,
        local_bundle_profile="https_web",
        remote_bundle_profile="https_spiffe",
        endpoint_spiffe_id=f"spiffe://{local_app_domain}/spire/server",
        https_web_secret_ref=hybrid_acme_config.cert_secret_name,
    )

    ocp_client.wait_for_pods_ready(
        namespace=operator_namespace,
        label_selector="app.kubernetes.io/name=spire-server",
        expected_count=1,
        timeout=300,
    )
    remote_ocp_client.wait_for_pods_ready(
        namespace=operator_namespace,
        label_selector="app.kubernetes.io/name=spire-server",
        expected_count=1,
        timeout=300,
    )
    yield


@pytest.fixture(scope="module")
def hybrid_cfdt_names(
    skip_cleanup, federation_helper, ocp_client, remote_ocp_client
) -> Generator[Dict[str, str], None, None]:
    """Provide CFDT names and cleanup resources at module end."""
    names = {
        "local": f"cluster-12-hybrid-{uuid.uuid4().hex[:6]}",
        "remote": f"cluster-21-hybrid-{uuid.uuid4().hex[:6]}",
    }
    yield names
    if skip_cleanup:
        return
    federation_helper.delete_cluster_federated_trust_domain(ocp_client, names["local"])
    federation_helper.delete_cluster_federated_trust_domain(remote_ocp_client, names["remote"])


@pytest.mark.federation
@pytest.mark.acme_certmanager
@pytest.mark.order(20)
class TestHybridACMECertManagerFederation:
    """Validate hybrid profile federation with cert-manager-issued TLS certs."""

    def test_local_spire_server_uses_sqlite(self, ocp_client):
        """Verify local SpireServer spec still uses sqlite datastore."""
        server = ocp_client.get_custom_resource(
            api_version="operator.openshift.io/v1alpha1",
            kind="SpireServer",
            name="cluster",
            namespace="",
        )
        datastore = server.get("spec", {}).get("datastore", {})
        assert datastore.get("databaseType") == "sqlite3", (
            f"Expected sqlite3 datastore on local, got '{datastore.get('databaseType')}'"
        )

    def test_remote_spire_server_uses_sqlite(self, remote_ocp_client):
        """Verify remote SpireServer spec still uses sqlite datastore."""
        server = remote_ocp_client.get_custom_resource(
            api_version="operator.openshift.io/v1alpha1",
            kind="SpireServer",
            name="cluster",
            namespace="",
        )
        datastore = server.get("spec", {}).get("datastore", {})
        assert datastore.get("databaseType") == "sqlite3", (
            f"Expected sqlite3 datastore on remote, got '{datastore.get('databaseType')}'"
        )

    def test_remote_uses_https_web_external_cert(self, remote_ocp_client, operator_namespace):
        """Verify remote bundle endpoint is https_web with externalSecretRef configured."""
        server = remote_ocp_client.get_custom_resource(
            api_version="operator.openshift.io/v1alpha1",
            kind="SpireServer",
            name="cluster",
            namespace="",
        )
        bundle_endpoint = server.get("spec", {}).get("federation", {}).get("bundleEndpoint", {})
        assert bundle_endpoint.get("profile") == "https_web", "Remote profile is not https_web"
        cert_ref = (
            bundle_endpoint.get("httpsWeb", {})
            .get("servingCert", {})
            .get("externalSecretRef")
        )
        assert cert_ref, "externalSecretRef missing for remote https_web serving cert"
        secret = remote_ocp_client.core_v1.read_namespaced_secret(
            name=cert_ref, namespace=operator_namespace
        )
        assert secret is not None, f"Referenced secret '{cert_ref}' not found"

    def test_create_cfdt_local_to_remote_https_web(
        self,
        federation_helper,
        ocp_client,
        remote_ocp_client,
        remote_app_domain,
        hybrid_cfdt_names,
    ):
        """Create local CFDT that trusts remote https_web endpoint."""
        remote_bundle = federation_helper.fetch_trust_bundle_via_exec(remote_ocp_client)
        result = federation_helper.create_cluster_federated_trust_domain(
            client=ocp_client,
            name=hybrid_cfdt_names["local"],
            remote_trust_domain=remote_app_domain,
            remote_app_domain=remote_app_domain,
            trust_bundle_json=remote_bundle,
            profile_type="https_web",
        )
        assert result.get("metadata", {}).get("name") == hybrid_cfdt_names["local"]

    def test_create_cfdt_remote_to_local_https_spiffe(
        self,
        federation_helper,
        ocp_client,
        remote_ocp_client,
        local_app_domain,
        hybrid_cfdt_names,
    ):
        """Create remote CFDT that trusts local https_spiffe endpoint."""
        local_bundle = federation_helper.fetch_trust_bundle_via_exec(ocp_client)
        result = federation_helper.create_cluster_federated_trust_domain(
            client=remote_ocp_client,
            name=hybrid_cfdt_names["remote"],
            remote_trust_domain=local_app_domain,
            remote_app_domain=local_app_domain,
            trust_bundle_json=local_bundle,
            profile_type="https_spiffe",
            endpoint_spiffe_id=f"spiffe://{local_app_domain}/spire/server",
        )
        assert result.get("metadata", {}).get("name") == hybrid_cfdt_names["remote"]

    def test_bundle_sync_local(
        self, federation_helper, ocp_client, remote_app_domain, federation_timeout
    ):
        """Verify local cluster sees remote trust domain in bundle list."""

        def _check():
            output = federation_helper.list_federated_bundles(ocp_client)
            return output if remote_app_domain in output else None

        result = wait_until(
            _check,
            message="Local federated bundle sync",
            timeout=federation_timeout,
            interval=10,
        )
        assert result.success, f"Remote trust domain {remote_app_domain} not visible on local"

    def test_bundle_sync_remote(
        self, federation_helper, remote_ocp_client, local_app_domain, federation_timeout
    ):
        """Verify remote cluster sees local trust domain in bundle list."""

        def _check():
            output = federation_helper.list_federated_bundles(remote_ocp_client)
            return output if local_app_domain in output else None

        result = wait_until(
            _check,
            message="Remote federated bundle sync",
            timeout=federation_timeout,
            interval=10,
        )
        assert result.success, f"Local trust domain {local_app_domain} not visible on remote"
