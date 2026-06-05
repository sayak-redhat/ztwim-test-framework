"""
Cross-cluster OSSM + SPIRE federation helper.

OSSMFederationHelper composes two OSSMHelper instances (one per cluster)
and adds federation-specific methods for SPIRE bundle exchange, Istio
multi-cluster configuration, east-west gateways, and workload deployment
with SPIRE injection.
"""

import ast
import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from kubernetes.client import ApiException

from src.ocp_client.client import OCPClient
from src.helpers.ossm import OSSMHelper
from src.utils.logger import get_logger
from src.utils.polling import wait_until

logger = get_logger("ossm.federation.helper")

SPIRE_SERVER_POD_LABEL = "app.kubernetes.io/name=spire-server"
ZTWIM_API_VERSION = "operator.openshift.io/v1alpha1"
FEDERATION_ROUTE_NAME = "spire-server-federation"
SPIFFE_API_VERSION = "spire.spiffe.io/v1alpha1"
SPIRE_CLASS_NAME = "zero-trust-workload-identity-manager-spire"


class OSSMFederationHelper:
    """
    Encapsulates cross-cluster OSSM + SPIRE federation operations.

    Composes two OSSMHelper instances (one per cluster) and adds
    federation-specific methods for SPIRE bundle exchange, Istio
    multi-cluster configuration, east-west gateways, and workload
    deployment with SPIRE injection.
    """

    _SPIRE_SERVER_BIN_CANDIDATES = [
        "/spire-server",
        "/opt/spire/bin/spire-server",
    ]

    def __init__(
        self,
        local_client: OCPClient,
        remote_client: OCPClient,
        operator_namespace: str,
        local_ossm: OSSMHelper,
        remote_ossm: OSSMHelper,
        local_app_domain: str,
        remote_app_domain: str,
        local_trust_domain: str,
        remote_trust_domain: str,
        local_kubeconfig: str,
        remote_kubeconfig: str,
        ossm_namespace: str,
        workload_namespace: str,
        nofed_namespace: str,
        local_cluster_name: str,
        remote_cluster_name: str,
    ):
        self.local = local_client
        self.remote = remote_client
        self.operator_ns = operator_namespace
        self.local_ossm = local_ossm
        self.remote_ossm = remote_ossm
        self.local_app_domain = local_app_domain
        self.remote_app_domain = remote_app_domain
        self.local_trust_domain = local_trust_domain
        self.remote_trust_domain = remote_trust_domain
        self.local_kubeconfig = local_kubeconfig
        self.remote_kubeconfig = remote_kubeconfig
        self.ossm_namespace = ossm_namespace
        self.workload_ns = workload_namespace
        self.nofed_ns = nofed_namespace
        self.local_cluster_name = local_cluster_name
        self.remote_cluster_name = remote_cluster_name
        self._spire_bin_cache: Dict[int, str] = {}

    # ── SPIRE binary auto-detection ─────────────────────────────────────

    def _get_spire_server_bin(self, client: OCPClient) -> str:
        cache_key = id(client)
        if cache_key in self._spire_bin_cache:
            return self._spire_bin_cache[cache_key]

        pods = client.get_pods(namespace=self.operator_ns, label_selector=SPIRE_SERVER_POD_LABEL)
        if not pods:
            raise RuntimeError("No spire-server pods found")

        pod_name = pods[0]["metadata"]["name"]
        for candidate in self._SPIRE_SERVER_BIN_CANDIDATES:
            try:
                output = client.exec_in_pod(
                    name=pod_name, namespace=self.operator_ns,
                    command=[candidate, "--help"], container="spire-server",
                )
                if "not found" not in (output or ""):
                    logger.info(f"Detected spire-server binary: {candidate}")
                    self._spire_bin_cache[cache_key] = candidate
                    return candidate
            except Exception:
                continue

        fallback = self._SPIRE_SERVER_BIN_CANDIDATES[0]
        logger.warning(f"Could not detect spire-server binary, falling back to {fallback}")
        self._spire_bin_cache[cache_key] = fallback
        return fallback

    # ── SPIRE Federation ────────────────────────────────────────────────

    def enable_federation_on_spire_server(
        self, client: OCPClient, remote_trust_domain: str, remote_app_domain: str,
    ) -> Dict[str, Any]:
        """Patch SpireServer CR to enable https_spiffe federation."""
        federation_spec = {
            "spec": {
                "federation": {
                    "bundleEndpoint": {"profile": "https_spiffe"},
                    "managedRoute": "true",
                    "federatesWith": [{
                        "trustDomain": remote_trust_domain,
                        "bundleEndpointUrl": f"https://federation.{remote_app_domain}",
                        "bundleEndpointProfile": "https_spiffe",
                        "endpointSpiffeId": f"spiffe://{remote_trust_domain}/spire/server",
                    }],
                }
            }
        }
        result = client.patch_custom_resource(
            api_version=ZTWIM_API_VERSION,
            kind="SpireServer",
            name="cluster",
            namespace="",
            body=federation_spec,
        )
        logger.info(f"Enabled federation on SpireServer (remote: {remote_trust_domain})")
        return result

    def wait_for_federation_route(self, client: OCPClient, timeout: int = 120) -> Dict:
        """Wait for the federation route to be created and admitted."""
        def _check():
            route = client.get_route(FEDERATION_ROUTE_NAME, self.operator_ns)
            if route:
                ingress = route.get("status", {}).get("ingress", [])
                if ingress:
                    return route
            return None

        result = wait_until(_check, message="Federation route ready", timeout=timeout, interval=5)
        if not result.success:
            raise TimeoutError(f"Federation route not ready within {timeout}s")
        return result.value

    def get_federation_endpoint(self, client: OCPClient) -> str:
        route = client.get_route(FEDERATION_ROUTE_NAME, self.operator_ns)
        if not route:
            raise RuntimeError("Federation route not found")
        return f"https://{route['spec']['host']}"

    def seed_remote_bundle(self, client: OCPClient, remote_fed_url: str) -> None:
        """Fetch remote bundle via curl and seed it into local SPIRE server.

        Pipes curl output directly into ``bundle set`` via a shell command
        so we don't need stdin support on the exec API.
        """
        spire_bin = self._get_spire_server_bin(client)
        pods = client.get_pods(namespace=self.operator_ns, label_selector=SPIRE_SERVER_POD_LABEL)
        if not pods:
            raise RuntimeError("No spire-server pods found")
        pod_name = pods[0]["metadata"]["name"]
        td = self._trust_domain_from_url(remote_fed_url)

        client.exec_in_pod_with_retry(
            name=pod_name, namespace=self.operator_ns,
            command=[
                "/bin/sh", "-c",
                f"curl -sk {remote_fed_url}/bundle | "
                f"{spire_bin} bundle set -format spiffe "
                f"-socketPath /tmp/spire-server/private/api.sock "
                f"-id spiffe://{td}",
            ],
            container="spire-server",
        )
        logger.info(f"Seeded remote bundle from {remote_fed_url}")

    @staticmethod
    def _trust_domain_from_url(fed_url: str) -> str:
        host = fed_url.replace("https://", "").replace("http://", "").split("/")[0]
        return host.replace("federation.", "")

    def verify_bundle_exchange(self, client: OCPClient, expected_remote_domain: str) -> bool:
        """Check that the remote trust domain appears in SPIRE bundle list."""
        spire_bin = self._get_spire_server_bin(client)
        pods = client.get_pods(namespace=self.operator_ns, label_selector=SPIRE_SERVER_POD_LABEL)
        pod_name = pods[0]["metadata"]["name"]
        output = client.exec_in_pod_with_retry(
            name=pod_name, namespace=self.operator_ns,
            command=[spire_bin, "bundle", "list",
                     "-socketPath", "/tmp/spire-server/private/api.sock",
                     "-format", "spiffe"],
            container="spire-server",
        )
        return expected_remote_domain in output

    def get_sds_config(self, client: OCPClient) -> Optional[Dict]:
        """Read SDS section from spire-agent ConfigMap on given cluster."""
        cm = client.core_v1.read_namespaced_config_map(
            name="spire-agent", namespace=self.operator_ns,
        )
        agent_conf_raw = cm.data.get("agent.conf", "")
        agent_conf = json.loads(agent_conf_raw)
        return agent_conf.get("agent", {}).get("sds")

    # ── Istio CR with federation fields ─────────────────────────────────

    def deploy_istio_cr_with_federation(
        self,
        client: OCPClient,
        ossm_helper: OSSMHelper,
        local_trust_domain: str,
        remote_trust_domain: str,
        local_fed_url: str,
        remote_fed_url: str,
        cluster_name: str,
        network_name: str,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Deploy Istio CR with multi-cluster federation fields."""
        client.create_namespace(name=self.ossm_namespace)
        extra_root_ca = ossm_helper.get_oidc_serving_cert()

        body = {
            "apiVersion": "sailoperator.io/v1",
            "kind": "Istio",
            "metadata": {"name": "default"},
            "spec": {
                "version": ossm_helper.config.sail_version,
                "namespace": self.ossm_namespace,
                "updateStrategy": {"type": "InPlace"},
                "values": {
                    "pilot": {
                        "jwksResolverExtraRootCA": extra_root_ca,
                        "env": {"PILOT_JWT_ENABLE_REMOTE_JWKS": "true"},
                    },
                    "meshConfig": {
                        "trustDomain": local_trust_domain,
                        "trustDomainAliases": [remote_trust_domain],
                        "defaultConfig": {
                            "proxyMetadata": {
                                "WORKLOAD_IDENTITY_SOCKET_FILE": "spire-agent.sock",
                            },
                        },
                        "caCertificates": [
                            {"spiffeBundleUrl": f"{local_fed_url}/bundle"},
                            {"spiffeBundleUrl": f"{remote_fed_url}/bundle"},
                        ],
                    },
                    "global": {
                        "meshID": "mesh1",
                        "multiCluster": {"clusterName": cluster_name},
                        "network": network_name,
                    },
                    "sidecarInjectorWebhook": {
                        "templates": {
                            "spire": (
                                "spec:\n"
                                "  initContainers:\n"
                                "  - name: istio-proxy\n"
                                "    volumeMounts:\n"
                                "    - name: workload-socket\n"
                                "      mountPath: /run/secrets/workload-spiffe-uds\n"
                                "      readOnly: true\n"
                                "  volumes:\n"
                                "    - name: workload-socket\n"
                                "      csi:\n"
                                '        driver: "csi.spiffe.io"\n'
                                "        readOnly: true\n"
                            ),
                            "spireGateway": (
                                "spec:\n"
                                "  containers:\n"
                                "  - name: istio-proxy\n"
                                "    volumeMounts:\n"
                                "    - name: workload-socket\n"
                                "      mountPath: /run/secrets/workload-spiffe-uds\n"
                                "      readOnly: true\n"
                                "  volumes:\n"
                                "    - name: workload-socket\n"
                                "      csi:\n"
                                '        driver: "csi.spiffe.io"\n'
                                "        readOnly: true\n"
                            ),
                        },
                    },
                },
            },
        }

        try:
            resource = client.get_crd_resource("sailoperator.io/v1", "Istio")
            try:
                resource.get(name="default")
                result = resource.patch(
                    name="default", body=body,
                    content_type="application/merge-patch+json",
                )
                logger.info(f"Patched Istio CR with federation config (cluster={cluster_name})")
                return result.to_dict()
            except ApiException as e:
                if e.status == 404:
                    result = resource.create(body=body)
                    logger.info(f"Created Istio CR with federation config (cluster={cluster_name})")
                    return result.to_dict()
                raise
        except Exception as e:
            raise RuntimeError(f"Failed to deploy federated Istio CR: {e}")

    # ── East-West Gateway ───────────────────────────────────────────────

    def deploy_ew_gateway(self, client: OCPClient, network_name: str, kubeconfig: str) -> None:
        """Deploy east-west gateway via helm with SPIRE injection."""
        subprocess.run(
            ["oc", "--kubeconfig", kubeconfig, "adm", "policy", "add-scc-to-user",
             "anyuid", f"system:serviceaccount:{self.ossm_namespace}:istio-eastwestgateway"],
            check=False, capture_output=True,
        )
        subprocess.run(["helm", "repo", "add", "istio",
                        "https://istio-release.storage.googleapis.com/charts"],
                       check=False, capture_output=True)
        subprocess.run(["helm", "repo", "update"], check=False, capture_output=True)

        result = subprocess.run(
            ["helm", "upgrade", "--install", "istio-eastwestgateway",
             "-n", self.ossm_namespace,
             "istio/gateway",
             "--kubeconfig", kubeconfig,
             "--set", f"networkGateway={network_name}",
             "--set-json",
             '{"podAnnotations":{"inject.istio.io/templates":"gateway,spireGateway"}}',
             "--set", "service.ports[0].name=status-port",
             "--set", "service.ports[0].port=15021",
             "--set", "service.ports[0].targetPort=15021",
             "--set", "service.ports[1].name=tls",
             "--set", "service.ports[1].port=15443",
             "--set", "service.ports[1].targetPort=15443",
             "--set", "service.ports[2].name=tls-istiod",
             "--set", "service.ports[2].port=15012",
             "--set", "service.ports[2].targetPort=15012",
             "--set", "service.ports[3].name=tls-webhook",
             "--set", "service.ports[3].port=15017",
             "--set", "service.ports[3].targetPort=15017",
             ],
            capture_output=True, text=True,
        )
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(f"EW gateway helm install failed: {result.stderr}")
        logger.info(f"Deployed east-west gateway (network={network_name})")

    def delete_ew_gateway(self, kubeconfig: str) -> None:
        subprocess.run(
            ["helm", "uninstall", "istio-eastwestgateway",
             "-n", self.ossm_namespace, "--kubeconfig", kubeconfig],
            check=False, capture_output=True,
        )

    def deploy_cross_network_gateway(self, client: OCPClient, namespace: str) -> None:
        """Create a Gateway resource for AUTO_PASSTHROUGH on port 15443."""
        body = {
            "apiVersion": "networking.istio.io/v1",
            "kind": "Gateway",
            "metadata": {"name": "cross-network-gateway", "namespace": namespace},
            "spec": {
                "selector": {"istio": "eastwestgateway"},
                "servers": [{
                    "port": {"number": 15443, "name": "tls", "protocol": "TLS"},
                    "tls": {"mode": "AUTO_PASSTHROUGH"},
                    "hosts": ["*.local"],
                }],
            },
        }
        resource = client.get_crd_resource("networking.istio.io/v1", "Gateway")
        try:
            resource.create(body=body, namespace=namespace)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Created cross-network gateway in {namespace}")

    # ── Remote secrets ──────────────────────────────────────────────────

    def create_and_apply_remote_secret(
        self, source_kubeconfig: str, source_cluster_name: str,
        target_client: OCPClient, target_kubeconfig: str,
    ) -> None:
        """Generate remote secret from source and apply to target cluster."""
        if not shutil.which("istioctl"):
            raise RuntimeError("istioctl not found in PATH")

        result = subprocess.run(
            ["istioctl", "create-remote-secret",
             "--kubeconfig", source_kubeconfig,
             "--name", source_cluster_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"istioctl create-remote-secret failed: {result.stderr}")

        secret_yaml = result.stdout
        apply_result = subprocess.run(
            ["kubectl", "--kubeconfig", target_kubeconfig,
             "apply", "-f", "-"],
            input=secret_yaml, capture_output=True, text=True,
        )
        if apply_result.returncode != 0:
            raise RuntimeError(f"Failed to apply remote secret: {apply_result.stderr}")
        logger.info(f"Applied remote secret for {source_cluster_name}")

    # ── Workload deployment ─────────────────────────────────────────────

    def deploy_helloworld(
        self, client: OCPClient, namespace: str, version: str = "v1",
    ) -> None:
        """Deploy helloworld with SPIRE sidecar injection."""
        client.create_namespace(name=namespace, labels={"istio-injection": "enabled"})

        svc_body = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "helloworld", "namespace": namespace,
                         "labels": {"app": "helloworld", "service": "helloworld"}},
            "spec": {
                "ports": [{"port": 5000, "name": "http", "targetPort": 5000}],
                "selector": {"app": "helloworld"},
            },
        }
        try:
            client.core_v1.create_namespaced_service(namespace=namespace, body=svc_body)
        except ApiException as e:
            if e.status != 409:
                raise

        deploy_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": f"helloworld-{version}", "namespace": namespace,
                         "labels": {"app": "helloworld", "version": version}},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "helloworld", "version": version}},
                "template": {
                    "metadata": {
                        "annotations": {"inject.istio.io/templates": "sidecar,spire"},
                        "labels": {"app": "helloworld", "version": version},
                    },
                    "spec": {
                        "containers": [{
                            "name": "helloworld",
                            "image": "docker.io/istio/examples-helloworld-v1",
                            "imagePullPolicy": "IfNotPresent",
                            "ports": [{"containerPort": 5000}],
                            "env": [{"name": "SERVICE_VERSION", "value": version}],
                        }],
                    },
                },
            },
        }
        try:
            client.apps_v1.create_namespaced_deployment(namespace=namespace, body=deploy_body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Deployed helloworld-{version} in {namespace}")

    def deploy_sleep(self, client: OCPClient, namespace: str, name: str = "sleep") -> None:
        """Deploy sleep workload with SPIRE sidecar injection."""
        client.create_namespace(name=namespace, labels={"istio-injection": "enabled"})

        deploy_body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": namespace,
                         "labels": {"app": name}},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {
                        "annotations": {"inject.istio.io/templates": "sidecar,spire"},
                        "labels": {"app": name},
                    },
                    "spec": {
                        "terminationGracePeriodSeconds": 0,
                        "containers": [{
                            "name": "sleep",
                            "image": "curlimages/curl:8.16.0",
                            "command": ["/bin/sh", "-c", "sleep inf"],
                            "imagePullPolicy": "IfNotPresent",
                        }],
                    },
                },
            },
        }
        try:
            client.apps_v1.create_namespaced_deployment(namespace=namespace, body=deploy_body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Deployed {name} in {namespace}")

    # ── ClusterSPIFFEID management ──────────────────────────────────────

    def create_federated_cluster_spiffeid(
        self, client: OCPClient, name: str, namespace: str, remote_trust_domain: str,
    ) -> None:
        """Create a ClusterSPIFFEID with federatesWith for the remote trust domain."""
        body = {
            "apiVersion": SPIFFE_API_VERSION,
            "kind": "ClusterSPIFFEID",
            "metadata": {"name": name},
            "spec": {
                "className": SPIRE_CLASS_NAME,
                "spiffeIDTemplate": (
                    "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}"
                    "/sa/{{ .PodSpec.ServiceAccountName }}"
                ),
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": namespace},
                },
                "podSelector": {},
                "federatesWith": [remote_trust_domain],
            },
        }
        resource = client.get_crd_resource(SPIFFE_API_VERSION, "ClusterSPIFFEID")
        try:
            resource.create(body=body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Created federated ClusterSPIFFEID {name} (federatesWith: {remote_trust_domain})")

    def create_unfederated_cluster_spiffeid(
        self, client: OCPClient, name: str, namespace: str,
    ) -> None:
        """Create a ClusterSPIFFEID WITHOUT federatesWith (negative test)."""
        body = {
            "apiVersion": SPIFFE_API_VERSION,
            "kind": "ClusterSPIFFEID",
            "metadata": {"name": name},
            "spec": {
                "className": SPIRE_CLASS_NAME,
                "spiffeIDTemplate": (
                    "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}"
                    "/sa/{{ .PodSpec.ServiceAccountName }}"
                ),
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": namespace},
                },
                "podSelector": {},
            },
        }
        resource = client.get_crd_resource(SPIFFE_API_VERSION, "ClusterSPIFFEID")
        try:
            resource.create(body=body)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Created unfederated ClusterSPIFFEID {name} (no federatesWith)")

    # ── Verification helpers ────────────────────────────────────────────

    @staticmethod
    def _parse_exec_json(output: str) -> Any:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return ast.literal_eval(output)

    def exec_curl(
        self, client: OCPClient, source_deploy: str, namespace: str, target_url: str,
    ) -> str:
        """Curl from a pod, return the response body."""
        pods = client.get_pods(namespace=namespace, label_selector=f"app={source_deploy}")
        if not pods:
            raise RuntimeError(f"No pods found for app={source_deploy} in {namespace}")
        pod_name = pods[0]["metadata"]["name"]
        return client.exec_in_pod_with_retry(
            name=pod_name, namespace=namespace,
            command=["curl", "-s", target_url],
            container="sleep",
        )

    def exec_curl_status(
        self, client: OCPClient, source_deploy: str, namespace: str, target_url: str,
    ) -> str:
        """Curl from a pod, return HTTP status code only."""
        pods = client.get_pods(namespace=namespace, label_selector=f"app={source_deploy}")
        if not pods:
            raise RuntimeError(f"No pods found for app={source_deploy} in {namespace}")
        pod_name = pods[0]["metadata"]["name"]
        return client.exec_in_pod_with_retry(
            name=pod_name, namespace=namespace,
            command=["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", target_url],
            container="sleep",
        )

    def exec_curl_multi(
        self, client: OCPClient, source_deploy: str, namespace: str,
        target_url: str, count: int = 10,
    ) -> List[str]:
        """Repeat curl N times, return list of response bodies."""
        results = []
        for _ in range(count):
            try:
                body = self.exec_curl(client, source_deploy, namespace, target_url)
                results.append(body)
            except Exception:
                results.append("")
        return results

    def get_workload_spiffe_id(
        self, client: OCPClient, deploy_label: str, namespace: str,
    ) -> str:
        """Get the SPIFFE ID from a workload's Envoy sidecar."""
        pods = client.get_pods(namespace=namespace, label_selector=f"app={deploy_label}")
        if not pods:
            raise RuntimeError(f"No pods for app={deploy_label}")
        pod_name = pods[0]["metadata"]["name"]
        output = client.exec_in_pod_with_retry(
            name=pod_name, namespace=namespace,
            command=["curl", "-s", "localhost:15000/certs"],
            container="istio-proxy",
        )
        certs = self._parse_exec_json(output)
        return certs["certificates"][0]["cert_chain"][0]["subject_alt_names"][0]["uri"]

    def get_workload_cert_issuer(
        self, client: OCPClient, deploy_label: str, namespace: str,
    ) -> str:
        """Parse cert issuer organization from Envoy admin API."""
        pods = client.get_pods(namespace=namespace, label_selector=f"app={deploy_label}")
        if not pods:
            raise RuntimeError(f"No pods for app={deploy_label}")
        pod_name = pods[0]["metadata"]["name"]

        output = client.exec_in_pod_with_retry(
            name=pod_name, namespace=namespace,
            command=["curl", "-s", "localhost:15000/certs"],
            container="istio-proxy",
        )
        certs = self._parse_exec_json(output)
        cert_chain = certs["certificates"][0]["cert_chain"]
        for cert in cert_chain:
            subject = cert.get("subject", "")
            if "O=" in subject:
                org_start = subject.index("O=") + 2
                org_end = subject.find(",", org_start)
                return subject[org_start:org_end] if org_end != -1 else subject[org_start:]
        return "unknown"

    def apply_strict_mtls(self, client: OCPClient, namespace: str) -> None:
        """Apply PeerAuthentication STRICT on the given cluster/namespace."""
        pa_body = {
            "apiVersion": "security.istio.io/v1beta1",
            "kind": "PeerAuthentication",
            "metadata": {"name": "default", "namespace": namespace},
            "spec": {"mtls": {"mode": "STRICT"}},
        }
        resource = client.get_crd_resource("security.istio.io/v1beta1", "PeerAuthentication")
        try:
            resource.create(body=pa_body, namespace=namespace)
        except ApiException as e:
            if e.status != 409:
                raise
        logger.info(f"Applied STRICT PeerAuthentication in {namespace}")

    @staticmethod
    def verify_cross_cluster_load_balancing(
        responses: List[str], expected_versions: List[str],
    ) -> bool:
        """Assert responses contain a mix of expected version strings."""
        found = {v: False for v in expected_versions}
        for resp in responses:
            for v in expected_versions:
                if v in resp:
                    found[v] = True
        return all(found.values())
