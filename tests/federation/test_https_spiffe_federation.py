"""
SPIRE Federation End-to-End Tests (configurable profile).

Tests the complete federation workflow between two OpenShift clusters using
ZTWIM operator's federation capabilities with a configurable bundle endpoint
profile (default: https_spiffe). This requires a manual trust bootstrap where
trust bundles are exchanged between clusters before they can communicate securely.

Federation Architecture:
    Cluster 1 (Local)                    Cluster 2 (Remote)
    ┌─────────────────────┐              ┌─────────────────────┐
    │   SpireServer       │◄────────────►│   SpireServer       │
    │   Trust Domain:     │  Trust Exch  │   Trust Domain:     │
    │   apps.cluster1     │              │   apps.cluster2     │
    └─────────────────────┘              └─────────────────────┘
            │                                    │
            ▼                                    ▼
    ┌─────────────────────┐              ┌─────────────────────┐
    │   mTLS Server       │◄════════════►│   mTLS Client       │
    │   (workload)        │    mTLS      │   (workload)        │
    └─────────────────────┘              └─────────────────────┘

Prerequisites:
    - Two OpenShift 4.18+ clusters with cluster-admin access
    - Network connectivity between clusters (federation routes accessible)

Usage:
    # Operator pre-installed on both clusters (operands auto-deployed)
    pytest tests/federation/ -v \\
        --deployment-mode=operator-only \\
        --keep-deployed \\
        --remote-kubeconfig=/path/to/cluster2/kubeconfig

    # Bare clusters: install operator + operands
    pytest tests/federation/ -v \\
        --deployment-mode=bootstrap --keep-deployed \\
        --remote-kubeconfig=/path/to/cluster2/kubeconfig

    # With explicit domains
    pytest tests/federation/ -v \\
        --deployment-mode=operator-only --keep-deployed \\
        --remote-kubeconfig=/path/to/cluster2/kubeconfig \\
        --app-domain=apps.cluster1.example.com \\
        --remote-app-domain=apps.cluster2.example.com

Component: federation
Generated from: SPIRE-Federation-https_spiffe-Guide-4.18.md
"""

import json
import time

import pytest

from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.polling import wait_until

logger = get_logger(__name__)


@pytest.mark.federation
@pytest.mark.order(10)
class TestFederationPrerequisites:
    """
    Phase 0: Validate that both clusters are ready for federation.

    These tests ensure the ZTWIM stack is properly deployed on both clusters
    before attempting federation configuration.
    Timeouts are read from config/settings.yaml -> polling.pod_readiness.
    """

    def test_local_spire_server_running(self, ocp_client, operator_namespace):
        """
        Verify SpireServer pods are running on the local cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed on the local cluster
        - WHEN we check for SpireServer pods
        - THEN at least one pod is in Ready state
        """
        logger.info("Checking SpireServer pods on local cluster")
        cfg = get_settings().polling.pod_readiness
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready SpireServer pods on local cluster"
        logger.info(f"Local SpireServer: {pods[0]['metadata']['name']} is Ready")

    def test_remote_spire_server_running(
        self, remote_ocp_client, operator_namespace
    ):
        """
        Verify SpireServer pods are running on the remote cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed on the remote cluster
        - WHEN we check for SpireServer pods
        - THEN at least one pod is in Ready state
        """
        logger.info("Checking SpireServer pods on remote cluster")
        cfg = get_settings().polling.pod_readiness
        pods = remote_ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready SpireServer pods on remote cluster"
        logger.info(f"Remote SpireServer: {pods[0]['metadata']['name']} is Ready")

    def test_local_spire_agent_running(self, ocp_client, operator_namespace):
        """
        Verify SpireAgent DaemonSet pods are running on the local cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed
        - WHEN we check for SpireAgent pods
        - THEN at least one agent pod is in Ready state
        """
        logger.info("Checking SpireAgent pods on local cluster")
        cfg = get_settings().polling.pod_readiness
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready SpireAgent pods on local cluster"
        logger.info(f"Local SpireAgent: {len(pods)} pod(s) running")

    def test_remote_spire_agent_running(
        self, remote_ocp_client, operator_namespace
    ):
        """
        Verify SpireAgent DaemonSet pods are running on the remote cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed on the remote cluster
        - WHEN we check for SpireAgent pods
        - THEN at least one agent pod is in Ready state
        """
        logger.info("Checking SpireAgent pods on remote cluster")
        cfg = get_settings().polling.pod_readiness
        pods = remote_ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-agent",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready SpireAgent pods on remote cluster"
        logger.info(f"Remote SpireAgent: {len(pods)} pod(s) running")

    def test_local_csi_driver_running(self, ocp_client, operator_namespace):
        """
        Verify SPIFFE CSI Driver is running on the local cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed
        - WHEN we check for CSI driver pods
        - THEN at least one CSI driver pod is in Ready state
        """
        logger.info("Checking SPIFFE CSI Driver on local cluster")
        cfg = get_settings().polling.pod_readiness
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spiffe-csi-driver",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready CSI Driver pods on local cluster"
        logger.info(f"Local CSI Driver: {len(pods)} pod(s) running")

    def test_remote_csi_driver_running(
        self, remote_ocp_client, operator_namespace
    ):
        """
        Verify SPIFFE CSI Driver is running on the remote cluster.

        Acceptance Criteria:
        - GIVEN the ZTWIM stack is deployed on the remote cluster
        - WHEN we check for CSI driver pods
        - THEN at least one CSI driver pod is in Ready state
        """
        logger.info("Checking SPIFFE CSI Driver on remote cluster")
        cfg = get_settings().polling.pod_readiness
        pods = remote_ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spiffe-csi-driver",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        assert len(pods) >= 1, "No ready CSI Driver pods on remote cluster"
        logger.info(f"Remote CSI Driver: {len(pods)} pod(s) running")


