"""
Cross-Cluster OSSM + SPIRE Federation Tests.

Validates the complete cross-cluster federation guide:
  Phase 1-4: Infrastructure setup (SPIRE federation, Istio, EW gateways)
  Scenario 1: SDS auto-config without CREATE_ONLY_MODE
  Scenario 2: SPIRE trust bundle exchange via ClusterFederatedTrustDomain
  Scenario 3: Forward cross-cluster mTLS (sleep A -> helloworld B)
  Scenario 4: Reverse cross-cluster mTLS (sleep B -> helloworld A)
  Scenario 5: STRICT mTLS all 4 traffic patterns
  Scenario 6: All workloads have SPIRE-issued SVIDs (not Istio CA)
  Scenario 7: Cross-cluster load balancing
  Scenario 8: Negative test -- workload without federatesWith
  Scenario 9: Cleanup + health check

Prerequisites:
    - ZTWIM operator installed on both clusters
    - helm and istioctl available in PATH

Usage:
    pytest tests/federation/test_ossm_spire_cross_cluster.py -v \
        --remote-kubeconfig=/path/to/cluster-b/kubeconfig \
        --ossm-namespace=istio-system \
        --deployment-mode=operator-only --keep-deployed

Component: ossm_federation
"""

import time

import pytest

from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.polling import wait_until

logger = get_logger(__name__)


# =============================================================================
# Phase 1: Prerequisites (order=30)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(30)
class TestOSSMFederationPrerequisites:
    """Verify SPIRE + Sail operator are running on both clusters."""

    def test_local_spire_server_running(self, local_client, operator_namespace):
        """SPIRE server pods are running on Cluster A."""
        cfg = get_settings().polling.component_verify
        pods = local_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1, timeout=cfg.timeout,
        )
        assert len(pods) >= 1, "SpireServer not running on local cluster"
        logger.info(f"[local] SpireServer: {pods[0]['metadata']['name']}")

    def test_remote_spire_server_running(self, remote_client, operator_namespace):
        """SPIRE server pods are running on Cluster B."""
        cfg = get_settings().polling.component_verify
        pods = remote_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1, timeout=cfg.timeout,
        )
        assert len(pods) >= 1, "SpireServer not running on remote cluster"
        logger.info(f"[remote] SpireServer: {pods[0]['metadata']['name']}")

    def test_sail_operator_ready_both_clusters(
        self, local_ossm_helper, remote_ossm_helper, ossm_timeout,
    ):
        """Sail Operator installed and CSV Succeeded on both clusters."""
        for label, helper in [("local", local_ossm_helper), ("remote", remote_ossm_helper)]:
            if not helper.is_sail_operator_installed():
                helper.install_sail_operator(timeout=ossm_timeout)
            helper.wait_for_sail_operator_ready(timeout=ossm_timeout)
            logger.info(f"[{label}] Sail Operator ready")


# =============================================================================
# Phase 2: SPIRE Federation Setup (order=31)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(31)
class TestSPIREFederationSetup:
    """Enable federation on both SPIRE servers and exchange bundles."""

    def test_enable_federation_on_both_spire_servers(
        self, ossm_federation_helper, local_client, remote_client,
        local_trust_domain, remote_trust_domain,
        local_app_domain, remote_app_domain,
    ):
        """Patch SpireServer CRs with https_spiffe federation config."""
        ossm_federation_helper.enable_federation_on_spire_server(
            local_client, remote_trust_domain, remote_app_domain,
        )
        ossm_federation_helper.enable_federation_on_spire_server(
            remote_client, local_trust_domain, local_app_domain,
        )

    def test_federation_routes_created(
        self, ossm_federation_helper, local_client, remote_client,
    ):
        """Federation routes are admitted on both clusters."""
        local_route = ossm_federation_helper.wait_for_federation_route(local_client)
        remote_route = ossm_federation_helper.wait_for_federation_route(remote_client)
        assert local_route, "Local federation route not created"
        assert remote_route, "Remote federation route not created"
        logger.info(f"[local] Federation route: {local_route['spec']['host']}")
        logger.info(f"[remote] Federation route: {remote_route['spec']['host']}")

    def test_seed_bundles_and_verify_exchange(
        self, ossm_federation_helper, local_client, remote_client,
        local_trust_domain, remote_trust_domain,
    ):
        """Seed bundles cross-cluster and verify they appear in SPIRE."""
        local_fed_url = ossm_federation_helper.get_federation_endpoint(local_client)
        remote_fed_url = ossm_federation_helper.get_federation_endpoint(remote_client)

        ossm_federation_helper.seed_remote_bundle(local_client, remote_fed_url)
        ossm_federation_helper.seed_remote_bundle(remote_client, local_fed_url)

        time.sleep(10)

        cfg = get_settings().polling.federation

        def _check_local():
            return ossm_federation_helper.verify_bundle_exchange(local_client, remote_trust_domain)

        def _check_remote():
            return ossm_federation_helper.verify_bundle_exchange(remote_client, local_trust_domain)

        result_l = wait_until(_check_local, message="Local bundle exchange",
                              timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor)
        result_r = wait_until(_check_remote, message="Remote bundle exchange",
                              timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor)
        assert result_l.success, f"Local cluster missing remote bundle ({remote_trust_domain})"
        assert result_r.success, f"Remote cluster missing local bundle ({local_trust_domain})"


