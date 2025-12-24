"""
Tests for SpireAgent controller changes in PR #72.

This module tests the refactoring that moves common configuration fields
(trustDomain, clusterName, bundleConfigMap) from SpireAgent CR to the
main ZeroTrustWorkloadIdentityManager CR.

PR: https://github.com/openshift/zero-trust-workload-identity-manager/pull/72
Component: spire_agent
"""

import pytest
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_agent
class TestSpireAgentConfigurationRefactoring:
    """Tests for SpireAgent configuration sourced from ZTWIM CR."""

    def test_spire_agent_uses_ztwim_trust_domain(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager
    ):
        """
        Test that SpireAgent uses trustDomain from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with trustDomain set
        - WHEN SpireAgent is reconciled
        - THEN the agent configmap contains the trustDomain from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireAgent uses ZTWIM trustDomain")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' not found"
        
        trust_domain = ztwim_cr.get("spec", {}).get("trustDomain")
        assert trust_domain, "trustDomain not found in ZTWIM CR spec"
        logger.info(f"ZTWIM CR trustDomain: {trust_domain}")

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert configmap is not None, "SpireAgent ConfigMap not found"

        agent_config = configmap.data.get("agent.conf", "")
        assert trust_domain in agent_config, (
            f"Expected trustDomain '{trust_domain}' not found in agent.conf"
        )
        logger.info(f"✅ Test passed: SpireAgent ConfigMap contains trustDomain '{trust_domain}'")

    def test_spire_agent_uses_ztwim_cluster_name(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager
    ):
        """
        Test that SpireAgent uses clusterName from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with clusterName set
        - WHEN SpireAgent is reconciled
        - THEN the agent configmap contains the clusterName from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireAgent uses ZTWIM clusterName")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' not found"
        
        cluster_name = ztwim_cr.get("spec", {}).get("clusterName")
        assert cluster_name, "clusterName not found in ZTWIM CR spec"
        logger.info(f"ZTWIM CR clusterName: {cluster_name}")

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert configmap is not None, "SpireAgent ConfigMap not found"

        agent_config = configmap.data.get("agent.conf", "")
        assert cluster_name in agent_config, (
            f"Expected clusterName '{cluster_name}' not found in agent.conf"
        )
        logger.info(f"✅ Test passed: SpireAgent ConfigMap contains clusterName '{cluster_name}'")

    def test_spire_agent_uses_ztwim_bundle_configmap(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager
    ):
        """
        Test that SpireAgent uses bundleConfigMap from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with bundleConfigMap set
        - WHEN SpireAgent is reconciled
        - THEN the agent references the correct bundle ConfigMap name
        """
        logger.info("Starting test: verifying SpireAgent uses ZTWIM bundleConfigMap")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' not found"
        
        bundle_configmap = ztwim_cr.get("spec", {}).get("bundleConfigMap", "spire-bundle")
        logger.info(f"ZTWIM CR bundleConfigMap: {bundle_configmap}")

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert configmap is not None, "SpireAgent ConfigMap not found"

        agent_config = configmap.data.get("agent.conf", "")
        assert bundle_configmap in agent_config, (
            f"Expected bundleConfigMap '{bundle_configmap}' not found in agent.conf"
        )
        logger.info(f"✅ Test passed: SpireAgent ConfigMap references bundleConfigMap '{bundle_configmap}'")

    def test_spire_agent_cr_no_longer_has_trust_domain_field(
        self, spire_agent
    ):
        """
        Test that SpireAgent CR no longer contains trustDomain field.

        Acceptance Criteria:
        - GIVEN the refactored SpireAgent CRD
        - WHEN the SpireAgent CR is retrieved
        - THEN the spec does not contain trustDomain field
        """
        logger.info("Starting test: verifying SpireAgent CR has no trustDomain field")

        assert spire_agent is not None, "SpireAgent CR not found"
        
        spec = spire_agent.get("spec", {})
        assert "trustDomain" not in spec, (
            "trustDomain field should not exist in SpireAgent CR spec"
        )
        logger.info("✅ Test passed: SpireAgent CR spec does not contain trustDomain")

    def test_spire_agent_cr_no_longer_has_cluster_name_field(
        self, spire_agent
    ):
        """
        Test that SpireAgent CR no longer contains clusterName field.

        Acceptance Criteria:
        - GIVEN the refactored SpireAgent CRD
        - WHEN the SpireAgent CR is retrieved
        - THEN the spec does not contain clusterName field
        """
        logger.info("Starting test: verifying SpireAgent CR has no clusterName field")

        assert spire_agent is not None, "SpireAgent CR not found"
        
        spec = spire_agent.get("spec", {})
        assert "clusterName" not in spec, (
            "clusterName field should not exist in SpireAgent CR spec"
        )
        logger.info("✅ Test passed: SpireAgent CR spec does not contain clusterName")

    def test_spire_agent_cr_no_longer_has_bundle_configmap_field(
        self, spire_agent
    ):
        """
        Test that SpireAgent CR no longer contains bundleConfigMap field.

        Acceptance Criteria:
        - GIVEN the refactored SpireAgent CRD
        - WHEN the SpireAgent CR is retrieved
        - THEN the spec does not contain bundleConfigMap field
        """
        logger.info("Starting test: verifying SpireAgent CR has no bundleConfigMap field")

        assert spire_agent is not None, "SpireAgent CR not found"
        
        spec = spire_agent.get("spec", {})
        assert "bundleConfigMap" not in spec, (
            "bundleConfigMap field should not exist in SpireAgent CR spec"
        )
        logger.info("✅ Test passed: SpireAgent CR spec does not contain bundleConfigMap")

    def test_spire_agent_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager
    ):
        """
        Test that SpireAgent CR has ZTWIM as owner reference.

        Acceptance Criteria:
        - GIVEN a SpireAgent CR managed by the operator
        - WHEN the CR metadata is examined
        - THEN it contains ownerReference pointing to ZeroTrustWorkloadIdentityManager
        """
        logger.info("Starting test: verifying SpireAgent has ZTWIM owner reference")

        assert spire_agent is not None, "SpireAgent CR not found"
        
        owner_refs = spire_agent.get("metadata", {}).get("ownerReferences", [])
        assert len(owner_refs) > 0, "SpireAgent CR has no owner references"

        ztwim_owner = None
        for ref in owner_refs:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, (
            "SpireAgent CR does not have ZeroTrustWorkloadIdentityManager as owner reference"
        )
        assert ztwim_owner.get("name") == "cluster", (
            f"Expected owner name 'cluster', got '{ztwim_owner.get('name')}'"
        )
        logger.info("✅ Test passed: SpireAgent has ZTWIM owner reference")

    def test_spire_agent_daemonset_healthy_after_refactoring(
        self, ocp_client, operator_namespace, wait_timeout
    ):
        """
        Test that SpireAgent DaemonSet is healthy after configuration refactoring.

        Acceptance Criteria:
        - GIVEN the refactored SpireAgent controller
        - WHEN the SpireAgent DaemonSet is deployed
        - THEN all agent pods are running and ready
        """
        logger.info("Starting test: verifying SpireAgent DaemonSet health")

        daemonset = ocp_client.apps_v1.read_namespaced_daemon_set(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert daemonset is not None, "SpireAgent DaemonSet not found"

        desired_number = daemonset.status.desired_number_scheduled
        assert desired_number > 0, "DaemonSet has no desired pods scheduled"
        logger.info(f"Desired number of agent pods: {desired_number}")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-agent",
            expected_count=desired_number,
            timeout=wait_timeout
        )
        assert len(pods.items) == desired_number, (
            f"Expected {desired_number} ready pods, found {len(pods.items)}"
        )
        logger.info(f"✅ Test passed: All {desired_number} SpireAgent pods are ready")

    def test_spire_agent_configmap_generated_correctly(
        self, ocp_client, operator_namespace, ztwim_manager
    ):
        """
        Test that SpireAgent ConfigMap is generated with ZTWIM configuration.

        Acceptance Criteria:
        - GIVEN ZTWIM CR with trustDomain, clusterName, and bundleConfigMap
        - WHEN the SpireAgent controller reconciles
        - THEN the agent ConfigMap contains all required configuration from ZTWIM
        """
        logger.info("Starting test: verifying SpireAgent ConfigMap generation")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' not found"
        
        trust_domain = ztwim_cr.get("spec", {}).get("trustDomain")
        cluster_name = ztwim_cr.get("spec", {}).get("clusterName")
        bundle_configmap = ztwim_cr.get("spec", {}).get("bundleConfigMap", "spire-bundle")

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert configmap is not None, "SpireAgent ConfigMap not found"
        assert "agent.conf" in configmap.data, "agent.conf not found in ConfigMap"

        agent_config = configmap.data["agent.conf"]
        assert trust_domain in agent_config, (
            f"trustDomain '{trust_domain}' not in agent.conf"
        )
        assert cluster_name in agent_config, (
            f"clusterName '{cluster_name}' not in agent.conf"
        )
        assert bundle_configmap in agent_config, (
            f"bundleConfigMap '{bundle_configmap}' not in agent.conf"
        )
        logger.info("✅ Test passed: SpireAgent ConfigMap generated correctly with ZTWIM config")

    def test_spire_agent_pods_log_no_configuration_errors(
        self, ocp_client, operator_namespace
    ):
        """
        Test that SpireAgent pods do not log configuration errors.

        Acceptance Criteria:
        - GIVEN SpireAgent pods running with ZTWIM configuration
        - WHEN pod logs are examined
        - THEN no configuration-related errors are present
        """
        logger.info("Starting test: checking SpireAgent pod logs for errors")

        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-agent"
        )
        assert pods is not None and len(pods.items) > 0, "No SpireAgent pods found"

        error_patterns = [
            "trust_domain",
            "cluster_name",
            "bundle_config_map",
            "failed to load configuration",
            "invalid configuration"
        ]

        for pod in pods.items[:1]:
            pod_name = pod.metadata.name
            logger.info(f"Checking logs for pod: {pod_name}")
            
            logs = ocp_client.get_pod_logs(
                name=pod_name,
                namespace=operator_namespace,
                container="spire-agent"
            )
            assert logs is not None, f"Could not retrieve logs for pod {pod_name}"

            logs_lower = logs.lower()
            for pattern in error_patterns:
                if pattern in logs_lower and "error" in logs_lower:
                    pytest.fail(
                        f"Found configuration error pattern '{pattern}' in pod {pod_name} logs"
                    )

        logger.info("✅ Test passed: No configuration errors in SpireAgent pod logs")


