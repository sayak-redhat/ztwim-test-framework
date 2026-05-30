# ZTWIM Federation Test Framework

Federation-focused pytest framework for validating SPIRE federation (mTLS workload identity) across two OpenShift clusters using the **Zero Trust Workload Identity Manager** operator.

---

## What This Framework Tests

- SpireServer federation configuration (`https_spiffe` profile)
- Federation route readiness and endpoint exposure
- Trust bundle exchange via `ClusterFederatedTrustDomain`
- mTLS workload identity provisioning (SVID certificates)
- Cross-cluster mTLS handshake validation

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Two OpenShift 4.18+ clusters | With cluster-admin access on both |
| ZTWIM operator installed | On both clusters (for `operator-only` mode) |
| Network connectivity | Federation routes must be accessible between clusters |
| Python 3.10+ | With pip available |
| `oc` CLI | Logged in to both clusters (for manual verification) |

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

The framework includes multiple test files under `tests/federation/`. Running `pytest tests/federation/` collects **all** of them, but some suites require additional configuration and will be skipped automatically if it is missing.

#### Available test suites

| Test File | Marker | Description | Extra Config Required |
|-----------|--------|-------------|----------------------|
| `test_https_spiffe_federation.py` | `@pytest.mark.federation` | Standard `https_spiffe` federation with mTLS validation | None (runs by default) |

#### Run all tests (default)

```bash
pytest tests/federation/ -v \
  --deployment-mode=operator-only \
  --keep-deployed \
  --remote-kubeconfig=/path/to/remote/kubeconfig
```

#### Run only the standard https_spiffe federation tests

```bash
pytest tests/federation/test_https_spiffe_federation.py -v \
  --deployment-mode=operator-only \
  --keep-deployed \
  --remote-kubeconfig=/path/to/remote/kubeconfig
```

#### Run a single test class or method

```bash
# A specific test class
pytest "tests/federation/test_https_spiffe_federation.py::TestCrossClusterMTLS" -v \
  --deployment-mode=operator-only --keep-deployed \
  --remote-kubeconfig=/path/to/remote/kubeconfig

```

#### Run tests by marker

```bash
# Only federation-marked tests (default for all tests under tests/federation/)
pytest tests/federation/ -v -m federation
```

### Full CLI Reference

```bash
pytest tests/federation/ -v \
  --kubeconfig=<path>              # Local cluster kubeconfig
  --remote-kubeconfig=<path>       # Remote cluster kubeconfig
  --deployment-mode=operator-only  # operator-only | bootstrap
  --keep-deployed                  # Keep operands after tests
  --app-domain=<domain>            # Override local apps domain
  --remote-app-domain=<domain>     # Override remote apps domain
  --cluster-name=<name>            # ZTWIM cluster name (default: test01)
  --federation-profile=https_spiffe  # Federation profile
  --federation-timeout=300         # Bundle sync timeout (seconds)
  --mtls-timeout=240               # mTLS workload timeout (seconds)
  --operator-timeout=300           # Operator install timeout (seconds)
  --component-timeout=120          # Per-component verify timeout (seconds)
  --skip-cleanup                   # Don't clean up test namespaces
  --cleanup-only-mode              # Only run cleanup, skip tests
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

```
1. Setup Phase
   ├── Connect to both clusters (local + remote)
   ├── Auto-detect app domains from DNS
   ├── Verify operator is ready (operator-only) OR install it (bootstrap)
   └── Deploy operands if missing

2. Prerequisite Checks (Phase 0)
   ├── SpireServer pods ready on both clusters
   ├── SpireAgent pods ready on both clusters
   └── CSI Driver pods ready on both clusters

3. Federation Configuration (Phase 1)
   ├── Patch SpireServers to enable federation
   ├── Verify federation routes are admitted
   └── Fetch trust bundles from both clusters

4. Trust Bootstrap (Phase 2)
   ├── Create ClusterFederatedTrustDomain on both clusters
   └── Wait for bundle sync (remote domain appears in local bundle list)

5. mTLS Workloads (Phase 3)
   ├── Deploy mTLS server on local cluster
   ├── Deploy mTLS client on remote cluster
   ├── Wait for SVID certificates to be provisioned
   └── Verify SPIFFE IDs in certificates

6. Cross-Cluster mTLS (Phase 4)
   └── Validate end-to-end mTLS handshake across clusters

7. Cleanup (Phase 5)
   └── Remove test workloads and federation resources
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
# Development: keep everything for debugging
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --deployment-mode=operator-only \
  --keep-deployed --skip-cleanup

# CI: full cleanup after each run
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --deployment-mode=bootstrap

# Manual cleanup of a stuck/failed run
pytest tests/federation/ -v \
  --kubeconfig=... --remote-kubeconfig=... \
  --cleanup-only-mode

# Clean up operands only (preserve operator) for a specific test file
pytest tests/federation/test_https_spiffe_federation.py \
  --deployment-mode=operator-only \
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
│   ├── ocp_client/
│   │   ├── client.py       # OCPClient (K8s API wrapper)
│   │   └── spire_crds.py   # CRD managers (operator, operands)
│   └── utils/
│       ├── config.py        # Settings model (loads settings.yaml)
│       ├── polling.py       # DynamicPoller, retry_on_error utilities
│       └── logger.py        # Framework logger
├── tests/
│   └── federation/
│       ├── conftest.py      # Fixtures, CLI options, setup/teardown
│       └── test_https_spiffe_federation.py              # Standard https_spiffe federation suite
├── scripts/
│   └── install_ztwim.py     # Standalone installer script
├── test-reports/            # Generated HTML reports
└── requirements.txt         # Python dependencies
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `TimeoutError: Pods not ready within 180s` | Increase `polling.pod_readiness.timeout` in settings.yaml |
| `container not found ("spire-server")` | Framework retries automatically (6x @ 10s). Increase `polling.exec_retry.max_attempts` if needed |
| `No spire-server pods found` | Operator may not have reconciled yet. Check `oc get pods -n zero-trust-workload-identity-manager` |
| `Federation route not ready` | Check `oc get routes -n zero-trust-workload-identity-manager`. Increase `polling.federation.timeout` |
| `Remote trust domain not found in bundle list` | Bundle sync takes time. Increase `polling.federation.timeout` |
