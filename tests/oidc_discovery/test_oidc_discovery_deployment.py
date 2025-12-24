"""
Tests for SpireOIDCDiscoveryProvider deployment on OpenShift.

These tests verify that the ZTWIM operator correctly deploys and manages
SpireOIDCDiscoveryProvider instances.

Prerequisites:
    - ZTWIM operator installed
    - SpireOIDCDiscoveryProvider CR 'cluster' created

API Version: operator.openshift.io/v1alpha1
"""

import pytest

from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.oidc_discovery
@pytest.mark.order(6)  # Run after SpireAgent and CSI Driver tests
class TestOIDCDiscoveryDeployment:
    """Tests for SpireOIDCDiscoveryProvider deployment lifecycle."""
    
    def test_oidc_provider_cr_exists(self, oidc_provider):
        """
        Test that SpireOIDCDiscoveryProvider CR exists.
        
        Acceptance Criteria:
        - GIVEN ZTWIM stack is deployed
        - WHEN we query for SpireOIDCDiscoveryProvider 'cluster'
        - THEN the CR exists with correct API version
        """
        logger.info("Verifying SpireOIDCDiscoveryProvider CR exists")
        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR not found"
        assert oidc_provider["kind"] == "SpireOIDCDiscoveryProvider"
        assert oidc_provider["apiVersion"] == "operator.openshift.io/v1alpha1"
        
        name = oidc_provider["metadata"]["name"]
        logger.info(f"✅ SpireOIDCDiscoveryProvider CR exists: {name}")
    
    def test_oidc_provider_trust_domain_configured(self, oidc_provider, app_domain):
        """
        Test that trust domain is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR with trustDomain
        - WHEN we check the spec
        - THEN trustDomain matches APP_DOMAIN
        """
        logger.info("Verifying trust domain configuration")
        trust_domain = oidc_provider["spec"].get("trustDomain", "")
        
        logger.info(f"Trust Domain: {trust_domain}")
        logger.info(f"Expected (APP_DOMAIN): {app_domain}")
        
        # trustDomain may or may not be set depending on operator version
        if trust_domain:
            assert trust_domain == app_domain, \
                f"Expected trustDomain='{app_domain}', got '{trust_domain}'"
            logger.info("✅ Trust domain configured correctly")
        else:
            logger.info("ℹ️ Trust domain not set in CR (may use default)")
    
    def test_oidc_provider_jwt_issuer_configured(self, oidc_provider, jwt_issuer_endpoint):
        """
        Test that JWT issuer is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR with jwtIssuer
        - WHEN we check the spec
        - THEN jwtIssuer matches expected endpoint
        """
        logger.info("Verifying JWT issuer configuration")
        jwt_issuer = oidc_provider["spec"].get("jwtIssuer", "")
        expected = f"https://{jwt_issuer_endpoint}"
        
        logger.info(f"JWT Issuer: {jwt_issuer}")
        logger.info(f"Expected: {expected}")
        
        assert jwt_issuer == expected, \
            f"Expected jwtIssuer='{expected}', got '{jwt_issuer}'"
        
        logger.info("✅ JWT issuer configured correctly")
    
    def test_oidc_provider_creates_deployment(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpireOIDCDiscoveryProvider CR results in a Deployment.
        
        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR is created
        - WHEN the operator reconciles the CR
        - THEN a Deployment is created
        """
        logger.info("Verifying Deployment was created")
        deployments = ocp_client.apps_v1.list_namespaced_deployment(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-spiffe-oidc-discovery-provider"
        )
        
        # Try alternative label if not found
        if not deployments.items:
            deployments = ocp_client.apps_v1.list_namespaced_deployment(
                namespace=operator_namespace
            )
            deployments.items = [d for d in deployments.items 
                               if "oidc" in d.metadata.name.lower()]
        
        assert len(deployments.items) > 0, "OIDC Discovery Provider Deployment not found"
        
        dep = deployments.items[0]
        name = dep.metadata.name
        replicas = dep.spec.replicas or 1
        ready = dep.status.ready_replicas or 0
        
        logger.info(f"Found Deployment: {name}")
        logger.info(f"  Replicas: {ready}/{replicas}")
        
        assert ready >= replicas, f"Deployment not ready: {ready}/{replicas}"
        logger.info("✅ OIDC Discovery Provider Deployment is ready")
    
    def test_oidc_provider_service_created(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that Services are created for OIDC Discovery Provider.
        
        Acceptance Criteria:
        - GIVEN a SpireOIDCDiscoveryProvider CR is deployed
        - WHEN the operator reconciles
        - THEN Services are created for OIDC endpoints
        """
        logger.info("Verifying Services were created")
        services = ocp_client.core_v1.list_namespaced_service(
            namespace=operator_namespace
        )
        
        oidc_services = [s for s in services.items if "oidc" in s.metadata.name.lower()]
        
        assert len(oidc_services) > 0, "No OIDC Discovery Provider services found"
        
        for svc in oidc_services:
            ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports]
            logger.info(f"Found Service: {svc.metadata.name} ({', '.join(ports)})")
        
        logger.info("✅ OIDC Services created successfully")
    
    def test_oidc_provider_pods_running(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that OIDC Discovery Provider pods are running.
        
        Acceptance Criteria:
        - GIVEN OIDC Discovery Provider is deployed
        - WHEN we check pod status
        - THEN at least one pod is Running
        """
        logger.info("Checking OIDC Discovery Provider pods")
        pods = ocp_client.core_v1.list_namespaced_pod(
            namespace=operator_namespace
        )
        
        oidc_pods = [p for p in pods.items if "oidc" in p.metadata.name.lower()]
        
        assert len(oidc_pods) > 0, "No OIDC Discovery Provider pods found"
        
        running_pods = [p for p in oidc_pods if p.status.phase == "Running"]
        assert len(running_pods) > 0, "No OIDC pods in Running state"
        
        for pod in running_pods:
            logger.info(f"  Pod {pod.metadata.name}: {pod.status.phase}")
        
        logger.info(f"✅ {len(running_pods)} OIDC pods running")


