"""
Operator Installation Validation Tests.

These tests run FIRST to validate the ZTWIM operator is properly installed
before testing individual operands.

Test Order: 1 (runs before all operand tests)
"""

import pytest

from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.order(1)  # Run first
class TestOperatorInstallation:
    """Tests for ZTWIM Operator installation via OLM."""

    @pytest.mark.order(1)
    def test_operator_namespace_exists(self, ocp_client, operator_namespace):
        """Verify the operator namespace was created."""
        try:
            ns = ocp_client.core_v1.read_namespace(name=operator_namespace)
            assert ns is not None
            assert ns.metadata.name == operator_namespace
            logger.info(f"✅ Namespace '{operator_namespace}' exists")
            
            # Check for cluster monitoring label
            labels = ns.metadata.labels or {}
            if labels.get("openshift.io/cluster-monitoring") == "true":
                logger.info("✅ Cluster monitoring label present")
                
        except Exception as e:
            pytest.fail(f"Namespace '{operator_namespace}' not found: {e}")

    @pytest.mark.order(2)
    def test_operator_subscription_exists(self, ocp_client, operator_namespace):
        """Verify the OLM subscription for ZTWIM operator exists."""
        try:
            subs = ocp_client.custom_objects.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=operator_namespace,
                plural="subscriptions"
            )
            
            assert len(subs.get("items", [])) > 0, "No subscriptions found"
            
            sub = subs["items"][0]
            sub_name = sub["metadata"]["name"]
            source = sub["spec"]["source"]
            channel = sub["spec"]["channel"]
            
            logger.info(f"✅ Subscription found: {sub_name}")
            logger.info(f"   Source: {source}")
            logger.info(f"   Channel: {channel}")
            
        except Exception as e:
            pytest.fail(f"Subscription not found: {e}")

    @pytest.mark.order(3)
    def test_subscription_source_valid(self, ocp_client, operator_namespace):
        """Verify the subscription source is a valid catalog (not unexpanded variable)."""
        subs = ocp_client.custom_objects.list_namespaced_custom_object(
            group="operators.coreos.com",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="subscriptions"
        )
        
        sub = subs["items"][0]
        source = sub["spec"]["source"]
        
        # Source should NOT contain unexpanded variables
        assert not source.startswith("$"), f"Source contains unexpanded variable: {source}"
        assert "${" not in source, f"Source contains unexpanded variable: {source}"
        
        logger.info(f"✅ Subscription source is valid: {source}")

    @pytest.mark.order(4)
    def test_csv_installed_and_succeeded(self, ocp_client, operator_namespace):
        """Verify the ClusterServiceVersion (CSV) is installed and in Succeeded phase."""
        try:
            csvs = ocp_client.custom_objects.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=operator_namespace,
                plural="clusterserviceversions"
            )
            
            assert len(csvs.get("items", [])) > 0, "No CSV found - operator not installed"
            
            # Find ZTWIM CSV
            ztwim_csv = None
            for csv in csvs["items"]:
                if "zero-trust" in csv["metadata"]["name"].lower():
                    ztwim_csv = csv
                    break
            
            assert ztwim_csv is not None, "ZTWIM CSV not found"
            
            csv_name = ztwim_csv["metadata"]["name"]
            phase = ztwim_csv.get("status", {}).get("phase", "Unknown")
            
            logger.info(f"CSV: {csv_name}")
            logger.info(f"Phase: {phase}")
            
            assert phase == "Succeeded", f"CSV phase is '{phase}', expected 'Succeeded'"
            
            logger.info(f"✅ CSV '{csv_name}' is in Succeeded phase")
            
        except AssertionError:
            raise
        except Exception as e:
            pytest.fail(f"CSV check failed: {e}")

    @pytest.mark.order(5)
    def test_operator_deployment_ready(self, ocp_client, operator_namespace):
        """Verify the operator deployment has ready replicas."""
        deployments = ocp_client.apps_v1.list_namespaced_deployment(
            namespace=operator_namespace
        )
        
        operator_dep = None
        for dep in deployments.items:
            if "zero-trust" in dep.metadata.name.lower():
                operator_dep = dep
                break
        
        assert operator_dep is not None, "Operator deployment not found"
        
        name = operator_dep.metadata.name
        replicas = operator_dep.spec.replicas or 1
        ready = operator_dep.status.ready_replicas or 0
        
        logger.info(f"Deployment: {name}")
        logger.info(f"Replicas: {ready}/{replicas}")
        
        assert ready >= replicas, f"Deployment not ready: {ready}/{replicas}"
        
        logger.info(f"✅ Operator deployment '{name}' is ready")

    @pytest.mark.order(6)
    def test_operator_pod_running(self, ocp_client, operator_namespace):
        """Verify the operator pod is in Running state."""
        pods = ocp_client.core_v1.list_namespaced_pod(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=zero-trust-workload-identity-manager"
        )
        
        # If no pods with that label, try broader search
        if not pods.items:
            pods = ocp_client.core_v1.list_namespaced_pod(namespace=operator_namespace)
            pods.items = [p for p in pods.items if "zero-trust" in p.metadata.name.lower()]
        
        assert len(pods.items) > 0, "No operator pod found"
        
        pod = pods.items[0]
        name = pod.metadata.name
        phase = pod.status.phase
        
        logger.info(f"Pod: {name}")
        logger.info(f"Phase: {phase}")
        
        assert phase == "Running", f"Pod phase is '{phase}', expected 'Running'"
        
        # Check container status
        container_statuses = pod.status.container_statuses or []
        for cs in container_statuses:
            assert cs.ready, f"Container '{cs.name}' is not ready"
            logger.info(f"  Container '{cs.name}': Ready")
        
        logger.info(f"✅ Operator pod '{name}' is running")


