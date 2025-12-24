"""
Tests for SpireServer deployment and lifecycle on OpenShift.

These tests verify that the ZTWIM operator correctly deploys and manages
SpireServer instances.

Prerequisites:
    - ZTWIM operator installed in zero-trust-workload-identity-manager namespace
    - ZeroTrustWorkloadIdentityManager CR 'cluster' created
    - SpireServer CR 'cluster' created

API Version: operator.openshift.io/v1alpha1
"""

import time
import pytest

from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_server
@pytest.mark.order(3)  # Run after operator tests
class TestSpireServerDeployment:
    """Tests for SpireServer deployment lifecycle."""
    
    def test_spire_server_cr_exists(self, spire_server):
        """
        Test that SpireServer CR exists.
        
        Acceptance Criteria:
        - GIVEN ZTWIM stack is deployed
        - WHEN we query for SpireServer 'cluster'
        - THEN the CR exists with correct API version
        """
        logger.info("Verifying SpireServer CR exists")
        assert spire_server is not None, "SpireServer CR not found"
        assert spire_server["kind"] == "SpireServer"
        assert spire_server["apiVersion"] == "operator.openshift.io/v1alpha1"
        
        name = spire_server["metadata"]["name"]
        logger.info(f"✅ SpireServer CR exists: {name}")
    
    def test_spire_server_creates_statefulset(
        self,
        ocp_client,
        spire_server,
        operator_namespace
    ):
        """
        Test that SpireServer CR results in a StatefulSet.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR is created
        - WHEN the operator reconciles the CR
        - THEN a StatefulSet is created in the operator namespace
        """
        logger.info("Verifying StatefulSet was created")
        sts_list = ocp_client.apps_v1.list_namespaced_stateful_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server"
        )
        
        assert len(sts_list.items) > 0, "StatefulSet not found"
        sts = sts_list.items[0]
        logger.info(f"Found StatefulSet: {sts.metadata.name}")
        logger.info(f"  Replicas: {sts.status.ready_replicas}/{sts.spec.replicas}")
        logger.info("✅ StatefulSet created successfully")
    
    def test_spire_server_pods_are_ready(
        self,
        ocp_client,
        operator_namespace,
        wait_timeout
    ):
        """
        Test that SpireServer pods reach ready state.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR is created
        - WHEN the operator reconciles the CR
        - THEN all pods reach Ready state
        """
        logger.info("Verifying SpireServer pods are ready")
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=wait_timeout
        )
        
        assert len(pods) >= 1, "No ready SpireServer pods found"
        
        for pod in pods:
            pod_name = pod["metadata"]["name"]
            logger.info(f"✅ Pod ready: {pod_name}")
    
    def test_spire_server_service_created(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that Services are created for SpireServer.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR is deployed
        - WHEN the operator reconciles
        - THEN Services are created for SPIRE server communication
        """
        logger.info("Verifying Services were created")
        services = ocp_client.core_v1.list_namespaced_service(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server"
        )
        
        assert len(services.items) > 0, "No SpireServer services found"
        
        for svc in services.items:
            ports = [f"{p.port}/{p.protocol}" for p in svc.spec.ports]
            logger.info(f"Found Service: {svc.metadata.name} ({', '.join(ports)})")
        
        logger.info("✅ Services created successfully")
    
    def test_spire_server_jwt_issuer_configured(
        self,
        spire_server,
        jwt_issuer_endpoint
    ):
        """
        Test that JWT issuer is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR with jwtIssuer
        - WHEN we check the spec
        - THEN jwtIssuer matches expected endpoint
        """
        logger.info("Verifying JWT issuer configuration")
        jwt_issuer = spire_server["spec"].get("jwtIssuer", "")
        expected = f"https://{jwt_issuer_endpoint}"
        
        logger.info(f"Configured JWT Issuer: {jwt_issuer}")
        logger.info(f"Expected: {expected}")
        
        assert jwt_issuer == expected, \
            f"JWT issuer mismatch: expected '{expected}', got '{jwt_issuer}'"
        
        logger.info("✅ JWT issuer configured correctly")
    
    def test_spire_server_ca_subject_configured(
        self,
        spire_server,
        app_domain
    ):
        """
        Test that CA subject is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR with caSubject
        - WHEN we check the spec
        - THEN caSubject contains expected values
        """
        logger.info("Verifying CA subject configuration")
        ca_subject = spire_server["spec"].get("caSubject", {})
        
        common_name = ca_subject.get("commonName", "")
        country = ca_subject.get("country", "")
        organization = ca_subject.get("organization", "")
        
        logger.info(f"CA Subject: CN={common_name}, C={country}, O={organization}")
        
        assert common_name == app_domain, \
            f"CA commonName mismatch: expected '{app_domain}', got '{common_name}'"
        assert country == "US", f"CA country mismatch: expected 'US', got '{country}'"
        assert organization == "RH", f"CA organization mismatch: expected 'RH', got '{organization}'"
        
        logger.info("✅ CA subject configured correctly")
    
    def test_spire_server_persistence_configured(self, spire_server):
        """
        Test that persistence is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR with persistence settings
        - WHEN we check the spec
        - THEN persistence is configured (size and accessMode present)
        """
        logger.info("Verifying persistence configuration")
        persistence = spire_server["spec"].get("persistence", {})
        
        # The 'type' field may be optional or named differently
        pvc_type = persistence.get("type", "")
        size = persistence.get("size", "")
        access_mode = persistence.get("accessMode", "")
        
        logger.info(f"Persistence: type={pvc_type}, size={size}, accessMode={access_mode}")
        
        # Size and accessMode are required; type may be omitted (defaults to pvc)
        assert size, f"Persistence size not configured, got: {persistence}"
        assert access_mode, f"Persistence accessMode not configured, got: {persistence}"
        
        logger.info("✅ Persistence configured correctly")


@pytest.mark.spire_server
@pytest.mark.order(3)  # Run after operator tests
class TestSpireServerDatastore:
    """Tests for SpireServer datastore configuration."""
    
    def test_datastore_sqlite3_configured(self, spire_server):
        """
        Test that SQLite3 datastore is configured.
        
        Acceptance Criteria:
        - GIVEN a SpireServer CR with datastore settings
        - WHEN we check the spec
        - THEN datastore is configured for SQLite3
        """
        logger.info("Verifying datastore configuration")
        datastore = spire_server["spec"].get("datastore", {})
        
        db_type = datastore.get("databaseType", "")
        conn_string = datastore.get("connectionString", "")
        max_open = datastore.get("maxOpenConns", 0)
        max_idle = datastore.get("maxIdleConns", 0)
        max_lifetime = datastore.get("connMaxLifetime", 0)
        
        logger.info(f"Datastore type: {db_type}")
        logger.info(f"Connection string: {conn_string}")
        logger.info(f"Max Open: {max_open}, Max Idle: {max_idle}, Max Lifetime: {max_lifetime}s")
        
        assert db_type == "sqlite3", f"Expected databaseType 'sqlite3', got '{db_type}'"
        assert conn_string == "/run/spire/data/datastore.sqlite3", \
            f"Unexpected connection string: {conn_string}"
        
        logger.info("✅ Datastore configured correctly")


@pytest.mark.spire_server
@pytest.mark.order(3)  # Run after operator tests
class TestSpireServerNegative:
    """Negative tests for SpireServer."""
    
    def test_spire_server_logs_accessible(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpireServer pod logs are accessible.
        
        Acceptance Criteria:
        - GIVEN SpireServer pods are running
        - WHEN we fetch pod logs
        - THEN logs are returned without errors
        """
        logger.info("Verifying pod logs are accessible")
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server"
        )
        assert len(pods) > 0, "No SpireServer pods found"
        
        pod_name = pods[0]["metadata"]["name"]
        
        try:
            logs = ocp_client.get_pod_logs(
                name=pod_name,
                namespace=operator_namespace,
                container="spire-server",
                tail_lines=50
            )
            
            logger.info(f"Got {len(logs)} bytes of logs from {pod_name}")
            
        except Exception as e:
            logger.error(f"Failed to get pod logs: {e}")
            raise
        
        if "FATAL" in logs or "panic" in logs.lower():
            logger.error("Critical errors found in SpireServer logs")
            pytest.fail("SpireServer has critical errors in logs")
        
        logger.info("✅ Pod logs accessible and no critical errors")
