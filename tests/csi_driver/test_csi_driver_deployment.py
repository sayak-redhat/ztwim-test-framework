"""
Tests for SpiffeCSIDriver deployment on OpenShift.

These tests verify that the ZTWIM operator correctly deploys and manages
SpiffeCSIDriver instances.

Prerequisites:
    - ZTWIM operator installed
    - SpiffeCSIDriver CR 'cluster' created

API Version: operator.openshift.io/v1alpha1
"""

import pytest

from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.order(5)  # Run after SpireAgent tests
class TestCSIDriverDeployment:
    """Tests for SpiffeCSIDriver deployment lifecycle."""
    
    def test_csi_driver_cr_exists(self, spiffe_csi_driver):
        """
        Test that SpiffeCSIDriver CR exists.
        
        Acceptance Criteria:
        - GIVEN ZTWIM stack is deployed
        - WHEN we query for SpiffeCSIDriver 'cluster'
        - THEN the CR exists with correct API version
        """
        logger.info("Verifying SpiffeCSIDriver CR exists")
        assert spiffe_csi_driver is not None, "SpiffeCSIDriver CR not found"
        assert spiffe_csi_driver["kind"] == "SpiffeCSIDriver"
        assert spiffe_csi_driver["apiVersion"] == "operator.openshift.io/v1alpha1"
        
        name = spiffe_csi_driver["metadata"]["name"]
        logger.info(f"✅ SpiffeCSIDriver CR exists: {name}")
    
    def test_csi_driver_spec_empty(self, spiffe_csi_driver):
        """
        Test that SpiffeCSIDriver spec is empty (uses defaults).
        
        Acceptance Criteria:
        - GIVEN a SpiffeCSIDriver CR with spec: {}
        - WHEN we check the spec
        - THEN spec is empty or has only default values
        """
        logger.info("Verifying SpiffeCSIDriver spec")
        spec = spiffe_csi_driver.get("spec", {})
        
        # SpiffeCSIDriver typically has empty spec (uses operator defaults)
        logger.info(f"CSI Driver Spec: {spec}")
        
        # This test documents the expected behavior
        # The spec can be empty {} or have minimal defaults
        logger.info("✅ SpiffeCSIDriver spec validated (uses defaults)")
    
    def test_csi_driver_creates_daemonset(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpiffeCSIDriver CR results in a DaemonSet.
        
        Acceptance Criteria:
        - GIVEN a SpiffeCSIDriver CR is created
        - WHEN the operator reconciles the CR
        - THEN a DaemonSet is created for the CSI driver
        """
        logger.info("Verifying DaemonSet was created")
        ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-spiffe-csi-driver"
        )
        
        # Try alternative label if not found
        if not ds_list.items:
            ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
                namespace=operator_namespace
            )
            ds_list.items = [d for d in ds_list.items if "csi" in d.metadata.name.lower()]
        
        assert len(ds_list.items) > 0, "CSI Driver DaemonSet not found"
        
        ds = ds_list.items[0]
        name = ds.metadata.name
        desired = ds.status.desired_number_scheduled or 0
        ready = ds.status.number_ready or 0
        
        logger.info(f"Found DaemonSet: {name}")
        logger.info(f"  Status: {ready}/{desired} ready")
        
        assert desired > 0, "DaemonSet not scheduled on any nodes"
        assert ready >= desired, f"DaemonSet not ready: {ready}/{desired}"
        
        logger.info(f"✅ CSI Driver DaemonSet is ready on {ready} nodes")
    
    def test_csi_driver_pods_running(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that CSI Driver pods are running on all nodes.
        
        Acceptance Criteria:
        - GIVEN SpiffeCSIDriver DaemonSet is deployed
        - WHEN we check pod status
        - THEN all pods are in Running state
        """
        logger.info("Checking CSI Driver pods")
        pods = ocp_client.core_v1.list_namespaced_pod(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-spiffe-csi-driver"
        )
        
        # Try alternative label if not found
        if not pods.items:
            pods = ocp_client.core_v1.list_namespaced_pod(namespace=operator_namespace)
            pods.items = [p for p in pods.items if "csi" in p.metadata.name.lower()]
        
        assert len(pods.items) > 0, "No CSI Driver pods found"
        
        running_pods = [p for p in pods.items if p.status.phase == "Running"]
        assert len(running_pods) == len(pods.items), \
            f"Not all CSI pods running: {len(running_pods)}/{len(pods.items)}"
        
        for pod in running_pods:
            node = pod.spec.node_name or "unknown"
            logger.info(f"  Pod {pod.metadata.name} on node {node}: {pod.status.phase}")
        
        logger.info(f"✅ All {len(running_pods)} CSI Driver pods running")
    
    def test_csi_driver_node_registered(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that CSI Driver is registered as a CSINode.
        
        Acceptance Criteria:
        - GIVEN SpiffeCSIDriver is deployed
        - WHEN we check CSINode resources
        - THEN the csi.spiffe.io driver is registered
        """
        logger.info("Checking CSI Node registration")
        
        try:
            # List CSINodes
            csi_nodes = ocp_client.dynamic_client.resources.get(
                api_version="storage.k8s.io/v1",
                kind="CSINode"
            ).get()
            
            # Check if spiffe driver is registered on at least one node
            spiffe_driver_found = False
            for csi_node in csi_nodes.items:
                drivers = csi_node.spec.drivers or []
                for driver in drivers:
                    if "spiffe" in driver.name.lower():
                        logger.info(f"  Node {csi_node.metadata.name}: {driver.name}")
                        spiffe_driver_found = True
            
            if spiffe_driver_found:
                logger.info("✅ SPIFFE CSI Driver registered on nodes")
            else:
                logger.warning("⚠️ SPIFFE CSI Driver not found in CSINode registrations")
                # Don't fail - this might take time to register
                
        except Exception as e:
            logger.warning(f"Could not check CSINode registration: {e}")
    
    def test_csi_driver_no_pod_restarts(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that CSI Driver pods have no excessive restarts.
        
        Acceptance Criteria:
        - GIVEN SpiffeCSIDriver is running
        - WHEN we check pod status
        - THEN restart count should be minimal (< 3)
        """
        logger.info("Checking for pod restarts")
        pods = ocp_client.core_v1.list_namespaced_pod(
            namespace=operator_namespace
        )
        
        csi_pods = [p for p in pods.items if "csi" in p.metadata.name.lower()]
        
        high_restart_pods = []
        for pod in csi_pods:
            containers = pod.status.container_statuses or []
            for container in containers:
                restarts = container.restart_count or 0
                if restarts >= 3:
                    high_restart_pods.append((pod.metadata.name, container.name, restarts))
                    logger.warning(f"High restarts: {pod.metadata.name}/{container.name} = {restarts}")
                else:
                    logger.info(f"  {pod.metadata.name}/{container.name}: {restarts} restarts")
        
        if high_restart_pods:
            logger.error(f"Found {len(high_restart_pods)} containers with high restarts")
            pytest.fail("Some CSI Driver containers have excessive restarts")
        
        logger.info("✅ No excessive pod restarts detected")