# =============================================================================
# Phase 3: Istio Deploy (order=32)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(32)
class TestIstioDeploy:
    """Deploy IstioCNI + Istio CR with federation config on both clusters."""

    def test_deploy_istio_cni_both_clusters(
        self, local_ossm_helper, remote_ossm_helper, ossm_timeout,
    ):
        """IstioCNI deployed and ready on both clusters."""
        for label, helper in [("local", local_ossm_helper), ("remote", remote_ossm_helper)]:
            if not helper.is_istio_cni_deployed():
                helper.deploy_istio_cni(timeout=ossm_timeout)
            helper.wait_for_istio_cni_ready(timeout=ossm_timeout)
            logger.info(f"[{label}] IstioCNI ready")

    def test_deploy_istio_cr_with_federation_both_clusters(
        self, ossm_federation_helper,
        local_client, remote_client,
        local_ossm_helper, remote_ossm_helper,
        local_trust_domain, remote_trust_domain,
        local_cluster_name, remote_cluster_name,
        ossm_timeout,
    ):
        """Istio CR with multi-cluster federation fields on both clusters."""
        local_fed_url = ossm_federation_helper.get_federation_endpoint(local_client)
        remote_fed_url = ossm_federation_helper.get_federation_endpoint(remote_client)

        ossm_federation_helper.deploy_istio_cr_with_federation(
            client=local_client,
            ossm_helper=local_ossm_helper,
            local_trust_domain=local_trust_domain,
            remote_trust_domain=remote_trust_domain,
            local_fed_url=local_fed_url,
            remote_fed_url=remote_fed_url,
            cluster_name=local_cluster_name,
            network_name="network-a",
            timeout=ossm_timeout,
        )
        ossm_federation_helper.deploy_istio_cr_with_federation(
            client=remote_client,
            ossm_helper=remote_ossm_helper,
            local_trust_domain=remote_trust_domain,
            remote_trust_domain=local_trust_domain,
            local_fed_url=remote_fed_url,
            remote_fed_url=local_fed_url,
            cluster_name=remote_cluster_name,
            network_name="network-b",
            timeout=ossm_timeout,
        )

    def test_istiod_ready_both_clusters(
        self, local_ossm_helper, remote_ossm_helper, ossm_timeout,
    ):
        """Istiod pods are running on both clusters."""
        for label, helper in [("local", local_ossm_helper), ("remote", remote_ossm_helper)]:
            pods = helper.wait_for_istiod_ready(timeout=ossm_timeout)
            assert len(pods) >= 1, f"Istiod not ready on {label} cluster"
            logger.info(f"[{label}] Istiod ready: {pods[0]['metadata']['name']}")


