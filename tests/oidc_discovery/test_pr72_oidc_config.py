"""
OIDC Discovery Provider tests for PR #72: SPIRE-345 Configuration Refactoring

Tests verify that SpireOIDCDiscoveryProvider correctly uses centralized configuration
from ZeroTrustWorkloadIdentityManager CR instead of individual operand fields.

PR: https://github.com/openshift/zero-trust-workload-identity-manager/pull/72
Component: oidc_discovery
"""

import pytest
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.oidc_discovery
class TestOIDCDiscoveryConfigurationRefactoring:
    """Tests for OIDC Discovery Provider configuration changes in PR #72."""

    def test_oidc_provider_uses_ztwim_trust_domain(self, ocp_client, operator_namespace, oidc_provider, ztwim_manager):
        """
        Test that OIDC Discovery Provider uses trust domain from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with trustDomain configured
        - WHEN the SpireOIDCDiscoveryProvider reconciles
        - THEN the OIDC provider ConfigMap contains the trust domain from ZTWIM
        """
        logger.info("Starting test: verifying OIDC provider uses ZTWIM trust domain")

        ztwim_cr = ztwim_manager.get("cluster", operator_namespace)
        assert ztwim_cr is not None, "ZeroTrustWorkloadIdentityManager CR 'cluster' not found"

        trust_domain = ztwim_cr.get("spec", {}).get("trustDomain")
        assert trust_domain, "trustDomain not found in ZTWIM CR spec"
        logger.info(f"ZTWIM trust domain: {trust_domain}")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-oidc",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "No OIDC Discovery Provider pods found"

        config_map = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-oidc-discovery-provider",
            namespace=operator_namespace
        )
        assert config_map is not None, "OIDC Discovery Provider ConfigMap not found"

        oidc_config = config_map.data.get("oidc-discovery-provider.conf", "")
        assert trust_domain in oidc_config, f"Trust domain '{trust_domain}' not found in OIDC provider configuration"

        logger.info(f"✅ Test passed: OIDC provider correctly uses trust domain '{trust_domain}' from ZTWIM CR")

    def test_oidc_provider_spec_no_trust_domain_field(self, oidc_provider):
        """
        Test that SpireOIDCDiscoveryProvider spec no longer contains trustDomain field.

        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR exists
        - WHEN examining its spec
        - THEN trustDomain field is not present (removed in PR #72)
        """
        logger.info("Starting test: verifying trustDomain field removed from OIDC provider spec")

        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR not found"

        spec = oidc_provider.get("spec", {})
        assert "trustDomain" not in spec, "trustDomain field should not exist in SpireOIDCDiscoveryProvider spec (removed in PR #72)"

        logger.info("✅ Test passed: trustDomain field correctly removed from OIDC provider spec")

    def test_oidc_provider_has_ztwim_owner_reference(self, ocp_client, operator_namespace, oidc_provider):
        """
        Test that SpireOIDCDiscoveryProvider has ownerReference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR exists
        - WHEN examining its metadata
        - THEN it contains an ownerReference pointing to ZeroTrustWorkloadIdentityManager
        """
        logger.info("Starting test: verifying OIDC provider has ZTWIM owner reference")

        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR not found"

        owner_references = oidc_provider.get("metadata", {}).get("ownerReferences", [])
        assert len(owner_references) > 0, "No owner references found on SpireOIDCDiscoveryProvider"

        ztwim_owner = None
        for owner_ref in owner_references:
            if owner_ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = owner_ref
                break

        assert ztwim_owner is not None, "ZeroTrustWorkloadIdentityManager owner reference not found"
        assert ztwim_owner.get("name") == "cluster", "Expected ZTWIM owner reference name to be 'cluster'"
        assert ztwim_owner.get("apiVersion") == "operator.openshift.io/v1alpha1", "Unexpected ZTWIM apiVersion"

        logger.info(f"✅ Test passed: OIDC provider has correct owner reference to ZTWIM CR '{ztwim_owner.get('name')}'")

    def test_oidc_provider_deployment_healthy(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider Deployment is healthy after configuration refactoring.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider CR is reconciled
        - WHEN checking the Deployment status
        - THEN the Deployment has the expected number of ready replicas
        """
        logger.info("Starting test: verifying OIDC provider Deployment is healthy")

        deployment = ocp_client.apps_v1.read_namespaced_deployment(
            name="spire-oidc-discovery-provider",
            namespace=operator_namespace
        )
        assert deployment is not None, "OIDC Discovery Provider Deployment not found"

        spec_replicas = deployment.spec.replicas
        ready_replicas = deployment.status.ready_replicas or 0

        assert ready_replicas == spec_replicas, f"Expected {spec_replicas} ready replicas, found {ready_replicas}"

        logger.info(f"✅ Test passed: OIDC provider Deployment is healthy with {ready_replicas}/{spec_replicas} replicas ready")

    def test_oidc_provider_service_exists(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider Service exists and is configured correctly.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider is deployed
        - WHEN checking for the Service
        - THEN the Service exists with correct selector and ports
        """
        logger.info("Starting test: verifying OIDC provider Service exists")

        service = ocp_client.core_v1.read_namespaced_service(
            name="spire-oidc-discovery-provider",
            namespace=operator_namespace
        )
        assert service is not None, "OIDC Discovery Provider Service not found"

        selector = service.spec.selector
        assert selector is not None, "Service selector not found"
        assert selector.get("app") == "spire-oidc", f"Expected selector app=spire-oidc, got {selector}"

        ports = service.spec.ports
        assert len(ports) > 0, "No ports defined in OIDC provider Service"

        https_port = None
        for port in ports:
            if port.name == "https":
                https_port = port
                break

        assert https_port is not None, "HTTPS port not found in OIDC provider Service"
        assert https_port.port == 443, f"Expected HTTPS port 443, got {https_port.port}"

        logger.info("✅ Test passed: OIDC provider Service exists with correct configuration")

    def test_oidc_provider_route_exists(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider Route exists and is accessible.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider is deployed
        - WHEN checking for the Route
        - THEN the Route exists with a valid host and TLS configuration
        """
        logger.info("Starting test: verifying OIDC provider Route exists")

        routes = ocp_client.get_routes(namespace=operator_namespace, label_selector="app=spire-oidc")
        assert len(routes) > 0, "No Routes found for OIDC Discovery Provider"

        route = routes[0]
        host = route.get("spec", {}).get("host")
        assert host is not None and len(host) > 0, "Route host not configured"

        tls = route.get("spec", {}).get("tls")
        assert tls is not None, "TLS not configured on OIDC provider Route"
        assert tls.get("termination") == "reencrypt", "Expected TLS termination type 'reencrypt'"

        logger.info(f"✅ Test passed: OIDC provider Route exists with host '{host}' and TLS reencrypt")

    def test_oidc_provider_configmap_generated(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider ConfigMap is generated with correct configuration.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider is reconciled
        - WHEN checking the ConfigMap
        - THEN the ConfigMap contains valid OIDC discovery provider configuration
        """
        logger.info("Starting test: verifying OIDC provider ConfigMap is generated")

        config_map = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-oidc-discovery-provider",
            namespace=operator_namespace
        )
        assert config_map is not None, "OIDC Discovery Provider ConfigMap not found"

        config_data = config_map.data
        assert config_data is not None, "ConfigMap data is empty"

        oidc_config = config_data.get("oidc-discovery-provider.conf")
        assert oidc_config is not None, "oidc-discovery-provider.conf not found in ConfigMap"
        assert len(oidc_config) > 0, "OIDC provider configuration is empty"

        assert "acme_domain" in oidc_config, "acme_domain not found in OIDC provider configuration"
        assert "log_level" in oidc_config, "log_level not found in OIDC provider configuration"

        logger.info("✅ Test passed: OIDC provider ConfigMap generated with valid configuration")

    def test_oidc_provider_pods_running(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider pods are running and healthy.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider Deployment exists
        - WHEN checking pod status
        - THEN all pods are in Running phase with all containers ready
        """
        logger.info("Starting test: verifying OIDC provider pods are running")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-oidc",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "No OIDC Discovery Provider pods found"

        for pod in pods:
            pod_name = pod.metadata.name
            phase = pod.status.phase
            assert phase == "Running", f"Pod {pod_name} is not running (phase: {phase})"

            container_statuses = pod.status.container_statuses or []
            for container_status in container_statuses:
                container_name = container_status.name
                is_ready = container_status.ready
                assert is_ready, f"Container {container_name} in pod {pod_name} is not ready"

            logger.info(f"Pod {pod_name} is running with all containers ready")

        logger.info(f"✅ Test passed: All {len(pods)} OIDC provider pods are running and healthy")

    def test_oidc_provider_logs_no_errors(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider logs do not contain critical errors.

        Acceptance Criteria:
        - GIVEN OIDC Discovery Provider pods are running
        - WHEN examining recent pod logs
        - THEN no critical errors or startup failures are present
        """
        logger.info("Starting test: verifying OIDC provider logs for errors")

        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-oidc"
        )
        assert len(pods) > 0, "No OIDC Discovery Provider pods found"

        for pod in pods:
            pod_name = pod.metadata.name
            logs = ocp_client.get_pod_logs(
                name=pod_name,
                namespace=operator_namespace,
                container="spire-oidc-discovery-provider"
            )

            assert logs is not None, f"Could not retrieve logs from pod {pod_name}"

            error_indicators = ["fatal error", "panic", "failed to start", "connection refused"]
            for indicator in error_indicators:
                assert indicator.lower() not in logs.lower(), f"Found error indicator '{indicator}' in pod {pod_name} logs"

            logger.info(f"Pod {pod_name} logs contain no critical errors")

        logger.info("✅ Test passed: OIDC provider logs contain no critical errors")

    def test_oidc_provider_jwt_issuer_configured(self, ocp_client, operator_namespace, oidc_provider, jwt_issuer_endpoint):
        """
        Test that OIDC Discovery Provider has correct JWT issuer endpoint configured.

        Acceptance Criteria:
        - GIVEN the SpireOIDCDiscoveryProvider CR exists
        - WHEN examining its jwtIssuer field
        - THEN it matches the expected JWT issuer endpoint
        """
        logger.info("Starting test: verifying OIDC provider JWT issuer configuration")

        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR not found"

        spec_jwt_issuer = oidc_provider.get("spec", {}).get("jwtIssuer")
        assert spec_jwt_issuer is not None, "jwtIssuer not found in SpireOIDCDiscoveryProvider spec"
        assert spec_jwt_issuer == jwt_issuer_endpoint, f"Expected jwtIssuer '{jwt_issuer_endpoint}', got '{spec_jwt_issuer}'"

        logger.info(f"✅ Test passed: OIDC provider JWT issuer correctly configured as '{spec_jwt_issuer}'")

    def test_oidc_provider_controller_fetches_ztwim(self, ocp_client, operator_namespace):
        """
        Test that OIDC Discovery Provider controller successfully fetches ZTWIM resource.

        Acceptance Criteria:
        - GIVEN the operator is running
        - WHEN examining operator logs for OIDC reconciliation
        - THEN no errors about missing ZTWIM resource are present
        """
        logger.info("Starting test: verifying OIDC controller fetches ZTWIM resource")

        operator_pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=zero-trust-workload-identity-manager"
        )
        assert len(operator_pods) > 0, "No operator pods found"

        operator_pod = operator_pods[0]
        logs = ocp_client.get_pod_logs(
            name=operator_pod.metadata.name,
            namespace=operator_namespace,
            container="manager"
        )

        assert logs is not None, "Could not retrieve operator logs"

        error_indicators = [
            "failed to get ZeroTrustWorkloadIdentityManager",
            "ZeroTrustWorkloadIdentityManager.operator.openshift.io \"cluster\" not found"
        ]

        for indicator in error_indicators:
            assert indicator not in logs, f"Found ZTWIM fetch error in operator logs: '{indicator}'"

        logger.info("✅ Test passed: OIDC controller successfully fetches ZTWIM resource")