@pytest.mark.order(2)  # Run after installation tests
class TestOperatorCRDs:
    """Tests for ZTWIM Operator Custom Resource Definitions."""

    @pytest.mark.order(1)
    def test_ztwim_crd_exists(self, ocp_client):
        """Verify the ZeroTrustWorkloadIdentityManager CRD is registered."""
        try:
            crd = ocp_client.apiextensions_v1.read_custom_resource_definition(
                name="zerotrust-workloadidentitymanagers.operator.openshift.io"
            )
            logger.info(f"✅ZeroTrustWorkloadIdentityManager CRD exists")
        except Exception:
            # Try alternative name
            try:
                crds = ocp_client.apiextensions_v1.list_custom_resource_definition()
                ztwim_crd = None
                for crd in crds.items:
                    if "zerotrust" in crd.metadata.name.lower() or "workloadidentity" in crd.metadata.name.lower():
                        ztwim_crd = crd
                        logger.info(f"✅ Found CRD: {crd.metadata.name}")
                        break
                assert ztwim_crd is not None, "ZeroTrustWorkloadIdentityManager CRD not found"
            except Exception as e:
                pytest.fail(f"CRD check failed: {e}")

    @pytest.mark.order(2)
    def test_spire_server_crd_exists(self, ocp_client):
        """Verify the SpireServer CRD is registered."""
        crds = ocp_client.apiextensions_v1.list_custom_resource_definition()
        spire_server_crd = None
        for crd in crds.items:
            if "spireserver" in crd.metadata.name.lower():
                spire_server_crd = crd
                break
        
        assert spire_server_crd is not None, "SpireServer CRD not found"
        logger.info(f"✅ SpireServer CRD exists: {spire_server_crd.metadata.name}")

    @pytest.mark.order(3)
    def test_spire_agent_crd_exists(self, ocp_client):
        """Verify the SpireAgent CRD is registered."""
        crds = ocp_client.apiextensions_v1.list_custom_resource_definition()
        spire_agent_crd = None
        for crd in crds.items:
            if "spireagent" in crd.metadata.name.lower():
                spire_agent_crd = crd
                break
        
        assert spire_agent_crd is not None, "SpireAgent CRD not found"
        logger.info(f"SpireAgent CRD exists: {spire_agent_crd.metadata.name}")

    @pytest.mark.order(4)
    def test_spiffe_csi_driver_crd_exists(self, ocp_client):
        """Verify the SpiffeCSIDriver CRD is registered."""
        crds = ocp_client.apiextensions_v1.list_custom_resource_definition()
        csi_crd = None
        for crd in crds.items:
            if "spiffecsidriver" in crd.metadata.name.lower():
                csi_crd = crd
                break
        
        assert csi_crd is not None, "SpiffeCSIDriver CRD not found"
        logger.info(f"SpiffeCSIDriver CRD exists: {csi_crd.metadata.name}")

    @pytest.mark.order(5)
    def test_spire_oidc_crd_exists(self, ocp_client):
        """Verify the SpireOIDCDiscoveryProvider CRD is registered."""
        crds = ocp_client.apiextensions_v1.list_custom_resource_definition()
        oidc_crd = None
        for crd in crds.items:
            if "oidcdiscoveryprovider" in crd.metadata.name.lower():
                oidc_crd = crd
                break
        
        assert oidc_crd is not None, "SpireOIDCDiscoveryProvider CRD not found"
        logger.info(f"SpireOIDCDiscoveryProvider CRD exists: {oidc_crd.metadata.name}")