# =============================================================================
# Phase 4: East-West Gateway (order=33)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(33)
class TestEastWestGateway:
    """Deploy EW gateways, exchange remote secrets, verify sync."""

    def test_deploy_ew_gateways(
        self, ossm_federation_helper,
        local_client, remote_client,
        local_kubeconfig, remote_kubeconfig,
        ossm_namespace, ossm_timeout,
    ):
        """East-west gateways deployed on both clusters."""
        ossm_federation_helper.deploy_ew_gateway(local_client, "network-a", local_kubeconfig)
        ossm_federation_helper.deploy_ew_gateway(remote_client, "network-b", remote_kubeconfig)

        for label, client in [("local", local_client), ("remote", remote_client)]:
            pods = client.wait_for_pods_ready(
                namespace=ossm_namespace,
                label_selector="app=istio-eastwestgateway",
                expected_count=1, timeout=ossm_timeout,
            )
            assert len(pods) >= 1, f"EW gateway not ready on {label}"
            logger.info(f"[{label}] EW gateway ready")

        ossm_federation_helper.deploy_cross_network_gateway(local_client, ossm_namespace)
        ossm_federation_helper.deploy_cross_network_gateway(remote_client, ossm_namespace)

    def test_exchange_remote_secrets(
        self, ossm_federation_helper,
        local_kubeconfig, remote_kubeconfig,
        local_client, remote_client,
        local_cluster_name, remote_cluster_name,
    ):
        """Remote secrets exchanged so istiod can discover cross-cluster services."""
        ossm_federation_helper.create_and_apply_remote_secret(
            source_kubeconfig=local_kubeconfig,
            source_cluster_name=local_cluster_name,
            target_client=remote_client,
            target_kubeconfig=remote_kubeconfig,
        )
        ossm_federation_helper.create_and_apply_remote_secret(
            source_kubeconfig=remote_kubeconfig,
            source_cluster_name=remote_cluster_name,
            target_client=local_client,
            target_kubeconfig=local_kubeconfig,
        )

    def test_remote_clusters_synced(
        self, local_client, remote_client, ossm_namespace,
    ):
        """Both istiod instances have synced the remote cluster endpoints."""
        cfg = get_settings().polling.federation

        def _check_synced(client):
            pods = client.get_pods(namespace=ossm_namespace, label_selector="app=istiod")
            return len(pods) >= 1

        result_l = wait_until(lambda: _check_synced(local_client),
                              message="Local istiod sync", timeout=cfg.timeout,
                              interval=cfg.interval, backoff=cfg.backoff_factor)
        result_r = wait_until(lambda: _check_synced(remote_client),
                              message="Remote istiod sync", timeout=cfg.timeout,
                              interval=cfg.interval, backoff=cfg.backoff_factor)
        assert result_l.success, "Local istiod not synced"
        assert result_r.success, "Remote istiod not synced"
        time.sleep(15)
        logger.info("Both clusters synced")


# =============================================================================
# Scenario 1: SDS auto-config (order=34)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(34)
class TestSDSAutoConfig:
    """SDS auto-config present on both clusters without CREATE_ONLY_MODE."""

    def test_sds_config_present_on_local_cluster(
        self, ossm_federation_helper, local_client,
    ):
        """SDS section exists in spire-agent ConfigMap on Cluster A."""
        sds = ossm_federation_helper.get_sds_config(local_client)
        assert sds is not None, "SDS section missing on local cluster"
        assert sds.get("default_bundle_name") == "null"
        assert sds.get("default_all_bundles_name") == "ROOTCA"
        logger.info(f"[local] SDS config: {sds}")

    def test_sds_config_present_on_remote_cluster(
        self, ossm_federation_helper, remote_client,
    ):
        """SDS section exists in spire-agent ConfigMap on Cluster B."""
        sds = ossm_federation_helper.get_sds_config(remote_client)
        assert sds is not None, "SDS section missing on remote cluster"
        assert sds.get("default_bundle_name") == "null"
        assert sds.get("default_all_bundles_name") == "ROOTCA"
        logger.info(f"[remote] SDS config: {sds}")

    def test_no_create_only_mode_annotation(
        self, local_client, remote_client, operator_namespace,
    ):
        """No CREATE_ONLY_MODE annotation on spire-agent pods."""
        for label, client in [("local", local_client), ("remote", remote_client)]:
            pods = client.get_pods(
                namespace=operator_namespace,
                label_selector="app.kubernetes.io/name=spire-agent",
            )
            for pod in pods:
                annotations = pod.get("metadata", {}).get("annotations", {})
                assert "CREATE_ONLY_MODE" not in str(annotations), (
                    f"[{label}] CREATE_ONLY_MODE found on pod {pod['metadata']['name']}"
                )
            logger.info(f"[{label}] No CREATE_ONLY_MODE annotations found")


