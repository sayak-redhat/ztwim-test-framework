# ZTWIM Test Framework

Pytest framework for validating the **Zero Trust Workload Identity Manager** operator on OpenShift. Covers two areas:

1. **Federation** — Cross-cluster SPIRE federation with mTLS (two clusters)
2. **OSSM Integration** — SPIRE + Istio service mesh on a single cluster

---

## What This Framework Tests

### SPIRE Federation (`tests/federation/test_https_spiffe_federation.py`)

- SpireServer federation configuration (`https_spiffe` profile)
- Federation route readiness and endpoint exposure
- Trust bundle exchange via `ClusterFederatedTrustDomain`
- mTLS workload identity provisioning (SVID certificates)
- Cross-cluster mTLS handshake validation

### OSSM Cross-Cluster Federation (`tests/federation/test_ossm_spire_cross_cluster_federation.py`)

- SDS auto-config without `CREATE_ONLY_MODE` on both clusters
- SPIRE trust bundle exchange via `ClusterFederatedTrustDomain`
- Istio CR with multi-cluster federation fields (trustDomainAliases, spiffeBundleUrl)
- East-west gateway deployment with SPIRE sidecar injection
- Forward and reverse cross-cluster mTLS (sleep A → helloworld B and vice versa)
- STRICT mTLS across all 4 traffic patterns (local + cross-cluster on both clusters)
- SPIRE-issued SPIFFE SVIDs on all workloads (not Istio CA)
- Cross-cluster load balancing (requests hit both v1 and v2)
- Negative test: workload without `federatesWith` fails cross-cluster

### OSSM + SPIRE Integration (`tests/ossm/`)

