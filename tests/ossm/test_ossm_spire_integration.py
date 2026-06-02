"""
Single-Cluster OSSM + SPIRE Integration Tests.

Tests validate the spire.adoc guide flow with PR #120:
- Automated SDS config in spire-agent ConfigMap
- SPIRE-issued certificates in Istio sidecars
- STRICT mTLS between services using SPIFFE IDs
- Operator reconciliation of SDS config
- Data plane resilience during component restarts

Test Scenarios (mapped from manual validation):
    Scenario 1: SDS config auto-present after deployment
    Scenario 2: Istio sidecars use SPIRE-issued certs (not Istio CA)
    Scenario 3: STRICT mTLS with distinct SPIFFE IDs per service
    Scenario 4: Operator restores SDS after manual deletion from ConfigMap
    Scenario 5: Full flow health check
    Scenario 6: Operator recreates ConfigMap after full deletion
    Scenario 7: Operator corrects corrupted SDS values
    Scenario 8: mTLS survives spire-agent pod restart
    Scenario 9: mTLS survives ZTWIM operator pod restart

Prerequisites:
    - ZTWIM operator with PR #120 changes installed
    - Framework deploys Sail Operator + IstioCNI + Istio CR

Usage:
    pytest tests/ossm/ -v --deployment-mode=operator-only --keep-deployed

Component: ossm
"""

import json
import time

import pytest
from kubernetes.client.exceptions import ApiException

from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.polling import wait_until

logger = get_logger(__name__)

HTTPBIN_NS = "verify-ossm-httpbin"
MTLS_NS = "verify-ossm-mtls"


def _ensure_namespace_clean(ocp_client, ns_name: str, timeout: int = 120):
    """Delete namespace if it exists and wait until fully gone."""
    try:
        ns = ocp_client.core_v1.read_namespace(name=ns_name)
        phase = ns.status.phase if ns.status else "Active"
    except ApiException as e:
        if e.status == 404:
            return
        raise

    if phase == "Active":
        logger.info(f"Deleting existing namespace {ns_name} for clean setup...")
        try:
            ocp_client.delete_namespace(ns_name, wait=False)
        except Exception:
            pass

    def _is_gone():
        try:
            ocp_client.core_v1.read_namespace(name=ns_name)
            return False
        except ApiException as e:
            return e.status == 404

    logger.info(f"Waiting for namespace {ns_name} to finish terminating...")
    wait_until(_is_gone, message=f"Namespace {ns_name} termination", timeout=timeout, interval=5, backoff=1.0)


# =============================================================================
# Phase 1: Prerequisites (Scenario 1)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(20)
class TestSPIREOSSMPrerequisites:
    """
    Phase 1: Verify SPIRE stack, Istiod, IstioCNI, and SDS config.

    Scenario 1: SDS config auto-present after deployment.
    Timeouts read from config/settings.yaml -> polling.component_verify.
    """

    def test_spire_server_running(self, ocp_client, operator_namespace):
        """
        Verify SpireServer pods are running.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed
        - WHEN we check for SpireServer pods
        - THEN at least one pod is in Ready state
        """
        cfg = get_settings().polling.component_verify
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=cfg.timeout,
        )
        assert len(pods) >= 1, "SpireServer pods not found"
        logger.info(f"SpireServer: {pods[0]['metadata']['name']} running")

    def test_spire_agent_running(self, ocp_client, operator_namespace):
        """
        Verify SpireAgent DaemonSet pods are running.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed
        - WHEN we check for SpireAgent pods
        - THEN at least one pod is in Ready state
        """
        cfg = get_settings().polling.component_verify
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
            expected_count=1,
            timeout=cfg.timeout,
        )
        assert len(pods) >= 1, "SpireAgent pods not found"
        logger.info(f"SpireAgent: {len(pods)} pod(s) running")

    def test_istiod_running(self, ossm_helper, ossm_namespace):
        """
        Verify Istiod is running in the OSSM namespace.

        Acceptance Criteria:
        - GIVEN the Istio CR is deployed with SPIRE config
        - WHEN we check for Istiod pods
        - THEN at least one pod is in Ready state
        """
        pods = ossm_helper.wait_for_istiod_ready(timeout=120)
        assert len(pods) >= 1, "Istiod pod not found"

    def test_istio_cni_running(self, ossm_helper, cni_namespace):
        """
        Verify IstioCNI DaemonSet pods are running.

        Acceptance Criteria:
        - GIVEN the IstioCNI CR is deployed
        - WHEN we check for istio-cni-node pods
        - THEN at least one pod is in Ready state
        """
        pods = ossm_helper.wait_for_istio_cni_ready(timeout=120)
        assert len(pods) >= 1, "IstioCNI pods not found"

    def test_sds_config_auto_present(self, ossm_helper):
        """
        Verify SDS config is auto-generated in spire-agent ConfigMap (PR #120).

        Acceptance Criteria:
        - GIVEN the ZTWIM operator with PR #120 is deployed
        - WHEN we read the spire-agent ConfigMap
        - THEN the SDS section contains:
            default_bundle_name = "null"
            default_all_bundles_name = "ROOTCA"
        """
        sds = ossm_helper.get_sds_config()
        assert sds is not None, "SDS section missing from spire-agent ConfigMap"
        assert sds.get("default_bundle_name") == "null", (
            f"Expected default_bundle_name='null', got '{sds.get('default_bundle_name')}'"
        )
        assert sds.get("default_all_bundles_name") == "ROOTCA", (
            f"Expected default_all_bundles_name='ROOTCA', got '{sds.get('default_all_bundles_name')}'"
        )
        logger.info(f"SDS config verified: {sds}")


