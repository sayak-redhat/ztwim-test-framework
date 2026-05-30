"""ZTWIM CRD management helpers for ZTWIM Test Framework.

This module provides high-level managers for ZTWIM Operator CRDs:
- ZeroTrustWorkloadIdentityManager
- SpireServer
- SpireAgent
- SpiffeCSIDriver
- SpireOIDCDiscoveryProvider

API Version: operator.openshift.io/v1alpha1
"""

import time
from typing import Any, Dict, List, Optional

from src.ocp_client import OCPClient
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.polling import DynamicPoller, PollConfig

logger = get_logger(__name__)

# Default poller instance reading from settings
_settings = get_settings()
_poller = DynamicPoller(PollConfig(
    initial_delay=2.0,
    min_interval=_settings.polling.component_verify.interval,
    max_interval=_settings.polling.component_verify.interval * 4,
    backoff_factor=_settings.polling.component_verify.backoff_factor,
    timeout=_settings.polling.component_verify.timeout,
    log_every=5
))

# ZTWIM API version (OpenShift operator)
ZTWIM_API_VERSION = "operator.openshift.io/v1alpha1"

# OLM API versions
OLM_OPERATORS_API = "operators.coreos.com/v1"
OLM_SUBSCRIPTION_API = "operators.coreos.com/v1alpha1"


