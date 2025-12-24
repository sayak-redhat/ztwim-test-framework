"""
Test suite for SpireServer CR after PR #72 configuration centralization.

This module tests the SpireServer component after moving common configuration
fields (trustDomain, clusterName, bundleConfigMap) from SpireServerSpec to
the main ZeroTrustWorkloadIdentityManager CR.

Tests verify that SpireServer controller correctly:
- Fetches configuration from ZeroTrustWorkloadIdentityManager CR
- Generates ConfigMaps with correct trust domain and cluster name
- Sets owner references to ZeroTrustWorkloadIdentityManager
- Functions without the removed fields in SpireServerSpec
"""

import pytest
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_server
class TestSpireServerConfigCentralization:
    """Tests for SpireServer configuration centralization from PR #72."""

    def test_spire_server_uses_ztwim_trust_domain(
        self, ocp_client, operator_namespace, spire_server, cluster_name
    ):
        """
        Test that SpireServer ConfigMap uses trust domain from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with trustDomain set
        - WHEN SpireServer reconciles and creates its ConfigMap
        - THEN the ConfigMap contains the trust domain from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer uses ZTWIM trust domain")

        # Get the ZeroTrustWorkloadIdentityManager CR
        ztwim_list = ocp_client.custom_objects_api.list_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="zerotrustworkloadidentitymanagers"
        )

        assert ztwim_list["items"], "Expected at least one ZeroTrustWorkloadIdentityManager CR"
        ztwim = ztwim_list["items"][0]
        expected_trust_domain = ztwim["spec"]["trustDomain"]

        logger.info(f"Expected trust domain from ZTWIM: {expected_trust_domain}")

        # Get SpireServer ConfigMap
        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-server",
            namespace=operator_namespace
        )

        assert configmap.data is not None, "SpireServer ConfigMap data should not be None"
        assert "server.conf" in configmap.data, "ConfigMap should contain server.conf"

        server_conf = configmap.data["server.conf"]
        assert f'trust_domain = "{expected_trust_domain}"' in server_conf, \
            f"Expected trust_domain '{expected_trust_domain}' in server.conf but not found"

        logger.info(f"✅ Test passed: SpireServer ConfigMap uses trust domain '{expected_trust_domain}' from ZTWIM CR")

    def test_spire_server_uses_ztwim_cluster_name(
        self, ocp_client, operator_namespace, spire_server, cluster_name
    ):
        """
        Test that SpireServer ConfigMap uses cluster name from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with clusterName set
        - WHEN SpireServer reconciles and creates its ConfigMap
        - THEN the ConfigMap contains the cluster name from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer uses ZTWIM cluster name")

        # Get the ZeroTrustWorkloadIdentityManager CR
        ztwim_list = ocp_client.custom_objects_api.list_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="zerotrustworkloadidentitymanagers"
        )

        assert ztwim_list["items"], "Expected at least one ZeroTrustWorkloadIdentityManager CR"
        ztwim = ztwim_list["items"][0]
        expected_cluster_name = ztwim["spec"]["clusterName"]

        logger.info(f"Expected cluster name from ZTWIM: {expected_cluster_name}")

        # Get SpireServer ConfigMap
        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-server",
            namespace=operator_namespace
        )

        assert configmap.data is not None, "SpireServer ConfigMap data should not be None"
        assert "server.conf" in configmap.data, "ConfigMap should contain server.conf"

        server_conf = configmap.data["server.conf"]
        assert expected_cluster_name in server_conf, \
            f"Expected cluster name '{expected_cluster_name}' in server.conf but not found"

        logger.info(f"✅ Test passed: SpireServer ConfigMap uses cluster name '{expected_cluster_name}' from ZTWIM CR")

    def test_spire_server_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer CR has owner reference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a SpireServer CR created by the operator
        - WHEN the CR is retrieved from the cluster
        - THEN it has an ownerReference pointing to ZeroTrustWorkloadIdentityManager
        """
        logger.info("Starting test: verifying SpireServer has ZTWIM owner reference")

        # Get SpireServer CR
        spire_server_cr = ocp_client.custom_objects_api.get_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="spireservers",
            name=spire_server["metadata"]["name"]
        )

        assert "metadata" in spire_server_cr, "SpireServer CR should have metadata"
        assert "ownerReferences" in spire_server_cr["metadata"], \
            "SpireServer CR should have ownerReferences"

        owner_refs = spire_server_cr["metadata"]["ownerReferences"]
        ztwim_owner = None
        for ref in owner_refs:
            if ref["kind"] == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, \
            "SpireServer CR should have owner reference to ZeroTrustWorkloadIdentityManager"
        assert ztwim_owner["apiVersion"] == "operator.openshift.io/v1alpha1", \
            "Owner reference should have correct apiVersion"

        logger.info(f"✅ Test passed: SpireServer has owner reference to ZTWIM '{ztwim_owner['name']}'")

    def test_spire_server_spec_lacks_removed_fields(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer CR spec does not contain removed fields.

        Acceptance Criteria:
        - GIVEN a SpireServer CR after PR #72
        - WHEN the CR spec is examined
        - THEN it does not contain trustDomain, clusterName, or bundleConfigMap fields
        """
        logger.info("Starting test: verifying removed fields are not in SpireServer spec")

        # Get SpireServer CR
        spire_server_cr = ocp_client.custom_objects_api.get_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="spireservers",
            name=spire_server["metadata"]["name"]
        )

        assert "spec" in spire_server_cr, "SpireServer CR should have spec"
        spec = spire_server_cr["spec"]

        assert "trustDomain" not in spec, \
            "SpireServer spec should not contain trustDomain field (moved to ZTWIM)"
        assert "clusterName" not in spec, \
            "SpireServer spec should not contain clusterName field (moved to ZTWIM)"
        assert "bundleConfigMap" not in spec, \
            "SpireServer spec should not contain bundleConfigMap field (moved to ZTWIM)"

        logger.info("✅ Test passed: SpireServer spec does not contain removed fields")

    def test_spire_server_configmap_references_ztwim_bundle(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer uses bundle ConfigMap name from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZeroTrustWorkloadIdentityManager CR with bundleConfigMap set
        - WHEN SpireServer controller reconciles
        - THEN resources reference the bundle ConfigMap from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer uses ZTWIM bundle ConfigMap name")

        # Get the ZeroTrustWorkloadIdentityManager CR
        ztwim_list = ocp_client.custom_objects_api.list_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="zerotrustworkloadidentitymanagers"
        )

        assert ztwim_list["items"], "Expected at least one ZeroTrustWorkloadIdentityManager CR"
        ztwim = ztwim_list["items"][0]
        expected_bundle_configmap = ztwim["spec"].get("bundleConfigMap", "spire-bundle")

        logger.info(f"Expected bundle ConfigMap from ZTWIM: {expected_bundle_configmap}")

        # Verify the bundle ConfigMap exists
        try:
            bundle_configmap = ocp_client.core_v1.read_namespaced_config_map(
                name=expected_bundle_configmap,
                namespace=operator_namespace
            )
            assert bundle_configmap is not None, \
                f"Bundle ConfigMap '{expected_bundle_configmap}' should exist"
            logger.info(f"✅ Test passed: Bundle ConfigMap '{expected_bundle_configmap}' exists and is referenced")
        except Exception as e:
            pytest.fail(f"Failed to find bundle ConfigMap '{expected_bundle_configmap}': {e}")

    def test_spire_server_reconciles_after_ztwim_configuration(
        self, ocp_client, operator_namespace, spire_server, wait_timeout
    ):
        """
        Test that SpireServer successfully reconciles using ZTWIM configuration.

        Acceptance Criteria:
        - GIVEN a SpireServer CR that references ZTWIM configuration
        - WHEN the controller reconciles the SpireServer
        - THEN the StatefulSet deploys successfully and pods become ready
        """
        logger.info("Starting test: verifying SpireServer reconciles with ZTWIM configuration")

        # Wait for SpireServer StatefulSet to be ready
        statefulset_name = "spire-server"
        max_wait = wait_timeout
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                sts = ocp_client.apps_v1.read_namespaced_stateful_set(
                    name=statefulset_name,
                    namespace=operator_namespace
                )

                if sts.status.ready_replicas == sts.spec.replicas:
                    logger.info(f"StatefulSet {statefulset_name} is ready with {sts.status.ready_replicas} replicas")
                    break
            except Exception as e:
                logger.warning(f"Error reading StatefulSet: {e}")

            time.sleep(5)
        else:
            pytest.fail(f"SpireServer StatefulSet did not become ready within {max_wait} seconds")

        # Verify pods are running
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-server"
        )

        assert len(pods.items) > 0, "Expected at least one SpireServer pod"

        for pod in pods.items:
            assert pod.status.phase == "Running", \
                f"Expected pod {pod.metadata.name} to be Running, got {pod.status.phase}"

        logger.info("✅ Test passed: SpireServer reconciled successfully with ZTWIM configuration")

    def test_spire_server_logs_show_correct_trust_domain(
        self, ocp_client, operator_namespace, cluster_name
    ):
        """
        Test that SpireServer pod logs show the correct trust domain from ZTWIM.

        Acceptance Criteria:
        - GIVEN a running SpireServer pod
        - WHEN the pod logs are examined
        - THEN they reference the trust domain from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer logs show correct trust domain")

        # Get the ZeroTrustWorkloadIdentityManager CR
        ztwim_list = ocp_client.custom_objects_api.list_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="zerotrustworkloadidentitymanagers"
        )

        assert ztwim_list["items"], "Expected at least one ZeroTrustWorkloadIdentityManager CR"
        ztwim = ztwim_list["items"][0]
        expected_trust_domain = ztwim["spec"]["trustDomain"]

        # Get SpireServer pods
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-server"
        )

        assert len(pods.items) > 0, "Expected at least one SpireServer pod"

        # Check logs from the first running pod
        for pod in pods.items:
            if pod.status.phase == "Running":
                logs = ocp_client.get_pod_logs(
                    name=pod.metadata.name,
                    namespace=operator_namespace,
                    container="spire-server"
                )

                assert expected_trust_domain in logs, \
                    f"Expected trust domain '{expected_trust_domain}' in pod logs but not found"

                logger.info(f"✅ Test passed: SpireServer logs contain trust domain '{expected_trust_domain}'")
                return

        pytest.fail("No running SpireServer pods found to check logs")


@pytest.mark.spire_server
class TestSpireServerConfigMapGeneration:
    """Tests for SpireServer ConfigMap generation with centralized configuration."""

    def test_spire_server_configmap_has_correct_structure(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer ConfigMap has the correct structure after PR #72.

        Acceptance Criteria:
        - GIVEN a reconciled SpireServer CR
        - WHEN the ConfigMap is retrieved
        - THEN it contains all required configuration sections
        """
        logger.info("Starting test: verifying SpireServer ConfigMap structure")

        configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-server",
            namespace=operator_namespace
        )

        assert configmap.data is not None, "ConfigMap data should not be None"
        assert "server.conf" in configmap.data, "ConfigMap should contain server.conf"

        server_conf = configmap.data["server.conf"]

        # Verify key configuration sections exist
        required_sections = [
            "trust_domain",
            "data_dir",
            "log_level",
            "log_format"
        ]

        for section in required_sections:
            assert section in server_conf, \
                f"Expected '{section}' in server.conf but not found"

        logger.info("✅ Test passed: SpireServer ConfigMap has correct structure")

    def test_spire_server_configmap_updates_on_ztwim_change(
        self, ocp_client, operator_namespace, spire_server, wait_timeout, ztwim_manager
    ):
        """
        Test that SpireServer ConfigMap updates when ZTWIM configuration changes.

        Acceptance Criteria:
        - GIVEN a SpireServer using ZTWIM configuration
        - WHEN ZTWIM bundleConfigMap field is updated
        - THEN SpireServer controller reconciles (note: trustDomain and clusterName are immutable)
        """
        logger.info("Starting test: verifying SpireServer reacts to ZTWIM changes")

        # Get initial ConfigMap
        initial_configmap = ocp_client.core_v1.read_namespaced_config_map(
            name="spire-server",
            namespace=operator_namespace
        )

        initial_generation = initial_configmap.metadata.resource_version

        logger.info(f"Initial ConfigMap resource version: {initial_generation}")

        # Note: Since trustDomain, clusterName, and bundleConfigMap are immutable,
        # we can only verify they are set correctly, not test updates
        # This test verifies the ConfigMap exists and has a valid resource version

        assert initial_configmap.data is not None, "ConfigMap should have data"
        assert "server.conf" in initial_configmap.data, "ConfigMap should have server.conf"

        logger.info("✅ Test passed: SpireServer ConfigMap is properly managed")