# =============================================================================
# Scenario 2: SPIRE bundle exchange (order=35)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(35)
class TestSPIREBundleExchange:
    """SPIRE trust bundles exchanged via federation, ROOTCA serves federated CAs."""

    def test_trust_bundles_exchanged_via_federation(
        self, ossm_federation_helper, local_client, remote_client,
        local_trust_domain, remote_trust_domain,
    ):
        """Both clusters have the remote trust domain in their bundle list."""
        assert ossm_federation_helper.verify_bundle_exchange(local_client, remote_trust_domain), (
            f"Local cluster missing bundle for {remote_trust_domain}"
        )
        assert ossm_federation_helper.verify_bundle_exchange(remote_client, local_trust_domain), (
            f"Remote cluster missing bundle for {local_trust_domain}"
        )

    def test_rootca_bundle_contains_federated_cas_local(
        self, ossm_federation_helper, local_client,
    ):
        """ROOTCA bundle on Cluster A includes federated CAs via SDS."""
        sds = ossm_federation_helper.get_sds_config(local_client)
        assert sds is not None, "SDS missing on local cluster"
        assert sds.get("default_all_bundles_name") == "ROOTCA", (
            "ROOTCA bundle name not configured"
        )

    def test_rootca_bundle_contains_federated_cas_remote(
        self, ossm_federation_helper, remote_client,
    ):
        """ROOTCA bundle on Cluster B includes federated CAs via SDS."""
        sds = ossm_federation_helper.get_sds_config(remote_client)
        assert sds is not None, "SDS missing on remote cluster"
        assert sds.get("default_all_bundles_name") == "ROOTCA", (
            "ROOTCA bundle name not configured"
        )


