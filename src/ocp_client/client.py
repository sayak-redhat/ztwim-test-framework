"""OpenShift/Kubernetes client wrapper for ZTWIM Test Framework.

This module provides a unified client for interacting with OpenShift clusters,
including support for ZTWIM CRDs and common Kubernetes operations.
"""

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.dynamic import DynamicClient
from kubernetes.dynamic.resource import Resource, ResourceInstance

from src.utils.config import get_settings, set_kubeconfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OCPClient:
    """
    OpenShift/Kubernetes client wrapper.
    
    Provides methods for common cluster operations and CRD management.
    Automatically sets KUBECONFIG from provided path or environment.
    """
    
    def __init__(self, kubeconfig_path: Optional[str] = None):
        """
        Initialize the OpenShift client.
        
        Args:
            kubeconfig_path: Path to kubeconfig file. If not provided,
                           uses KUBECONFIG env var or ~/.kube/config
        """
        self.kubeconfig_path = set_kubeconfig(kubeconfig_path)
        self.settings = get_settings()
        
        # Load kubernetes configuration
        try:
            config.load_kube_config(config_file=self.kubeconfig_path)
            logger.info(f"Loaded kubeconfig from: {self.kubeconfig_path}")
        except Exception as e:
            logger.warning(f"Failed to load kubeconfig, trying in-cluster config: {e}")
            config.load_incluster_config()
            logger.info("Loaded in-cluster configuration")
        
        # Initialize clients
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.custom_objects = client.CustomObjectsApi()
        self.custom_objects_api = self.custom_objects  # alias for compatibility
        self.apiextensions_v1 = client.ApiextensionsV1Api()
        self.api_client = client.ApiClient()
        self.dynamic_client = DynamicClient(self.api_client)
        
        # Cache for CRD resources
        self._resource_cache: Dict[str, Resource] = {}
    
    def get_cluster_info(self) -> Dict[str, Any]:
        """Get basic cluster information."""
        try:
            version_info = client.VersionApi().get_code()
            return {
                "git_version": version_info.git_version,
                "platform": version_info.platform,
                "go_version": version_info.go_version,
            }
        except ApiException as e:
            logger.error(f"Failed to get cluster info: {e}")
            raise
    
    def is_openshift(self) -> bool:
        """Check if the cluster is OpenShift."""
        try:
            # Try to access OpenShift-specific API
            self.dynamic_client.resources.get(
                api_version="route.openshift.io/v1",
                kind="Route"
            )
            return True
        except Exception:
            return False
    
    # ==================== Namespace Operations ====================
    
    def create_namespace(self, name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Create a namespace.
        
        Args:
            name: Namespace name
            labels: Optional labels to apply
        
        Returns:
            Created namespace object
        """
        body = client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=name,
                labels=labels or {}
            )
        )
        
        try:
            ns = self.core_v1.create_namespace(body=body)
            logger.info(f"Created namespace: {name}")
            return ns.to_dict()
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.info(f"Namespace already exists: {name}")
                return self.get_namespace(name)
            raise
    
    def get_namespace(self, name: str) -> Dict[str, Any]:
        """Get namespace by name."""
        ns = self.core_v1.read_namespace(name=name)
        return ns.to_dict()
    
    def delete_namespace(self, name: str, wait: bool = True, timeout: int = 300) -> None:
        """
        Delete a namespace.
        
        Args:
            name: Namespace name
            wait: Wait for deletion to complete
            timeout: Timeout in seconds
        """
        try:
            self.core_v1.delete_namespace(name=name)
            logger.info(f"Deleting namespace: {name}")
            
            if wait:
                self.wait_for_namespace_deletion(name, timeout)
        except ApiException as e:
            if e.status == 404:
                logger.info(f"Namespace already deleted: {name}")
            else:
                raise
    
    def wait_for_namespace_deletion(self, name: str, timeout: int = 300) -> None:
        """Wait for namespace to be fully deleted."""
        start_time = time.time()
        poll_interval = self.settings.testing.poll_interval
        
        while time.time() - start_time < timeout:
            try:
                self.core_v1.read_namespace(name=name)
                logger.debug(f"Waiting for namespace {name} deletion...")
                time.sleep(poll_interval)
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"Namespace {name} deleted successfully")
                    return
                raise
        
        raise TimeoutError(f"Namespace {name} not deleted within {timeout}s")
    
    # ==================== Pod Operations ====================
    
    def get_pods(
        self, 
        namespace: str, 
        label_selector: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get pods in a namespace.
        
        Args:
            namespace: Namespace name
            label_selector: Optional label selector (e.g., "app=spire-server")
        
        Returns:
            List of pod objects
        """
        pods = self.core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector
        )
        return [pod.to_dict() for pod in pods.items]
    
    def wait_for_pods_ready(
        self,
        namespace: str,
        label_selector: str,
        expected_count: int = 1,
        timeout: int = None
    ) -> List[Dict[str, Any]]:
        """
        Wait for pods matching selector to be ready.
        
        Args:
            namespace: Namespace name
            label_selector: Label selector
            expected_count: Expected number of ready pods
            timeout: Timeout in seconds (defaults to settings.polling.pod_readiness.timeout)
        
        Returns:
            List of ready pod objects
        """
        if timeout is None:
            timeout = int(self.settings.polling.pod_readiness.timeout)
        poll_interval = self.settings.polling.pod_readiness.interval
        
        start_time = time.time()
        ready_pods = []
        
        while time.time() - start_time < timeout:
            pods = self.get_pods(namespace, label_selector)
            ready_pods = [
                p for p in pods
                if self._is_pod_ready(p)
            ]
            
            if len(ready_pods) >= expected_count:
                logger.info(f"Found {len(ready_pods)} ready pods for {label_selector}")
                return ready_pods
            
            logger.debug(
                f"Waiting for pods ({len(ready_pods)}/{expected_count} ready): "
                f"{label_selector}"
            )
            time.sleep(poll_interval)
        
        raise TimeoutError(
            f"Pods not ready within {timeout}s: {label_selector} "
            f"(expected {expected_count}, got {len(ready_pods)})"
        )
    
    def _is_pod_ready(self, pod: Dict[str, Any]) -> bool:
        """Check if a pod is ready."""
        conditions = pod.get("status", {}).get("conditions") or []
        for condition in conditions:
            if condition.get("type") == "Ready" and condition.get("status") == "True":
                return True
        return False
    
    def get_pod_logs(
        self,
        name: str,
        namespace: str,
        container: Optional[str] = None,
        tail_lines: int = 100
    ) -> str:
        """Get pod logs."""
        return self.core_v1.read_namespaced_pod_log(
            name=name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines
        )
    
    def exec_in_pod(
        self,
        name: str,
        namespace: str,
        command: List[str],
        container: Optional[str] = None
    ) -> str:
        """
        Execute a command in a pod.
        
        Args:
            name: Pod name
            namespace: Namespace
            command: Command to execute
            container: Container name (optional)
        
        Returns:
            Command output
        """
        from kubernetes.stream import stream
        
        resp = stream(
            self.core_v1.connect_get_namespaced_pod_exec,
            name,
            namespace,
            command=command,
            container=container,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False
        )
        return resp

    def exec_in_pod_with_retry(
        self,
        name: str,
        namespace: str,
        command: List[str],
        container: Optional[str] = None
    ) -> str:
        """
        Execute a command in a pod with configurable retry logic.

        Retries on transient errors (container not found, 500 status) using
        settings from config/settings.yaml -> polling.exec_retry.

        Args:
            name: Pod name
            namespace: Namespace
            command: Command to execute
            container: Container name (optional)

        Returns:
            Command output
        """
        from src.utils.polling import retry_on_error

        cfg = self.settings.polling.exec_retry
        logger.debug(
            f"exec_in_pod_with_retry: pod={name}, container={container}, "
            f"max_attempts={cfg.max_attempts}, interval={cfg.interval}s"
        )

        try:
            from websocket import WebSocketBadStatusException
            retryable_exceptions = (WebSocketBadStatusException, ApiException, RuntimeError)
        except ImportError:
            retryable_exceptions = (ApiException, RuntimeError)

        return retry_on_error(
            func=lambda: self.exec_in_pod(name, namespace, command, container),
            max_attempts=cfg.max_attempts,
            delay=cfg.interval,
            backoff=cfg.backoff_factor,
            exceptions=retryable_exceptions,
        )
    
    # ==================== CRD Operations ====================
    
    def get_crd_resource(self, api_version: str, kind: str) -> Resource:
        """
        Get a dynamic resource for a CRD.
        
        Args:
            api_version: API version (e.g., "spire.spiffe.io/v1alpha1")
            kind: Kind name (e.g., "SpireServer")
        
        Returns:
            Dynamic resource object
        """
        cache_key = f"{api_version}/{kind}"
        
        if cache_key not in self._resource_cache:
            self._resource_cache[cache_key] = self.dynamic_client.resources.get(
                api_version=api_version,
                kind=kind
            )
        
        return self._resource_cache[cache_key]
    
    def create_custom_resource(
        self,
        api_version: str,
        kind: str,
        namespace: str,
        body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a custom resource.
        
        Args:
            api_version: API version
            kind: Kind name
            namespace: Namespace
            body: Resource body
        
        Returns:
            Created resource
        """
        resource = self.get_crd_resource(api_version, kind)
        result = resource.create(body=body, namespace=namespace)
        logger.info(f"Created {kind}: {body['metadata']['name']}")
        return result.to_dict()
    
    def get_custom_resource(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str
    ) -> Dict[str, Any]:
        """Get a custom resource by name."""
        resource = self.get_crd_resource(api_version, kind)
        result = resource.get(name=name, namespace=namespace)
        return result.to_dict()
    
    def patch_custom_resource(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str,
        body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Patch a custom resource."""
        resource = self.get_crd_resource(api_version, kind)
        result = resource.patch(
            name=name,
            namespace=namespace,
            body=body,
            content_type="application/merge-patch+json"
        )
        logger.info(f"Patched {kind}: {name}")
        return result.to_dict()
    
    def delete_custom_resource(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str
    ) -> None:
        """Delete a custom resource."""
        resource = self.get_crd_resource(api_version, kind)
        resource.delete(name=name, namespace=namespace)
        logger.info(f"Deleted {kind}: {name}")
    
    def wait_for_custom_resource_condition(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str,
        condition_type: str,
        expected_status: str = "True",
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for a custom resource to reach a specific condition.
        
        Args:
            api_version: API version
            kind: Kind name
            name: Resource name
            namespace: Namespace
            condition_type: Condition type to check (e.g., "Available")
            expected_status: Expected status value
            timeout: Timeout in seconds
        
        Returns:
            Resource when condition is met
        """
        start_time = time.time()
        poll_interval = self.settings.testing.poll_interval
        
        while time.time() - start_time < timeout:
            cr = self.get_custom_resource(api_version, kind, name, namespace)
            conditions = cr.get("status", {}).get("conditions", [])
            
            for condition in conditions:
                if (condition.get("type") == condition_type and 
                    condition.get("status") == expected_status):
                    logger.info(f"{kind}/{name} condition {condition_type}={expected_status}")
                    return cr
            
            logger.debug(f"Waiting for {kind}/{name} condition: {condition_type}")
            time.sleep(poll_interval)
        
        raise TimeoutError(
            f"{kind}/{name} did not reach condition {condition_type}={expected_status} "
            f"within {timeout}s"
        )
    
    # ==================== Service/Route Operations ====================
    
    def get_service(self, name: str, namespace: str) -> Dict[str, Any]:
        """Get a service by name."""
        svc = self.core_v1.read_namespaced_service(name=name, namespace=namespace)
        return svc.to_dict()
    
    def get_route(self, name: str, namespace: str) -> Optional[Dict[str, Any]]:
        """Get an OpenShift route by name (returns None if not OpenShift)."""
        if not self.is_openshift():
            return None
        
        try:
            resource = self.get_crd_resource("route.openshift.io/v1", "Route")
            result = resource.get(name=name, namespace=namespace)
            return result.to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise


@lru_cache
def get_ocp_client(kubeconfig_path: Optional[str] = None) -> OCPClient:
    """
    Get a cached OCP client instance.
    
    Args:
        kubeconfig_path: Path to kubeconfig file
    
    Returns:
        OCPClient instance
    """
    return OCPClient(kubeconfig_path)
