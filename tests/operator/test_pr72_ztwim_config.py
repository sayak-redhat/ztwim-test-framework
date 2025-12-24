"""
Tests for ZeroTrustWorkloadIdentityManager CR configuration centralization.

This test module validates the changes introduced in PR #72:
https://github.com/openshift/zero-trust-workload-identity-manager/pull/72

PR #72 (SPIRE-345) moves common configuration fields (trustDomain, clusterName, 
bundleConfigMap) from individual operand CRs to the main ZeroTrustWorkloadIdentityManager CR.
All operand controllers now fetch configuration from the ZTWIM CR.

Test Coverage:
- ZTWIM CR configuration validation
- Configuration propagation to operand controllers
- OwnerReference establishment between ZTWIM and operands
- Immutability validation for trustDomain, clusterName, and bundleConfigMap
- Operand reconciliation with centralized configuration
"""

import pytest
import time
from kubernetes.client.rest import ApiException
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.operator
class TestZTWIMCentralizedConfiguration:
    """Tests for centralized configuration in ZTWIM CR."""

    def test_ztwim_cr_has_required_configuration_fields(
        self, ocp_client, operator_namespace, ztwim_manager
    ):
        """
        Test that ZTWIM CR contains the required configuration fields.

        Acceptance Criteria:
        - GIVEN a deployed ZTWIM operator
        - WHEN the ZeroTrustWorkloadIdentityManager CR is retrieved
        - THEN it contains trustDomain, clusterName, and bundleConfigMap fields
        """
        logger.info("Starting test: verifying ZTWIM CR has required configuration fields")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"

        spec = ztwim_cr.get("spec", {})
        assert "trustDomain" in spec, "ZTWIM CR spec should contain trustDomain field"
        assert "clusterName" in spec, "ZTWIM CR spec should contain clusterName field"
        assert "bundleConfigMap" in spec, "ZTWIM CR spec should contain bundleConfigMap field"

        logger.info(f"✅ ZTWIM CR has trustDomain='{spec.get('trustDomain')}', "
                   f"clusterName='{spec.get('clusterName')}', "
                   f"bundleConfigMap='{spec.get('bundleConfigMap')}'")

    def test_ztwim_trust_domain_validation(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that trustDomain field follows validation rules.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with valid trustDomain
        - WHEN the trustDomain uses lowercase alphanumeric, hyphens, and dots
        - THEN the CR is accepted by the API server
        """
        logger.info("Starting test: verifying trustDomain validation rules")

        ztwim_name = unique_name
        valid_trust_domain = "example.test"

        ztwim_spec = {
            "trustDomain": valid_trust_domain,
            "clusterName": "test-cluster",
            "bundleConfigMap": "test-bundle"
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR with valid trustDomain should be created"
            
            created_spec = ztwim_cr.get("spec", {})
            assert created_spec.get("trustDomain") == valid_trust_domain, \
                f"Expected trustDomain '{valid_trust_domain}' but got '{created_spec.get('trustDomain')}'"

            logger.info(f"✅ ZTWIM CR created with valid trustDomain: {valid_trust_domain}")
        finally:
            ztwim_manager.delete(ztwim_name)

    def test_ztwim_cluster_name_validation(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that clusterName field follows DNS-1123 subdomain validation.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with valid clusterName
        - WHEN the clusterName follows DNS-1123 subdomain format
        - THEN the CR is accepted by the API server
        """
        logger.info("Starting test: verifying clusterName validation rules")

        ztwim_name = unique_name
        valid_cluster_name = "test-cluster.example"

        ztwim_spec = {
            "trustDomain": "test.domain",
            "clusterName": valid_cluster_name,
            "bundleConfigMap": "test-bundle"
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR with valid clusterName should be created"
            
            created_spec = ztwim_cr.get("spec", {})
            assert created_spec.get("clusterName") == valid_cluster_name, \
                f"Expected clusterName '{valid_cluster_name}' but got '{created_spec.get('clusterName')}'"

            logger.info(f"✅ ZTWIM CR created with valid clusterName: {valid_cluster_name}")
        finally:
            ztwim_manager.delete(ztwim_name)

    def test_ztwim_bundle_configmap_default_value(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that bundleConfigMap has default value 'spire-bundle'.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR created without specifying bundleConfigMap
        - WHEN the CR is retrieved from the API server
        - THEN bundleConfigMap defaults to 'spire-bundle'
        """
        logger.info("Starting test: verifying bundleConfigMap default value")

        ztwim_name = unique_name
        ztwim_spec = {
            "trustDomain": "test.domain",
            "clusterName": "test-cluster"
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR should be created"
            
            created_spec = ztwim_cr.get("spec", {})
            bundle_configmap = created_spec.get("bundleConfigMap")
            assert bundle_configmap == "spire-bundle", \
                f"Expected default bundleConfigMap 'spire-bundle' but got '{bundle_configmap}'"

            logger.info(f"✅ ZTWIM CR bundleConfigMap defaulted to: {bundle_configmap}")
        finally:
            ztwim_manager.delete(ztwim_name)

    def test_ztwim_trust_domain_immutability(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that trustDomain field is immutable after creation.

        Acceptance Criteria:
        - GIVEN an existing ZTWIM CR with trustDomain set
        - WHEN attempting to update the trustDomain field
        - THEN the update is rejected by the API server
        """
        logger.info("Starting test: verifying trustDomain immutability")

        ztwim_name = unique_name
        original_trust_domain = "original.domain"
        new_trust_domain = "modified.domain"

        ztwim_spec = {
            "trustDomain": original_trust_domain,
            "clusterName": "test-cluster",
            "bundleConfigMap": "test-bundle"
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR should be created"

            updated_spec = ztwim_cr.get("spec", {}).copy()
            updated_spec["trustDomain"] = new_trust_domain

            update_rejected = False
            try:
                ztwim_manager.update(ztwim_name, updated_spec)
            except ApiException as e:
                if e.status == 422 or "immutable" in str(e).lower():
                    update_rejected = True
                    logger.info(f"Update correctly rejected: {e.reason}")

            assert update_rejected, \
                "Updating immutable trustDomain should be rejected by API server"

            logger.info("✅ trustDomain immutability validated")
        finally:
            ztwim_manager.delete(ztwim_name)

    def test_ztwim_cluster_name_immutability(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that clusterName field is immutable after creation.

        Acceptance Criteria:
        - GIVEN an existing ZTWIM CR with clusterName set
        - WHEN attempting to update the clusterName field
        - THEN the update is rejected by the API server
        """
        logger.info("Starting test: verifying clusterName immutability")

        ztwim_name = unique_name
        original_cluster_name = "original-cluster"
        new_cluster_name = "modified-cluster"

        ztwim_spec = {
            "trustDomain": "test.domain",
            "clusterName": original_cluster_name,
            "bundleConfigMap": "test-bundle"
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR should be created"

            updated_spec = ztwim_cr.get("spec", {}).copy()
            updated_spec["clusterName"] = new_cluster_name

            update_rejected = False
            try:
                ztwim_manager.update(ztwim_name, updated_spec)
            except ApiException as e:
                if e.status == 422 or "immutable" in str(e).lower():
                    update_rejected = True
                    logger.info(f"Update correctly rejected: {e.reason}")

            assert update_rejected, \
                "Updating immutable clusterName should be rejected by API server"

            logger.info("✅ clusterName immutability validated")
        finally:
            ztwim_manager.delete(ztwim_name)

    def test_ztwim_bundle_configmap_immutability(
        self, ocp_client, operator_namespace, ztwim_manager, unique_name
    ):
        """
        Test that bundleConfigMap field is immutable after creation.

        Acceptance Criteria:
        - GIVEN an existing ZTWIM CR with bundleConfigMap set
        - WHEN attempting to update the bundleConfigMap field
        - THEN the update is rejected by the API server
        """
        logger.info("Starting test: verifying bundleConfigMap immutability")

        ztwim_name = unique_name
        original_bundle = "original-bundle"
        new_bundle = "modified-bundle"

        ztwim_spec = {
            "trustDomain": "test.domain",
            "clusterName": "test-cluster",
            "bundleConfigMap": original_bundle
        }

        try:
            ztwim_cr = ztwim_manager.create(ztwim_name, ztwim_spec)
            assert ztwim_cr is not None, "ZTWIM CR should be created"

            updated_spec = ztwim_cr.get("spec", {}).copy()
            updated_spec["bundleConfigMap"] = new_bundle

            update_rejected = False
            try:
                ztwim_manager.update(ztwim_name, updated_spec)
            except ApiException as e:
                if e.status == 422 or "immutable" in str(e).lower():
                    update_rejected = True
                    logger.info(f"Update correctly rejected: {e.reason}")

            assert update_rejected, \
                "Updating immutable bundleConfigMap should be rejected by API server"

            logger.info("✅ bundleConfigMap immutability validated")
        finally:
            ztwim_manager.delete(ztwim_name)


@pytest.mark.operator
class TestOperandConfigurationFields:
    """Tests verifying operand CRs no longer contain configuration fields."""

    def test_spire_server_cr_missing_removed_fields(
        self, ocp_client, operator_namespace, spire_server
    ):
        """
        Test that SpireServer CR no longer has trustDomain, clusterName, bundleConfigMap.

        Acceptance Criteria:
        - GIVEN a deployed SpireServer CR
        - WHEN the CR spec is inspected
        - THEN trustDomain, clusterName, and bundleConfigMap fields are not present
        """
        logger.info("Starting test: verifying SpireServer CR removed fields")

        assert spire_server is not None, "SpireServer CR 'cluster' should exist"

        spec = spire_server.get("spec", {})
        assert "trustDomain" not in spec, \
            "SpireServer CR should not contain trustDomain field (moved to ZTWIM CR)"
        assert "clusterName" not in spec, \
            "SpireServer CR should not contain clusterName field (moved to ZTWIM CR)"
        assert "bundleConfigMap" not in spec, \
            "SpireServer CR should not contain bundleConfigMap field (moved to ZTWIM CR)"

        logger.info("✅ SpireServer CR correctly lacks removed configuration fields")

    def test_spire_agent_cr_missing_removed_fields(
        self, ocp_client, operator_namespace, spire_agent
    ):
        """
        Test that SpireAgent CR no longer has trustDomain, clusterName, bundleConfigMap.

        Acceptance Criteria:
        - GIVEN a deployed SpireAgent CR
        - WHEN the CR spec is inspected
        - THEN trustDomain, clusterName, and bundleConfigMap fields are not present
        """
        logger.info("Starting test: verifying SpireAgent CR removed fields")

        assert spire_agent is not None, "SpireAgent CR 'cluster' should exist"

        spec = spire_agent.get("spec", {})
        assert "trustDomain" not in spec, \
            "SpireAgent CR should not contain trustDomain field (moved to ZTWIM CR)"
        assert "clusterName" not in spec, \
            "SpireAgent CR should not contain clusterName field (moved to ZTWIM CR)"
        assert "bundleConfigMap" not in spec, \
            "SpireAgent CR should not contain bundleConfigMap field (moved to ZTWIM CR)"

        logger.info("✅ SpireAgent CR correctly lacks removed configuration fields")

    def test_oidc_provider_cr_missing_removed_fields(
        self, ocp_client, operator_namespace, oidc_provider
    ):
        """
        Test that SpireOIDCDiscoveryProvider CR no longer has trustDomain.

        Acceptance Criteria:
        - GIVEN a deployed SpireOIDCDiscoveryProvider CR
        - WHEN the CR spec is inspected
        - THEN trustDomain field is not present
        """
        logger.info("Starting test: verifying SpireOIDCDiscoveryProvider CR removed fields")

        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR 'cluster' should exist"

        spec = oidc_provider.get("spec", {})
        assert "trustDomain" not in spec, \
            "SpireOIDCDiscoveryProvider CR should not contain trustDomain field (moved to ZTWIM CR)"

        logger.info("✅ SpireOIDCDiscoveryProvider CR correctly lacks removed configuration fields")


@pytest.mark.operator
class TestOperandOwnerReferences:
    """Tests verifying operand CRs have ownerReference to ZTWIM CR."""

    def test_spire_server_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, spire_server, ztwim_manager
    ):
        """
        Test that SpireServer CR has ownerReference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a deployed SpireServer CR
        - WHEN the CR metadata is inspected
        - THEN it contains an ownerReference pointing to the ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer CR ownerReference")

        assert spire_server is not None, "SpireServer CR 'cluster' should exist"

        owner_refs = spire_server.get("metadata", {}).get("ownerReferences", [])
        ztwim_owner = None
        for ref in owner_refs:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, \
            "SpireServer CR should have ownerReference to ZeroTrustWorkloadIdentityManager"
        assert ztwim_owner.get("name") == "cluster", \
            f"OwnerReference should point to ZTWIM CR 'cluster', got '{ztwim_owner.get('name')}'"

        logger.info(f"✅ SpireServer CR has ownerReference to ZTWIM CR: {ztwim_owner.get('name')}")

    def test_spire_agent_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, spire_agent, ztwim_manager
    ):
        """
        Test that SpireAgent CR has ownerReference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a deployed SpireAgent CR
        - WHEN the CR metadata is inspected
        - THEN it contains an ownerReference pointing to the ZTWIM CR
        """
        logger.info("Starting test: verifying SpireAgent CR ownerReference")

        assert spire_agent is not None, "SpireAgent CR 'cluster' should exist"

        owner_refs = spire_agent.get("metadata", {}).get("ownerReferences", [])
        ztwim_owner = None
        for ref in owner_refs:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, \
            "SpireAgent CR should have ownerReference to ZeroTrustWorkloadIdentityManager"
        assert ztwim_owner.get("name") == "cluster", \
            f"OwnerReference should point to ZTWIM CR 'cluster', got '{ztwim_owner.get('name')}'"

        logger.info(f"✅ SpireAgent CR has ownerReference to ZTWIM CR: {ztwim_owner.get('name')}")

    def test_spiffe_csi_driver_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, spiffe_csi_driver, ztwim_manager
    ):
        """
        Test that SpiffeCSIDriver CR has ownerReference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a deployed SpiffeCSIDriver CR
        - WHEN the CR metadata is inspected
        - THEN it contains an ownerReference pointing to the ZTWIM CR
        """
        logger.info("Starting test: verifying SpiffeCSIDriver CR ownerReference")

        assert spiffe_csi_driver is not None, "SpiffeCSIDriver CR 'cluster' should exist"

        owner_refs = spiffe_csi_driver.get("metadata", {}).get("ownerReferences", [])
        ztwim_owner = None
        for ref in owner_refs:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, \
            "SpiffeCSIDriver CR should have ownerReference to ZeroTrustWorkloadIdentityManager"
        assert ztwim_owner.get("name") == "cluster", \
            f"OwnerReference should point to ZTWIM CR 'cluster', got '{ztwim_owner.get('name')}'"

        logger.info(f"✅ SpiffeCSIDriver CR has ownerReference to ZTWIM CR: {ztwim_owner.get('name')}")

    def test_oidc_provider_has_ztwim_owner_reference(
        self, ocp_client, operator_namespace, oidc_provider, ztwim_manager
    ):
        """
        Test that SpireOIDCDiscoveryProvider CR has ownerReference to ZeroTrustWorkloadIdentityManager.

        Acceptance Criteria:
        - GIVEN a deployed SpireOIDCDiscoveryProvider CR
        - WHEN the CR metadata is inspected
        - THEN it contains an ownerReference pointing to the ZTWIM CR
        """
        logger.info("Starting test: verifying SpireOIDCDiscoveryProvider CR ownerReference")

        assert oidc_provider is not None, "SpireOIDCDiscoveryProvider CR 'cluster' should exist"

        owner_refs = oidc_provider.get("metadata", {}).get("ownerReferences", [])
        ztwim_owner = None
        for ref in owner_refs:
            if ref.get("kind") == "ZeroTrustWorkloadIdentityManager":
                ztwim_owner = ref
                break

        assert ztwim_owner is not None, \
            "SpireOIDCDiscoveryProvider CR should have ownerReference to ZeroTrustWorkloadIdentityManager"
        assert ztwim_owner.get("name") == "cluster", \
            f"OwnerReference should point to ZTWIM CR 'cluster', got '{ztwim_owner.get('name')}'"

        logger.info(f"✅ SpireOIDCDiscoveryProvider CR has ownerReference to ZTWIM CR: {ztwim_owner.get('name')}")


@pytest.mark.operator
class TestConfigurationPropagation:
    """Tests verifying configuration propagates from ZTWIM CR to operand resources."""

    def test_spire_server_configmap_uses_ztwim_configuration(
        self, ocp_client, operator_namespace, ztwim_manager, wait_timeout
    ):
        """
        Test that SpireServer ConfigMap uses configuration from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with trustDomain and clusterName
        - WHEN the SpireServer ConfigMap is inspected
        - THEN it contains the trustDomain and clusterName from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireServer ConfigMap uses ZTWIM configuration")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"

        ztwim_spec = ztwim_cr.get("spec", {})
        expected_trust_domain = ztwim_spec.get("trustDomain")
        expected_cluster_name = ztwim_spec.get("clusterName")

        assert expected_trust_domain is not None, "ZTWIM CR should have trustDomain"
        assert expected_cluster_name is not None, "ZTWIM CR should have clusterName"

        configmap = None
        end_time = time.time() + wait_timeout
        while time.time() < end_time:
            try:
                configmap = ocp_client.core_v1.read_namespaced_config_map(
                    name="spire-server",
                    namespace=operator_namespace
                )
                break
            except ApiException:
                time.sleep(2)

        assert configmap is not None, "SpireServer ConfigMap should exist"

        server_config_data = configmap.data.get("server.conf", "")
        assert expected_trust_domain in server_config_data, \
            f"SpireServer ConfigMap should contain trustDomain '{expected_trust_domain}'"
        assert expected_cluster_name in server_config_data, \
            f"SpireServer ConfigMap should contain clusterName '{expected_cluster_name}'"

        logger.info(f"✅ SpireServer ConfigMap correctly uses ZTWIM configuration: "
                   f"trustDomain={expected_trust_domain}, clusterName={expected_cluster_name}")

    def test_spire_agent_configmap_uses_ztwim_configuration(
        self, ocp_client, operator_namespace, ztwim_manager, wait_timeout
    ):
        """
        Test that SpireAgent ConfigMap uses configuration from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with trustDomain and clusterName
        - WHEN the SpireAgent ConfigMap is inspected
        - THEN it contains the trustDomain and clusterName from ZTWIM CR
        """
        logger.info("Starting test: verifying SpireAgent ConfigMap uses ZTWIM configuration")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"

        ztwim_spec = ztwim_cr.get("spec", {})
        expected_trust_domain = ztwim_spec.get("trustDomain")
        expected_cluster_name = ztwim_spec.get("clusterName")

        assert expected_trust_domain is not None, "ZTWIM CR should have trustDomain"
        assert expected_cluster_name is not None, "ZTWIM CR should have clusterName"

        configmap = None
        end_time = time.time() + wait_timeout
        while time.time() < end_time:
            try:
                configmap = ocp_client.core_v1.read_namespaced_config_map(
                    name="spire-agent",
                    namespace=operator_namespace
                )
                break
            except ApiException:
                time.sleep(2)

        assert configmap is not None, "SpireAgent ConfigMap should exist"

        agent_config_data = configmap.data.get("agent.conf", "")
        assert expected_trust_domain in agent_config_data, \
            f"SpireAgent ConfigMap should contain trustDomain '{expected_trust_domain}'"
        assert expected_cluster_name in agent_config_data, \
            f"SpireAgent ConfigMap should contain clusterName '{expected_cluster_name}'"

        logger.info(f"✅ SpireAgent ConfigMap correctly uses ZTWIM configuration: "
                   f"trustDomain={expected_trust_domain}, clusterName={expected_cluster_name}")

    def test_oidc_provider_configmap_uses_ztwim_configuration(
        self, ocp_client, operator_namespace, ztwim_manager, wait_timeout
    ):
        """
        Test that OIDC Discovery Provider ConfigMap uses configuration from ZTWIM CR.

        Acceptance Criteria:
        - GIVEN a ZTWIM CR with trustDomain
        - WHEN the OIDC Discovery Provider ConfigMap is inspected
        - THEN it contains the trustDomain from ZTWIM CR
        """
        logger.info("Starting test: verifying OIDC Provider ConfigMap uses ZTWIM configuration")

        ztwim_cr = ztwim_manager.get("cluster")
        assert ztwim_cr is not None, "ZTWIM CR 'cluster' should exist"

        ztwim_spec = ztwim_cr.get("spec", {})
        expected_trust_domain = ztwim_spec.get("trustDomain")

        assert expected_trust_domain is not None, "ZTWIM CR should have trustDomain"

        configmap = None
        end_time = time.time() + wait_timeout
        while time.time() < end_time:
            try:
                configmap = ocp_client.core_v1.read_namespaced_config_map(
                    name="spire-oidc-discovery-provider",
                    namespace=operator_namespace
                )
                break
            except ApiException:
                time.sleep(2)

        assert configmap is not None, "OIDC Discovery Provider ConfigMap should exist"

        oidc_config_data = configmap.data.get("oidc-discovery-provider.conf", "")
        assert expected_trust_domain in oidc_config_data, \
            f"OIDC Provider ConfigMap should contain trustDomain '{expected_trust_domain}'"

        logger.info(f"✅ OIDC Provider ConfigMap correctly uses ZTWIM configuration: "
                   f"trustDomain={expected_trust_domain}")


@pytest.mark.operator
class TestBootstrapRemoval:
    """Tests verifying bootstrap CR creation has been removed from main.go."""

    def test_operator_starts_without_bootstrap(
        self, ocp_client, operator_namespace, wait_timeout
    ):
        """
        Test that operator starts successfully without bootstrap CR creation.

        Acceptance Criteria:
        - GIVEN the operator deployment
        - WHEN the operator pod starts
        - THEN it does not perform bootstrap CR creation and starts successfully
        """
        logger.info("Starting test: verifying operator starts without bootstrap")

        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="control-plane=controller-manager",
            expected_count=1,
            timeout=wait_timeout
        )

        assert len(pods) == 1, "Operator controller-manager pod should be running"

        operator_pod = pods[0]
        logs = ocp_client.get_pod_logs(
            name=operator_pod.metadata.name,
            namespace=operator_namespace,
            container="manager"
        )

        assert "Failed to bootstrap ZeroTrustWorkloadIdentityManager CR" not in logs, \
            "Operator logs should not contain bootstrap failure messages"
        assert "BootstrapCR" not in logs, \
            "Operator logs should not reference bootstrap CR creation"

        logger.info("✅ Operator started successfully without bootstrap CR creation")