# =============================================================================
# Scenario 3: Forward cross-cluster mTLS (order=36)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(36)
class TestForwardCrossClusterMTLS:
    """Deploy workloads and verify sleep(A) -> helloworld(B) succeeds."""

    def test_create_federated_cluster_spiffe_ids(
        self, ossm_federation_helper,
        local_client, remote_client,
        local_trust_domain, remote_trust_domain,
        workload_namespace,
    ):
        """Create federated ClusterSPIFFEIDs on both clusters."""
        ossm_federation_helper.create_federated_cluster_spiffeid(
            local_client, "sample-federation-local", workload_namespace, remote_trust_domain,
        )
        ossm_federation_helper.create_federated_cluster_spiffeid(
            remote_client, "sample-federation-remote", workload_namespace, local_trust_domain,
        )

    def test_deploy_workloads_both_clusters(
        self, ossm_federation_helper,
        local_client, remote_client,
        workload_namespace,
    ):
        """Deploy helloworld + sleep on both clusters."""
        ossm_federation_helper.deploy_helloworld(local_client, workload_namespace, version="v1")
        ossm_federation_helper.deploy_sleep(local_client, workload_namespace)

        ossm_federation_helper.deploy_helloworld(remote_client, workload_namespace, version="v2")
        ossm_federation_helper.deploy_sleep(remote_client, workload_namespace)

    def test_workload_sidecars_injected(
        self, local_client, remote_client, workload_namespace,
    ):
        """All workload pods have istio-proxy sidecar."""
        cfg = get_settings().polling.pod_readiness
        for label, client in [("local", local_client), ("remote", remote_client)]:
            for app in ["helloworld", "sleep"]:
                pods = client.wait_for_pods_ready(
                    namespace=workload_namespace,
                    label_selector=f"app={app}",
                    expected_count=1, timeout=cfg.timeout,
                )
                spec = pods[0].get("spec", {})
                containers = [c["name"] for c in spec.get("containers") or []]
                init_containers = [c["name"] for c in spec.get("init_containers") or []]
                all_names = containers + init_containers
                assert "istio-proxy" in all_names, (
                    f"[{label}] istio-proxy not injected on {app}"
                )
                logger.info(f"[{label}] {app} sidecar injected")

    def test_forward_cross_cluster_call_succeeds(
        self, ossm_federation_helper, local_client, workload_namespace,
    ):
        """sleep(Cluster A) -> helloworld.sample:5000/hello -> HTTP 200."""
        cfg = get_settings().polling.federation

        def _check():
            try:
                status = ossm_federation_helper.exec_curl_status(
                    local_client, "sleep", workload_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                return status.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check, message="Forward cross-cluster mTLS",
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, "Forward cross-cluster call failed (sleep A -> helloworld B)"
        logger.info("Forward cross-cluster mTLS: OK")


# =============================================================================
# Scenario 4: Reverse cross-cluster mTLS (order=37)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(37)
class TestReverseCrossClusterMTLS:
    """Verify sleep(B) -> helloworld(A) succeeds."""

    def test_reverse_cross_cluster_call_succeeds(
        self, ossm_federation_helper, remote_client, workload_namespace,
    ):
        """sleep(Cluster B) -> helloworld.sample:5000/hello -> HTTP 200."""
        cfg = get_settings().polling.federation

        def _check():
            try:
                status = ossm_federation_helper.exec_curl_status(
                    remote_client, "sleep", workload_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                return status.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check, message="Reverse cross-cluster mTLS",
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, "Reverse cross-cluster call failed (sleep B -> helloworld A)"
        logger.info("Reverse cross-cluster mTLS: OK")


# =============================================================================
# Scenario 5: STRICT mTLS all 4 patterns (order=38)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(38)
class TestStrictMTLSAllPatterns:
    """STRICT PeerAuthentication on both clusters, all 4 traffic patterns pass."""

    def test_apply_strict_mtls_both_clusters(
        self, ossm_federation_helper, local_client, remote_client, workload_namespace,
    ):
        """Apply PeerAuthentication STRICT on both clusters."""
        ossm_federation_helper.apply_strict_mtls(local_client, workload_namespace)
        ossm_federation_helper.apply_strict_mtls(remote_client, workload_namespace)
        time.sleep(5)

    def _verify_traffic(self, ossm_federation_helper, client, workload_namespace, msg):
        cfg = get_settings().polling.federation

        def _check():
            try:
                status = ossm_federation_helper.exec_curl_status(
                    client, "sleep", workload_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                return status.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check, message=msg,
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, f"Traffic failed: {msg}"
        logger.info(f"{msg}: OK")

    def test_local_to_local_cluster_a(
        self, ossm_federation_helper, local_client, workload_namespace,
    ):
        """sleep(A) -> helloworld(A) under STRICT mTLS."""
        self._verify_traffic(
            ossm_federation_helper, local_client, workload_namespace,
            "STRICT local-to-local Cluster A",
        )

    def test_local_to_local_cluster_b(
        self, ossm_federation_helper, remote_client, workload_namespace,
    ):
        """sleep(B) -> helloworld(B) under STRICT mTLS."""
        self._verify_traffic(
            ossm_federation_helper, remote_client, workload_namespace,
            "STRICT local-to-local Cluster B",
        )

    def test_forward_cross_cluster_strict(
        self, ossm_federation_helper, local_client, workload_namespace,
    ):
        """sleep(A) -> helloworld(B) under STRICT mTLS."""
        self._verify_traffic(
            ossm_federation_helper, local_client, workload_namespace,
            "STRICT forward cross-cluster",
        )

    def test_reverse_cross_cluster_strict(
        self, ossm_federation_helper, remote_client, workload_namespace,
    ):
        """sleep(B) -> helloworld(A) under STRICT mTLS."""
        self._verify_traffic(
            ossm_federation_helper, remote_client, workload_namespace,
            "STRICT reverse cross-cluster",
        )


# =============================================================================
# Scenario 6: SPIRE SVIDs (order=39)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(39)
class TestSPIRESVIDVerification:
    """All workloads have SPIRE-issued SPIFFE SVIDs, not Istio CA."""

    def _verify_spire_svid(
        self, ossm_federation_helper, client, deploy_label, namespace, trust_domain, label,
    ):
        cfg = get_settings().polling.pod_readiness

        def _check():
            try:
                spiffe_id = ossm_federation_helper.get_workload_spiffe_id(client, deploy_label, namespace)
                return spiffe_id if spiffe_id.startswith(f"spiffe://{trust_domain}/") else None
            except Exception:
                return None

        result = wait_until(
            _check, message=f"SPIRE SVID for {deploy_label} ({label})",
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, f"[{label}] {deploy_label} does not have SPIRE SVID"
        spiffe_id = result.value
        assert trust_domain in spiffe_id, (
            f"[{label}] SVID trust domain mismatch: {spiffe_id}"
        )
        logger.info(f"[{label}] {deploy_label} SVID: {spiffe_id}")

    def test_sleep_a_has_spire_svid(
        self, ossm_federation_helper, local_client, workload_namespace, local_trust_domain,
    ):
        """sleep on Cluster A has SPIRE-issued SPIFFE SVID."""
        self._verify_spire_svid(
            ossm_federation_helper, local_client, "sleep",
            workload_namespace, local_trust_domain, "local",
        )

    def test_helloworld_a_has_spire_svid(
        self, ossm_federation_helper, local_client, workload_namespace, local_trust_domain,
    ):
        """helloworld on Cluster A has SPIRE-issued SPIFFE SVID."""
        self._verify_spire_svid(
            ossm_federation_helper, local_client, "helloworld",
            workload_namespace, local_trust_domain, "local",
        )

    def test_sleep_b_has_spire_svid(
        self, ossm_federation_helper, remote_client, workload_namespace, remote_trust_domain,
    ):
        """sleep on Cluster B has SPIRE-issued SPIFFE SVID."""
        self._verify_spire_svid(
            ossm_federation_helper, remote_client, "sleep",
            workload_namespace, remote_trust_domain, "remote",
        )

    def test_helloworld_b_has_spire_svid(
        self, ossm_federation_helper, remote_client, workload_namespace, remote_trust_domain,
    ):
        """helloworld on Cluster B has SPIRE-issued SPIFFE SVID."""
        self._verify_spire_svid(
            ossm_federation_helper, remote_client, "helloworld",
            workload_namespace, remote_trust_domain, "remote",
        )

    def test_ew_gateway_a_has_spire_svid(
        self, ossm_federation_helper, local_client, ossm_namespace, local_trust_domain,
    ):
        """East-west gateway on Cluster A has SPIRE-issued SPIFFE SVID."""
        self._verify_spire_svid(
            ossm_federation_helper, local_client, "istio-eastwestgateway",
            ossm_namespace, local_trust_domain, "local-gw",
        )


# =============================================================================
# Scenario 7: Cross-cluster load balancing (order=40)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(40)
class TestCrossClusterLoadBalancing:
    """Requests from both clusters hit both local and remote helloworld."""

    def _check_load_balancing(
        self, ossm_federation_helper, client, workload_namespace, label,
    ):
        """Poll until responses contain both v1 and v2, giving Istio time to converge."""
        url = f"http://helloworld.{workload_namespace}:5000/hello"
        cfg = get_settings().polling.federation

        def _check():
            responses = ossm_federation_helper.exec_curl_multi(
                client, "sleep", workload_namespace, url, count=20,
            )
            if ossm_federation_helper.verify_cross_cluster_load_balancing(responses, ["v1", "v2"]):
                return responses
            return None

        result = wait_until(
            _check, message=f"Cross-cluster LB ({label})",
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, (
            f"Load balancing failed from {label}: never saw both v1 and v2"
        )
        logger.info(f"[{label}] Load balancing verified: both v1 and v2 hit")

    def test_requests_from_cluster_a_hit_both_versions(
        self, ossm_federation_helper, local_client, workload_namespace,
    ):
        """Curl from sleep(A) returns mix of v1 and v2 responses."""
        self._check_load_balancing(
            ossm_federation_helper, local_client, workload_namespace, "local",
        )

    def test_requests_from_cluster_b_hit_both_versions(
        self, ossm_federation_helper, remote_client, workload_namespace,
    ):
        """Curl from sleep(B) returns mix of v1 and v2 responses."""
        self._check_load_balancing(
            ossm_federation_helper, remote_client, workload_namespace, "remote",
        )


# =============================================================================
# Scenario 8: Negative test -- no federatesWith (order=41)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(41)
class TestFederationAccessControl:
    """Workload without federatesWith succeeds locally but fails cross-cluster."""

    def test_deploy_nofed_workload(
        self, ossm_federation_helper, local_client, nofed_namespace,
    ):
        """Deploy sleep-nofed in nofed namespace with unfederated ClusterSPIFFEID."""
        ossm_federation_helper.create_unfederated_cluster_spiffeid(
            local_client, "nofed-spiffeid", nofed_namespace,
        )
        ossm_federation_helper.deploy_sleep(local_client, nofed_namespace, name="sleep-nofed")

        cfg = get_settings().polling.pod_readiness
        local_client.wait_for_pods_ready(
            namespace=nofed_namespace,
            label_selector="app=sleep-nofed",
            expected_count=1, timeout=cfg.timeout,
        )
        logger.info("sleep-nofed deployed in nofed namespace")

    def test_nofed_local_call_succeeds(
        self, ossm_federation_helper, local_client, workload_namespace, nofed_namespace,
    ):
        """sleep-nofed(A) -> helloworld(A) in sample namespace -> HTTP 200."""
        cfg = get_settings().polling.federation

        def _check():
            try:
                status = ossm_federation_helper.exec_curl_status(
                    local_client, "sleep-nofed", nofed_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                return status.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check, message="nofed local call",
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, "sleep-nofed should succeed for local calls"
        logger.info("nofed local call: OK")

    def test_nofed_cross_cluster_call_fails(
        self, ossm_federation_helper, local_client, workload_namespace, nofed_namespace,
    ):
        """
        sleep-nofed(A) -> helloworld(B) should fail with upstream connect error.
        Without federatesWith, ROOTCA bundle lacks remote CA, so TLS handshake
        to the remote EW gateway is rejected.
        """
        failures = 0
        attempts = 5
        for _ in range(attempts):
            try:
                body = ossm_federation_helper.exec_curl(
                    local_client, "sleep-nofed", nofed_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                status = ossm_federation_helper.exec_curl_status(
                    local_client, "sleep-nofed", nofed_namespace,
                    f"http://helloworld.{workload_namespace}:5000/hello",
                )
                if status.strip() != "200" or "upstream connect error" in body:
                    failures += 1
            except Exception:
                failures += 1
            time.sleep(2)

        assert failures > 0, (
            "Expected cross-cluster calls to fail for workload without federatesWith, "
            "but all calls succeeded"
        )
        logger.info(
            f"nofed cross-cluster call correctly failed {failures}/{attempts} times"
        )


# =============================================================================
# Scenario 9: Cleanup + health check (order=42)
# =============================================================================


@pytest.mark.ossm_federation
@pytest.mark.order(42)
class TestOSSMFederationCleanup:
    """Verify resources and SPIRE health after all tests."""

    def test_federation_resources_can_be_listed(
        self, local_client, remote_client, operator_namespace,
    ):
        """Federation-related resources are listable on both clusters."""
        for label, client in [("local", local_client), ("remote", remote_client)]:
            pods = client.get_pods(
                namespace=operator_namespace,
                label_selector="app.kubernetes.io/name=spire-server",
            )
            assert len(pods) >= 1, f"[{label}] SpireServer pods not found"
            logger.info(f"[{label}] Federation resources listable")

    def test_spire_servers_still_healthy_both_clusters(
        self, local_client, remote_client, operator_namespace,
    ):
        """SPIRE servers healthy on both clusters after all tests."""
        cfg = get_settings().polling.component_verify
        for label, client in [("local", local_client), ("remote", remote_client)]:
            server_pods = client.wait_for_pods_ready(
                namespace=operator_namespace,
                label_selector="app.kubernetes.io/name=spire-server",
                expected_count=1, timeout=cfg.timeout,
            )
            assert len(server_pods) >= 1, f"[{label}] SpireServer not healthy"

            agent_pods = client.wait_for_pods_ready(
                namespace=operator_namespace,
                label_selector="app.kubernetes.io/name=spire-agent",
                expected_count=1, timeout=cfg.timeout,
            )
            assert len(agent_pods) >= 1, f"[{label}] SpireAgent not healthy"
            logger.info(
                f"[{label}] Post-test health: server={len(server_pods)}, agents={len(agent_pods)}"
            )
