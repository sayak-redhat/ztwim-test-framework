# ZTWIM Federation Test Framework

Federation-focused pytest framework for validating SPIRE federation across two OpenShift clusters.

This repository is now optimized for **federation testing only**.

## What This Framework Tests

- SpireServer federation configuration
- Federation route readiness
- Trust bundle exchange with `ClusterFederatedTrustDomain`
- mTLS workload identity flow across clusters
- Cross-cluster mTLS handshake validation

## Scope

Only federation tests are active:

- `tests/federation/`
- Single pytest configuration file: `tests/federation/conftest.py`

Other component test suites were intentionally removed.

## Prerequisites

- Two OpenShift clusters (4.18+ recommended)
- Cluster admin access on both clusters
- Local kubeconfig for cluster A
- Remote kubeconfig for cluster B
- Python 3.10+

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run Federation Tests

### Naming (clear options)

- `--deployment-mode=bootstrap`: install operator + operands on both clusters
- `--deployment-mode=operands-only`: deploy/repair operands only (default)
- `--deployment-mode=existing`: do not install/deploy, only verify
- `--keep-deployed`: keep resources after tests (skip teardown)

### Quick Mode Selector

- If clusters are bare (no operator, no operands), use `--deployment-mode=bootstrap`.
- If operator exists but operands are missing/partial, use `--deployment-mode=operands-only`.
- If everything is already deployed and you only want validation, use `--deployment-mode=existing`.

### Option A: Bare Clusters (no operator, no operands)

```bash
pytest -v \
  --deployment-mode=bootstrap \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2
```

### Option B: Operator installed, operands missing (default path)

```bash
pytest -v \
  --deployment-mode=operands-only \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2
```

### Option C: Everything already deployed

```bash
pytest -v \
  --deployment-mode=existing \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2
```

## Federation Scenario Configuration

The federation suite is configurable via CLI (no test code change needed):

- `--federation-profile` (default: `https_spiffe`)
- `--federation-managed-route` (`true`/`false`)
- `--federation-timeout` (default: `300`)
- `--mtls-timeout` (default: `240`)
- `--mtls-server-image`
- `--mtls-client-image`
- `--spiffe-helper-image`
- `--remote-app-domain` (optional override)

Example:

```bash
pytest -v \
  --deployment-mode=bootstrap \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2 \
  --federation-profile=https_spiffe \
  --federation-managed-route=true \
  --federation-timeout=600 \
  --mtls-timeout=360
```

## Hybrid ACME + cert-manager Scenario (Guide 4.19)

Automated module:

- `tests/federation/test_hybrid_acme_certmanager_federation.py`

This automates the in-cluster configuration from the guide:

- Cluster 1 federation profile as `https_spiffe`
- Cluster 2 federation profile as `https_web` (Let's Encrypt certificate)
- SPIRE datastore remains self-hosted `sqlite3` (default in-cluster datastore)
- Bidirectional `ClusterFederatedTrustDomain` creation and bundle sync checks
- CRDs are loaded by flow from:
  - `fixtures/crds/ztwim/`
  - `fixtures/crds/cert-manager/`
  - `fixtures/crds/sqlite/`

Manual prerequisites still required:

- Public DNS and ingress reachability for ACME HTTP-01 challenge
- Let's Encrypt account email for issuer registration

Set environment variables:

```bash
export HYBRID_LETSENCRYPT_EMAIL="<your-email@example.com>"

# Optional
export HYBRID_CERT_SECRET_NAME="spire-server-federation-tls"
export HYBRID_CERT_MANAGER_TIMEOUT="600"
export HYBRID_INSTALL_CERT_MANAGER="true"   # set true to auto-install cert-manager on remote
```

Run only the hybrid scenario:

```bash
pytest tests/federation/test_hybrid_acme_certmanager_federation.py -v \
  --deployment-mode=operands-only \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2
```

Run by marker:

```bash
pytest -m acme_certmanager -v \
  --deployment-mode=operands-only \
  --keep-deployed \
  --kubeconfig=~/.kube/config-cluster1 \
  --remote-kubeconfig=~/.kube/config-cluster2
```

## Reports and Logs

- HTML report: `test-reports/latest/test-report.html`
- Pytest log file: `logs/pytest.log`
- Console logs are printed during test execution.

Open latest report on Linux:

```bash
xdg-open test-reports/latest/test-report.html
```

## Project Structure

```text
.
├── config/
├── fixtures/
│   └── crds/
│       ├── cert-manager/
│       ├── sqlite/
│       └── ztwim/
├── src/
│   ├── ocp_client/
│   └── utils/
├── tests/
│   ├── __init__.py
│   └── federation/
│       ├── conftest.py
│       ├── test_https_spiffe_federation.py
│       └── test_hybrid_acme_certmanager_federation.py
├── scripts/
│   └── install_ztwim.py
└── README.md
```

## Notes

- Legacy plugin content under `plugins/ztwim-test/` was removed.