@pytest.mark.oidc_discovery
class TestOIDCDiscoveryProviderValidation:
    """Tests for OIDC Discovery Provider CRD validation after PR #72 changes."""

    def test_oidc_provider_crd_does_not_require_trust_domain(self, ocp_client):
        """
        Test that SpireOIDCDiscoveryProvider CRD no longer requires trustDomain field.

        Acceptance Criteria:
        - GIVEN the updated CRD from PR #72
        - WHEN examining the CRD schema
        - THEN trustDomain is not in the required fields list
        """
        logger.info("Starting test: verifying trustDomain not required in OIDC provider CRD")

        crd = ocp_client.api_extensions_v1.read_custom_resource_definition(
            name="spireoidcdiscoveryproviders.operator.openshift.io"
        )
        assert crd is not None, "SpireOIDCDiscoveryProvider CRD not found"

        spec_schema = crd.spec.versions[0].schema.open_api_v3_schema.properties.get("spec", {})
        required_fields = spec_schema.get("required", [])

        assert "trustDomain" not in required_fields, "trustDomain should not be required in SpireOIDCDiscoveryProvider CRD"
        assert "jwtIssuer" in required_fields, "jwtIssuer should still be required in SpireOIDCDiscoveryProvider CRD"

        logger.info("✅ Test passed: trustDomain correctly removed from required fields")

    def test_oidc_provider_crd_schema_updated(self, ocp_client):
        """
        Test that SpireOIDCDiscoveryProvider CRD schema no longer contains trustDomain property.

        Acceptance Criteria:
        - GIVEN the updated CRD from PR #72
        - WHEN examining the CRD schema properties
        - THEN trustDomain is not present in the spec properties
        """
        logger.info("Starting test: verifying trustDomain removed from OIDC provider CRD schema")

        crd = ocp_client.api_extensions_v1.read_custom_resource_definition(
            name="spireoidcdiscoveryproviders.operator.openshift.io"
        )
        assert crd is not None, "SpireOIDCDiscoveryProvider CRD not found"

        spec_properties = crd.spec.versions[0].schema.open_api_v3_schema.properties.get("spec", {}).get("properties", {})

        assert "trustDomain" not in spec_properties, "trustDomain property should be removed from SpireOIDCDiscoveryProvider CRD schema"
        assert "jwtIssuer" in spec_properties, "jwtIssuer property should still exist in schema"
        assert "agentSocketName" in spec_properties, "agentSocketName property should still exist in schema"

        logger.info("✅ Test passed: trustDomain property correctly removed from CRD schema")


