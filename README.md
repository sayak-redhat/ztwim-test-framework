# 🔐 ZTWIM Test Framework

Automated testing framework for **Zero Trust Workload Identity Manager (ZTWIM)** on OpenShift.

---

## 📋 Table of Contents

- [What is This?](#-what-is-this)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Ways to Run Tests](#-ways-to-run-tests)
- [Generate Tests from PR](#-generate-tests-from-pr)
- [Framework Flow](#-framework-flow)
- [Project Structure](#-project-structure)
- [Test Reports & Coverage](#-test-reports--coverage)
- [Writing Tests](#-writing-tests)
- [Troubleshooting](#-troubleshooting)

---

## 🤔 What is This?

This framework automatically tests the **ZTWIM Operator** and its components:

| Component | What it does |
|-----------|--------------|
| **Operator** | Manages all ZTWIM components |
| **SpireServer** | Issues SPIFFE identities |
| **SpireAgent** | Runs on each node, talks to server |
| **CSI Driver** | Mounts SPIFFE credentials into pods |
| **OIDC Discovery** | Provides JWT tokens for workloads |

**The framework handles everything automatically:**
```
Install ZTWIM → Run Tests → Generate Reports → Cleanup
```

---

## ✅ Prerequisites

### 1. Python 3.9+
```bash
python3 --version  # Should be 3.9 or higher
```

### 2. Access to an OpenShift Cluster
```bash
# Login to your cluster
oc login https://api.your-cluster.com:6443

# Verify you're connected
oc whoami
oc get nodes
```

### 3. Install Dependencies
```bash
cd ztwim-test-framework
pip install -r requirements.txt
```

### 4. (Optional) For AI Test Generation
```bash
# Install Claude CLI
npm install -g @anthropic-ai/claude-code

# Login to Claude
claude login
```

---

## 🚀 Quick Start

```bash
# Set your kubeconfig (if not already set)
export KUBECONFIG=~/.kube/config

# Run ALL tests (installs ZTWIM, tests, cleans up)
pytest tests/ -v
```

**That's it!** The framework will:
1. ✅ Install ZTWIM operator
2. ✅ Deploy all components (SpireServer, Agent, CSI, OIDC)
3. ✅ Run all tests
4. ✅ Generate HTML report with coverage
5. ✅ Clean up everything

---

## 🎯 Ways to Run Tests

### Basic Commands

| What you want | Command |
|---------------|---------|
| Run all tests | `pytest tests/ -v` |
| Run without coverage (faster) | `pytest tests/ -v --no-cov` |
| Run specific component | `pytest tests/spire_server/ -v` |
| Run with marker | `pytest tests/ -m spire_agent -v` |

### Installation Control

| Scenario | Command |
|----------|---------|
| **Full cycle** (install → test → cleanup) | `pytest tests/ -v` |
| **Keep ZTWIM** after tests | `pytest tests/ -v --keep-ztwim` |
| **Skip install** (ZTWIM already deployed) | `pytest tests/ -v --skip-install` |
| **Test existing + keep** | `pytest tests/ -v --skip-install --keep-ztwim` |
| **Cleanup only** (delete ZTWIM, no tests) | `pytest tests/ -v --cleanup-only` |

### Run by Component

```bash
# Test only one component
pytest tests/operator/ -v           # Operator tests
pytest tests/spire_server/ -v       # SpireServer tests
pytest tests/spire_agent/ -v        # SpireAgent tests
pytest tests/csi_driver/ -v         # CSI Driver tests
pytest tests/oidc_discovery/ -v     # OIDC tests
```

### Run by Marker

```bash
# Use pytest markers
pytest tests/ -m spire_server -v    # Only @pytest.mark.spire_server
pytest tests/ -m spire_agent -v     # Only @pytest.mark.spire_agent
pytest tests/ -m "not slow" -v      # Skip slow tests
```

### Run Specific Test

```bash
# Run one test file
pytest tests/spire_server/test_spire_server_deployment.py -v

# Run one test class
pytest tests/spire_server/test_spire_server_deployment.py::TestSpireServerDeployment -v

# Run one test method
pytest tests/spire_server/test_spire_server_deployment.py::TestSpireServerDeployment::test_pods_ready -v
```

### CLI Options Reference

| Option | Default | What it does |
|--------|---------|--------------|
| `--kubeconfig PATH` | `$KUBECONFIG` | Path to kubeconfig file |
| `--keep-ztwim` | Off | Don't delete ZTWIM after tests |
| `--skip-install` | Off | Don't install ZTWIM (use existing) |
| `--cleanup-only` | Off | Just delete ZTWIM, skip all tests |
| `--operator-timeout SEC` | 300 | Max time to wait for operator |
| `--component-timeout SEC` | 120 | Max time per component |
| `--no-cov` | Off | Disable coverage (faster) |
| `-v` | Off | Verbose output |
| `-s` | Off | Show print statements |

---

## 🤖 Generate Tests from PR

**Automatically generate test scripts from any GitHub PR!**

### Prerequisites
```bash
# Install Claude CLI (one-time setup)
npm install -g @anthropic-ai/claude-code
claude login
```

### Generate Tests

```bash
# Basic usage - generates for primary component
python scripts/auto_gen.py 72 --use-cli --save

# Generate for ALL affected components
python scripts/auto_gen.py 72 --use-cli --save --all

# Preview what would be generated (dry-run)
python scripts/auto_gen.py 72 --use-cli --dry-run

# Force a specific component
python scripts/auto_gen.py 72 --use-cli --save -c spire_server

# Using full GitHub URL
python scripts/auto_gen.py https://github.com/openshift/zero-trust-workload-identity-manager/pull/72 --use-cli --save
```

### What Happens

```
┌─────────────────────────────────────────────────────────────┐
│  python scripts/auto_gen.py 72 --use-cli --save --all       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Fetches PR #72 from GitHub                              │
│     - Title, description, files changed, code diff          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Analyzes PR to detect:                                  │
│     - PR type (bugfix, feature, refactor, config)           │
│     - Affected components (spire_server, agent, etc.)       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Claude AI generates test code:                          │
│     - Uses framework fixtures                               │
│     - Follows test patterns                                 │
│     - Covers PR changes                                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Saves to correct directory:                             │
│     tests/spire_server/test_pr72_feature_name.py            │
│     tests/spire_agent/test_pr72_feature_name.py             │
│     ...                                                     │
└─────────────────────────────────────────────────────────────┘
```

### Example Output

```
$ python scripts/auto_gen.py 72 --use-cli --save --all

🤖 ZTWIM Robust Test Generator
────────────────────────────────────────────────────────────

📥 Fetching PR details...
   ✓ PR #72: SPIRE-345: Move Common Configuration to ZTWIM CR
   ✓ Type: refactor | Files: 28 | Author: @developer

🎯 Affected components: spire_server, spire_agent, oidc_discovery, operator, csi_driver
   → Generating for ALL 5 components

📦 [1/5] spire_server
   ✓ Generated 20059 chars, 11 tests
   💾 Saved: tests/spire_server/test_pr72_move_common_configuration.py

📦 [2/5] spire_agent
   ✓ Generated 19146 chars, 14 tests
   💾 Saved: tests/spire_agent/test_pr72_move_common_configuration.py

... (continues for all components)

✅ Generation Complete!
   • Files generated: 5
   • Total tests: 73

🧪 Run tests:
   pytest tests/*/test_pr72_*.py -v
```

---

## 🔄 Framework Flow

### How Tests Run (Step by Step)

```
┌────────────────────────────────────────────────────────────────┐
│                    pytest tests/ -v                             │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  STEP 1: Setup (conftest.py)                                   │
│  ─────────────────────────────                                 │
│  • Load kubeconfig                                             │
│  • Connect to OpenShift cluster                                │
│  • Create OCP client                                           │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  STEP 2: Install ZTWIM (unless --skip-install)                 │
│  ─────────────────────────────────────────────                 │
│  • Create namespace: zero-trust-workload-identity-manager      │
│  • Install operator via OperatorHub subscription               │
│  • Wait for operator pod to be ready                           │
│  • Create ZeroTrustWorkloadIdentityManager CR                  │
│  • Create SpireServer, SpireAgent, CSI, OIDC CRs               │
│  • Wait for all components to be ready                         │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  STEP 3: Run Tests                                             │
│  ─────────────────                                             │
│  • Discover all test_*.py files                                │
│  • Run each test class/method                                  │
│  • Each test uses fixtures (ocp_client, spire_server, etc.)    │
│  • Log results (pass/fail/skip)                                │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  STEP 4: Generate Reports                                      │
│  ────────────────────────                                      │
│  • HTML test report (pass/fail details)                        │
│  • Coverage report (which code was tested)                     │
│  • Save to test-reports/<timestamp>/                           │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  STEP 5: Cleanup (unless --keep-ztwim)                         │
│  ─────────────────────────────────────                         │
│  • Delete all ZTWIM CRs                                        │
│  • Delete operator subscription                                │
│  • Delete namespace                                            │
│  • Cluster is clean!                                           │
└────────────────────────────────────────────────────────────────┘
```

### Fixture Hierarchy

```
Session Scope (created once, shared by all tests)
├── ocp_client          → OpenShift API client
├── operator_namespace  → "zero-trust-workload-identity-manager"
├── app_domain          → Auto-detected apps domain
├── cluster_name        → ZTWIM cluster name
└── *_manager           → CRD managers for CRUD operations

Module Scope (created once per test file)
├── spire_server        → Gets SpireServer CR "cluster"
├── spire_agent         → Gets SpireAgent CR "cluster"
├── spiffe_csi_driver   → Gets SpiffeCSIDriver CR "cluster"
├── oidc_provider       → Gets OIDC CR "cluster"
└── test_namespace      → Creates temp namespace, auto-cleanup

Function Scope (created for each test)
├── unique_name         → Random name like "test-a1b2c3d4"
├── wait_timeout        → Default timeout value
└── poll_interval       → Default poll interval
```

---

## 📁 Project Structure

```
ztwim-test-framework/
│
├── conftest.py              # 🔧 All pytest fixtures defined here
│
├── config/
│   └── settings.yaml        # Framework configuration
│
├── src/
│   ├── ocp_client/
│   │   ├── client.py        # OpenShift API client wrapper
│   │   └── spire_crds.py    # CRD managers (create/get/delete)
│   └── utils/
│       ├── logger.py        # Logging utilities
│       ├── config.py        # Configuration loader
│       └── polling.py       # Wait/retry utilities
│
├── tests/
│   ├── operator/            # Operator installation tests
│   ├── spire_server/        # SpireServer tests
│   ├── spire_agent/         # SpireAgent tests
│   ├── csi_driver/          # CSI Driver tests
│   ├── oidc_discovery/      # OIDC Discovery tests
│   └── workload_identity/   # End-to-end tests
│
├── scripts/
│   ├── auto_gen.py          # 🤖 AI test generator
│   ├── ci_run_tests.sh      # CI pipeline script
│   └── install_ztwim.py     # Standalone ZTWIM installer
│
├── test-reports/            # Generated after each run
│   ├── latest/              # Symlink to most recent
│   └── 2025-12-23_10-30-00/ # Timestamped reports
│
├── requirements.txt         # Python dependencies
└── requirements-ai.txt      # AI test generation dependencies
```

---

## 📊 Test Reports & Coverage

### Where are Reports?

After running tests, find reports here:

```
test-reports/
├── latest/                      ← Always points to most recent run
│   ├── test-report.html         ← Test results (pass/fail)
│   └── coverage/
│       └── index.html           ← Code coverage details
│
└── 2025-12-23_10-30-00/         ← Timestamped directories
    ├── test-report.html
    └── coverage/
```

### View Reports

```bash
# Open test results
open test-reports/latest/test-report.html      # Mac
xdg-open test-reports/latest/test-report.html  # Linux

# Open coverage report
open test-reports/latest/coverage/index.html
```

### How Coverage Works

The framework uses `pytest-cov` to track which code is executed during tests:

```
┌─────────────────────────────────────────────────────────────┐
│  pytest tests/ -v                                           │
│  (coverage is ON by default)                                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  During tests, pytest-cov tracks:                           │
│  • Which lines of src/ were executed                        │
│  • Which functions were called                              │
│  • Which branches were taken                                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  After tests, generates:                                    │
│  • coverage/index.html  → Visual HTML report                │
│  • Shows % covered per file                                 │
│  • Highlights uncovered lines in red                        │
└─────────────────────────────────────────────────────────────┘
```

### Coverage Commands

```bash
# Run with coverage (default)
pytest tests/ -v

# Run WITHOUT coverage (faster)
pytest tests/ -v --no-cov

# Run with specific coverage target
pytest tests/ -v --cov=src/ocp_client
```

### Report Cleanup

The framework automatically keeps only the **5 most recent** reports to save disk space.

---

## ✍️ Writing Tests

### Basic Test Template

```python
"""
Tests for <feature description>.

Component: spire_server
"""

import pytest
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_server  # Required marker
class TestMyFeature:
    """Tests for my feature."""

    def test_something_works(self, ocp_client, operator_namespace):
        """
        Test that something works correctly.

        Acceptance Criteria:
        - GIVEN the component is deployed
        - WHEN we check something
        - THEN it should be correct
        """
        logger.info("Starting test: checking something")

        # Your test code here
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-server"
        )

        assert len(pods) > 0, "Expected at least one pod"
        logger.info("✅ Test passed: something works")
```

### Available Fixtures

| Fixture | What it gives you |
|---------|-------------------|
| `ocp_client` | OpenShift API client |
| `operator_namespace` | `"zero-trust-workload-identity-manager"` |
| `spire_server` | SpireServer CR dict |
| `spire_agent` | SpireAgent CR dict |
| `spiffe_csi_driver` | SpiffeCSIDriver CR dict |
| `oidc_provider` | OIDC Provider CR dict |
| `app_domain` | Apps domain (e.g., `apps.cluster.example.com`) |
| `unique_name` | Random name like `test-a1b2c3d4` |
| `wait_timeout` | Default timeout (120 seconds) |

### Common OCP Client Methods

```python
# Get pods with label selector
pods = ocp_client.get_pods(namespace="ns", label_selector="app=name")

# Wait for pods to be ready
pods = ocp_client.wait_for_pods_ready(
    namespace="ns",
    label_selector="app=name",
    expected_count=1,
    timeout=120
)

# Get pod logs
logs = ocp_client.get_pod_logs(name="pod-name", namespace="ns")

# Direct Kubernetes API
deployment = ocp_client.apps_v1.read_namespaced_deployment("name", "ns")
configmap = ocp_client.core_v1.read_namespaced_config_map("name", "ns")
```

### Markers

```python
@pytest.mark.operator       # Operator tests
@pytest.mark.spire_server   # SpireServer tests
@pytest.mark.spire_agent    # SpireAgent tests
@pytest.mark.csi_driver     # CSI Driver tests
@pytest.mark.oidc_discovery # OIDC tests
@pytest.mark.slow           # Slow tests (can skip with -m "not slow")
```

---

## 🔧 Troubleshooting

### "Cannot get resource dnses" (403 Forbidden)

The framework auto-detects APP_DOMAIN. If it fails:

```bash
# Find your domain from console URL
# Console: https://console-openshift-console.apps.mycluster.example.com
# Domain:  apps.mycluster.example.com

export APP_DOMAIN=apps.mycluster.example.com
pytest tests/ -v
```

### "Already exists" Error

Something wasn't cleaned up. Run cleanup first:

```bash
pytest tests/ -v --cleanup-only
```

### Namespace Stuck in "Terminating"

```bash
# Force delete
oc delete ns zero-trust-workload-identity-manager --force --grace-period=0
```

### Check What's Running

```bash
# See all ZTWIM resources
oc get ns zero-trust-workload-identity-manager
oc get pods -n zero-trust-workload-identity-manager
oc get zerotrustworkloadidentitymanagers,spireservers,spireagents,spiffecsidrivers,spireoidcdiscoveryproviders
```

### Manual Cleanup

```bash
# Delete CRs first
oc delete zerotrustworkloadidentitymanagers cluster --ignore-not-found
oc delete spireservers cluster --ignore-not-found
oc delete spireagents cluster --ignore-not-found
oc delete spiffecsidrivers cluster --ignore-not-found
oc delete spireoidcdiscoveryproviders cluster --ignore-not-found

# Then delete namespace
oc delete ns zero-trust-workload-identity-manager
```

---

## 🤝 Contributing

1. Generate tests from a PR:
   ```bash
   python scripts/auto_gen.py <PR_NUMBER> --use-cli --save --all
   ```

2. Review and refine generated tests

3. Run tests locally:
   ```bash
   pytest tests/<component>/test_pr<N>_*.py -v
   ```

4. Submit PR with your test additions

---

## 📜 License

Apache 2.0

## 👤 Author

Sayak Das - Red Hat