- Auto-generated SDS config in spire-agent ConfigMap (PR #120)
- SPIRE-issued certificates in Istio sidecars (not Istio CA)
- STRICT mTLS between services using SPIFFE IDs
- Operator reconciliation of SDS config (delete, corrupt, recreate)
- Data plane resilience (spire-agent restart, operator restart)

---

## Prerequisites

### Common

| Requirement | Details |
|-------------|---------|
| Python 3.10+ | With pip available |
| `oc` CLI | Logged in to cluster(s) for manual verification |

### Federation tests (two clusters)

| Requirement | Details |
|-------------|---------|
| Two OpenShift 4.18+ clusters | With cluster-admin access on both |
| ZTWIM operator installed | On both clusters (for `operator-only` mode) |
| Network connectivity | Federation routes must be accessible between clusters |

### OSSM tests (single cluster)

| Requirement | Details |
|-------------|---------|
| One OpenShift 4.18+ cluster | With cluster-admin access |
| ZTWIM operator installed | With PR #120 SDS auto-config support |
| Sail Operator available | In `community-operators` catalog (framework auto-installs it) |

---

## Installation

```bash
git clone <repo-url>
cd ztwim-test-framework
pip install -r requirements.txt
```

---

## Configuration

The framework uses a layered configuration approach:

```
CLI arguments  >  Environment variables  >  config/settings.yaml
(highest priority)                          (lowest priority)
```

### Configuration File

All tunable settings live in `config/settings.yaml`:

```yaml
# Cluster settings
openshift:
  operator_namespace: "zero-trust-workload-identity-manager"

# Operator install settings (used in bootstrap mode)
ztwim:
  catalog_name: "redhat-operators"
  channel: "stable-v1"

# Dynamic polling / retry (tune these if tests timeout)
polling:
  exec_retry:          # Retry for exec-into-pod (container not found)
    max_attempts: 6    #   try up to 6 times
    interval: 10       #   every 10 seconds
    backoff_factor: 1.0

  pod_readiness:       # Pod readiness checks
    timeout: 180       #   wait up to 180s
    interval: 10       #   poll every 10s

  component_verify:    # StatefulSet/DaemonSet/Deployment readiness
    timeout: 120
    interval: 5

  federation:          # Federation route, bundle sync, mTLS
    timeout: 300
    interval: 10
```

You can override any value with environment variables:
```bash
export CLUSTER_NAME="mycluster"
export APP_DOMAIN="apps.mycluster.example.com"
```

---

## Running Tests

Federation tests require access to **two clusters**. You provide paths to both kubeconfig files.

### Cluster Credentials

**Option A: Pass as CLI arguments**

```bash
pytest tests/federation/ -v \
  --kubeconfig=~/Downloads/cluster1.kubeconfig \
  --remote-kubeconfig=~/Downloads/cluster2.kubeconfig \
  --deployment-mode=operator-only \
  --keep-deployed
```

**Option B: Export as environment variables**

```bash
export KUBECONFIG=/home/sayadas/POC/Cluster1/aws/auth/kubeconfig
export REMOTE_KUBECONFIG=/home/sayadas/POC/Cluster2/aws/auth/kubeconfig

pytest tests/federation/ -v \
  --deployment-mode=operator-only \
  --keep-deployed
```

**Option C: Mix both (env var for local, CLI for remote)**

```bash
export KUBECONFIG=/path/to/cluster1.kubeconfig

pytest tests/federation/ -v \
  --remote-kubeconfig=/path/to/cluster2.kubeconfig \
  --deployment-mode=operator-only
```

**Priority order**: CLI argument > environment variable > config/settings.yaml

| Cluster | CLI flag | Environment variable |
|---------|----------|---------------------|
| Local (first) | `--kubeconfig=<path>` | `export KUBECONFIG=<path>` |
| Remote (second) | `--remote-kubeconfig=<path>` | `export REMOTE_KUBECONFIG=<path>` |

### Deployment Modes

| Mode | When to use | What it does |
|------|-------------|--------------|
| `operator-only` | Operator already installed on both clusters | Verifies operator is present, deploys/repairs operands, runs tests |
| `bootstrap` | Fresh clusters with nothing installed | Installs operator + all operands from scratch, then runs tests |

### App Domain (auto-detected)

The framework auto-detects each cluster's apps domain from the DNS configuration. To override:

```bash
pytest tests/federation/ -v \
  --app-domain=apps.cluster1.example.com \
  --remote-app-domain=apps.cluster2.example.com
```

### Running Specific Test Suites

#### Available test suites

| Test Suite | Path | Marker | Clusters | What it validates |
|------------|------|--------|----------|-------------------|
| SPIRE Federation | `tests/federation/test_https_spiffe_federation.py` | `federation` | 2 | Cross-cluster SPIRE federation + raw mTLS |
| OSSM Federation | `tests/federation/test_ossm_spire_cross_cluster_federation.py` | `ossm_federation` | 2 | Cross-cluster OSSM + SPIRE (Istio mesh, EW gateway, SVID, load balancing) |
| OSSM + SPIRE | `tests/ossm/` | `ossm` | 1 | Single-cluster Istio service mesh with SPIRE identities |

#### Run all federation tests (SPIRE + OSSM)

```bash
python -m pytest tests/federation/ -v -s \
  --kubeconfig=/path/to/cluster1/kubeconfig \
  --remote-kubeconfig=/path/to/cluster2/kubeconfig \
  --deployment-mode=operator-only \
  --keep-deployed \
  --ossm-namespace=istio-system
```

#### SPIRE-only federation tests

```bash
python -m pytest tests/federation/test_https_spiffe_federation.py -v -s \
  --kubeconfig=/path/to/cluster1/kubeconfig \
  --remote-kubeconfig=/path/to/cluster2/kubeconfig \
  --deployment-mode=operator-only \
  --keep-deployed
```

#### OSSM cross-cluster federation tests

```bash
python -m pytest tests/federation/test_ossm_spire_cross_cluster_federation.py -v -s \
  --kubeconfig=/path/to/cluster1/kubeconfig \
  --remote-kubeconfig=/path/to/cluster2/kubeconfig \
  --deployment-mode=operator-only \
  --keep-deployed \
  --ossm-namespace=istio-system
```

#### Run a specific test class

```bash
pytest "tests/federation/test_https_spiffe_federation.py::TestCrossClusterMTLS" -v \
  --deployment-mode=operator-only --keep-deployed \
  --remote-kubeconfig=/path/to/remote/kubeconfig
```

#### OSSM tests (single cluster, no remote kubeconfig needed)

```bash
# Run all OSSM tests
pytest tests/ossm/ -v \
  --deployment-mode=operator-only \
  --keep-deployed

# Run a specific phase
pytest "tests/ossm/test_ossm_spire_integration.py::TestIstioMutualWithSpire" -v \
  --deployment-mode=operator-only --keep-deployed
```

The framework auto-installs the **Sail Operator**, **IstioCNI**, and **Istio CR** with SPIRE config. No manual Istio setup needed.

#### Run tests by marker

```bash
pytest tests/federation/ -v -m federation
pytest tests/ossm/ -v -m ossm
```

### Full CLI Reference

#### Common options (both suites)

```bash
  --kubeconfig=<path>              # Cluster kubeconfig
  --deployment-mode=operator-only  # operator-only | bootstrap
  --keep-deployed                  # Keep operands after tests
  --app-domain=<domain>            # Override apps domain
  --cluster-name=<name>            # ZTWIM cluster name (default: test01)
  --operator-timeout=300           # Operator install timeout (seconds)
  --component-timeout=120          # Per-component verify timeout (seconds)
  --skip-cleanup                   # Don't clean up test namespaces
  --cleanup-only-mode              # Only run cleanup, skip tests
```

#### Federation-only options

```bash
  --remote-kubeconfig=<path>       # Remote cluster kubeconfig
  --remote-app-domain=<domain>     # Override remote apps domain
  --federation-profile=https_spiffe  # Federation profile
  --federation-timeout=300         # Bundle sync timeout (seconds)
  --mtls-timeout=240               # mTLS workload timeout (seconds)
```

#### OSSM-only options

```bash
  --ossm-namespace=<ns>            # Istiod namespace (default: istio-system)
  --ossm-cni-namespace=<ns>        # IstioCNI namespace (default: istio-cni)
  --ossm-timeout=300               # OSSM operations timeout (seconds)
  --spiffe-audience=<audience>     # SPIFFE audience annotation (default: sky-computing-demo)
  --httpbin-image=<image>          # httpbin container image
  --curl-image=<image>             # curl client container image
  --sail-channel=<channel>         # Sail Operator OLM channel (default: stable)
  --sail-version=<version>         # Istio/IstioCNI version (default: v1.30-latest)
  --skip-gateway-tests             # Skip ingress gateway tests
```

---

## CI/CD Integration

In CI, kubeconfig files are typically stored as secrets and written to temp paths.

### GitHub Actions Example

```yaml
jobs:
  federation-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Write kubeconfigs from secrets
        run: |
          echo "${{ secrets.CLUSTER1_KUBECONFIG }}" > /tmp/cluster1.kubeconfig
          echo "${{ secrets.CLUSTER2_KUBECONFIG }}" > /tmp/cluster2.kubeconfig

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run federation tests
        run: |
          pytest tests/federation/ -v \
            --kubeconfig=/tmp/cluster1.kubeconfig \
            --remote-kubeconfig=/tmp/cluster2.kubeconfig \
            --deployment-mode=operator-only \
            --keep-deployed \
            --html=test-reports/report.html --self-contained-html

      - name: Run OSSM tests (single cluster)
        run: |
          pytest tests/ossm/ -v \
            --kubeconfig=/tmp/cluster1.kubeconfig \
            --deployment-mode=operator-only \
            --keep-deployed \
            --html=test-reports/ossm-report.html --self-contained-html
```

### OpenShift CI (Prow) Example

```yaml
# ci-operator config snippet
tests:
  - as: federation-e2e
    steps:
      env:
        KUBECONFIG_LOCAL: /tmp/cluster1.kubeconfig
        KUBECONFIG_REMOTE: /tmp/cluster2.kubeconfig
      test:
        - ref: ztwim-federation-test
        # The ref script runs:
        # pytest tests/federation/ -v \
        #   --kubeconfig=$KUBECONFIG_LOCAL \
        #   --remote-kubeconfig=$KUBECONFIG_REMOTE \
        #   --deployment-mode=bootstrap
```

---

## Test Execution Flow

### Federation tests

```
1. Setup — Connect to both clusters, deploy ZTWIM stack
2. Prerequisites — SpireServer, SpireAgent, CSI Driver ready on both
3. Federation Config — Patch SpireServers, verify routes, fetch bundles
4. Trust Bootstrap — Create ClusterFederatedTrustDomain, wait for sync
5. mTLS Workloads — Deploy server (local) + client (remote), verify SVIDs
6. Cross-Cluster mTLS — End-to-end mTLS handshake across clusters
7. Cleanup — Remove test workloads and federation resources
```

### OSSM tests

```
1. Setup — Connect to cluster, deploy ZTWIM stack + Sail Operator + IstioCNI + Istio CR
2. Prerequisites — SpireServer, SpireAgent, Istiod, IstioCNI, SDS config verified
3. SPIRE Cert Verification — Deploy httpbin, confirm SPIRE-issued certs in Envoy sidecars
4. STRICT mTLS — Deploy httpbin + curl, apply STRICT PeerAuthentication, verify traffic
5. Operator Reconciliation — Delete/corrupt SDS config, verify operator self-heals
6. Data Plane Resilience — Restart spire-agent and operator pods, verify mTLS survives
7. Final Health Check — Confirm SPIRE stack + SDS config intact after all tests
```

---

## Tuning Timeouts

If tests fail due to timeouts (slow clusters, cold caches), edit `config/settings.yaml`:

```yaml
polling:
  pod_readiness:
    timeout: 300       # increase from default 180s
    interval: 15       # poll less frequently

  exec_retry:
    max_attempts: 10   # increase from default 6
    interval: 15       # wait longer between retries
```

No code changes needed -- just edit the YAML and rerun.

---

## Cleanup Process (Post-Testing)

The framework has a **3-layer automatic cleanup** after tests complete:

### Layer 1: Federation Resources (per test class)

After each test class finishes, its fixture teardown removes what it created:
- `ClusterFederatedTrustDomain` on both clusters
- `ClusterSPIFFEID` for server and client workloads

### Layer 2: Test Namespaces (module scope)

After all test modules complete:
- Deletes the mTLS server namespace on the local cluster
- Deletes the mTLS client namespace on the remote cluster

### Layer 3: ZTWIM Stack (session scope)

At session end, based on deployment mode:

| Mode | `--keep-deployed` | What happens |
|------|-------------------|--------------|
| `operator-only` | Yes | Nothing removed |
| `operator-only` | No | Operand CRs deleted (SpireServer, Agent, CSI, OIDC). Operator stays. |
| `bootstrap` | Yes | Nothing removed |
| `bootstrap` | No | Full uninstall (operands + operator + namespace) |

### Flags That Control Cleanup

| Flag | Effect | When to use |
|------|--------|-------------|
| `--keep-deployed` | Skips Layer 3. Operator and operands (SpireServer, Agent, CSI, OIDC) remain running on both clusters after tests finish. | You want to **rerun tests quickly** without waiting for operands to redeploy. Or you want to **manually inspect** pods/logs after a run. |
| `--skip-cleanup` | Skips Layers 1 and 2. Federation resources (CFDTs, ClusterSPIFFEIDs) and test namespaces (mTLS server/client pods) are **not deleted**. | You want to **debug federation state** post-test -- e.g., run `oc exec` into spire-server to check bundle list, or inspect mTLS certificates in the running workload pods. |
| `--cleanup-only-mode` | Runs **ONLY** the teardown logic (no tests execute). Deletes federation resources (CFDTs, ClusterSPIFFEIDs), test namespaces, and operands on both clusters. With `--deployment-mode=bootstrap`, also removes the operator. Leaves clusters ready for a **completely fresh rerun**. | A previous test run **failed mid-way** and left resources behind, or you simply want to **wipe everything** before starting fresh. |

**Combining flags:**

```bash
# Keep EVERYTHING (max debugging) -- nothing is removed
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --keep-deployed --skip-cleanup

# Run tests, auto-cleanup federation resources but keep operands
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --keep-deployed

# Wipe clusters clean after a failed run (no tests executed)
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --cleanup-only-mode
```

### Common Scenarios

```bash
# Federation — development (keep everything)
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --deployment-mode=operator-only \
  --keep-deployed --skip-cleanup

# Federation — CI (full cleanup)
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --deployment-mode=bootstrap

# Federation — cleanup stuck/failed run
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --cleanup-only-mode

# OSSM — development (keep Sail + Istio deployed)
pytest tests/ossm/ -v \
  --kubeconfig=... \
  --deployment-mode=operator-only \
  --keep-deployed

# OSSM — cleanup (remove Istio CR, IstioCNI, Sail Operator, test namespaces)
pytest tests/ossm/ -v \
  --kubeconfig=... \
  --cleanup-only-mode
```

---

## Viewing Test Reports

After a test run, HTML reports are generated in `test-reports/`:

```bash
# Latest report
open test-reports/latest/test-report.html

# Timestamped reports
ls test-reports/
# 2026-05-13_11-02-45/
# latest -> 2026-05-13_11-02-45/
```

---

## Project Structure

```text
.
├── config/
│   └── settings.yaml        # All tunable settings (timeouts, polling, etc.)
├── src/
│   ├── helpers/
│   │   ├── ossm.py              # OSSMHelper (Sail/Istio lifecycle)
│   │   └── ossm_federation.py   # OSSMFederationHelper (cross-cluster OSSM + SPIRE)
│   ├── ocp_client/
│   │   ├── client.py            # OCPClient (K8s API wrapper)
│   │   └── spire_crds.py        # CRD managers (operator, operands)
│   └── utils/
│       ├── config.py             # Settings model (loads settings.yaml)
│       ├── polling.py            # DynamicPoller, retry_on_error utilities
│       └── logger.py             # Framework logger
├── tests/
│   ├── federation/
│   │   ├── conftest.py          # Federation fixtures (two-cluster setup, OSSM fixtures)
│   │   ├── test_https_spiffe_federation.py
│   │   └── test_ossm_spire_cross_cluster_federation.py
│   └── ossm/
│       ├── conftest.py          # OSSM fixtures (single-cluster Sail + SPIRE)
│       └── test_ossm_spire_integration.py
├── scripts/
│   └── install_ztwim.py     # Standalone installer script
├── test-reports/            # Generated HTML reports
└── requirements.txt         # Python dependencies
```

---

## Troubleshooting

### Federation

| Symptom | Fix |
|---------|-----|
| `TimeoutError: Pods not ready within 180s` | Increase `polling.pod_readiness.timeout` in settings.yaml |
| `container not found ("spire-server")` | Framework retries automatically (6x @ 10s). Increase `polling.exec_retry.max_attempts` if needed |
| `No spire-server pods found` | Operator may not have reconciled yet. Check `oc get pods -n zero-trust-workload-identity-manager` |
| `Federation route not ready` | Check `oc get routes -n zero-trust-workload-identity-manager`. Increase `polling.federation.timeout` |
| `Remote trust domain not found in bundle list` | Bundle sync takes time. Increase `polling.federation.timeout` |

### OSSM

| Symptom | Fix |
|---------|-----|
| `Sail Operator CSV not ready` | Check `oc get csv -n openshift-operators`. Verify `community-operators` catalog is available |
| `Istiod pod not found` | Istio CR may not have reconciled. Check `oc get istio default -o yaml` for status |
| `SDS section missing from ConfigMap` | Requires ZTWIM operator with PR #120. Check operator version |
| `istio-proxy sidecar not injected` | Ensure namespace has label `istio-injection=enabled` and injection webhook exists |
| `SPIRE-issued certificate not found in Envoy` | SPIRE agent may not have rotated certs yet. Increase `polling.pod_readiness.timeout` |
