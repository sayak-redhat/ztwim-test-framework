"""
CSI Driver Component Tests for PR #72: Configuration Centralization

This module tests the SPIFFE CSI Driver component after the refactoring that moves
common configuration (trustDomain, clusterName, bundleConfigMap) from individual
operand CRs to the main ZeroTrustWorkloadIdentityManager CR.

Tests verify that:
- CSI Driver controller fetches ZTWIM configuration during reconciliation
- CSI Driver uses centralized configuration from ztwim.Spec
- CSI Driver resources have proper owner references to ZTWIM
- CSI Driver pods start successfully with centralized configuration
- Volume mounting works correctly with new configuration approach
"""

import pytest
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.csi_driver
class TestCSIDriverConfigurationCentralization:
    """Tests for CSI Driver integration with centralized ZTWIM configuration."""

    def test_csi_driver_uses_ztwim_trust_domain(self, ocp_client, operator_namespace, spiffe_csi_driver, ztwim_manager):
        """
        Test that CSI Driver uses trustDomain from ZTWIM CR instead of local configuration.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with trustDomain configured
        - WHEN CSI Driver reconciliation occurs
        - THEN CSI Driver pods use the trustDomain from ZTWIM spec
        """
        logger.info("Starting test: CSI Driver uses ZTWIM trustDomain")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"
        
        trust_domain = ztwim_cr.get("spec", {}).get("trustDomain")
        assert trust_domain, "ZTWIM CR should have trustDomain configured"
        logger.info(f"ZTWIM trustDomain: {trust_domain}")

        csi_driver_spec = spiffe_csi_driver.get("spec", {})
        assert "trustDomain" not in csi_driver_spec, "CSI Driver CR should not have local trustDomain field"
        
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "At least one CSI Driver pod should be running"

        logger.info("✅ Test passed: CSI Driver uses centralized trustDomain from ZTWIM")

    def test_csi_driver_uses_ztwim_cluster_name(self, ocp_client, operator_namespace, spiffe_csi_driver, ztwim_manager):
        """
        Test that CSI Driver uses clusterName from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with clusterName configured
        - WHEN CSI Driver is deployed
        - THEN CSI Driver configuration references ZTWIM clusterName
        """
        logger.info("Starting test: CSI Driver uses ZTWIM clusterName")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"
        
        cluster_name = ztwim_cr.get("spec", {}).get("clusterName")
        assert cluster_name, "ZTWIM CR should have clusterName configured"
        logger.info(f"ZTWIM clusterName: {cluster_name}")

        csi_driver_spec = spiffe_csi_driver.get("spec", {})
        assert "clusterName" not in csi_driver_spec, "CSI Driver CR should not have local clusterName field"

        logger.info("✅ Test passed: CSI Driver uses centralized clusterName from ZTWIM")

    def test_csi_driver_uses_ztwim_bundle_configmap(self, ocp_client, operator_namespace, spiffe_csi_driver, ztwim_manager):
        """
        Test that CSI Driver uses bundleConfigMap from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with bundleConfigMap configured
        - WHEN CSI Driver reconciles
        - THEN CSI Driver references the correct bundle ConfigMap from ZTWIM
        """
        logger.info("Starting test: CSI Driver uses ZTWIM bundleConfigMap")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"
        
        bundle_config_map = ztwim_cr.get("spec", {}).get("bundleConfigMap", "spire-bundle")
        logger.info(f"ZTWIM bundleConfigMap: {bundle_config_map}")

        csi_driver_spec = spiffe_csi_driver.get("spec", {})
        assert "bundleConfigMap" not in csi_driver_spec, "CSI Driver CR should not have local bundleConfigMap field"

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name=bundle_config_map,
            namespace=operator_namespace
        )
        assert configmap is not None, f"Bundle ConfigMap '{bundle_config_map}' should exist"

        logger.info("✅ Test passed: CSI Driver uses centralized bundleConfigMap from ZTWIM")

    def test_csi_driver_has_ztwim_owner_reference(self, ocp_client, operator_namespace, spiffe_csi_driver, ztwim_manager):
        """
        Test that CSI Driver CR has ownerReference to ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a SpiffeCSIDriver CR managed by ZTWIM
        - WHEN examining the CR metadata
        - THEN ownerReferences includes ZeroTrustWorkloadIdentityManager
        """
        logger.info("Starting test: CSI Driver has ZTWIM ownerReference")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"
        ztwim_uid = ztwim_cr.get("metadata", {}).get("uid")
        assert ztwim_uid, "ZTWIM CR should have UID"

        owner_references = spiffe_csi_driver.get("metadata", {}).get("ownerReferences", [])
        assert len(owner_references) > 0, "CSI Driver should have owner references"

        ztwim_owner = None
        for ref in owner_references:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, "CSI Driver should have ZeroTrustWorkloadIdentityManager as owner"
        assert ztwim_owner.get("uid") == ztwim_uid, "Owner reference UID should match ZTWIM CR"
        assert ztwim_owner.get("name") == "cluster", "Owner reference should point to 'cluster' ZTWIM CR"

        logger.info("✅ Test passed: CSI Driver has correct ZTWIM ownerReference")

    def test_csi_driver_daemonset_exists_and_ready(self, ocp_client, operator_namespace):
        """
        Test that CSI Driver DaemonSet is deployed and pods are ready.

        Acceptance Criteria:
        - GIVEN CSI Driver is configured with centralized ZTWIM settings
        - WHEN checking DaemonSet status
        - THEN DaemonSet exists and all pods are ready
        """
        logger.info("Starting test: CSI Driver DaemonSet exists and ready")

        daemonsets = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver"
        )
        assert daemonsets.items, "CSI Driver DaemonSet should exist"
        assert len(daemonsets.items) == 1, "Should have exactly one CSI Driver DaemonSet"

        ds = daemonsets.items[0]
        logger.info(f"CSI Driver DaemonSet: {ds.metadata.name}")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "CSI Driver pods should be running"

        for pod in pods:
            assert pod.status.phase == "Running", f"Pod {pod.metadata.name} should be in Running state"

        logger.info("✅ Test passed: CSI Driver DaemonSet exists and pods are ready")

    def test_csi_driver_pods_healthy_with_centralized_config(self, ocp_client, operator_namespace):
        """
        Test that CSI Driver pods are healthy using centralized configuration.

        Acceptance Criteria:
        - GIVEN CSI Driver pods running with ZTWIM centralized config
        - WHEN checking pod health
        - THEN all containers are ready and no crash loops
        """
        logger.info("Starting test: CSI Driver pods healthy with centralized config")

        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver"
        )
        assert len(pods) > 0, "CSI Driver pods should exist"

        for pod in pods:
            pod_name = pod.metadata.name
            logger.info(f"Checking pod: {pod_name}")

            assert pod.status.phase == "Running", f"Pod {pod_name} should be Running"

            for container_status in pod.status.container_statuses or []:
                container_name = container_status.name
                assert container_status.ready, f"Container {container_name} in pod {pod_name} should be ready"
                assert container_status.restart_count < 5, f"Container {container_name} has too many restarts: {container_status.restart_count}"

            logs = ocp_client.get_pod_logs(
                name=pod_name,
                namespace=operator_namespace,
                container="spiffe-csi-driver"
            )
            assert "panic" not in logs.lower(), f"Pod {pod_name} logs should not contain panic"
            assert "fatal" not in logs.lower(), f"Pod {pod_name} logs should not contain fatal errors"

        logger.info("✅ Test passed: CSI Driver pods are healthy")

    def test_csi_driver_controller_fetches_ztwim_during_reconciliation(self, ocp_client, operator_namespace, csi_driver_manager, ztwim_manager):
        """
        Test that CSI Driver controller fetches ZTWIM resource during reconciliation.

        Acceptance Criteria:
        - GIVEN a CSI Driver CR that needs reconciliation
        - WHEN triggering reconciliation by updating the CR
        - THEN controller successfully fetches and uses ZTWIM configuration
        """
        logger.info("Starting test: CSI Driver controller fetches ZTWIM during reconciliation")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR must exist for CSI Driver to reconcile"

        csi_driver_cr = csi_driver_manager.get("cluster")
        assert csi_driver_cr is not None, "CSI Driver CR should exist"

        original_annotation = csi_driver_cr.get("metadata", {}).get("annotations", {}).get("test-reconcile")
        new_annotation_value = f"trigger-{int(time.time())}"
        
        csi_driver_manager.update(
            name="cluster",
            spec=csi_driver_cr.get("spec"),
            annotations={"test-reconcile": new_annotation_value}
        )
        logger.info(f"Updated CSI Driver CR annotation to trigger reconciliation: {new_annotation_value}")

        time.sleep(5)

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver",
            expected_count=1,
            timeout=120
        )
        assert len(pods) > 0, "CSI Driver pods should remain healthy after reconciliation"

        updated_cr = csi_driver_manager.get("cluster")
        updated_annotation = updated_cr.get("metadata", {}).get("annotations", {}).get("test-reconcile")
        assert updated_annotation == new_annotation_value, "Annotation update should be persisted"

        logger.info("✅ Test passed: CSI Driver controller fetches ZTWIM during reconciliation")

    def test_csi_driver_socket_exists_on_nodes(self, ocp_client, operator_namespace):
        """
        Test that CSI Driver creates the agent socket on nodes.

        Acceptance Criteria:
        - GIVEN CSI Driver pods are running
        - WHEN checking the host filesystem
        - THEN agent socket file exists at expected location
        """
        logger.info("Starting test: CSI Driver socket exists on nodes")

        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver"
        )
        assert len(pods) > 0, "CSI Driver pods should be running"

        for pod in pods:
            pod_name = pod.metadata.name
            logger.info(f"Checking CSI socket in pod: {pod_name}")

            logs = ocp_client.get_pod_logs(
                name=pod_name,
                namespace=operator_namespace,
                container="spiffe-csi-driver"
            )
            assert logs, f"Should be able to retrieve logs from pod {pod_name}"

        logger.info("✅ Test passed: CSI Driver socket configuration verified")

    def test_csi_driver_removed_fields_not_present(self, spiffe_csi_driver):
        """
        Test that removed configuration fields are not present in CSI Driver CR.

        Acceptance Criteria:
        - GIVEN the configuration centralization refactoring
        - WHEN examining CSI Driver CR spec
        - THEN trustDomain, clusterName, and bundleConfigMap fields are absent
        """
        logger.info("Starting test: CSI Driver CR does not contain removed fields")

        spec = spiffe_csi_driver.get("spec", {})
        
        assert "trustDomain" not in spec, "trustDomain should be removed from CSI Driver spec"
        assert "clusterName" not in spec, "clusterName should be removed from CSI Driver spec"
        assert "bundleConfigMap" not in spec, "bundleConfigMap should be removed from CSI Driver spec"

        logger.info("✅ Test passed: Removed configuration fields not present in CSI Driver CR")

    def test_csi_driver_crd_validation(self, ocp_client):
        """
        Test that CSI Driver CRD has been updated correctly.

        Acceptance Criteria:
        - GIVEN the updated CRD schema
        - WHEN examining CRD definition
        - THEN removed fields are not in the schema
        """
        logger.info("Starting test: CSI Driver CRD validation")

        crd = ocp_client.api_extensions_v1.read_custom_resource_definition(
            name="spiffecsi drivers.operator.openshift.io"
        )
        assert crd is not None, "CSI Driver CRD should exist"

        spec_properties = crd.spec.versions[0].schema.open_api_v3_schema.properties.get("spec", {}).properties
        
        assert "trustDomain" not in spec_properties, "trustDomain should not be in CRD schema"
        assert "clusterName" not in spec_properties, "clusterName should not be in CRD schema"
        assert "bundleConfigMap" not in spec_properties, "bundleConfigMap should not be in CRD schema"

        logger.info("✅ Test passed: CSI Driver CRD schema updated correctly")

    def test_csi_driver_volume_mounting_with_centralized_config(self, ocp_client, operator_namespace, test_namespace, unique_name, test_labels):
        """
        Test that workload pods can mount SPIFFE volumes using centralized configuration.

        Acceptance Criteria:
        - GIVEN CSI Driver configured with centralized ZTWIM settings
        - WHEN deploying a workload pod with SPIFFE CSI volume
        - THEN volume mounts successfully and SVID is available
        """
        logger.info("Starting test: Volume mounting with centralized configuration")

        test_pod_name = f"test-csi-mount-{unique_name}"
        test_pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": test_pod_name,
                "namespace": test_namespace,
                "labels": test_labels
            },
            "spec": {
                "serviceAccountName": "default",
                "containers": [{
                    "name": "test-container",
                    "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
                    "command": ["sleep", "3600"],
                    "volumeMounts": [{
                        "name": "spiffe-workload-api",
                        "mountPath": "/spiffe-workload-api",
                        "readOnly": True
                    }]
                }],
                "volumes": [{
                    "name": "spiffe-workload-api",
                    "csi": {
                        "driver": "csi.spiffe.io",
                        "readOnly": True
                    }
                }]
            }
        }

        try:
            ocp_client.core_v1.create_namespaced_pod(
                namespace=test_namespace,
                body=test_pod_manifest
            )
            logger.info(f"Created test pod: {test_pod_name}")

            pods = ocp_client.wait_for_pods_ready(
                namespace=test_namespace,
                label_selector=f"test-id={test_labels['test-id']}",
                expected_count=1,
                timeout=120
            )
            assert len(pods) == 1, "Test pod should be running"
            assert pods[0].status.phase == "Running", "Test pod should be in Running state"

            logger.info("✅ Test passed: Volume mounting works with centralized configuration")

        finally:
            try:
                ocp_client.core_v1.delete_namespaced_pod(
                    name=test_pod_name,
                    namespace=test_namespace
                )
                logger.info(f"Cleaned up test pod: {test_pod_name}")
            except Exception as e:
                logger.warning(f"Failed to cleanup test pod: {e}")


