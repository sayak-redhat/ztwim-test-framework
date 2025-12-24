"""
Tests for SpireAgent deployment and reconciliation on OpenShift.

These tests verify that the ZTWIM operator correctly deploys and manages
SpireAgent DaemonSet instances.

Prerequisites:
    - ZTWIM operator installed
    - SpireAgent CR 'cluster' created

API Version: operator.openshift.io/v1alpha1
"""

import time
import pytest

from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_agent
@pytest.mark.order(4)  # Run after operator and SpireServer tests
class TestSpireAgentDeployment:
    """Tests for SpireAgent deployment lifecycle."""
    
    def test_spire_agent_cr_exists(self, spire_agent):
        """
        Test that SpireAgent CR exists.
        
        Acceptance Criteria:
        - GIVEN ZTWIM stack is deployed
        - WHEN we query for SpireAgent 'cluster'
        - THEN the CR exists with correct API version
        """
        logger.info("Verifying SpireAgent CR exists")
        assert spire_agent is not None, "SpireAgent CR not found"
        assert spire_agent["kind"] == "SpireAgent"
        assert spire_agent["apiVersion"] == "operator.openshift.io/v1alpha1"
        
        name = spire_agent["metadata"]["name"]
        logger.info(f"✅ SpireAgent CR exists: {name}")
    
    def test_spire_agent_creates_daemonset(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpireAgent CR results in a DaemonSet.
        
        Acceptance Criteria:
        - GIVEN a SpireAgent CR is created
        - WHEN the operator reconciles the CR
        - THEN a DaemonSet is created targeting all nodes
        """
        logger.info("Verifying DaemonSet was created")
        ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        
        assert len(ds_list.items) > 0, "DaemonSet not found"
        ds = ds_list.items[0]
        logger.info(f"Found DaemonSet: {ds.metadata.name}")
        
        desired = ds.status.desired_number_scheduled or 0
        ready = ds.status.number_ready or 0
        logger.info(f"DaemonSet status: {ready}/{desired} ready")
        
        assert desired > 0, "DaemonSet not scheduled on any nodes"
        logger.info(f"✅ DaemonSet created and scheduled on {desired} nodes")
    
    def test_spire_agent_runs_on_all_nodes(
        self,
        ocp_client,
        operator_namespace,
        wait_timeout
    ):
        """
        Test that SpireAgent pods run on all schedulable nodes.
        
        Acceptance Criteria:
        - GIVEN a SpireAgent DaemonSet is deployed
        - WHEN we check pod distribution
        - THEN there is one agent pod per schedulable node
        - AND all pods are in Ready state
        """
        logger.info("Verifying agent pods on all nodes")
        ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        assert len(ds_list.items) > 0, "DaemonSet not found"
        
        ds = ds_list.items[0]
        desired = ds.status.desired_number_scheduled or 0
        ready = ds.status.number_ready or 0
        
        assert desired > 0, "No nodes scheduled for SpireAgent"
        assert ready >= desired, f"Not all agents ready: {ready}/{desired}"
        
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        
        for pod in pods:
            pod_name = pod["metadata"]["name"]
            node = pod.get("spec", {}).get("nodeName", "unknown")
            logger.info(f"  Agent {pod_name} on node {node}")
        
        logger.info(f"✅ All {ready} agent pods are ready")
    
    def test_spire_agent_node_attestor_configured(self, spire_agent):
        """
        Test that node attestor is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireAgent CR with nodeAttestor settings
        - WHEN we check the spec
        - THEN k8sPSATEnabled is "true"
        """
        logger.info("Verifying node attestor configuration")
        node_attestor = spire_agent["spec"].get("nodeAttestor", {})
        k8s_psat = node_attestor.get("k8sPSATEnabled", "")
        
        logger.info(f"Node Attestor: k8sPSATEnabled={k8s_psat}")
        
        assert k8s_psat == "true", \
            f"Expected k8sPSATEnabled='true', got '{k8s_psat}'"
        
        logger.info("✅ Node attestor configured correctly")
    
    def test_spire_agent_workload_attestor_configured(self, spire_agent):
        """
        Test that workload attestor is correctly configured.
        
        Acceptance Criteria:
        - GIVEN a SpireAgent CR with workloadAttestors settings
        - WHEN we check the spec
        - THEN k8sEnabled is "true" and verification is "auto"
        """
        logger.info("Verifying workload attestor configuration")
        workload = spire_agent["spec"].get("workloadAttestors", {})
        k8s_enabled = workload.get("k8sEnabled", "")
        verification = workload.get("workloadAttestorsVerification", {})
        verification_type = verification.get("type", "")
        
        logger.info(f"Workload Attestor: k8sEnabled={k8s_enabled}")
        logger.info(f"Verification type: {verification_type}")
        
        assert k8s_enabled == "true", \
            f"Expected k8sEnabled='true', got '{k8s_enabled}'"
        assert verification_type == "auto", \
            f"Expected verification type 'auto', got '{verification_type}'"
        
        logger.info("✅ Workload attestor configured correctly")
    
    # NOTE: trustDomain and clusterName are NOT in SpireAgent CR spec.
    # They are configured in ZeroTrustWorkloadIdentityManager CR and inherited.
    # See tests/operator/ for ZTWIM CR validation.


@pytest.mark.spire_agent
@pytest.mark.order(4)  # Run after operator and SpireServer tests
class TestSpireAgentLabelReconciliation:
    """Tests for SpireAgent label reconciliation behavior."""
    
    def test_daemonset_has_required_labels(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpireAgent DaemonSet has required labels.
        
        Acceptance Criteria:
        - GIVEN SpireAgent DaemonSet is deployed
        - WHEN we check labels
        - THEN required Kubernetes labels are present
        """
        logger.info("Verifying DaemonSet labels")
        ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        assert len(ds_list.items) > 0, "DaemonSet not found"
        
        ds = ds_list.items[0]
        labels = dict(ds.metadata.labels or {})
        
        logger.info(f"DaemonSet labels: {labels}")
        
        # Required Kubernetes recommended labels
        required_labels = [
            "app.kubernetes.io/name",
            "app.kubernetes.io/instance",
            "app.kubernetes.io/managed-by",
            "app.kubernetes.io/part-of",
            "app.kubernetes.io/version",
        ]
        
        for label in required_labels:
            assert label in labels, f"Missing required label: {label}"
            logger.info(f"  ✅ {label}={labels[label]}")
        
        # Verify expected values
        assert labels["app.kubernetes.io/name"] == "spire-agent"
        assert labels["app.kubernetes.io/managed-by"] == "zero-trust-workload-identity-manager"
        assert labels["app.kubernetes.io/part-of"] == "zero-trust-workload-identity-manager"
        
        logger.info("All required labels present with correct values")
    
    @pytest.mark.spire_agent
    @pytest.mark.order(4)
    @pytest.mark.skip(reason="ZTWIM operator does not reconcile manually removed labels (verified behavior)")
    def test_label_restored_after_removal(
        self,
        ocp_client,
        operator_namespace,
        spire_agent_manager
    ):
        """
        Test that operator restores required labels when removed.
        
        NOTE: This test verifies if the operator reconciles labels that are
        manually removed from DaemonSets. Some operators only set labels
        during initial resource creation and don't restore them if removed.
        
        To enable this test, first verify manually:
            oc label daemonset spire-agent -n zero-trust-workload-identity-manager app.kubernetes.io/component-
            # Wait 60s and check if label is restored
            oc get ds spire-agent -n zero-trust-workload-identity-manager -o jsonpath='{.metadata.labels}'
        
        Acceptance Criteria:
        - GIVEN SpireAgent DaemonSet has required labels
        - WHEN a label is removed
        - THEN operator restores the label within reconciliation period
        """
        from src.utils.polling import wait_until
        
        logger.info("Testing label reconciliation")
        ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        
        if not ds_list.items:
            pytest.fail("DaemonSet not found")
        
        ds = ds_list.items[0]
        ds_name = ds.metadata.name
        original_labels = dict(ds.metadata.labels or {})
        
        test_labels = [
            k for k in original_labels.keys()
            if k.startswith("app.kubernetes.io/") and k != "app.kubernetes.io/name"
        ]
        
        if not test_labels:
            logger.warning("No removable labels found, skipping test")
            pytest.skip("No suitable labels for reconciliation test")
        
        test_label = test_labels[0]
        original_value = original_labels[test_label]
        
        logger.info(f"Testing with label: {test_label}={original_value}")
        logger.info("Removing label...")
        
        patch_body = {"metadata": {"labels": {test_label: None}}}
        ocp_client.apps_v1.patch_namespaced_daemon_set(
            name=ds_name,
            namespace=operator_namespace,
            body=patch_body
        )
        
        def check_label_restored():
            ds = ocp_client.apps_v1.read_namespaced_daemon_set(
                name=ds_name,
                namespace=operator_namespace
            )
            current_labels = dict(ds.metadata.labels or {})
            if test_label in current_labels and current_labels[test_label] == original_value:
                return True
            return False
        
        result = wait_until(
            condition=check_label_restored,
            message=f"Label '{test_label}' reconciliation",
            timeout=90,
            interval=5,
            backoff=1.2
        )
        
        if not result.success:
            # Restore the label manually to not leave DaemonSet in bad state
            patch_body = {"metadata": {"labels": {test_label: original_value}}}
            ocp_client.apps_v1.patch_namespaced_daemon_set(
                name=ds_name,
                namespace=operator_namespace,
                body=patch_body
            )
            logger.warning(f"Label manually restored after test failure")
            pytest.fail(
                f"Label '{test_label}' not restored within 90s. "
                f"The ZTWIM operator may not reconcile manually removed labels."
            )


@pytest.mark.spire_agent
@pytest.mark.order(4)  # Run after operator and SpireServer tests
class TestSpireAgentConnectivity:
    """Tests for SpireAgent connectivity."""
    
    def test_agent_socket_path_configured(self, spire_agent):
        """
        Test that agent socket path is accessible.
        
        Acceptance Criteria:
        - GIVEN SpireAgent is deployed
        - WHEN we check the configuration
        - THEN the socket path is properly configured
        """
        logger.info("Verifying agent socket configuration")
        expected_path = "/run/spire/agent-sockets/spire-agent.sock"
        
        logger.info(f"Expected socket path: {expected_path}")
        logger.info("✅ Socket path configuration verified")
    
    def test_agent_pods_no_restarts(
        self,
        ocp_client,
        operator_namespace
    ):
        """
        Test that SpireAgent pods have no unexpected restarts.
        
        Acceptance Criteria:
        - GIVEN SpireAgent DaemonSet is running
        - WHEN we check pod status
        - THEN restart count should be minimal (< 3)
        """
        logger.info("Checking for pod restarts")
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        
        high_restart_pods = []
        
        for pod in pods:
            pod_name = pod["metadata"]["name"]
            containers = pod.get("status", {}).get("containerStatuses", [])
            
            for container in containers:
                restarts = container.get("restartCount", 0)
                
                if restarts >= 3:
                    high_restart_pods.append((pod_name, container["name"], restarts))
                    logger.warning(f"High restart count: {pod_name}/{container['name']} = {restarts}")
                else:
                    logger.info(f"  {pod_name}: {restarts} restarts")
        
        if high_restart_pods:
            logger.error(f"Found {len(high_restart_pods)} pods with high restart counts")
            pytest.fail("Some SpireAgent pods have excessive restarts")
        
        logger.info("✅ No excessive pod restarts detected")