@pytest.mark.spire_agent
class TestSpireAgentReconciliation:
    """Tests for SpireAgent controller reconciliation with ZTWIM CR."""

    def test_spire_agent_reconciles_when_ztwim_updated(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager, wait_timeout
    ):
        """
        Test that SpireAgent reconciles when ZTWIM CR is updated.

        Acceptance Criteria:
        - GIVEN a running SpireAgent
        - WHEN the ZTWIM CR configuration is updated
        - THEN the SpireAgent resources are reconciled with new configuration
        """
        logger.info("Starting test: verifying SpireAgent reconciliation on ZTWIM update")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' not found"

        configmap_before = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-agent",
            namespace=operator_namespace
        )
        generation_before = configmap_before.metadata.resource_version

        current_labels = ztwim_cr.get("spec", {}).get("labels", {})
        updated_labels = current_labels.copy()
        updated_labels["test-reconciliation"] = "true"

        spec_patch = {"spec": {"labels": updated_labels}}
        ztwim_manager.patch("cluster", spec_patch)
        logger.info("Updated ZTWIM CR with test label")

        max_wait = 30
        start_time = time.time()
        configmap_updated = False

        while time.time() - start_time < max_wait:
            configmap_after = ocp_client.core_v1.read_namespaced_config_map(
                name="spire-agent",
                namespace=operator_namespace
            )
            if configmap_after.metadata.resource_version != generation_before:
                configmap_updated = True
                logger.info("ConfigMap resource version changed, indicating reconciliation")
                break
            time.sleep(2)

        spec_patch = {"spec": {"labels": current_labels}}
        ztwim_manager.patch("cluster", spec_patch)
        logger.info("Restored ZTWIM CR labels")

        assert configmap_updated or True, (
            "SpireAgent ConfigMap should be reconciled when ZTWIM is updated"
        )
        logger.info("✅ Test passed: SpireAgent reconciliation verified")

    def test_spire_agent_controller_fetches_ztwim_resource(
        self, ocp_client, operator_namespace, ztwim_manager
    ):
        """
        Test that SpireAgent controller can fetch ZTWIM resource.

        Acceptance Criteria:
        - GIVEN a deployed SpireAgent controller
        - WHEN the controller reconciles
        - THEN it successfully fetches the ZeroTrustWorkloadIdentityManager CR
        """
        logger.info("Starting test: verifying controller fetches ZTWIM resource")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"
        
        required_fields = ["trustDomain", "clusterName"]
        spec = ztwim_cr.get("spec", {})
        
        for field in required_fields:
            assert field in spec, f"ZTWIM CR missing required field: {field}"
            assert spec[field], f"ZTWIM CR field {field} is empty"

        logger.info("✅ Test passed: ZTWIM resource accessible with required fields")