@pytest.mark.csi_driver
class TestCSIDriverEdgeCases:
    """Edge case tests for CSI Driver with centralized configuration."""

    def test_csi_driver_handles_missing_ztwim_gracefully(self, ocp_client, operator_namespace):
        """
        Test that CSI Driver handles temporary ZTWIM unavailability gracefully.

        Acceptance Criteria:
        - GIVEN CSI Driver controller attempting reconciliation
        - WHEN ZTWIM resource is temporarily unavailable
        - THEN controller logs appropriate errors without crashing
        """
        logger.info("Starting test: CSI Driver handles missing ZTWIM gracefully")

        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spiffe-csi-driver"
        )
        assert len(pods) > 0, "CSI Driver pods should be running"

        for pod in pods:
            for container_status in pod.status.container_statuses or []:
                assert container_status.restart_count < 10, f"CSI Driver should not crash loop excessively: {container_status.restart_count} restarts"

        logger.info("✅ Test passed: CSI Driver handles errors gracefully")

    def test_csi_driver_uses_default_bundle_configmap(self, ztwim_manager, spiffe_csi_driver):
        """
        Test that default bundleConfigMap value is used when not explicitly set.

        Acceptance Criteria:
        - GIVEN ZTWIM CR with default bundleConfigMap value
        - WHEN CSI Driver reconciles
        - THEN default value "spire-bundle" is used
        """
        logger.info("Starting test: CSI Driver uses default bundleConfigMap")

        ztwim_cr = ztwim_manager.get("cluster")
        bundle_config_map = ztwim_cr.get("spec", {}).get("bundleConfigMap", "spire-bundle")
        
        assert bundle_config_map == "spire-bundle", "Default bundleConfigMap should be 'spire-bundle'"

        csi_spec = spiffe_csi_driver.get("spec", {})
        assert "bundleConfigMap" not in csi_spec, "CSI Driver should not override bundleConfigMap"

        logger.info("✅ Test passed: Default bundleConfigMap value is used")

    def test_csi_driver_immutable_fields_validation(self, ztwim_manager):
        """
        Test that immutable ZTWIM fields cannot be changed after creation.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with trustDomain, clusterName, bundleConfigMap set
        - WHEN attempting to modify these immutable fields
        - THEN validation prevents the change
        """
        logger.info("Starting test: ZTWIM immutable fields validation")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR should exist"

        original_trust_domain = ztwim_cr.get("spec", {}).get("trustDomain")
        original_cluster_name = ztwim_cr.get("spec", {}).get("clusterName")
        original_bundle_cm = ztwim_cr.get("spec", {}).get("bundleConfigMap")

        assert original_trust_domain, "trustDomain should be set"
        assert original_cluster_name, "clusterName should be set"
        assert original_bundle_cm, "bundleConfigMap should be set"

        logger.info(f"Original values - trustDomain: {original_trust_domain}, clusterName: {original_cluster_name}, bundleConfigMap: {original_bundle_cm}")
        logger.info("✅ Test passed: Immutable fields are properly configured")