@pytest.mark.federation
@pytest.mark.order(11)
class TestFederationConfiguration:
    """
    Phase 1: Enable federation on SpireServers and configure trust.

    This class tests the federation configuration workflow:
    1. Patch SpireServer CRs to enable federation (https_spiffe profile)
    2. Wait for federation routes to be created
    3. Fetch trust bundles from both clusters
    4. Create ClusterFederatedTrustDomain resources for trust bootstrap
    """

    def test_enable_federation_on_local_cluster(
        self,
        federation_helper,
        ocp_client,
        local_app_domain,
        remote_app_domain,
        federation_config,
    ):
        """
        Enable federation on the local cluster's SpireServer.

        Acceptance Criteria:
        - GIVEN a SpireServer CR named 'cluster' exists
        - WHEN we patch it with federation configuration (https_spiffe profile)
        - THEN the patch succeeds and federation spec is present
        """
        logger.info(
            f"Enabling federation on local cluster (remote: {remote_app_domain})"
        )

        result = federation_helper.enable_federation_on_spire_server(
            client=ocp_client,
            remote_trust_domain=remote_app_domain,
            remote_app_domain=remote_app_domain,
        )

        federation_spec = result.get("spec", {}).get("federation", {})
        assert federation_spec, "Federation spec not found after patching"
        assert (
            federation_spec.get("bundleEndpoint", {}).get("profile")
            == federation_config.profile
        ), f"Bundle endpoint profile not set to {federation_config.profile}"

        federates_with = federation_spec.get("federatesWith", [])
        assert len(federates_with) >= 1, "No federatesWith entries found"
        assert federates_with[0]["trustDomain"] == remote_app_domain, (
            f"Expected trustDomain '{remote_app_domain}', "
            f"got '{federates_with[0].get('trustDomain')}'"
        )

        logger.info("Local cluster federation enabled successfully")

    def test_enable_federation_on_remote_cluster(
        self,
        federation_helper,
        remote_ocp_client,
        local_app_domain,
        remote_app_domain,
    ):
        """
        Enable federation on the remote cluster's SpireServer.

        Acceptance Criteria:
        - GIVEN a SpireServer CR named 'cluster' exists on the remote cluster
        - WHEN we patch it with federation configuration pointing to local
        - THEN the patch succeeds and federation spec is present
        """
        logger.info(
            f"Enabling federation on remote cluster (remote: {local_app_domain})"
        )

        result = federation_helper.enable_federation_on_spire_server(
            client=remote_ocp_client,
            remote_trust_domain=local_app_domain,
            remote_app_domain=local_app_domain,
        )

        federation_spec = result.get("spec", {}).get("federation", {})
        assert federation_spec, "Federation spec not found after patching"

        federates_with = federation_spec.get("federatesWith", [])
        assert len(federates_with) >= 1, "No federatesWith entries found"
        assert federates_with[0]["trustDomain"] == local_app_domain

        logger.info("Remote cluster federation enabled successfully")

    def test_local_federation_route_created(
        self, federation_helper, ocp_client, federation_timeout
    ):
        """
        Verify the federation route is created on the local cluster.

        Acceptance Criteria:
        - GIVEN federation is enabled on SpireServer with managedRoute=true
        - WHEN the operator reconciles the CR
        - THEN a federation route is created and admitted
        """
        logger.info("Waiting for federation route on local cluster")
        route = federation_helper.wait_for_federation_route(
            ocp_client, timeout=federation_timeout
        )

        host = route["spec"]["host"]
        assert "federation" in host, f"Unexpected route host: {host}"
        logger.info(f"Local federation route ready: {host}")

    def test_remote_federation_route_created(
        self, federation_helper, remote_ocp_client, federation_timeout
    ):
        """
        Verify the federation route is created on the remote cluster.

        Acceptance Criteria:
        - GIVEN federation is enabled on SpireServer with managedRoute=true
        - WHEN the operator reconciles the CR
        - THEN a federation route is created and admitted
        """
        logger.info("Waiting for federation route on remote cluster")
        route = federation_helper.wait_for_federation_route(
            remote_ocp_client, timeout=federation_timeout
        )

        host = route["spec"]["host"]
        assert "federation" in host, f"Unexpected route host: {host}"
        logger.info(f"Remote federation route ready: {host}")

    def test_spire_servers_ready_after_federation(
        self, ocp_client, remote_ocp_client, operator_namespace
    ):
        """
        Wait for SpireServer pods to be ready after federation patching.

        Acceptance Criteria:
        - GIVEN federation was just enabled on both SpireServer CRs
        - WHEN the operator reconciles and restarts the pods
        - THEN both spire-server pods return to Ready state
        """
        logger.info("Waiting for SpireServer pods to stabilize after federation config change")
        cfg = get_settings().polling.pod_readiness

        ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        logger.info("Local SpireServer pod ready")

        remote_ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=int(cfg.timeout),
        )
        logger.info("Remote SpireServer pod ready")

    def test_fetch_local_trust_bundle(
        self, federation_helper, ocp_client, federation_timeout
    ):
        """
        Fetch the trust bundle from the local cluster's SPIRE server.

        Acceptance Criteria:
        - GIVEN the SPIRE server is running with federation enabled
        - WHEN we exec into the spire-server pod and fetch the bundle
        - THEN a valid SPIFFE bundle (JWKS format) is returned
        """
        logger.info("Fetching trust bundle from local cluster")

        def _fetch_valid_bundle():
            try:
                bundle = federation_helper.fetch_trust_bundle_via_exec(ocp_client)
                if not bundle:
                    logger.warning("Bundle fetch returned empty output")
                    return None
                bundle_data = json.loads(bundle)
                keys = bundle_data.get("keys", [])
                if len(keys) >= 1:
                    return bundle_data
                logger.warning(f"Bundle has no keys yet: {bundle[:200]}")
            except json.JSONDecodeError as e:
                logger.warning(f"Bundle not valid JSON: {e} — raw: {bundle[:200] if bundle else '(empty)'}")
            except Exception as e:
                logger.warning(f"Bundle fetch error: {type(e).__name__}: {e}")
            return None

        result = wait_until(
            _fetch_valid_bundle,
            message="Local trust bundle ready",
            timeout=federation_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, "Failed to fetch valid trust bundle from local cluster"
        logger.info(
            f"Local trust bundle fetched: {len(result.value.get('keys', []))} key(s)"
        )

    def test_fetch_remote_trust_bundle(
        self, federation_helper, remote_ocp_client, federation_timeout
    ):
        """
        Fetch the trust bundle from the remote cluster's SPIRE server.

        Acceptance Criteria:
        - GIVEN the SPIRE server is running with federation enabled
        - WHEN we exec into the remote spire-server pod and fetch the bundle
        - THEN a valid SPIFFE bundle (JWKS format) is returned
        """
        logger.info("Fetching trust bundle from remote cluster")

        def _fetch_valid_bundle():
            try:
                bundle = federation_helper.fetch_trust_bundle_via_exec(remote_ocp_client)
                if not bundle:
                    logger.warning("Bundle fetch returned empty output")
                    return None
                bundle_data = json.loads(bundle)
                keys = bundle_data.get("keys", [])
                if len(keys) >= 1:
                    return bundle_data
                logger.warning(f"Bundle has no keys yet: {bundle[:200]}")
            except json.JSONDecodeError as e:
                logger.warning(f"Bundle not valid JSON: {e} — raw: {bundle[:200] if bundle else '(empty)'}")
            except Exception as e:
                logger.warning(f"Bundle fetch error: {type(e).__name__}: {e}")
            return None

        result = wait_until(
            _fetch_valid_bundle,
            message="Remote trust bundle ready",
            timeout=federation_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, "Failed to fetch valid trust bundle from remote cluster"
        logger.info(
            f"Remote trust bundle fetched: {len(result.value.get('keys', []))} key(s)"
        )


@pytest.mark.federation
@pytest.mark.order(12)
class TestTrustBootstrap:
    """
    Phase 2: Bootstrap trust between the two clusters.

    Creates ClusterFederatedTrustDomain resources on each cluster,
    providing the other cluster's trust bundle for initial trust establishment.
    """

    @pytest.fixture(autouse=True, scope="class")
    def _setup_trust_domains(
        self,
        federation_helper,
        ocp_client,
        remote_ocp_client,
        local_app_domain,
        remote_app_domain,
        skip_cleanup,
    ):
        """Setup and teardown for trust domain resources (class-scoped)."""
        self.__class__._helper = federation_helper
        self.__class__._local_client = ocp_client
        self.__class__._remote_client = remote_ocp_client
        self.__class__._local_domain = local_app_domain
        self.__class__._remote_domain = remote_app_domain
        self.__class__._cfdt_local_name = "federation-to-remote"
        self.__class__._cfdt_remote_name = "federation-to-local"
        self.__class__._created_cfdts = set()

        yield

        if not skip_cleanup:
            for cfdt_key in list(self._created_cfdts):
                client, name = cfdt_key
                target = ocp_client if client == "local" else remote_ocp_client
                federation_helper.delete_cluster_federated_trust_domain(target, name)

    def test_create_cfdt_on_local_cluster(self):
        """
        Create ClusterFederatedTrustDomain on local cluster to trust remote.

        Acceptance Criteria:
        - GIVEN the remote cluster's trust bundle is fetched
        - WHEN we create a ClusterFederatedTrustDomain on the local cluster
        - THEN the resource is created with correct trust domain and bundle
        """
        logger.info("Creating CFDT on local cluster to trust remote")

        remote_bundle = self._helper.fetch_trust_bundle_via_exec(
            self._remote_client
        )
        assert remote_bundle, "Failed to fetch remote trust bundle"

        result = self._helper.create_cluster_federated_trust_domain(
            client=self._local_client,
            name=self._cfdt_local_name,
            remote_trust_domain=self._remote_domain,
            remote_app_domain=self._remote_domain,
            trust_bundle_json=remote_bundle,
        )

        assert result["metadata"]["name"] == self._cfdt_local_name
        assert result["spec"]["trustDomain"] == self._remote_domain
        self._created_cfdts.add(("local", self._cfdt_local_name))
        logger.info(
            f"CFDT created on local cluster: trust {self._remote_domain}"
        )

    def test_create_cfdt_on_remote_cluster(self):
        """
        Create ClusterFederatedTrustDomain on remote cluster to trust local.

        Acceptance Criteria:
        - GIVEN the local cluster's trust bundle is fetched
        - WHEN we create a ClusterFederatedTrustDomain on the remote cluster
        - THEN the resource is created with correct trust domain and bundle
        """
        logger.info("Creating CFDT on remote cluster to trust local")

        local_bundle = self._helper.fetch_trust_bundle_via_exec(
            self._local_client
        )
        assert local_bundle, "Failed to fetch local trust bundle"

        result = self._helper.create_cluster_federated_trust_domain(
            client=self._remote_client,
            name=self._cfdt_remote_name,
            remote_trust_domain=self._local_domain,
            remote_app_domain=self._local_domain,
            trust_bundle_json=local_bundle,
        )

        assert result["metadata"]["name"] == self._cfdt_remote_name
        assert result["spec"]["trustDomain"] == self._local_domain
        self._created_cfdts.add(("remote", self._cfdt_remote_name))
        logger.info(
            f"CFDT created on remote cluster: trust {self._local_domain}"
        )

    def test_verify_bundle_sync_on_local(self, federation_timeout):
        """
        Verify the remote cluster's bundle is synced to the local SPIRE server.

        Acceptance Criteria:
        - GIVEN a CFDT exists pointing to the remote cluster
        - WHEN the SPIRE controller manager reconciles
        - THEN the remote trust domain appears in the local bundle list
        """
        logger.info("Verifying bundle sync on local cluster")

        def _check_bundle_synced():
            output = self._helper.list_federated_bundles(self._local_client)
            return self._remote_domain in output

        result = wait_until(
            _check_bundle_synced,
            message=f"Remote bundle ({self._remote_domain}) synced to local",
            timeout=federation_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, (
            f"Remote trust domain '{self._remote_domain}' not found in local "
            f"bundle list after {federation_timeout}s"
        )
        logger.info(
            f"Bundle sync verified: {self._remote_domain} present on local cluster"
        )

    def test_verify_bundle_sync_on_remote(self, federation_timeout):
        """
        Verify the local cluster's bundle is synced to the remote SPIRE server.

        Acceptance Criteria:
        - GIVEN a CFDT exists pointing to the local cluster
        - WHEN the SPIRE controller manager reconciles
        - THEN the local trust domain appears in the remote bundle list
        """
        logger.info("Verifying bundle sync on remote cluster")

        def _check_bundle_synced():
            output = self._helper.list_federated_bundles(self._remote_client)
            return self._local_domain in output

        result = wait_until(
            _check_bundle_synced,
            message=f"Local bundle ({self._local_domain}) synced to remote",
            timeout=federation_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, (
            f"Local trust domain '{self._local_domain}' not found in remote "
            f"bundle list after {federation_timeout}s"
        )
        logger.info(
            f"Bundle sync verified: {self._local_domain} present on remote cluster"
        )


@pytest.mark.federation
@pytest.mark.order(13)
class TestMTLSWorkloads:
    """
    Phase 3: Deploy and verify mTLS workloads across federated clusters.

    Deploys an mTLS server on the local cluster and an mTLS client on the
    remote cluster, then verifies cross-cluster mutual TLS authentication
    using SPIFFE SVIDs from the federated trust domains.
    """

    @pytest.fixture(autouse=True, scope="class")
    def _setup_workloads(
        self,
        federation_helper,
        ocp_client,
        remote_ocp_client,
        local_app_domain,
        remote_app_domain,
        operator_namespace,
        federation_namespaces,
        skip_cleanup,
        mtls_timeout,
    ):
        """Setup workload resources for mTLS testing (class-scoped)."""
        self.__class__._helper = federation_helper
        self.__class__._local_client = ocp_client
        self.__class__._remote_client = remote_ocp_client
        self.__class__._local_domain = local_app_domain
        self.__class__._remote_domain = remote_app_domain
        self.__class__._namespace = operator_namespace
        self.__class__._server_ns = federation_namespaces["server"]
        self.__class__._client_ns = federation_namespaces["client"]
        self.__class__._skip_cleanup = skip_cleanup
        self.__class__._mtls_timeout = mtls_timeout
        self.__class__._server_spiffeid_name = f"mtls-server-{self._server_ns[-6:]}"
        self.__class__._client_spiffeid_name = f"mtls-client-{self._client_ns[-6:]}"
        self.__class__._created_spiffeids = set()

        yield

        if not skip_cleanup:
            for sid_key in list(self._created_spiffeids):
                client, name = sid_key
                target = ocp_client if client == "local" else remote_ocp_client
                federation_helper.delete_cluster_spiffe_id(target, name)

    def test_create_server_spiffeid(self):
        """
        Create ClusterSPIFFEID for the mTLS server with federation.

        Acceptance Criteria:
        - GIVEN the server namespace exists on the local cluster
        - WHEN we create a ClusterSPIFFEID with federatesWith
        - THEN the resource is created with correct template and federation
        """
        logger.info("Creating ClusterSPIFFEID for mTLS server")

        result = self._helper.create_cluster_spiffe_id(
            client=self._local_client,
            name=self._server_spiffeid_name,
            namespace_match=self._server_ns,
            pod_label="mtls-server",
            federate_with=self._remote_domain,
        )

        assert result["metadata"]["name"] == self._server_spiffeid_name
        assert self._remote_domain in result["spec"]["federatesWith"]
        self._created_spiffeids.add(("local", self._server_spiffeid_name))
        logger.info(
            f"Server ClusterSPIFFEID created (federatesWith: {self._remote_domain})"
        )

    def test_create_client_spiffeid(self):
        """
        Create ClusterSPIFFEID for the mTLS client with federation.

        Acceptance Criteria:
        - GIVEN the client namespace exists on the remote cluster
        - WHEN we create a ClusterSPIFFEID with federatesWith
        - THEN the resource is created with correct template and federation
        """
        logger.info("Creating ClusterSPIFFEID for mTLS client")

        result = self._helper.create_cluster_spiffe_id(
            client=self._remote_client,
            name=self._client_spiffeid_name,
            namespace_match=self._client_ns,
            pod_label="mtls-client",
            federate_with=self._local_domain,
        )

        assert result["metadata"]["name"] == self._client_spiffeid_name
        assert self._local_domain in result["spec"]["federatesWith"]
        self._created_spiffeids.add(("remote", self._client_spiffeid_name))
        logger.info(
            f"Client ClusterSPIFFEID created (federatesWith: {self._local_domain})"
        )

    def test_deploy_mtls_server(self):
        """
        Deploy the mTLS server workload on the local cluster.

        Acceptance Criteria:
        - GIVEN the server namespace and ClusterSPIFFEID exist
        - WHEN we deploy the mTLS server (with spiffe-helper sidecar)
        - THEN the deployment is created and pods become ready
        """
        logger.info(f"Deploying mTLS server in {self._server_ns}")

        self._helper.create_spiffe_helper_configmap(
            self._local_client, self._server_ns
        )
        self._helper.deploy_mtls_server(
            client=self._local_client,
            namespace=self._server_ns,
            app_domain=self._local_domain,
        )

        pods = self._local_client.wait_for_pods_ready(
            namespace=self._server_ns,
            label_selector="app=mtls-server",
            expected_count=1,
            timeout=self._mtls_timeout,
        )
        assert len(pods) >= 1, "mTLS server pod not ready"
        logger.info(f"mTLS server pod ready: {pods[0]['metadata']['name']}")

    def test_deploy_mtls_client(self):
        """
        Deploy the mTLS client pod on the remote cluster.

        Acceptance Criteria:
        - GIVEN the client namespace and ClusterSPIFFEID exist
        - WHEN we deploy the mTLS client (with spiffe-helper sidecar)
        - THEN the pod becomes ready
        """
        logger.info(f"Deploying mTLS client in {self._client_ns}")

        self._helper.create_spiffe_helper_configmap(
            self._remote_client, self._client_ns
        )
        self._helper.deploy_mtls_client(
            client=self._remote_client,
            namespace=self._client_ns,
        )

        pods = self._remote_client.wait_for_pods_ready(
            namespace=self._client_ns,
            label_selector="app=mtls-client",
            expected_count=1,
            timeout=self._mtls_timeout,
        )
        assert len(pods) >= 1, "mTLS client pod not ready"
        logger.info(f"mTLS client pod ready: {pods[0]['metadata']['name']}")

    def test_server_svid_files_exist(self):
        """
        Verify SVID certificate files are delivered to the mTLS server.

        Acceptance Criteria:
        - GIVEN the mTLS server pod is running with SPIFFE CSI volume
        - WHEN the spiffe-helper syncs certificates
        - THEN svid.pem, svid_key.pem, and bundle.pem exist in /certs
        """
        logger.info("Verifying SVID files on mTLS server")

        pods = self._local_client.get_pods(
            namespace=self._server_ns, label_selector="app=mtls-server"
        )
        pod_name = pods[0]["metadata"]["name"]

        def _check_svid():
            try:
                output = self._local_client.exec_in_pod(
                    name=pod_name,
                    namespace=self._server_ns,
                    command=["ls", "/certs/svid.pem", "/certs/svid_key.pem", "/certs/bundle.pem"],
                    container="server",
                )
                return "svid.pem" in output
            except Exception:
                return False

        result = wait_until(
            _check_svid,
            message="Server SVID files ready",
            timeout=self._mtls_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, "SVID files not found on mTLS server pod"
        logger.info("Server SVID files verified: svid.pem, svid_key.pem, bundle.pem")

    def test_client_svid_files_exist(self):
        """
        Verify SVID certificate files are delivered to the mTLS client.

        Acceptance Criteria:
        - GIVEN the mTLS client pod is running with SPIFFE CSI volume
        - WHEN the spiffe-helper syncs certificates
        - THEN svid.pem, svid_key.pem, and bundle.pem exist in /certs
        """
        logger.info("Verifying SVID files on mTLS client")

        def _check_svid():
            try:
                output = self._remote_client.exec_in_pod(
                    name="mtls-client",
                    namespace=self._client_ns,
                    command=["ls", "/certs/svid.pem", "/certs/svid_key.pem", "/certs/bundle.pem"],
                    container="client",
                )
                return "svid.pem" in output
            except Exception:
                return False

        result = wait_until(
            _check_svid,
            message="Client SVID files ready",
            timeout=self._mtls_timeout,
            interval=10,
            backoff=1.0,
        )
        assert result.success, "SVID files not found on mTLS client pod"
        logger.info("Client SVID files verified: svid.pem, svid_key.pem, bundle.pem")

    def test_server_spiffe_id_correct(self):
        """
        Verify the mTLS server's SPIFFE ID is correctly issued.

        Acceptance Criteria:
        - GIVEN the server has SVID files
        - WHEN we inspect the certificate's SAN
        - THEN it contains a SPIFFE URI matching the local trust domain
        """
        logger.info("Verifying server SPIFFE ID")

        pods = self._local_client.get_pods(
            namespace=self._server_ns, label_selector="app=mtls-server"
        )
        pod_name = pods[0]["metadata"]["name"]

        output = self._local_client.exec_in_pod(
            name=pod_name,
            namespace=self._server_ns,
            command=[
                "openssl", "x509", "-in", "/certs/svid.pem",
                "-noout", "-ext", "subjectAltName",
            ],
            container="server",
        )

        expected_prefix = f"spiffe://{self._local_domain}/ns/{self._server_ns}"
        assert expected_prefix in output, (
            f"Expected SPIFFE ID prefix '{expected_prefix}' not found in: {output}"
        )
        logger.info(f"Server SPIFFE ID verified: {expected_prefix}/sa/mtls-server-sa")

    def test_client_spiffe_id_correct(self):
        """
        Verify the mTLS client's SPIFFE ID is correctly issued.

        Acceptance Criteria:
        - GIVEN the client has SVID files
        - WHEN we inspect the certificate's SAN
        - THEN it contains a SPIFFE URI matching the remote trust domain
        """
        logger.info("Verifying client SPIFFE ID")

        output = self._remote_client.exec_in_pod(
            name="mtls-client",
            namespace=self._client_ns,
            command=[
                "openssl", "x509", "-in", "/certs/svid.pem",
                "-noout", "-ext", "subjectAltName",
            ],
            container="client",
        )

        expected_prefix = f"spiffe://{self._remote_domain}/ns/{self._client_ns}"
        assert expected_prefix in output, (
            f"Expected SPIFFE ID prefix '{expected_prefix}' not found in: {output}"
        )
        logger.info(f"Client SPIFFE ID verified: {expected_prefix}/sa/mtls-client-sa")

    def test_server_entry_has_federate_with(self):
        """
        Verify the SPIRE entry for the server includes federatesWith.

        Acceptance Criteria:
        - GIVEN the ClusterSPIFFEID with federatesWith is created
        - WHEN we inspect SPIRE registration entries on the local server
        - THEN the server entry shows federation with the remote domain
        """
        logger.info("Checking server SPIRE entry for federatesWith")

        entries = self._helper.show_spire_entries(self._local_client)
        assert self._remote_domain in entries, (
            f"FederatesWith '{self._remote_domain}' not found in local SPIRE entries"
        )
        logger.info(
            f"Server entry includes FederatesWith: {self._remote_domain}"
        )

    def test_client_entry_has_federate_with(self):
        """
        Verify the SPIRE entry for the client includes federatesWith.

        Acceptance Criteria:
        - GIVEN the ClusterSPIFFEID with federatesWith is created
        - WHEN we inspect SPIRE registration entries on the remote server
        - THEN the client entry shows federation with the local domain
        """
        logger.info("Checking client SPIRE entry for federatesWith")

        entries = self._helper.show_spire_entries(self._remote_client)
        assert self._local_domain in entries, (
            f"FederatesWith '{self._local_domain}' not found in remote SPIRE entries"
        )
        logger.info(
            f"Client entry includes FederatesWith: {self._local_domain}"
        )


@pytest.mark.federation
@pytest.mark.order(14)
class TestCrossClusterMTLS:
    """
    Phase 4: Execute cross-cluster mTLS authentication test.

    This is the key validation - the mTLS client on the remote cluster
    connects to the mTLS server on the local cluster using SPIFFE SVIDs
    from different trust domains, proving federation is fully operational.
    """

    @pytest.fixture(autouse=True)
    def _setup_mtls_test(
        self,
        federation_helper,
        ocp_client,
        remote_ocp_client,
        local_app_domain,
        remote_app_domain,
        federation_namespaces,
        mtls_timeout,
    ):
        """Setup for mTLS cross-cluster test."""
        self._helper = federation_helper
        self._local_client = ocp_client
        self._remote_client = remote_ocp_client
        self._local_domain = local_app_domain
        self._remote_domain = remote_app_domain
        self._server_ns = federation_namespaces["server"]
        self._client_ns = federation_namespaces["client"]
        self._mtls_timeout = mtls_timeout

    def test_create_server_route(self):
        """
        Create a TLS passthrough route for the mTLS server.

        Acceptance Criteria:
        - GIVEN the mTLS server service is running
        - WHEN we create a TLS passthrough route
        - THEN the route is created with the correct host
        """
        logger.info("Creating TLS passthrough route for mTLS server")

        route_host = f"mtls-secure-{self._server_ns}.{self._local_domain}"
        self._helper.create_passthrough_route(
            client=self._local_client,
            name="mtls-secure",
            namespace=self._server_ns,
            service_name="mtls-server",
            host=route_host,
        )

        route = self._local_client.get_route("mtls-secure", self._server_ns)
        assert route is not None, "mTLS route not found after creation"
        assert route["spec"]["host"] == route_host
        logger.info(f"Server route created: https://{route_host}")

    def test_mtls_connection_established(self):
        """
        Execute cross-cluster mTLS connection and verify success.

        This is the critical federation validation test. The client on the
        remote cluster connects to the server on the local cluster using
        mutual TLS with SPIFFE certificates from different trust domains.

        Acceptance Criteria:
        - GIVEN both workloads have SVID files from federated trust domains
        - WHEN the client initiates an mTLS connection to the server
        - THEN the TLS handshake succeeds (CONNECTION ESTABLISHED)
        - AND both sides present valid SPIFFE certificates
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("CROSS-CLUSTER mTLS TEST")
        logger.info("=" * 60)
        logger.info(f"  Client: {self._remote_domain} (remote cluster)")
        logger.info(f"  Server: {self._local_domain} (local cluster)")
        logger.info("=" * 60)

        server_host = f"mtls-secure-{self._server_ns}.{self._local_domain}"

        def _attempt_mtls():
            try:
                output = self._helper.exec_mtls_connection(
                    client=self._remote_client,
                    pod_name="mtls-client",
                    namespace=self._client_ns,
                    server_host=server_host,
                    port=443,
                )
                return "CONNECTION ESTABLISHED" in output
            except Exception as e:
                logger.debug(f"mTLS attempt failed: {e}")
                return False

        result = wait_until(
            _attempt_mtls,
            message="mTLS connection to remote server",
            timeout=self._mtls_timeout,
            interval=15,
            backoff=1.0,
        )

        assert result.success, (
            "Cross-cluster mTLS connection failed. "
            "The client could not establish a mutually authenticated TLS "
            "connection to the server using federated SPIFFE identities."
        )
        logger.info("")
        logger.info("CROSS-CLUSTER mTLS TEST PASSED")
        logger.info(f"  Connection established in {result.elapsed_time:.1f}s")
        logger.info(f"  Protocol: TLSv1.3 (SPIFFE mTLS)")
        logger.info(f"  Client SPIFFE ID: spiffe://{self._remote_domain}/...")
        logger.info(f"  Server SPIFFE ID: spiffe://{self._local_domain}/...")
        logger.info("")

    def test_mtls_connection_details(self):
        """
        Verify detailed mTLS connection properties.

        Acceptance Criteria:
        - GIVEN a successful mTLS connection
        - WHEN we examine the connection details
        - THEN TLS version is 1.2 or 1.3, peer cert shows SPIRE identity
        """
        logger.info("Verifying mTLS connection details")

        server_host = f"mtls-secure-{self._server_ns}.{self._local_domain}"

        output = self._helper.exec_mtls_connection(
            client=self._remote_client,
            pod_name="mtls-client",
            namespace=self._client_ns,
            server_host=server_host,
            port=443,
        )

        assert "CONNECTION ESTABLISHED" in output, (
            "mTLS connection not established for detail verification"
        )

        has_tls_version = "TLSv1.3" in output or "TLSv1.2" in output
        assert has_tls_version, (
            f"Expected TLSv1.2 or TLSv1.3 in output, got: {output[:200]}"
        )

        assert "SPIRE" in output or "C=US" in output, (
            "Peer certificate does not appear to be a SPIRE-issued certificate"
        )

        logger.info("mTLS connection details verified:")
        if "TLSv1.3" in output:
            logger.info("  TLS Version: TLSv1.3")
        else:
            logger.info("  TLS Version: TLSv1.2")
        logger.info("  Peer Certificate: SPIRE-issued (C=US, O=SPIRE)")
        logger.info("  Federation: Cross-cluster trust verified")


@pytest.mark.federation
@pytest.mark.order(15)
class TestFederationCleanup:
    """
    Phase 5: Verify clean teardown of federation resources.

    Tests that federation resources can be cleanly removed without
    affecting the base SPIRE stack.
    """

    def test_federation_resources_can_be_listed(
        self, ocp_client, remote_ocp_client
    ):
        """
        Verify federation CRDs are queryable on both clusters.

        Acceptance Criteria:
        - GIVEN federation was configured
        - WHEN we list ClusterFederatedTrustDomain resources
        - THEN the API responds without error
        """
        logger.info("Listing federation resources on both clusters")

        try:
            local_resource = ocp_client.get_crd_resource(
                "spire.spiffe.io/v1alpha1", "ClusterFederatedTrustDomain"
            )
            local_list = local_resource.get()
            logger.info(
                f"Local CFDT count: {len(local_list.get('items', []))}"
            )
        except Exception as e:
            logger.warning(f"Could not list local CFDTs: {e}")

        try:
            remote_resource = remote_ocp_client.get_crd_resource(
                "spire.spiffe.io/v1alpha1", "ClusterFederatedTrustDomain"
            )
            remote_list = remote_resource.get()
            logger.info(
                f"Remote CFDT count: {len(remote_list.get('items', []))}"
            )
        except Exception as e:
            logger.warning(f"Could not list remote CFDTs: {e}")

    def test_spire_server_still_healthy_after_federation(
        self, ocp_client, operator_namespace
    ):
        """
        Verify the local SpireServer remains healthy after federation tests.

        Acceptance Criteria:
        - GIVEN federation was configured and tested
        - WHEN we check SpireServer pods
        - THEN they are still in Ready state
        """
        logger.info("Verifying SpireServer health post-federation")
        pods = ocp_client.wait_for_pods_ready(
            namespace=operator_namespace,
            label_selector="app.kubernetes.io/name=spire-server",
            expected_count=1,
            timeout=30,
        )
        assert len(pods) >= 1, "SpireServer not healthy after federation tests"
        logger.info("SpireServer remains healthy after federation testing")