class BaseCRDManager:
    """Base class for CRD managers."""
    
    API_VERSION: str = ZTWIM_API_VERSION
    KIND: str = ""
    
    def __init__(self, ocp_client: "OCPClient"):
        """
        Initialize the CRD manager.
        
        Args:
            ocp_client: OCPClient instance
        """
        self.client = ocp_client
        self.settings = get_settings()
    
    def create(
        self,
        name: str,
        namespace: Optional[str] = None,
        spec: Dict[str, Any] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Create a custom resource (or return existing if already exists).
        
        Args:
            name: Resource name
            namespace: Namespace (None for cluster-scoped)
            spec: Resource spec
            labels: Optional labels
            annotations: Optional annotations
        
        Returns:
            Created or existing resource
        """
        from kubernetes.dynamic.exceptions import ConflictError
        
        body = {
            "apiVersion": self.API_VERSION,
            "kind": self.KIND,
            "metadata": {
                "name": name,
                "labels": labels or {},
                "annotations": annotations or {},
            },
            "spec": spec or {},
        }
        
        if namespace:
            body["metadata"]["namespace"] = namespace
        
        try:
            return self.client.create_custom_resource(
                api_version=self.API_VERSION,
                kind=self.KIND,
                namespace=namespace or "",
                body=body
            )
        except ConflictError:
            # Resource already exists - return the existing one
            logger.info(f"{self.KIND} '{name}' already exists, using existing resource")
            return self.get(name, namespace)
    
    def get(self, name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get a resource by name."""
        return self.client.get_custom_resource(
            api_version=self.API_VERSION,
            kind=self.KIND,
            name=name,
            namespace=namespace or ""
        )
    
    def patch(
        self,
        name: str,
        namespace: Optional[str] = None,
        spec: Optional[Dict[str, Any]] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Patch a resource."""
        body: Dict[str, Any] = {}
        
        if spec:
            body["spec"] = spec
        if labels or annotations:
            body["metadata"] = {}
            if labels:
                body["metadata"]["labels"] = labels
            if annotations:
                body["metadata"]["annotations"] = annotations
        
        return self.client.patch_custom_resource(
            api_version=self.API_VERSION,
            kind=self.KIND,
            name=name,
            namespace=namespace or "",
            body=body
        )
    
    def delete(self, name: str, namespace: Optional[str] = None) -> None:
        """Delete a resource."""
        self.client.delete_custom_resource(
            api_version=self.API_VERSION,
            kind=self.KIND,
            name=name,
            namespace=namespace or ""
        )
    
    def exists(self, name: str, namespace: Optional[str] = None) -> bool:
        """Check if resource exists."""
        try:
            self.get(name, namespace)
            return True
        except Exception:
            return False
    
    def wait_for_ready(
        self,
        name: str,
        namespace: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """Wait for resource to be ready."""
        return self.client.wait_for_custom_resource_condition(
            api_version=self.API_VERSION,
            kind=self.KIND,
            name=name,
            namespace=namespace or "",
            condition_type="Available",
            expected_status="True",
            timeout=timeout
        )
    
    def get_status(self, name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get resource status."""
        cr = self.get(name, namespace)
        return cr.get("status", {})
    
    def get_conditions(self, name: str, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get resource conditions."""
        status = self.get_status(name, namespace)
        return status.get("conditions", [])


class OperatorInstaller:
    """Helper to install ZTWIM operator via OLM."""
    
    OPERATOR_NAMESPACE = "zero-trust-workload-identity-manager"
    OPERATOR_NAME = "openshift-zero-trust-workload-identity-manager"
    
    # Default OLM configuration
    DEFAULT_CATALOG_SOURCE = "redhat-operators"
    DEFAULT_CHANNEL = "stable-v1"
    
    def __init__(self, ocp_client: "OCPClient"):
        self.client = ocp_client
        self.settings = get_settings()
    
    def install(
        self,
        catalog_name: Optional[str] = None,
        channel: Optional[str] = None
    ) -> None:
        """
        Install ZTWIM operator via OLM Subscription.
        
        Args:
            catalog_name: Catalog source name (default: redhat-operators)
            channel: Subscription channel (default: stable-v1)
        """
        import os
        
        # Resolve catalog name (check for unexpanded variables)
        catalog = catalog_name
        if not catalog or catalog.startswith("$"):
            catalog = os.environ.get("CATALOG_NAME", "")
        if not catalog or catalog.startswith("$"):
            settings_catalog = self.settings.ztwim.catalog_name
            if settings_catalog and not settings_catalog.startswith("$"):
                catalog = settings_catalog
        if not catalog or catalog.startswith("$"):
            catalog = self.DEFAULT_CATALOG_SOURCE
        
        # Resolve channel
        sub_channel = channel
        if not sub_channel or sub_channel.startswith("$"):
            settings_channel = self.settings.ztwim.channel
            if settings_channel and not settings_channel.startswith("$"):
                sub_channel = settings_channel
        if not sub_channel or sub_channel.startswith("$"):
            sub_channel = self.DEFAULT_CHANNEL
        
        logger.info(f"Installing ZTWIM operator from catalog: {catalog}, channel: {sub_channel}")
        
        # 1. Check if namespace exists and is terminating - wait for deletion
        self._wait_for_namespace_deletion_if_terminating()
        
        # 2. Create namespace
        logger.info(f"Creating namespace: {self.OPERATOR_NAMESPACE}")
        self.client.create_namespace(
            name=self.OPERATOR_NAMESPACE,
            labels={"openshift.io/cluster-monitoring": "true"}
        )
        
        # 3. Create OperatorGroup (if not exists)
        logger.info("Creating OperatorGroup")
        og_body = {
            "apiVersion": OLM_OPERATORS_API,
            "kind": "OperatorGroup",
            "metadata": {
                "name": f"{self.OPERATOR_NAMESPACE}-og",
                "namespace": self.OPERATOR_NAMESPACE,
            },
            "spec": {
                "upgradeStrategy": "Default"
            }
        }
        try:
            self.client.create_custom_resource(
                api_version=OLM_OPERATORS_API,
                kind="OperatorGroup",
                namespace=self.OPERATOR_NAMESPACE,
                body=og_body
            )
        except Exception as e:
            if "already exists" in str(e).lower() or "409" in str(e):
                logger.info("OperatorGroup already exists, continuing...")
            else:
                raise
        
        # 4. Create Subscription (if not exists)
        logger.info(f"Creating Subscription (channel: {sub_channel})")
        sub_body = {
            "apiVersion": OLM_SUBSCRIPTION_API,
            "kind": "Subscription",
            "metadata": {
                "name": self.OPERATOR_NAME,
                "namespace": self.OPERATOR_NAMESPACE,
            },
            "spec": {
                "source": catalog,
                "sourceNamespace": "openshift-marketplace",
                "name": self.OPERATOR_NAME,
                "channel": sub_channel,
            }
        }
        try:
            self.client.create_custom_resource(
                api_version=OLM_SUBSCRIPTION_API,
                kind="Subscription",
                namespace=self.OPERATOR_NAMESPACE,
                body=sub_body
            )
            logger.info("ZTWIM operator subscription created")
        except Exception as e:
            if "already exists" in str(e).lower() or "409" in str(e):
                logger.info("Subscription already exists, continuing...")
            else:
                raise
    
    def _wait_for_namespace_deletion_if_terminating(self, timeout: int = 300) -> None:
        """
        Check if namespace is terminating and wait for it to be fully deleted.
        
        This handles the case where a previous test run triggered cleanup
        and the namespace is still being deleted.
        
        Uses dynamic polling with exponential backoff.
        """
        from src.utils.polling import wait_until

        try:
            ns = self.client.core_v1.read_namespace(name=self.OPERATOR_NAMESPACE)
            phase = ns.status.phase if ns.status else None
            
            if phase == "Terminating":
                logger.info(f"Namespace '{self.OPERATOR_NAMESPACE}' is terminating, waiting for deletion...")
                
                def check_namespace_deleted():
                    """Return True when namespace is deleted."""
                    try:
                        ns = self.client.core_v1.read_namespace(name=self.OPERATOR_NAMESPACE)
                        phase = ns.status.phase if ns.status else None
                        
                        if phase != "Terminating":
                            # Unexpected state
                            logger.warning(f"Namespace in unexpected state: {phase}")
                            return True  # Exit polling
                        
                        return False  # Still terminating
                        
                    except Exception as e:
                        # Namespace no longer exists - deletion complete
                        if "not found" in str(e).lower() or "404" in str(e):
                            return True
                        raise
                
                result = wait_until(
                    condition=check_namespace_deleted,
                    message=f"Namespace '{self.OPERATOR_NAMESPACE}' deletion",
                    timeout=timeout,
                    interval=5,
                    backoff=1.2
                )
                
                if not result.success:
                    raise TimeoutError(
                        f"Namespace '{self.OPERATOR_NAMESPACE}' still terminating after {timeout}s.\n"
                        f"This usually happens when previous cleanup is still in progress.\n"
                        f"Options:\n"
                        f"  1. Wait a few minutes and retry\n"
                        f"  2. Force delete: oc delete ns {self.OPERATOR_NAMESPACE} --force --grace-period=0\n"
                        f"  3. Check stuck resources: oc get all -n {self.OPERATOR_NAMESPACE}"
                    )
            else:
                logger.debug(f"Namespace '{self.OPERATOR_NAMESPACE}' exists in phase: {phase}")
                
        except Exception as e:
            # Namespace doesn't exist - that's fine, we'll create it
            if "not found" in str(e).lower() or "404" in str(e):
                logger.debug(f"Namespace '{self.OPERATOR_NAMESPACE}' does not exist yet")
                return
            raise
    
    def wait_for_operator_ready(self, timeout: int = 300) -> bool:
        """
        Wait for operator deployment to be ready using dynamic polling.
        
        Uses exponential backoff for efficient polling.
        """
        def check_operator_ready():
            try:
                deployments = self.client.apps_v1.list_namespaced_deployment(
                    namespace=self.OPERATOR_NAMESPACE
                )
                
                for dep in deployments.items:
                    if "zero-trust" in dep.metadata.name.lower():
                        ready = dep.status.ready_replicas or 0
                        desired = dep.spec.replicas or 1
                        if ready >= desired:
                            return dep.metadata.name
                return None
            except Exception:
                return None
        
        config = PollConfig(
            initial_delay=5.0,
            min_interval=_settings.polling.operator.interval,
            max_interval=_settings.polling.operator.interval * 4,
            backoff_factor=_settings.polling.operator.backoff_factor,
            timeout=float(timeout),
            message="ZTWIM operator deployment"
        )
        
        result = _poller.wait_until(check_operator_ready, config=config)
        
        if result.success:
            logger.info(f"✅ Operator ready: {result.value}")
            return True
        else:
            raise TimeoutError(f"Operator not ready within {timeout}s")
    
    def is_installed(self) -> bool:
        """Check if operator is installed."""
        try:
            subs = self.client.custom_objects.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=self.OPERATOR_NAMESPACE,
                plural="subscriptions"
            )
            return len(subs.get("items", [])) > 0
        except Exception:
            return False
    
    def uninstall(self, timeout: int = 120) -> None:
        """
        Uninstall ZTWIM operator completely.
        
        Deletes in order:
        1. Subscription
        2. ClusterServiceVersion (CSV)
        3. OperatorGroup
        4. Namespace (which deletes everything in it)
        """
        logger.info("=" * 50)
        logger.info("UNINSTALLING ZTWIM OPERATOR")
        logger.info("=" * 50)
        
        # 1. Delete Subscription
        try:
            logger.info(f"Deleting Subscription: {self.OPERATOR_NAME}")
            self.client.custom_objects.delete_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=self.OPERATOR_NAMESPACE,
                plural="subscriptions",
                name=self.OPERATOR_NAME
            )
            logger.info("✅ Subscription deleted")
        except Exception as e:
            logger.debug(f"Subscription not found or already deleted: {e}")
        
        # 2. Delete ClusterServiceVersion (CSV)
        try:
            logger.info("Deleting ClusterServiceVersions...")
            csvs = self.client.custom_objects.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=self.OPERATOR_NAMESPACE,
                plural="clusterserviceversions"
            )
            for csv in csvs.get("items", []):
                csv_name = csv["metadata"]["name"]
                if "zero-trust" in csv_name.lower():
                    logger.info(f"Deleting CSV: {csv_name}")
                    self.client.custom_objects.delete_namespaced_custom_object(
                        group="operators.coreos.com",
                        version="v1alpha1",
                        namespace=self.OPERATOR_NAMESPACE,
                        plural="clusterserviceversions",
                        name=csv_name
                    )
            logger.info("✅ CSVs deleted")
        except Exception as e:
            logger.debug(f"CSVs not found or already deleted: {e}")
        
        # 3. Delete OperatorGroup
        try:
            og_name = f"{self.OPERATOR_NAMESPACE}-og"
            logger.info(f"Deleting OperatorGroup: {og_name}")
            self.client.custom_objects.delete_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1",
                namespace=self.OPERATOR_NAMESPACE,
                plural="operatorgroups",
                name=og_name
            )
            logger.info("✅ OperatorGroup deleted")
        except Exception as e:
            logger.debug(f"OperatorGroup not found or already deleted: {e}")
        
        # 4. Delete Namespace (this will delete everything in it)
        try:
            logger.info(f"Deleting Namespace: {self.OPERATOR_NAMESPACE}")
            self.client.core_v1.delete_namespace(name=self.OPERATOR_NAMESPACE)
            
            # Wait for namespace to be deleted
            logger.info("Waiting for namespace deletion...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    self.client.core_v1.read_namespace(name=self.OPERATOR_NAMESPACE)
                    time.sleep(_settings.polling.cleanup.interval)
                except Exception:
                    logger.info("✅ Namespace deleted")
                    break
            else:
                logger.warning(f"Namespace deletion timed out after {timeout}s")
        except Exception as e:
            logger.debug(f"Namespace not found or already deleted: {e}")
        
        logger.info("=" * 50)
        logger.info("✅ ZTWIM OPERATOR UNINSTALL COMPLETE")
        logger.info("=" * 50)


class ZTWIMManager(BaseCRDManager):
    """Manager for ZeroTrustWorkloadIdentityManager custom resources."""
    
    KIND = "ZeroTrustWorkloadIdentityManager"
    
    def create_cluster(
        self,
        trust_domain: str,
        cluster_name: str,
        name: str = "cluster"
    ) -> Dict[str, Any]:
        """
        Create the cluster ZeroTrustWorkloadIdentityManager.
        
        Args:
            trust_domain: Trust domain (usually APP_DOMAIN)
            cluster_name: Cluster name identifier
            name: Resource name (default: "cluster")
        
        Returns:
            Created ZeroTrustWorkloadIdentityManager
        """
        spec = {
            "trustDomain": trust_domain,
            "clusterName": cluster_name,
        }
        
        return self.create(name=name, spec=spec)


class SpireServerManager(BaseCRDManager):
    """Manager for SpireServer custom resources."""
    
    KIND = "SpireServer"
    
    def create_default(
        self,
        app_domain: str,
        jwt_issuer_endpoint: str,
        trust_domain: str,
        cluster_name: str,
        name: str = "cluster",
        ca_country: str = "US",
        ca_organization: str = "RH",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a SpireServer with default configuration.
        
        Args:
            app_domain: OpenShift apps domain
            jwt_issuer_endpoint: JWT issuer endpoint URL
            trust_domain: SPIFFE trust domain
            cluster_name: Cluster name identifier
            name: Resource name (default: "cluster")
            ca_country: CA certificate country
            ca_organization: CA certificate organization
            **kwargs: Additional spec fields
        
        Returns:
            Created SpireServer
        """
        trust_domain = (trust_domain or "").strip()
        cluster_name = (cluster_name or "").strip()
        if not trust_domain:
            raise ValueError(
                "SpireServer requires a non-empty trust_domain. "
                "Provide --app-domain or set APP_DOMAIN."
            )
        if not cluster_name:
            raise ValueError(
                "SpireServer requires a non-empty cluster_name. "
                "Provide --cluster-name or set CLUSTER_NAME."
            )

        spec = {
            "caSubject": {
                "commonName": app_domain,
                "country": ca_country,
                "organization": ca_organization,
            },
            "persistence": {
                "type": "pvc",
                "size": "1Gi",
                "accessMode": "ReadWriteOncePod",
            },
            "datastore": {
                "databaseType": "sqlite3",
                "connectionString": "/run/spire/data/datastore.sqlite3",
                "maxOpenConns": 100,
                "maxIdleConns": 2,
                "connMaxLifetime": 3600,
            },
            "jwtIssuer": f"https://{jwt_issuer_endpoint}",
            "trustDomain": trust_domain,
            "clusterName": cluster_name,
            **kwargs
        }
        
        return self.create(name=name, spec=spec)
    
    def wait_for_ready(
        self,
        name: str = "cluster",
        namespace: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for SpireServer to be ready using dynamic polling.
        
        Polls with exponential backoff until StatefulSet pods are ready.
        """
        operator_ns = self.settings.openshift.operator_namespace
        
        def check_spire_server_ready():
            try:
                pods = self.client.get_pods(
                    namespace=operator_ns,
                    label_selector="app.kubernetes.io/name=spire-server"
                )
                ready_pods = [p for p in pods if self.client._is_pod_ready(p)]
                if len(ready_pods) > 0:
                    return ready_pods
                return None
            except Exception:
                return None
        
        config = PollConfig(
            initial_delay=3.0,
            min_interval=5.0,
            max_interval=15.0,
            backoff_factor=1.3,
            timeout=float(timeout),
            message="SpireServer StatefulSet"
        )
        
        result = _poller.wait_until(check_spire_server_ready, config=config)
        
        if result.success:
            return self.get(name)
        else:
            raise TimeoutError(f"SpireServer not ready within {timeout}s")


class SpireAgentManager(BaseCRDManager):
    """Manager for SpireAgent custom resources."""
    
    KIND = "SpireAgent"
    
    def create_default(
        self,
        name: str = "cluster",
        k8s_psat_enabled: str = "true",
        k8s_workload_enabled: str = "true",
        verification_type: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a SpireAgent with default configuration.
        
        Args:
            name: Resource name (default: "cluster")
            k8s_psat_enabled: Enable K8s PSAT node attestor
            k8s_workload_enabled: Enable K8s workload attestor
            verification_type: Workload verification type
            **kwargs: Additional spec fields
        
        Returns:
            Created SpireAgent
        """
        spec = {
            "nodeAttestor": {
                "k8sPSATEnabled": k8s_psat_enabled,
            },
            "workloadAttestors": {
                "k8sEnabled": k8s_workload_enabled,
                "workloadAttestorsVerification": {
                    "type": verification_type,
                },
            },
            **kwargs
        }
        
        return self.create(name=name, spec=spec)
    
    def wait_for_ready(
        self,
        name: str = "cluster",
        namespace: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for SpireAgent to be ready on all nodes using dynamic polling.
        
        Polls with exponential backoff until DaemonSet has all pods ready.
        """
        operator_ns = self.settings.openshift.operator_namespace
        
        def check_spire_agent_ready():
            try:
                ds_list = self.client.apps_v1.list_namespaced_daemon_set(
                    namespace=operator_ns,
                    label_selector="app.kubernetes.io/name=spire-agent"
                )
                
                if ds_list.items:
                    ds = ds_list.items[0]
                    desired = ds.status.desired_number_scheduled or 0
                    ready = ds.status.number_ready or 0
                    
                    if desired > 0 and ready >= desired:
                        return {"desired": desired, "ready": ready}
                return None
            except Exception:
                return None
        
        config = PollConfig(
            initial_delay=3.0,
            min_interval=5.0,
            max_interval=15.0,
            backoff_factor=1.3,
            timeout=float(timeout),
            message="SpireAgent DaemonSet"
        )
        
        result = _poller.wait_until(check_spire_agent_ready, config=config)
        
        if result.success:
            return self.get(name)
        else:
            raise TimeoutError(f"SpireAgent not ready within {timeout}s")
    
    def get_daemonset_labels(self) -> Dict[str, str]:
        """Get labels from SpireAgent DaemonSet."""
        operator_ns = self.settings.openshift.operator_namespace
        
        ds_list = self.client.apps_v1.list_namespaced_daemon_set(
            namespace=operator_ns,
            label_selector="app.kubernetes.io/name=spire-agent"
        )
        
        if ds_list.items:
            return dict(ds_list.items[0].metadata.labels or {})
        return {}


class SpiffeCSIDriverManager(BaseCRDManager):
    """Manager for SpiffeCSIDriver custom resources."""
    
    KIND = "SpiffeCSIDriver"
    
    def create_default(self, name: str = "cluster", **kwargs) -> Dict[str, Any]:
        """
        Create a SpiffeCSIDriver with default configuration.
        
        Args:
            name: Resource name (default: "cluster")
            **kwargs: Additional spec fields
        
        Returns:
            Created SpiffeCSIDriver
        """
        spec = {**kwargs}
        return self.create(name=name, spec=spec)
    
    def wait_for_ready(
        self,
        name: str = "cluster",
        namespace: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for SpiffeCSIDriver to be ready using dynamic polling.
        
        Polls with exponential backoff until CSI driver DaemonSet is ready.
        """
        operator_ns = self.settings.openshift.operator_namespace
        
        def check_csi_driver_ready():
            try:
                ds_list = self.client.apps_v1.list_namespaced_daemon_set(
                    namespace=operator_ns,
                    label_selector="app.kubernetes.io/name=spiffe-csi-driver"
                )
                
                # Try alternative label if not found
                if not ds_list.items:
                    ds_list = self.client.apps_v1.list_namespaced_daemon_set(
                        namespace=operator_ns,
                        label_selector="app.kubernetes.io/name=spire-spiffe-csi-driver"
                    )
                
                if ds_list.items:
                    ds = ds_list.items[0]
                    desired = ds.status.desired_number_scheduled or 0
                    ready = ds.status.number_ready or 0
                    
                    if desired > 0 and ready >= desired:
                        return {"desired": desired, "ready": ready}
                return None
            except Exception:
                return None
        
        config = PollConfig(
            initial_delay=3.0,
            min_interval=5.0,
            max_interval=15.0,
            backoff_factor=1.3,
            timeout=float(timeout),
            message="SpiffeCSIDriver DaemonSet"
        )
        
        result = _poller.wait_until(check_csi_driver_ready, config=config)
        
        if result.success:
            return self.get(name)
        else:
            raise TimeoutError(f"SpiffeCSIDriver not ready within {timeout}s")


class SpireOIDCDiscoveryManager(BaseCRDManager):
    """Manager for SpireOIDCDiscoveryProvider custom resources."""
    
    KIND = "SpireOIDCDiscoveryProvider"
    
    def create_default(
        self,
        jwt_issuer_endpoint: str,
        name: str = "cluster",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a SpireOIDCDiscoveryProvider with default configuration.
        
        Args:
            jwt_issuer_endpoint: JWT issuer endpoint URL
            name: Resource name (default: "cluster")
            **kwargs: Additional spec fields
        
        Returns:
            Created SpireOIDCDiscoveryProvider
        """
        spec = {
            "jwtIssuer": f"https://{jwt_issuer_endpoint}",
            **kwargs
        }
        
        return self.create(name=name, spec=spec)
    
    def get_oidc_endpoint(self, name: str = "cluster") -> Optional[str]:
        """Get the OIDC discovery endpoint URL."""
        try:
            cr = self.get(name)
            return cr.get("spec", {}).get("jwtIssuer")
        except Exception:
            return None
    
    def wait_for_ready(
        self,
        name: str = "cluster",
        namespace: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for SpireOIDCDiscoveryProvider to be ready using dynamic polling.
        
        Polls with exponential backoff until OIDC Deployment is ready.
        """
        operator_ns = self.settings.openshift.operator_namespace
        
        def check_oidc_ready():
            try:
                # Try different label selectors
                for label in [
                    "app.kubernetes.io/name=spire-oidc",
                    "app.kubernetes.io/name=spire-spiffe-oidc-discovery-provider",
                ]:
                    deployments = self.client.apps_v1.list_namespaced_deployment(
                        namespace=operator_ns,
                        label_selector=label
                    )
                    
                    if deployments.items:
                        dep = deployments.items[0]
                        ready = dep.status.ready_replicas or 0
                        desired = dep.spec.replicas or 1
                        if ready >= desired:
                            return dep.metadata.name
                
                # Try finding by name pattern
                all_deps = self.client.apps_v1.list_namespaced_deployment(namespace=operator_ns)
                for dep in all_deps.items:
                    if "oidc" in dep.metadata.name.lower():
                        ready = dep.status.ready_replicas or 0
                        desired = dep.spec.replicas or 1
                        if ready >= desired:
                            return dep.metadata.name
                
                return None
            except Exception:
                return None
        
        config = PollConfig(
            initial_delay=3.0,
            min_interval=5.0,
            max_interval=15.0,
            backoff_factor=1.3,
            timeout=float(timeout),
            message="SpireOIDCDiscoveryProvider Deployment"
        )
        
        result = _poller.wait_until(check_oidc_ready, config=config)
        
        if result.success:
            return self.get(name)
        else:
            raise TimeoutError(f"SpireOIDCDiscoveryProvider not ready within {timeout}s")


class ZTWIMInstallationVerifier:
    """
    Helper class to verify ZTWIM installation.
    
    Verifies the following resources are ready:
    - spire-server (StatefulSet)
    - spire-agent (DaemonSet)
    - spire-spiffe-csi-driver (DaemonSet)
    - spire-spiffe-oidc-discovery-provider (Deployment)
    """
    
    NAMESPACE = "zero-trust-workload-identity-manager"
    
    # Resource names (exact names from the operator)
    SPIRE_SERVER_STATEFULSET = "spire-server"
    SPIRE_AGENT_DAEMONSET = "spire-agent"
    CSI_DRIVER_DAEMONSET = "spire-spiffe-csi-driver"
    OIDC_DEPLOYMENT = "spire-spiffe-oidc-discovery-provider"
    
    def __init__(self, ocp_client: "OCPClient"):
        self.client = ocp_client
        self.settings = get_settings()
    
    def verify_spire_server(self, timeout: int = 120) -> bool:
        """
        Verify SpireServer StatefulSet is ready.
        
        Equivalent to: oc rollout status statefulset/spire-server -n zero-trust-workload-identity-manager --timeout=2m
        """
        logger.info(f"Verifying SpireServer StatefulSet: {self.SPIRE_SERVER_STATEFULSET}")
        
        start_time = time.time()
        poll_interval = self.settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                sts = self.client.apps_v1.read_namespaced_stateful_set(
                    name=self.SPIRE_SERVER_STATEFULSET,
                    namespace=self.NAMESPACE
                )
                
                replicas = sts.spec.replicas or 1
                ready_replicas = sts.status.ready_replicas or 0
                
                if ready_replicas >= replicas:
                    logger.info(f"✅ SpireServer ready: {ready_replicas}/{replicas} replicas")
                    return True
                
                logger.debug(f"SpireServer: {ready_replicas}/{replicas} replicas ready...")
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.debug(f"Waiting for SpireServer StatefulSet: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"SpireServer StatefulSet not ready within {timeout}s")
    
    def verify_spire_agent(self, timeout: int = 120) -> bool:
        """
        Verify SpireAgent DaemonSet is ready.
        
        Equivalent to: oc rollout status daemonset/spire-agent -n zero-trust-workload-identity-manager --timeout=2m
        """
        logger.info(f"Verifying SpireAgent DaemonSet: {self.SPIRE_AGENT_DAEMONSET}")
        
        start_time = time.time()
        poll_interval = self.settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                ds = self.client.apps_v1.read_namespaced_daemon_set(
                    name=self.SPIRE_AGENT_DAEMONSET,
                    namespace=self.NAMESPACE
                )
                
                desired = ds.status.desired_number_scheduled or 0
                ready = ds.status.number_ready or 0
                
                if desired > 0 and ready >= desired:
                    logger.info(f"✅ SpireAgent ready: {ready}/{desired} pods on all nodes")
                    return True
                
                logger.debug(f"SpireAgent: {ready}/{desired} pods ready...")
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.debug(f"Waiting for SpireAgent DaemonSet: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"SpireAgent DaemonSet not ready within {timeout}s")
    
    def verify_csi_driver(self, timeout: int = 120) -> bool:
        """
        Verify SpiffeCSIDriver DaemonSet is ready.
        
        Equivalent to: oc rollout status daemonset/spire-spiffe-csi-driver -n zero-trust-workload-identity-manager --timeout=2m
        """
        logger.info(f"Verifying SpiffeCSIDriver DaemonSet: {self.CSI_DRIVER_DAEMONSET}")
        
        start_time = time.time()
        poll_interval = self.settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                ds = self.client.apps_v1.read_namespaced_daemon_set(
                    name=self.CSI_DRIVER_DAEMONSET,
                    namespace=self.NAMESPACE
                )
                
                desired = ds.status.desired_number_scheduled or 0
                ready = ds.status.number_ready or 0
                
                if desired > 0 and ready >= desired:
                    logger.info(f"✅ SpiffeCSIDriver ready: {ready}/{desired} pods on all nodes")
                    return True
                
                logger.debug(f"SpiffeCSIDriver: {ready}/{desired} pods ready...")
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.debug(f"Waiting for SpiffeCSIDriver DaemonSet: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"SpiffeCSIDriver DaemonSet not ready within {timeout}s")
    
    def verify_oidc_provider(self, timeout: int = 120) -> bool:
        """
        Verify SpireOIDCDiscoveryProvider Deployment is ready.
        
        Equivalent to: oc wait --for=condition=Available deployment/spire-spiffe-oidc-discovery-provider -n zero-trust-workload-identity-manager --timeout=2m
        """
        logger.info(f"Verifying OIDC Provider Deployment: {self.OIDC_DEPLOYMENT}")
        
        start_time = time.time()
        poll_interval = self.settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                dep = self.client.apps_v1.read_namespaced_deployment(
                    name=self.OIDC_DEPLOYMENT,
                    namespace=self.NAMESPACE
                )
                
                # Check for Available condition
                conditions = dep.status.conditions or []
                for condition in conditions:
                    if condition.type == "Available" and condition.status == "True":
                        logger.info(f"✅ OIDC Provider ready: Available=True")
                        return True
                
                # Also check replicas
                replicas = dep.spec.replicas or 1
                ready_replicas = dep.status.ready_replicas or 0
                
                if ready_replicas >= replicas:
                    logger.info(f"✅ OIDC Provider ready: {ready_replicas}/{replicas} replicas")
                    return True
                
                logger.debug(f"OIDC Provider: {ready_replicas}/{replicas} replicas, waiting for Available...")
                time.sleep(poll_interval)
                
            except Exception as e:
                logger.debug(f"Waiting for OIDC Provider Deployment: {e}")
                time.sleep(poll_interval)
        
        raise TimeoutError(f"OIDC Provider Deployment not ready within {timeout}s")
    
    def verify_all(self, timeout_per_component: int = 120) -> Dict[str, bool]:
        """
        Verify all ZTWIM components are ready.
        
        Returns:
            Dict with verification results for each component
        """
        logger.info("=" * 60)
        logger.info("VERIFYING ZTWIM STACK INSTALLATION")
        logger.info("=" * 60)
        
        results = {
            "spire_server": False,
            "spire_agent": False,
            "csi_driver": False,
            "oidc_provider": False,
        }
        
        try:
            results["spire_server"] = self.verify_spire_server(timeout=timeout_per_component)
        except TimeoutError as e:
            logger.error(f"❌ SpireServer verification failed: {e}")
            raise
        
        try:
            results["spire_agent"] = self.verify_spire_agent(timeout=timeout_per_component)
        except TimeoutError as e:
            logger.error(f"❌ SpireAgent verification failed: {e}")
            raise
        
        try:
            results["csi_driver"] = self.verify_csi_driver(timeout=timeout_per_component)
        except TimeoutError as e:
            logger.error(f"❌ CSI Driver verification failed: {e}")
            raise
        
        try:
            results["oidc_provider"] = self.verify_oidc_provider(timeout=timeout_per_component)
        except TimeoutError as e:
            logger.error(f"❌ OIDC Provider verification failed: {e}")
            raise
        
        logger.info("=" * 60)
        logger.info("✅ ALL ZTWIM COMPONENTS VERIFIED SUCCESSFULLY")
        logger.info("=" * 60)
        
        return results


class ZTWIMStackDeployer:
    """
    Helper class to deploy the complete ZTWIM stack.
    
    Deploys in order:
    1. ZeroTrustWorkloadIdentityManager
    2. SpireServer
    3. SpireAgent
    4. SpiffeCSIDriver
    5. SpireOIDCDiscoveryProvider
    """
    
    def __init__(self, ocp_client: "OCPClient"):
        self.client = ocp_client
        self.settings = get_settings()
        
        # Initialize managers
        self.ztwim_manager = ZTWIMManager(ocp_client)
        self.server_manager = SpireServerManager(ocp_client)
        self.agent_manager = SpireAgentManager(ocp_client)
        self.csi_manager = SpiffeCSIDriverManager(ocp_client)
        self.oidc_manager = SpireOIDCDiscoveryManager(ocp_client)
        
        # Initialize verifier
        self.verifier = ZTWIMInstallationVerifier(ocp_client)
    
    def get_app_domain(self) -> str:
        """Get the OpenShift apps domain."""
        import os
        
        # Try from environment variable first
        env_domain = os.environ.get("APP_DOMAIN", "")
        if env_domain and not env_domain.startswith("$"):
            return env_domain
        
        # Try from settings (if not an unexpanded variable)
        settings_domain = self.settings.ztwim.app_domain
        if settings_domain and not settings_domain.startswith("$"):
            return settings_domain
        
        # Auto-detect using multiple methods (in order of preference)
        detection_methods = [
            ("DNS config", self._detect_from_dns_config),
            ("Console route", self._detect_from_console_route),
            ("OAuth route", self._detect_from_oauth_route),
            ("Ingress config", self._detect_from_ingress),
            ("API server URL", self._detect_from_api_url),
        ]
        
        for method_name, method in detection_methods:
            try:
                domain = method()
                if domain:
                    logger.info(f"Auto-detected APP_DOMAIN via {method_name}: {domain}")
                    return domain
            except Exception as e:
                logger.debug(f"{method_name} detection failed: {e}")
                continue
        
        raise ValueError(
            "APP_DOMAIN could not be auto-detected. Your user may lack permissions.\n"
            "Please set APP_DOMAIN manually:\n"
            "  export APP_DOMAIN=apps.your-cluster.example.com\n"
            "  pytest tests/ -v\n"
            "Or use CLI option:\n"
            "  pytest tests/ -v --app-domain=apps.your-cluster.example.com"
        )
    
    def _detect_from_dns_config(self) -> Optional[str]:
        """Detect APP_DOMAIN from cluster DNS config (requires cluster-admin)."""
        dns = self.client.custom_objects.get_cluster_custom_object(
            group="config.openshift.io",
            version="v1",
            plural="dnses",
            name="cluster"
        )
        base_domain = dns.get("spec", {}).get("baseDomain", "")
        if base_domain:
            return f"apps.{base_domain}"
        return None
    
    def _detect_from_console_route(self) -> Optional[str]:
        """Detect APP_DOMAIN from OpenShift Console route (works without cluster-admin)."""
        try:
            route = self.client.custom_objects.get_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace="openshift-console",
                plural="routes",
                name="console"
            )
            host = route.get("spec", {}).get("host", "")
            # host is like: console-openshift-console.apps.cluster.example.com
            if host and ".apps." in host:
                # Extract apps.cluster.example.com
                apps_domain = host.split(".apps.", 1)[1]
                return f"apps.{apps_domain}"
            elif host:
                # Try to extract domain pattern
                parts = host.split(".")
                if len(parts) >= 3:
                    # Skip the first part (console-openshift-console)
                    return ".".join(parts[1:]) if parts[0].startswith("console") else None
        except Exception:
            pass
        return None
    
    def _detect_from_oauth_route(self) -> Optional[str]:
        """Detect APP_DOMAIN from OAuth server route."""
        try:
            route = self.client.custom_objects.get_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace="openshift-authentication",
                plural="routes",
                name="oauth-openshift"
            )
            host = route.get("spec", {}).get("host", "")
            # host is like: oauth-openshift.apps.cluster.example.com
            if host and ".apps." in host:
                apps_domain = host.split(".apps.", 1)[1]
                return f"apps.{apps_domain}"
        except Exception:
            pass
        return None
    
    def _detect_from_ingress(self) -> Optional[str]:
        """Detect APP_DOMAIN from Ingress config."""
        try:
            ingress = self.client.custom_objects.get_cluster_custom_object(
                group="config.openshift.io",
                version="v1",
                plural="ingresses",
                name="cluster"
            )
            domain = ingress.get("spec", {}).get("domain", "")
            if domain:
                return domain
        except Exception:
            pass
        return None
    
    def _detect_from_api_url(self) -> Optional[str]:
        """Detect APP_DOMAIN from API server URL in kubeconfig."""
        try:
            # Get the API server URL from the client configuration
            host = self.client.api_client.configuration.host
            # host is like: https://api.cluster.example.com:6443
            if host:
                import re
                match = re.search(r'api\.([^:]+)', host)
                if match:
                    base_domain = match.group(1)
                    return f"apps.{base_domain}"
        except Exception:
            pass
        return None
    
    def get_jwt_issuer_endpoint(self, app_domain: str) -> str:
        """Get JWT issuer endpoint."""
        import os
        
        # Try environment variable first
        env_jwt = os.environ.get("JWT_ISSUER_ENDPOINT", "")
        if env_jwt and not env_jwt.startswith("$"):
            return env_jwt
        
        # Try settings (if not unexpanded)
        settings_jwt = self.settings.ztwim.jwt_issuer_endpoint
        if settings_jwt and not settings_jwt.startswith("$"):
            return settings_jwt
        
        # Derive from app_domain
        return f"oidc-discovery.{app_domain}"
    
    def deploy_all(
        self,
        app_domain: Optional[str] = None,
        cluster_name: Optional[str] = None,
        wait: bool = True,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """
        Deploy the complete ZTWIM stack with proper ordering and waits.
        
        Deployment order with dependencies:
        1. ZeroTrustWorkloadIdentityManager (cluster config)
        2. SpireServer → wait for StatefulSet ready
        3. SpireAgent → wait for DaemonSet ready
        4. SpiffeCSIDriver → wait for CSI driver registration
        5. SpireOIDCDiscoveryProvider (depends on CSI being ready)
        
        Args:
            app_domain: Apps domain (auto-detected if not provided)
            cluster_name: Cluster name (from settings if not provided)
            wait: Wait for all components to be ready
            timeout: Total timeout for deployment
        
        Returns:
            Dict with all created resources
        """
        domain = app_domain or self.get_app_domain()
        name = cluster_name or self.settings.ztwim.cluster_name or "test01"
        jwt_endpoint = self.get_jwt_issuer_endpoint(domain)
        
        logger.info(f"Deploying ZTWIM stack:")
        logger.info(f"  APP_DOMAIN: {domain}")
        logger.info(f"  CLUSTER_NAME: {name}")
        logger.info(f"  JWT_ISSUER: {jwt_endpoint}")
        
        results = {}
        component_timeout = timeout // 5  # Divide timeout among components
        
        # 1. ZeroTrustWorkloadIdentityManager
        logger.info("")
        logger.info("Step 1/5: Creating ZeroTrustWorkloadIdentityManager...")
        results["ztwim"] = self.ztwim_manager.create_cluster(
            trust_domain=domain,
            cluster_name=name
        )
        logger.info("✅ ZeroTrustWorkloadIdentityManager CR created")
        time.sleep(_settings.polling.component_verify.interval)
        
        # 2. SpireServer - MUST be ready before SpireAgent
        logger.info("")
        logger.info("Step 2/5: Creating SpireServer...")
        results["spire_server"] = self.server_manager.create_default(
            app_domain=domain,
            jwt_issuer_endpoint=jwt_endpoint,
            trust_domain=domain,
            cluster_name=name,
        )
        logger.info("✅ SpireServer CR created")
        
        if wait:
            logger.info("⏳ Waiting for SpireServer StatefulSet to be ready...")
            self._wait_for_spire_server_ready(timeout=component_timeout)
        
        # 3. SpireAgent - depends on SpireServer
        logger.info("")
        logger.info("Step 3/5: Creating SpireAgent...")
        results["spire_agent"] = self.agent_manager.create_default()
        logger.info("✅ SpireAgent CR created")
        
        if wait:
            logger.info("⏳ Waiting for SpireAgent DaemonSet to be ready...")
            self._wait_for_spire_agent_ready(timeout=component_timeout)
        
        # 4. SpiffeCSIDriver - MUST register before OIDC
        logger.info("")
        logger.info("Step 4/5: Creating SpiffeCSIDriver...")
        results["csi_driver"] = self.csi_manager.create_default()
        logger.info("✅ SpiffeCSIDriver CR created")
        
        if wait:
            logger.info("⏳ Waiting for CSI Driver to register (csi.spiffe.io)...")
            self._wait_for_csi_driver_registered(timeout=component_timeout)
        
        # 5. SpireOIDCDiscoveryProvider - depends on CSI being registered
        logger.info("")
        logger.info("Step 5/5: Creating SpireOIDCDiscoveryProvider...")
        results["oidc"] = self.oidc_manager.create_default(
            jwt_issuer_endpoint=jwt_endpoint
        )
        logger.info("✅ SpireOIDCDiscoveryProvider CR created")
        
        if wait:
            logger.info("⏳ Waiting for OIDC Discovery Provider to be ready...")
            self.verifier.verify_oidc_provider(timeout=component_timeout)
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ ALL ZTWIM COMPONENTS DEPLOYED AND READY!")
            logger.info("=" * 60)
        
        return results
    
    def _wait_for_spire_server_ready(self, timeout: int = 120) -> bool:
        """Wait for SpireServer StatefulSet to be ready."""
        start_time = time.time()
        poll_interval = _settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                sts = self.client.apps_v1.read_namespaced_stateful_set(
                    name="spire-server",
                    namespace=OperatorInstaller.OPERATOR_NAMESPACE
                )
                replicas = sts.spec.replicas or 1
                ready_replicas = sts.status.ready_replicas or 0
                
                if ready_replicas >= replicas:
                    logger.info(f"✅ SpireServer ready: {ready_replicas}/{replicas} replicas")
                    return True
                
                logger.debug(f"SpireServer: {ready_replicas}/{replicas} replicas ready")
            except Exception as e:
                logger.debug(f"Waiting for SpireServer StatefulSet: {e}")
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"SpireServer not ready within {timeout}s")
    
    def _wait_for_spire_agent_ready(self, timeout: int = 120) -> bool:
        """Wait for SpireAgent DaemonSet to be ready."""
        start_time = time.time()
        poll_interval = _settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                ds = self.client.apps_v1.read_namespaced_daemon_set(
                    name="spire-agent",
                    namespace=OperatorInstaller.OPERATOR_NAMESPACE
                )
                desired = ds.status.desired_number_scheduled or 1
                ready = ds.status.number_ready or 0
                
                if ready >= desired:
                    logger.info(f"✅ SpireAgent ready: {ready}/{desired} pods")
                    return True
                
                logger.debug(f"SpireAgent: {ready}/{desired} pods ready")
            except Exception as e:
                logger.debug(f"Waiting for SpireAgent DaemonSet: {e}")
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"SpireAgent not ready within {timeout}s")
    
    def _wait_for_csi_driver_registered(self, timeout: int = 120) -> bool:
        """
        Wait for CSI Driver to be registered in the cluster.
        
        The OIDC Discovery Provider needs the csi.spiffe.io driver to be
        registered before it can mount SPIFFE workload API volumes.
        """
        start_time = time.time()
        poll_interval = _settings.polling.component_verify.interval
        
        while time.time() - start_time < timeout:
            try:
                # Check if CSI driver is registered cluster-wide
                csi_drivers = self.client.api_client.call_api(
                    '/apis/storage.k8s.io/v1/csidrivers/csi.spiffe.io',
                    'GET',
                    auth_settings=['BearerToken'],
                    response_type='object',
                    _return_http_data_only=True
                )
                
                if csi_drivers:
                    logger.info("✅ CSI Driver registered: csi.spiffe.io")
                    time.sleep(poll_interval)
                    return True
                    
            except Exception as e:
                # CSI driver not yet registered
                logger.debug(f"Waiting for CSI driver registration: {e}")
            
            # Also check DaemonSet pods
            try:
                ds = self.client.apps_v1.read_namespaced_daemon_set(
                    name="spiffe-csi-driver",
                    namespace=OperatorInstaller.OPERATOR_NAMESPACE
                )
                desired = ds.status.desired_number_scheduled or 1
                ready = ds.status.number_ready or 0
                
                if ready >= desired and ready > 0:
                    logger.info(f"✅ CSI Driver DaemonSet ready: {ready}/{desired} pods")
                    time.sleep(poll_interval * 2)
                    return True
                
                logger.debug(f"CSI Driver: {ready}/{desired} pods ready")
            except Exception as e:
                logger.debug(f"Waiting for CSI Driver DaemonSet: {e}")
            
            time.sleep(poll_interval)
        
        raise TimeoutError(
            f"CSI Driver (csi.spiffe.io) not registered within {timeout}s. "
            "OIDC Discovery Provider cannot start without CSI driver."
        )
    
    def is_deployed(self) -> bool:
        """
        Check if ZTWIM stack is deployed.
        
        Checks:
        1. Operator namespace exists and is not terminating
        2. ZeroTrustWorkloadIdentityManager CR exists
        3. At least one operand component is running
        """
        try:
            # Check namespace exists and is Active
            ns = self.client.core_v1.read_namespace(
                name=OperatorInstaller.OPERATOR_NAMESPACE
            )
            if ns.status.phase != "Active":
                logger.debug(f"Namespace exists but phase is: {ns.status.phase}")
                return False
            
            # Check ZTWIM CR exists
            self.ztwim_manager.get("cluster")
            
            # Check at least one workload exists (StatefulSet or DaemonSet)
            sts = self.client.apps_v1.list_namespaced_stateful_set(
                namespace=OperatorInstaller.OPERATOR_NAMESPACE
            )
            ds = self.client.apps_v1.list_namespaced_daemon_set(
                namespace=OperatorInstaller.OPERATOR_NAMESPACE
            )
            
            if not sts.items and not ds.items:
                logger.debug("No StatefulSets or DaemonSets found")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"is_deployed check failed: {e}")
            return False
    
    def is_operator_installed(self) -> bool:
        """Check if ZTWIM operator is installed (subscription exists)."""
        try:
            subs = self.client.custom_objects.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=OperatorInstaller.OPERATOR_NAMESPACE,
                plural="subscriptions"
            )
            return len(subs.get("items", [])) > 0
        except Exception:
            return False
    
    def delete_all_operands(self, wait_for_pods: bool = True, force_delete_pods: bool = True) -> None:
        """
        Delete all ZTWIM operand CRs and wait for pods to terminate.
        
        Deletes in reverse order:
        1. SpireOIDCDiscoveryProvider
        2. SpiffeCSIDriver
        3. SpireAgent
        4. SpireServer
        5. ZeroTrustWorkloadIdentityManager
        
        Args:
            wait_for_pods: Wait for all pods to terminate after deleting CRs
            force_delete_pods: Force delete any stuck pods
        """
        logger.info("-" * 50)
        logger.info("DELETING ZTWIM OPERANDS")
        logger.info("-" * 50)
        
        operands = [
            ("SpireOIDCDiscoveryProvider", self.oidc_manager),
            ("SpiffeCSIDriver", self.csi_manager),
            ("SpireAgent", self.agent_manager),
            ("SpireServer", self.server_manager),
            ("ZeroTrustWorkloadIdentityManager", self.ztwim_manager),
        ]
        
        for name, manager in operands:
            try:
                logger.info(f"Deleting {name} 'cluster'...")
                manager.delete("cluster")
                logger.info(f"✅ {name} deleted")
            except Exception as e:
                logger.debug(f"{name} not found or already deleted: {e}")
        
        if wait_for_pods:
            logger.info("")
            logger.info("⏳ Waiting for operand pods to terminate...")
            self._wait_for_pods_terminated(timeout=120, force_delete=force_delete_pods)
        
        logger.info("✅ All operands deleted")
    
    def _wait_for_pods_terminated(self, timeout: int = 120, force_delete: bool = True) -> None:
        """
        Wait for all operand pods to terminate.
        
        Args:
            timeout: How long to wait before force deleting
            force_delete: Force delete pods if they don't terminate in time
        """
        namespace = OperatorInstaller.OPERATOR_NAMESPACE
        start_time = time.time()
        poll_interval = _settings.polling.cleanup.interval
        
        # Pod label selectors for operand components
        operand_labels = [
            "app.kubernetes.io/name=spiffe-oidc-discovery-provider",
            "app.kubernetes.io/name=spiffe-csi-driver",
            "app.kubernetes.io/name=spire-agent",
            "app.kubernetes.io/name=spire-server",
        ]
        
        while time.time() - start_time < timeout:
            try:
                # Get all pods in namespace
                pods = self.client.core_v1.list_namespaced_pod(namespace=namespace)
                
                # Filter for operand pods (not operator pod)
                operand_pods = [
                    p for p in pods.items 
                    if p.metadata.labels and any(
                        p.metadata.labels.get("app.kubernetes.io/name", "") in label
                        for label in ["spiffe-oidc-discovery-provider", "spiffe-csi-driver", "spire-agent", "spire-server"]
                    )
                ]
                
                if not operand_pods:
                    logger.info("✅ All operand pods terminated")
                    return
                
                pod_names = [p.metadata.name for p in operand_pods]
                logger.debug(f"Waiting for {len(operand_pods)} pods to terminate: {pod_names[:3]}...")
                
            except Exception as e:
                # Namespace might be gone
                logger.debug(f"Error checking pods: {e}")
                return
            
            time.sleep(poll_interval)
        
        # Timeout reached - force delete if enabled
        if force_delete:
            logger.warning(f"Pods didn't terminate within {timeout}s, force deleting...")
            self._force_delete_operand_pods(namespace)
        else:
            logger.warning(f"Pods didn't terminate within {timeout}s")
    
    def _force_delete_operand_pods(self, namespace: str) -> None:
        """Force delete all operand pods."""
        from kubernetes.client import V1DeleteOptions
        
        try:
            pods = self.client.core_v1.list_namespaced_pod(namespace=namespace)
            
            for pod in pods.items:
                # Skip operator pod
                pod_name = pod.metadata.labels.get("app.kubernetes.io/name", "")
                if pod_name in ["spiffe-oidc-discovery-provider", "spiffe-csi-driver", "spire-agent", "spire-server"]:
                    try:
                        logger.info(f"Force deleting pod: {pod.metadata.name}")
                        self.client.core_v1.delete_namespaced_pod(
                            name=pod.metadata.name,
                            namespace=namespace,
                            body=V1DeleteOptions(grace_period_seconds=0),
                            grace_period_seconds=0
                        )
                    except Exception as e:
                        logger.debug(f"Failed to force delete {pod.metadata.name}: {e}")
            
            # Give a moment for deletions to process
            time.sleep(_settings.polling.cleanup.interval)
            logger.info("✅ Force deleted stuck pods")
            
        except Exception as e:
            logger.debug(f"Error force deleting pods: {e}")


class ZTWIMFullInstaller:
    """
    Complete ZTWIM installation manager.
    
    Handles full installation flow:
    1. Create Namespace
    2. Create OperatorGroup
    3. Create Subscription
    4. Wait for Operator ready
    5. Create ZeroTrustWorkloadIdentityManager
    6. Create SpireServer
    7. Create SpireAgent
    8. Create SpiffeCSIDriver
    9. Create SpireOIDCDiscoveryProvider
    10. Verify all components
    """
    
    def __init__(self, ocp_client: "OCPClient"):
        self.client = ocp_client
        self.settings = get_settings()
        
        self.operator_installer = OperatorInstaller(ocp_client)
        self.stack_deployer = ZTWIMStackDeployer(ocp_client)
        self.verifier = ZTWIMInstallationVerifier(ocp_client)
    
    def install_and_verify(
        self,
        app_domain: Optional[str] = None,
        cluster_name: Optional[str] = None,
        catalog_name: Optional[str] = None,
        channel: Optional[str] = None,
        skip_if_exists: bool = True,
        operator_timeout: int = 300,
        component_timeout: int = 120,
    ) -> Dict[str, Any]:
        """
        Perform complete ZTWIM installation and verification.
        
        Args:
            app_domain: OpenShift apps domain (auto-detected if not set)
            cluster_name: Cluster name (default: test01)
            catalog_name: OLM catalog source (default: redhat-operators)
            channel: OLM channel (default: stable-v1)
            skip_if_exists: Skip installation if already deployed
            operator_timeout: Timeout for operator installation
            component_timeout: Timeout per component verification
        
        Returns:
            Dict with installation results
        """
        results = {
            "operator_installed": False,
            "operator_ready": False,
            "operands_deployed": False,
            "verification_passed": False,
            "app_domain": None,
            "cluster_name": None,
        }
        
        logger.info("=" * 70)
        logger.info("ZTWIM FULL INSTALLATION AND VERIFICATION")
        logger.info("=" * 70)
        
        # Check if already deployed
        if skip_if_exists and self.stack_deployer.is_deployed():
            logger.info("✅ ZTWIM stack already deployed, skipping installation")
            results["operator_installed"] = True
            results["operator_ready"] = True
            results["operands_deployed"] = True
            
            # Still verify
            logger.info("Verifying existing installation...")
            self.verifier.verify_all(timeout_per_component=component_timeout)
            results["verification_passed"] = True
            
            return results
        
        # Get domain and cluster name
        domain = app_domain or self.stack_deployer.get_app_domain()
        name = cluster_name or self.settings.ztwim.cluster_name or "test01"
        jwt_endpoint = self.stack_deployer.get_jwt_issuer_endpoint(domain)
        
        results["app_domain"] = domain
        results["cluster_name"] = name
        
        logger.info(f"Configuration:")
        logger.info(f"  APP_DOMAIN: {domain}")
        logger.info(f"  CLUSTER_NAME: {name}")
        logger.info(f"  JWT_ISSUER: {jwt_endpoint}")
        logger.info("")
        
        # PHASE 1: Install Operator
        logger.info("-" * 50)
        logger.info("PHASE 1: Installing ZTWIM Operator via OLM")
        logger.info("-" * 50)
        
        if not self.stack_deployer.is_operator_installed():
            self.operator_installer.install(
                catalog_name=catalog_name,
                channel=channel
            )
            results["operator_installed"] = True
            logger.info("✅ Operator subscription created")
        else:
            logger.info("✅ Operator already installed")
            results["operator_installed"] = True
        
        # Wait for operator to be ready
        logger.info("Waiting for operator deployment to be ready...")
        self.operator_installer.wait_for_operator_ready(timeout=operator_timeout)
        results["operator_ready"] = True
        logger.info("✅ Operator deployment is ready")
        
        # PHASE 2: Deploy Operands
        logger.info("")
        logger.info("-" * 50)
        logger.info("PHASE 2: Deploying ZTWIM Operands")
        logger.info("-" * 50)
        
        if not self.stack_deployer.is_deployed():
            self.stack_deployer.deploy_all(
                app_domain=domain,
                cluster_name=name,
                wait=False  # We'll verify separately
            )
            results["operands_deployed"] = True
            logger.info("✅ All operand CRs created")
        else:
            logger.info("✅ Operands already deployed")
            results["operands_deployed"] = True
        
        # PHASE 3: Verify Installation
        logger.info("")
        logger.info("-" * 50)
        logger.info("PHASE 3: Verifying Installation")
        logger.info("-" * 50)
        
        self.verifier.verify_all(timeout_per_component=component_timeout)
        results["verification_passed"] = True
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("✅ ZTWIM INSTALLATION AND VERIFICATION COMPLETE")
        logger.info("=" * 70)
        
        return results
    
    def uninstall_all(self, timeout: int = 180, force_cleanup: bool = True) -> None:
        """
        Completely uninstall ZTWIM stack.
        
        Deletes in order:
        1. All Operand CRs (SpireOIDCDiscoveryProvider, SpiffeCSIDriver, SpireAgent, SpireServer, ZeroTrustWorkloadIdentityManager)
        2. Wait for operand pods to terminate (with force delete if stuck)
        3. Subscription
        4. ClusterServiceVersion (CSV)
        5. OperatorGroup
        6. Namespace
        
        Args:
            timeout: Timeout for namespace deletion
            force_cleanup: Force delete stuck pods
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("ZTWIM COMPLETE UNINSTALLATION")
        logger.info("=" * 70)
        logger.info("")
        
        # PHASE 1: Delete Operands
        logger.info("-" * 50)
        logger.info("PHASE 1: Deleting Operand CRs and waiting for pods")
        logger.info("-" * 50)
        
        # Delete operand CRs and wait for pods to terminate
        self.stack_deployer.delete_all_operands(
            wait_for_pods=True,
            force_delete_pods=force_cleanup
        )
        
        # PHASE 2: Clean up any remaining resources (PVCs, secrets, etc.)
        logger.info("")
        logger.info("-" * 50)
        logger.info("PHASE 2: Cleaning up remaining resources")
        logger.info("-" * 50)
        self._cleanup_remaining_resources()
        
        # PHASE 3: Delete Operator
        logger.info("")
        logger.info("-" * 50)
        logger.info("PHASE 3: Deleting Operator")
        logger.info("-" * 50)
        self.operator_installer.uninstall(timeout=timeout)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("✅ ZTWIM COMPLETE UNINSTALLATION FINISHED")
        logger.info("=" * 70)
    
    def _cleanup_remaining_resources(self) -> None:
        """Clean up PVCs and other resources that might block reinstall."""
        namespace = OperatorInstaller.OPERATOR_NAMESPACE
        
        try:
            # Delete PVCs (SpireServer uses PVC)
            pvcs = self.client.core_v1.list_namespaced_persistent_volume_claim(
                namespace=namespace
            )
            for pvc in pvcs.items:
                try:
                    logger.info(f"Deleting PVC: {pvc.metadata.name}")
                    self.client.core_v1.delete_namespaced_persistent_volume_claim(
                        name=pvc.metadata.name,
                        namespace=namespace
                    )
                except Exception as e:
                    logger.debug(f"Failed to delete PVC {pvc.metadata.name}: {e}")
            
            if pvcs.items:
                logger.info(f"✅ Deleted {len(pvcs.items)} PVCs")
                time.sleep(_settings.polling.cleanup.interval)
                
        except Exception as e:
            logger.debug(f"Error cleaning up resources: {e}")
        logger.info("")