@pytest.mark.order(2)  # Run after operator installation, before component tests
class TestZTWIMCommonConfiguration:
    """
    Tests for ZeroTrustWorkloadIdentityManager CR common configuration.
    
    The ZTWIM CR holds common configuration that is inherited by all
    child operands (SpireServer, SpireAgent, SpiffeCSIDriver, OIDC).
    """

    @pytest.mark.order(1)
    def test_ztwim_cr_exists(self, ztwim_cr):
        """Verify the ZeroTrustWorkloadIdentityManager CR exists."""
        assert ztwim_cr is not None, "ZTWIM CR not found"
        assert ztwim_cr["kind"] == "ZeroTrustWorkloadIdentityManager"
        assert ztwim_cr["apiVersion"] == "operator.openshift.io/v1alpha1"
        
        name = ztwim_cr["metadata"]["name"]
        logger.info(f"✅ ZeroTrustWorkloadIdentityManager CR exists: {name}")

    @pytest.mark.order(2)
    def test_ztwim_trust_domain_configured(self, ztwim_cr, app_domain):
        """
        Verify trustDomain is correctly configured in ZTWIM CR.
        
        This is the COMMON configuration inherited by all operands.
        """
        trust_domain = ztwim_cr["spec"].get("trustDomain", "")
        
        logger.info(f"ZTWIM trustDomain: {trust_domain}")
        logger.info(f"Expected (APP_DOMAIN): {app_domain}")
        
        assert trust_domain, "trustDomain not set in ZTWIM CR"
        assert trust_domain == app_domain, \
            f"Expected trustDomain='{app_domain}', got '{trust_domain}'"
        
        logger.info("✅ trustDomain configured correctly (inherited by all operands)")

    @pytest.mark.order(3)
    def test_ztwim_cluster_name_configured(self, ztwim_cr, cluster_name):
        """
        Verify clusterName is correctly configured in ZTWIM CR.
        
        This is the COMMON configuration inherited by all operands.
        """
        cr_cluster_name = ztwim_cr["spec"].get("clusterName", "")
        
        logger.info(f"ZTWIM clusterName: {cr_cluster_name}")
        logger.info(f"Expected: {cluster_name}")
        
        assert cr_cluster_name, "clusterName not set in ZTWIM CR"
        assert cr_cluster_name == cluster_name, \
            f"Expected clusterName='{cluster_name}', got '{cr_cluster_name}'"
        
        logger.info("✅ clusterName configured correctly (inherited by all operands)")

    @pytest.mark.order(4)
    def test_ztwim_spec_complete(self, ztwim_cr):
        """Verify ZTWIM CR has all required spec fields."""
        spec = ztwim_cr.get("spec", {})
        
        required_fields = ["trustDomain", "clusterName"]
        missing = [f for f in required_fields if not spec.get(f)]
        
        if missing:
            pytest.fail(f"ZTWIM CR missing required fields: {missing}")
        
        logger.info(f"✅ ZTWIM CR spec complete: {list(spec.keys())}")