# =============================================================================
# Phase 2: SPIRE cert verification (Scenario 2)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(21)
class TestIstioSpireVerification:
    """
    Phase 2: Deploy httpbin and verify SPIRE-issued certificates.

    Scenario 2: Istio sidecars use SPIRE-issued certs, not Istio CA.
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_httpbin_namespace(self, ocp_client, ossm_helper, ossm_namespace):
        """Create test namespace with Istio injection, deploy httpbin."""
        self._wait_for_injection_webhook(ocp_client, ossm_namespace)
        _ensure_namespace_clean(ocp_client, HTTPBIN_NS)

        ocp_client.create_namespace(
            name=HTTPBIN_NS,
            labels={"istio-injection": "enabled"},
        )
        ossm_helper.deploy_httpbin(
            namespace=HTTPBIN_NS,
            with_service=True,
            service_account="httpbin",
        )
        cfg = get_settings().polling.pod_readiness
        ocp_client.wait_for_pods_ready(
            namespace=HTTPBIN_NS,
            label_selector="app=httpbin",
            expected_count=1,
            timeout=cfg.timeout,
        )
        yield
        try:
            ocp_client.delete_namespace(HTTPBIN_NS, wait=True, timeout=60)
        except Exception:
            pass

    @staticmethod
    def _wait_for_injection_webhook(ocp_client, ossm_namespace):
        from kubernetes import client as k8s_client
        admission_api = k8s_client.AdmissionregistrationV1Api(ocp_client.api_client)
        cfg = get_settings().polling.component_verify

        def _check():
            try:
                webhooks = admission_api.list_mutating_webhook_configuration()
                for wh in webhooks.items:
                    if "istio" in wh.metadata.name and "sidecar" in wh.metadata.name:
                        return True
                return False
            except Exception:
                return False

        result = wait_until(
            _check,
            message="Istio sidecar injection webhook",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        if not result.success:
            logger.warning("Injection webhook not detected, proceeding anyway")

    def test_sidecar_injected(self, ocp_client):
        """
        Verify httpbin pod has istio-proxy sidecar injected.

        Acceptance Criteria:
        - GIVEN httpbin is deployed in an istio-injection=enabled namespace
        - WHEN we inspect the pod's containers
        - THEN an istio-proxy container is present
        """
        cfg = get_settings().polling.pod_readiness

        def _check_sidecar():
            pods = ocp_client.get_pods(namespace=HTTPBIN_NS, label_selector="app=httpbin")
            if not pods:
                return None
            spec = pods[0].get("spec", {})
            containers = [c["name"] for c in spec.get("containers") or []]
            init_containers = [c["name"] for c in spec.get("init_containers") or []]
            all_containers = containers + init_containers
            return all_containers if "istio-proxy" in all_containers else None

        result = wait_until(
            _check_sidecar,
            message="Sidecar injection check",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, (
            f"istio-proxy sidecar not injected. Check namespace labels and webhook."
        )

    def test_spire_issued_cert(self, ocp_client, ossm_helper, app_domain):
        """
        Verify Envoy uses SPIRE-issued certificate, not Istio CA.

        Acceptance Criteria:
        - GIVEN httpbin has an istio-proxy sidecar
        - WHEN we query the Envoy admin /certs endpoint
        - THEN the certificate subject_alt_names contains a spiffe:// URI
        - AND the SPIFFE ID matches the trust domain
        """
        pods = ocp_client.get_pods(namespace=HTTPBIN_NS, label_selector="app=httpbin")
        pod_name = pods[0]["metadata"]["name"]

        cfg = get_settings().polling.pod_readiness

        def _check_spiffe_cert():
            try:
                spiffe_id = ossm_helper.get_envoy_spiffe_id(pod_name, HTTPBIN_NS)
                return spiffe_id if spiffe_id.startswith("spiffe://") else None
            except Exception as e:
                logger.warning(f"SPIRE cert check failed: {type(e).__name__}: {e}")
                return None

        result = wait_until(
            _check_spiffe_cert,
            message="SPIRE-issued cert in Envoy",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "SPIRE-issued certificate not found in Envoy"
        spiffe_id = result.value
        assert app_domain in spiffe_id, (
            f"SPIFFE ID '{spiffe_id}' does not contain trust domain '{app_domain}'"
        )
        logger.info(f"Envoy cert verified: {spiffe_id}")


# =============================================================================
# Phase 3: STRICT mTLS (Scenario 3)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(22)
class TestIstioMutualWithSpire:
    """
    Phase 3: STRICT mTLS between services using SPIFFE IDs.

    Scenario 3: Deploy httpbin + curl with distinct service accounts,
    apply STRICT PeerAuthentication + ISTIO_MUTUAL DestinationRules,
    verify mutual TLS with SPIRE-issued identities.
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_mtls_namespace(self, ocp_client, ossm_helper):
        """Create namespace, deploy httpbin + curl with SPIRE annotations."""
        _ensure_namespace_clean(ocp_client, MTLS_NS)
        ocp_client.create_namespace(
            name=MTLS_NS,
            labels={"istio-injection": "enabled"},
        )
        ossm_helper.deploy_httpbin(
            namespace=MTLS_NS, with_service=True, service_account="httpbin",
        )
        ossm_helper.deploy_curl_client(
            namespace=MTLS_NS, service_account="curl",
        )
        cfg = get_settings().polling.pod_readiness
        ocp_client.wait_for_pods_ready(
            namespace=MTLS_NS, label_selector="app=httpbin",
            expected_count=1, timeout=cfg.timeout,
        )
        ocp_client.wait_for_pods_ready(
            namespace=MTLS_NS, label_selector="app=curl",
            expected_count=1, timeout=cfg.timeout,
        )
        yield
        try:
            ocp_client.delete_namespace(MTLS_NS, wait=True, timeout=60)
        except Exception:
            pass

    def test_permissive_mtls_traffic(self, ocp_client, ossm_helper):
        """
        Verify traffic flows in PERMISSIVE mode (before applying STRICT).

        Acceptance Criteria:
        - GIVEN httpbin and curl are deployed with SPIRE sidecar annotations
        - WHEN curl sends a request to httpbin (PERMISSIVE mode, default)
        - THEN the response is HTTP 200
        """
        pods = ocp_client.get_pods(namespace=MTLS_NS, label_selector="app=curl")
        pod_name = pods[0]["metadata"]["name"]

        cfg = get_settings().polling.pod_readiness

        def _check_traffic():
            try:
                code = ossm_helper.exec_curl(
                    pod_name, MTLS_NS, "http://httpbin.verify-ossm-mtls.svc.cluster.local/status/200",
                )
                return code.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check_traffic,
            message="PERMISSIVE mTLS traffic",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Traffic failed in PERMISSIVE mode"
        logger.info("PERMISSIVE mTLS traffic: OK")

    def test_distinct_spiffe_ids(self, ocp_client, ossm_helper, app_domain):
        """
        Verify httpbin and curl have distinct SPIFFE IDs from SPIRE.

        Acceptance Criteria:
        - GIVEN both services have SPIRE sidecar annotations
        - WHEN we query each pod's Envoy /certs endpoint
        - THEN each has a unique spiffe:// identity containing its service account
        """
        httpbin_pods = ocp_client.get_pods(namespace=MTLS_NS, label_selector="app=httpbin")
        curl_pods = ocp_client.get_pods(namespace=MTLS_NS, label_selector="app=curl")

        cfg = get_settings().polling.pod_readiness

        def _get_ids():
            try:
                httpbin_id = ossm_helper.get_envoy_spiffe_id(
                    httpbin_pods[0]["metadata"]["name"], MTLS_NS,
                )
                curl_id = ossm_helper.get_envoy_spiffe_id(
                    curl_pods[0]["metadata"]["name"], MTLS_NS,
                )
                if httpbin_id.startswith("spiffe://") and curl_id.startswith("spiffe://"):
                    return (httpbin_id, curl_id)
                return None
            except Exception:
                return None

        result = wait_until(
            _get_ids,
            message="Distinct SPIFFE IDs",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Failed to get SPIFFE IDs from both pods"
        httpbin_id, curl_id = result.value
        assert httpbin_id != curl_id, (
            f"SPIFFE IDs must be distinct: httpbin={httpbin_id}, curl={curl_id}"
        )
        assert "httpbin" in httpbin_id or "sa/httpbin" in httpbin_id, (
            f"httpbin SPIFFE ID should reference httpbin SA: {httpbin_id}"
        )
        assert "curl" in curl_id or "sa/curl" in curl_id, (
            f"curl SPIFFE ID should reference curl SA: {curl_id}"
        )
        logger.info(f"Distinct SPIFFE IDs: httpbin={httpbin_id}, curl={curl_id}")

    def test_strict_mtls_traffic(self, ocp_client, ossm_helper):
        """
        Verify traffic flows with STRICT PeerAuthentication + ISTIO_MUTUAL.

        Acceptance Criteria:
        - GIVEN httpbin and curl are deployed with SPIRE certs
        - WHEN STRICT PeerAuthentication and ISTIO_MUTUAL DestinationRules are applied
        - AND curl sends a request to httpbin
        - THEN the response is HTTP 200 (mTLS enforced via SPIRE certs)
        """
        ossm_helper.apply_strict_mtls(MTLS_NS)
        ossm_helper.apply_destination_rules(MTLS_NS, ["httpbin", "curl"])

        time.sleep(5)

        pods = ocp_client.get_pods(namespace=MTLS_NS, label_selector="app=curl")
        pod_name = pods[0]["metadata"]["name"]

        cfg = get_settings().polling.pod_readiness

        def _check_strict():
            try:
                code = ossm_helper.exec_curl(
                    pod_name, MTLS_NS, "http://httpbin.verify-ossm-mtls.svc.cluster.local/status/200",
                )
                return code.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check_strict,
            message="STRICT mTLS traffic with SPIRE certs",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Traffic failed under STRICT mTLS"
        logger.info("STRICT mTLS traffic with SPIRE certs: OK")


# =============================================================================
# Phase 4: Operator reconciliation (Scenarios 4, 6, 7)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(23)
class TestOperatorReconciliation:
    """
    Phase 4: Operator self-heals SDS config.

    Scenario 4: Delete SDS section from ConfigMap -> operator restores it.
    Scenario 6: Delete entire spire-agent ConfigMap -> operator recreates it.
    Scenario 7: Corrupt SDS values -> operator corrects them.
    """

    def test_restore_sds_after_deletion(self, ossm_helper):
        """
        Scenario 4: Operator restores SDS config after manual deletion.

        Acceptance Criteria:
        - GIVEN the spire-agent ConfigMap has a valid SDS section
        - WHEN we delete the SDS section from the ConfigMap
        - THEN the ZTWIM operator reconciles and restores the SDS config
        - AND default_bundle_name = "null" and default_all_bundles_name = "ROOTCA"
        """
        sds_before = ossm_helper.get_sds_config()
        assert sds_before is not None, "SDS config missing before test"

        ossm_helper.delete_sds_from_configmap()
        logger.info("SDS section removed from ConfigMap, waiting for operator reconcile...")

        cfg = get_settings().polling.operator

        def _check_restored():
            try:
                sds = ossm_helper.get_sds_config()
                if sds and sds.get("default_bundle_name") == "null":
                    return sds
                return None
            except Exception:
                return None

        result = wait_until(
            _check_restored,
            message="Operator restoring SDS config",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Operator did not restore SDS config"
        sds = result.value
        assert sds["default_bundle_name"] == "null"
        assert sds["default_all_bundles_name"] == "ROOTCA"
        logger.info(f"Operator restored SDS config: {sds}")

    def test_recreate_configmap_after_full_deletion(self, ossm_helper):
        """
        Scenario 6: Operator recreates ConfigMap after full deletion.

        Acceptance Criteria:
        - GIVEN the spire-agent ConfigMap exists
        - WHEN we delete the entire ConfigMap
        - THEN the operator reconciles and recreates it
        - AND the SDS section is present with correct values
        """
        ossm_helper.delete_spire_agent_configmap()
        logger.info("Deleted entire spire-agent ConfigMap")

        cfg = get_settings().polling.operator

        def _check_recreated():
            try:
                sds = ossm_helper.get_sds_config()
                if sds and sds.get("default_bundle_name") == "null":
                    return sds
                return None
            except Exception:
                return None

        result = wait_until(
            _check_recreated,
            message="Operator recreating ConfigMap + SDS",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Operator did not recreate spire-agent ConfigMap"
        sds = result.value
        assert sds["default_bundle_name"] == "null"
        assert sds["default_all_bundles_name"] == "ROOTCA"
        logger.info(f"Operator recreated ConfigMap with SDS: {sds}")

    def test_correct_corrupted_sds_values(self, ossm_helper):
        """
        Scenario 7: Operator corrects corrupted SDS values.

        Acceptance Criteria:
        - GIVEN the spire-agent ConfigMap has correct SDS values
        - WHEN we corrupt the SDS values to invalid strings
        - THEN the operator reconciles and restores correct values
        """
        ossm_helper.corrupt_sds_config({
            "default_bundle_name": "WRONG_VALUE",
            "default_all_bundles_name": "ALSO_WRONG",
        })

        cfg = get_settings().polling.operator

        def _check_corrected():
            try:
                sds = ossm_helper.get_sds_config()
                if (sds
                    and sds.get("default_bundle_name") == "null"
                    and sds.get("default_all_bundles_name") == "ROOTCA"):
                    return sds
                return None
            except Exception:
                return None

        result = wait_until(
            _check_corrected,
            message="Operator correcting corrupted SDS values",
            timeout=cfg.timeout,
            interval=cfg.interval,
            backoff=cfg.backoff_factor,
        )
        assert result.success, "Operator did not correct corrupted SDS values"
        sds = result.value
        assert sds["default_bundle_name"] == "null"
        assert sds["default_all_bundles_name"] == "ROOTCA"
        logger.info(f"Operator corrected SDS values: {sds}")


# =============================================================================
# Phase 5: Data plane resilience (Scenarios 8, 9)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(24)
class TestDataPlaneResilience:
    """
    Phase 5: mTLS survives component restarts.

    Scenario 8: Kill all spire-agent pods -> mTLS continues working.
    Scenario 9: Kill ZTWIM operator pod -> mTLS continues working.
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_mtls_for_resilience(self, ocp_client, ossm_helper):
        """Ensure httpbin + curl with STRICT mTLS are deployed."""
        _ensure_namespace_clean(ocp_client, MTLS_NS)

        ocp_client.create_namespace(
            name=MTLS_NS, labels={"istio-injection": "enabled"},
        )
        ossm_helper.deploy_httpbin(
            namespace=MTLS_NS, with_service=True, service_account="httpbin",
        )
        ossm_helper.deploy_curl_client(
            namespace=MTLS_NS, service_account="curl",
        )
        cfg = get_settings().polling.pod_readiness
        ocp_client.wait_for_pods_ready(
            namespace=MTLS_NS, label_selector="app=httpbin",
            expected_count=1, timeout=cfg.timeout,
        )
        ocp_client.wait_for_pods_ready(
            namespace=MTLS_NS, label_selector="app=curl",
            expected_count=1, timeout=cfg.timeout,
        )
        ossm_helper.apply_strict_mtls(MTLS_NS)
        ossm_helper.apply_destination_rules(MTLS_NS, ["httpbin", "curl"])
        yield
        try:
            ocp_client.delete_namespace(MTLS_NS, wait=True, timeout=60)
        except Exception:
            pass

    def _verify_mtls_traffic(self, ocp_client, ossm_helper, msg: str) -> None:
        """Poll until mTLS traffic succeeds."""
        pods = ocp_client.get_pods(namespace=MTLS_NS, label_selector="app=curl")
        assert len(pods) >= 1, "curl pod not found"
        pod_name = pods[0]["metadata"]["name"]

        cfg = get_settings().polling.pod_readiness

        def _check():
            try:
                code = ossm_helper.exec_curl(
                    pod_name, MTLS_NS, "http://httpbin.verify-ossm-mtls.svc.cluster.local/status/200",
                )
                return code.strip() == "200"
            except Exception:
                return False

        result = wait_until(
            _check, message=msg,
            timeout=cfg.timeout, interval=cfg.interval, backoff=cfg.backoff_factor,
        )
        assert result.success, f"mTLS traffic failed: {msg}"
        logger.info(f"{msg}: OK")

    def test_mtls_survives_spire_agent_restart(self, ocp_client, ossm_helper, operator_namespace):
        """
        Scenario 8: mTLS continues after spire-agent pod restart.

        Acceptance Criteria:
        - GIVEN mTLS is working between httpbin and curl
        - WHEN all spire-agent pods are deleted
        - AND new spire-agent pods come back to Ready
        - THEN mTLS traffic still works
        """
        self._verify_mtls_traffic(ocp_client, ossm_helper, "Pre-restart baseline")

        agent_pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
        )
        expected_count = len(agent_pods)
        ossm_helper.delete_all_spire_agent_pods()

        cfg = get_settings().polling.pod_readiness
        recovered = ossm_helper.wait_for_spire_agents_recovered(
            expected_count=expected_count, timeout=cfg.timeout,
        )
        logger.info(f"Spire agents recovered: {len(recovered)} pods")

        self._verify_mtls_traffic(ocp_client, ossm_helper, "Post spire-agent restart")

    def test_mtls_survives_operator_restart(self, ocp_client, ossm_helper):
        """
        Scenario 9: mTLS continues after ZTWIM operator pod restart.

        Acceptance Criteria:
        - GIVEN mTLS is working between httpbin and curl
        - WHEN the ZTWIM operator pod is deleted
        - AND a new operator pod comes back to Ready
        - THEN mTLS traffic still works
        """
        self._verify_mtls_traffic(ocp_client, ossm_helper, "Pre-restart baseline")

        old_pod = ossm_helper.delete_operator_pod()
        logger.info(f"Deleted operator pod: {old_pod}")

        cfg = get_settings().polling.operator
        ossm_helper.wait_for_operator_recovered(timeout=cfg.timeout)
        logger.info("Operator pod recovered")

        self._verify_mtls_traffic(ocp_client, ossm_helper, "Post operator restart")


# =============================================================================
# Phase 6: Final health check (Scenario 5)
# =============================================================================


@pytest.mark.ossm
@pytest.mark.order(25)
class TestOSSMCleanup:
    """
    Phase 6: Verify SPIRE stack is healthy after all tests.

    Scenario 5: Full flow health check.
    """

    def test_spire_stack_healthy_after_tests(self, ocp_client, operator_namespace):
        """
        Verify SPIRE components remain healthy after destructive tests.

        Acceptance Criteria:
        - GIVEN all previous tests have run (including destructive scenarios)
        - WHEN we check SPIRE server and agent pods
        - THEN all pods are in Ready state
        """
        cfg = get_settings().polling.component_verify

        server_pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=cfg.timeout,
        )
        assert len(server_pods) >= 1, "SpireServer not healthy"

        agent_pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
            expected_count=1,
            timeout=cfg.timeout,
        )
        assert len(agent_pods) >= 1, "SpireAgent not healthy"
        logger.info(f"Post-test health: server={len(server_pods)}, agents={len(agent_pods)}")

    def test_sds_config_intact_after_tests(self, ossm_helper):
        """
        Verify SDS config is still correct after all destructive tests.

        Acceptance Criteria:
        - GIVEN all reconciliation and resilience tests have run
        - WHEN we read the spire-agent ConfigMap
        - THEN the SDS config has correct values
        """
        sds = ossm_helper.get_sds_config()
        assert sds is not None, "SDS config missing after tests"
        assert sds.get("default_bundle_name") == "null"
        assert sds.get("default_all_bundles_name") == "ROOTCA"
        logger.info(f"SDS config intact: {sds}")

    def test_istiod_healthy_after_tests(self, ossm_helper):
        """
        Verify Istiod remains healthy after all tests.

        Acceptance Criteria:
        - GIVEN all tests have completed
        - WHEN we check for Istiod pods
        - THEN at least one pod is in Ready state
        """
        pods = ossm_helper.wait_for_istiod_ready(timeout=60)
        assert len(pods) >= 1, "Istiod not healthy after tests"
        logger.info("Istiod healthy after tests")