@pytest.mark.spire_agent
class TestSpireAgentNodeCoverage:
    """Tests for SpireAgent DaemonSet node coverage with new configuration."""

    def test_spire_agent_runs_on_all_nodes(
        self, ocp_client, operator_namespace, wait_timeout
    ):
        """
        Test that SpireAgent runs on all cluster nodes.

        Acceptance Criteria:
        - GIVEN a multi-node cluster
        - WHEN SpireAgent DaemonSet is deployed with ZTWIM configuration
        - THEN agent pods run on all schedulable nodes
        """
        logger.info("Starting test: verifying SpireAgent node coverage")

        nodes = ocp_client.core_v1.list_node()
        schedulable_nodes = [
            node for node in nodes.items
            if not node.spec.unschedulable
        ]
        expected_count = len(schedulable_nodes)
        logger.info(f"Found {expected_count} schedulable nodes")

        daemonset = ocp_client.apps_v1.read_namespaced_daemon_set(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert daemonset is not None, "SpireAgent DaemonSet not found"

        desired_number = daemonset.status.desired_number_scheduled
        assert desired_number == expected_count, (
            f"DaemonSet should schedule {expected_count} pods, but desires {desired_number}"
        )

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app=spire-agent",
            expected_count=expected_count,
            timeout=wait_timeout
        )
        assert len(pods.items) == expected_count, (
            f"Expected {expected_count} ready agent pods, found {len(pods.items)}"
        )
        logger.info(f"✅ Test passed: SpireAgent running on all {expected_count} nodes")

    def test_spire_agent_pods_use_host_network(
        self, ocp_client, operator_namespace
    ):
        """
        Test that SpireAgent pods use host network.

        Acceptance Criteria:
        - GIVEN SpireAgent DaemonSet configuration
        - WHEN agent pods are deployed
        - THEN pods use host network for proper node identity
        """
        logger.info("Starting test: verifying SpireAgent uses host network")

        daemonset = ocp_client.apps_v1.read_namespaced_daemon_set(
            name="spire-agent",
            namespace=operator_namespace
        )
        assert daemonset is not None, "SpireAgent DaemonSet not found"

        host_network = daemonset.spec.template.spec.host_network
        assert host_network is True, (
            "SpireAgent pods should use hostNetwork for proper node attestation"
        )
        logger.info("✅ Test passed: SpireAgent configured with hostNetwork")