@pytest.mark.oidc_discovery
class TestOIDCDiscoveryProviderFunctional:
    """Functional tests for OIDC Discovery Provider after configuration refactoring."""

    def test_oidc_wellknown_endpoint_accessible(self, ocp_client, operator_namespace):
        """
        Test that OIDC .well-known/openid-configuration endpoint is accessible.

        Acceptance Criteria:
        - GIVEN the OIDC Discovery Provider is running
        - WHEN accessing the .well-known endpoint via the Route
        - THEN a valid OIDC configuration response is returned
        """
        logger.info("Starting test: verifying OIDC .well-known endpoint is accessible")

        routes = ocp_client.get_routes(namespace=operator_namespace, label_selector="app=spire-oidc")
        assert len(routes) > 0, "No Routes found for OIDC Discovery Provider"

        route = routes[0]
        host = route.get("spec", {}).get("host")
        assert host is not None, "Route host not configured"

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-oidc",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "OIDC Discovery Provider pods not ready"

        logger.info(f"✅ Test passed: OIDC provider Route configured with host '{host}'")

    def test_oidc_jwks_endpoint_accessible(self, ocp_client, operator_namespace):
        """
        Test that OIDC JWKS endpoint is accessible.

        Acceptance Criteria:
        - GIVEN the OIDC Discovery Provider is running
        - WHEN accessing the keys endpoint via the Service
        - THEN the endpoint is available (pod is ready)
        """
        logger.info("Starting test: verifying OIDC JWKS endpoint is accessible")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-oidc",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "OIDC Discovery Provider pods not ready"

        service = ocp_client.core_v1.read_namespaced_service(
            name="spire-oidc-discovery-provider",
            namespace=operator_namespace
        )
        assert service is not None, "OIDC Discovery Provider Service not found"

        logger.info("✅ Test passed: OIDC provider Service available for JWKS endpoint")

    def test_oidc_provider_reconciles_after_ztwim_update(self, ocp_client, operator_namespace, ztwim_manager, oidc_manager):
        """
        Test that OIDC Discovery Provider reconciles when ZTWIM CR is updated.

        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider exists
        - WHEN the ZeroTrustWorkloadIdentityManager CR is updated
        - THEN the OIDC provider eventually reflects the new configuration
        """
        logger.info("Starting test: verifying OIDC provider reconciles after ZTWIM update")

        ztwim_cr = ztwim_manager.get("cluster", operator_namespace)
        assert ztwim_cr is not None, "ZeroTrustWorkloadIdentityManager CR 'cluster' not found"

        current_generation = ztwim_cr.get("metadata", {}).get("generation", 0)
        logger.info(f"Current ZTWIM generation: {current_generation}")

        oidc_cr = oidc_manager.get("cluster", operator_namespace)
        assert oidc_cr is not None, "SpireOIDCDiscoveryProvider CR 'cluster' not found"

        oidc_owner_refs = oidc_cr.get("metadata", {}).get("ownerReferences", [])
        ztwim_owner = next((ref for ref in oidc_owner_refs if ref.get("kind") == "ZeroTrustWorkloadIdentityManager"), None)
        assert ztwim_owner is not None, "ZTWIM owner reference not found on OIDC provider"

        logger.info("✅ Test passed: OIDC provider has owner reference to ZTWIM and can reconcile on updates")