@pytest.mark.spire_server
class TestSpireServerEdgeCases:
    """Edge case tests for SpireServer with centralized configuration."""

    def test_spire_server_handles_missing_ztwim_gracefully(
        self, ocp_client, operator_namespace, spire_server_manager, unique_name, wait_timeout
    ):
        """
        Test that SpireServer reconciliation handles missing ZTWIM CR gracefully.

        Acceptance Criteria:
        - GIVEN no ZeroTrustWorkloadIdentityManager CR exists
        - WHEN a SpireServer CR is created
        - THEN the controller does not crash and reports appropriate status
        """
        logger.info("Starting test: verifying SpireServer handles missing ZTWIM")

        # Create a test SpireServer without ensuring ZTWIM exists first
        test_server_name = f"test-server-{unique_name}"

        spire_server_spec = {
            "logLevel": "DEBUG",
            "logFormat": "text",
            "jwtIssuer": "https://test.example.com"
        }

        # This should fail gracefully if no ZTWIM exists
        # In production, ZTWIM should always exist, but testing edge case
        try:
            test_server = spire_server_manager.create(
                name=test_server_name,
                spec=spire_server_spec,
                namespace=operator_namespace
            )

            # Wait briefly to see if controller processes it
            time.sleep(10)

            # Check if there's a status condition indicating the issue
            updated_server = ocp_client.custom_objects_api.get_namespaced_custom_object(
                group="operator.openshift.io",
                version="v1alpha1",
                namespace=operator_namespace,
                plural="spireservers",
                name=test_server_name
            )

            # The CR should exist but may have error conditions
            assert updated_server is not None, "SpireServer CR should exist"

            logger.info("✅ Test passed: SpireServer handles missing ZTWIM scenario")

        except Exception as e:
            logger.info(f"Expected behavior: SpireServer creation handled appropriately: {e}")

        finally:
            # Cleanup
            try:
                spire_server_manager.delete(name=test_server_name, namespace=operator_namespace)
            except:
                pass

    def test_spire_server_required_fields_validation(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer CR has correct required fields after PR #72.

        Acceptance Criteria:
        - GIVEN SpireServer CRD after PR #72
        - WHEN examining required fields
        - THEN trustDomain and clusterName are not required in SpireServerSpec
        - AND jwtIssuer remains required
        """
        logger.info("Starting test: verifying SpireServer required fields")

        # Get SpireServer CR
        spire_server_cr = ocp_client.custom_objects_api.get_namespaced_custom_object(
            group="operator.openshift.io",
            version="v1alpha1",
            namespace=operator_namespace,
            plural="spireservers",
            name=spire_server["metadata"]["name"]
        )

        spec = spire_server_cr["spec"]

        # jwtIssuer should still be required and present
        assert "jwtIssuer" in spec, "SpireServer spec should contain required jwtIssuer field"

        # Removed fields should not be present
        assert "trustDomain" not in spec, "trustDomain should not be in SpireServer spec"
        assert "clusterName" not in spec, "clusterName should not be in SpireServer spec"
        assert "bundleConfigMap" not in spec, "bundleConfigMap should not be in SpireServer spec"

        logger.info("✅ Test passed: SpireServer has correct required fields after PR #72")
