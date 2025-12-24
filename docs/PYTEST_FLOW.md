# 🎯 What Happens When You Run `pytest tests/ -v`

This document explains the complete execution flow of the ZTWIM Test Framework.

## 📚 Pytest Concepts (Simple Explanation)

| Concept | What It Is | Real-World Analogy |
|---------|------------|-------------------|
| **Fixture** | Reusable setup code that runs before tests | Like a waiter preparing your table before you eat |
| **Scope** | How long a fixture lives | `session` = entire meal, `module` = one course, `function` = one bite |
| **autouse** | Fixture runs automatically without asking | Auto-refill water glass |
| **Hook** | Code that runs at specific pytest events | Kitchen bell that rings when order is ready |
| **Marker** | Labels/tags on tests | Like hashtags (#vegetarian, #spicy) |
| **conftest.py** | Shared fixtures file | Restaurant's central kitchen |

---

## 🔄 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           pytest tests/ -v                                       │
│                                                                                  │
│                    YOU TYPE THIS COMMAND AND PRESS ENTER                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 1: STARTUP (Pytest initializes)                                          ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  1️⃣ pytest_addoption() HOOK runs                                                 ┃
┃     ┌────────────────────────────────────────────────────────────────┐          ┃
┃     │ "Hey pytest! I want these custom CLI options:"                 │          ┃
┃     │   --kubeconfig     (where's the cluster?)                      │          ┃
┃     │   --skip-install   (don't install ZTWIM)                       │          ┃
┃     │   --keep-ztwim     (don't cleanup after)                       │          ┃
┃     │   --cleanup-only   (just cleanup, skip tests)                  │          ┃
┃     └────────────────────────────────────────────────────────────────┘          ┃
┃                                      │                                           ┃
┃                                      ▼                                           ┃
┃  2️⃣ pytest_configure() HOOK runs                                                 ┃
┃     ┌────────────────────────────────────────────────────────────────┐          ┃
┃     │ "Let me setup the report directory:"                           │          ┃
┃     │   📁 test-reports/2025-12-18_11-30-00/                        │          ┃
┃     │      ├── test-report.html                                      │          ┃
┃     │      └── coverage/                                             │          ┃
┃     │   📁 test-reports/latest → symlink                            │          ┃
┃     └────────────────────────────────────────────────────────────────┘          ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 2: COLLECTION (Pytest finds all tests)                                   ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  Pytest scans tests/ folder looking for:                                         ┃
┃    📄 Files named test_*.py                                                     ┃
┃    🏷️ Classes named Test*                                                       ┃
┃    🔧 Functions named test_*                                                    ┃
┃                                                                                  ┃
┃  Found:                                                                          ┃
┃  ┌────────────────────────────────────────────────────────────────┐             ┃
┃  │ tests/                                                         │             ┃
┃  │ ├── operator/test_operator_installation.py                     │             ┃
┃  │ │   ├── TestOperatorInstallation::test_operator_namespace_exists│            ┃
┃  │ │   ├── TestOperatorInstallation::test_subscription_exists     │             ┃
┃  │ │   └── ... (12 tests)                                         │             ┃
┃  │ ├── spire_server/test_spire_server_deployment.py               │             ┃
┃  │ │   └── ... (9 tests)                                          │             ┃
┃  │ ├── spire_agent/test_spire_agent_deployment.py                 │             ┃
┃  │ │   └── ... (10 tests)                                         │             ┃
┃  │ ├── csi_driver/test_csi_driver_deployment.py                   │             ┃
┃  │ │   └── ... (6 tests)                                          │             ┃
┃  │ └── oidc_discovery/test_oidc_discovery_deployment.py           │             ┃
┃  │     └── ... (7 tests)                                          │             ┃
┃  │                                                                │             ┃
┃  │ TOTAL: 45 tests collected                                      │             ┃
┃  └────────────────────────────────────────────────────────────────┘             ┃
┃                                                                                  ┃
┃  3️⃣ pytest_collection_modifyitems() HOOK runs                                    ┃
┃     "Auto-add markers to tests based on folder name"                            ┃
┃     tests/spire_server/* → gets @pytest.mark.spire_server                       ┃
┃     tests/spire_agent/*  → gets @pytest.mark.spire_agent                        ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 3: SESSION FIXTURES (Run ONCE for entire test session)                   ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  scope="session" means: CREATE ONCE, USE FOR ALL 45 TESTS                       ┃
┃                                                                                  ┃
┃  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐          ┃
┃  │ kubeconfig_path │  ──► │   ocp_client    │  ──► │    settings     │          ┃
┃  │                 │      │                 │      │                 │          ┃
┃  │ Gets path to    │      │ Connects to     │      │ Loads config    │          ┃
┃  │ kubeconfig file │      │ OpenShift API   │      │ from YAML       │          ┃
┃  │                 │      │                 │      │                 │          ┃
┃  │ Output:         │      │ Output:         │      │ Output:         │          ┃
┃  │ "/path/to/kube" │      │ "Connected to   │      │ Settings object │          ┃
┃  │                 │      │  v1.27.0"       │      │                 │          ┃
┃  └─────────────────┘      └─────────────────┘      └─────────────────┘          ┃
┃           │                       │                       │                      ┃
┃           └───────────────────────┼───────────────────────┘                      ┃
┃                                   ▼                                              ┃
┃  ┌─────────────────────────────────────────────────────────────────────────┐    ┃
┃  │  4️⃣ ztwim_setup FIXTURE (autouse=True)                                  │    ┃
┃  │                                                                         │    ┃
┃  │  THIS IS THE MAGIC! ✨                                                  │    ┃
┃  │  autouse=True means: "RUN AUTOMATICALLY, DON'T WAIT TO BE ASKED"       │    ┃
┃  │                                                                         │    ┃
┃  │  ┌─────────────────────────────────────────────────────────────────┐   │    ┃
┃  │  │               🚀 INSTALLS ZTWIM OPERATOR                        │   │    ┃
┃  │  │                                                                 │   │    ┃
┃  │  │  Step 1: Auto-detect APP_DOMAIN from cluster                    │   │    ┃
┃  │  │  Step 2: Create namespace                                       │   │    ┃
┃  │  │  Step 3: Install operator via OLM                               │   │    ┃
┃  │  │          - OperatorGroup                                        │   │    ┃
┃  │  │          - Subscription (channel: stable-v1)                    │   │    ┃
┃  │  │          - Wait for CSV to succeed (~2-3 min)                   │   │    ┃
┃  │  │  Step 4: Deploy all CRs                                         │   │    ┃
┃  │  │          - ZeroTrustWorkloadIdentityManager                     │   │    ┃
┃  │  │          - SpireServer                                          │   │    ┃
┃  │  │          - SpireAgent                                           │   │    ┃
┃  │  │          - SpiffeCSIDriver                                      │   │    ┃
┃  │  │          - SpireOIDCDiscoveryProvider                           │   │    ┃
┃  │  │  Step 5: Verify all pods are running                            │   │    ┃
┃  │  │                                                                 │   │    ┃
┃  │  │  ✅ "ZTWIM setup complete - ready to run tests"                 │   │    ┃
┃  │  └─────────────────────────────────────────────────────────────────┘   │    ┃
┃  │                                                                         │    ┃
┃  │  This takes ~4-5 minutes                                               │    ┃
┃  └─────────────────────────────────────────────────────────────────────────┘    ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 4: RUN TESTS (The actual testing!)                                       ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  For EACH test file (module):                                                    ┃
┃                                                                                  ┃
┃  ┌─────────────────────────────────────────────────────────────────────────┐    ┃
┃  │  📄 tests/spire_server/test_spire_server_deployment.py                  │    ┃
┃  │                                                                         │    ┃
┃  │  5️⃣ MODULE FIXTURES run (scope="module" = once per file)               │    ┃
┃  │     ┌─────────────────────────────────────────────────────────────┐    │    ┃
┃  │     │  spire_server = spire_server_manager.get("cluster")         │    │    ┃
┃  │     │  "Get the SpireServer CR from the cluster"                  │    │    ┃
┃  │     └─────────────────────────────────────────────────────────────┘    │    ┃
┃  │                                                                         │    ┃
┃  │  For EACH test in this file:                                           │    ┃
┃  │                                                                         │    ┃
┃  │  ┌───────────────────────────────────────────────────────────────────┐ │    ┃
┃  │  │  TEST 1: test_spire_server_cr_exists                              │ │    ┃
┃  │  │                                                                   │ │    ┃
┃  │  │  SETUP:   pytest_runtest_setup() → "Starting test..."            │ │    ┃
┃  │  │                       │                                           │ │    ┃
┃  │  │                       ▼                                           │ │    ┃
┃  │  │  FIXTURE: spire_server injected as parameter                     │ │    ┃
┃  │  │                       │                                           │ │    ┃
┃  │  │                       ▼                                           │ │    ┃
┃  │  │  RUN:     def test_spire_server_cr_exists(self, spire_server):   │ │    ┃
┃  │  │               assert spire_server is not None                    │ │    ┃
┃  │  │               assert spire_server["metadata"]["name"] == "cluster"│ │   ┃
┃  │  │                       │                                           │ │    ┃
┃  │  │                       ▼                                           │ │    ┃
┃  │  │  RESULT:  ✅ PASSED                                               │ │    ┃
┃  │  │                       │                                           │ │    ┃
┃  │  │                       ▼                                           │ │    ┃
┃  │  │  TEARDOWN: pytest_runtest_teardown() → "Test passed!"            │ │    ┃
┃  │  └───────────────────────────────────────────────────────────────────┘ │    ┃
┃  │                                                                         │    ┃
┃  │  ┌───────────────────────────────────────────────────────────────────┐ │    ┃
┃  │  │  TEST 2: test_spire_server_creates_statefulset                    │ │    ┃
┃  │  │  ... same flow ...                                                │ │    ┃
┃  │  └───────────────────────────────────────────────────────────────────┘ │    ┃
┃  │                                                                         │    ┃
┃  │  ... repeat for all 9 tests in this file ...                           │    ┃
┃  └─────────────────────────────────────────────────────────────────────────┘    ┃
┃                                                                                  ┃
┃  ... repeat for all 5 test files ...                                            ┃
┃                                                                                  ┃
┃  Output during tests:                                                            ┃
┃  tests/operator/test_operator_installation.py::TestOperatorInstallation::       ┃
┃      test_operator_namespace_exists PASSED                                      ┃
┃  tests/operator/test_operator_installation.py::TestOperatorInstallation::       ┃
┃      test_subscription_exists PASSED                                            ┃
┃  ... 43 more tests ...                                                          ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 5: TEARDOWN (Cleanup after all tests)                                    ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  6️⃣ ztwim_setup fixture TEARDOWN (after yield)                                   ┃
┃                                                                                  ┃
┃  ┌─────────────────────────────────────────────────────────────────────────┐    ┃
┃  │  The fixture has:                                                       │    ┃
┃  │                                                                         │    ┃
┃  │  def ztwim_setup():                                                    │    ┃
┃  │      # SETUP: Install ZTWIM (ran before tests)                         │    ┃
┃  │      installer.install_and_verify()                                    │    ┃
┃  │                                                                         │    ┃
┃  │      yield  # ← TESTS RAN HERE                                         │    ┃
┃  │                                                                         │    ┃
┃  │      # TEARDOWN: Cleanup (runs now, after all tests)                   │    ┃
┃  │      if not keep_ztwim:                                                │    ┃
┃  │          installer.uninstall_all()  # 🧹 DELETE EVERYTHING             │    ┃
┃  │                                                                         │    ┃
┃  └─────────────────────────────────────────────────────────────────────────┘    ┃
┃                                                                                  ┃
┃  🧹 CLEANUP (unless --keep-ztwim was used):                                     ┃
┃     - Delete SpireOIDCDiscoveryProvider                                         ┃
┃     - Delete SpiffeCSIDriver                                                    ┃
┃     - Delete SpireAgent                                                         ┃
┃     - Delete SpireServer                                                        ┃
┃     - Delete ZeroTrustWorkloadIdentityManager                                   ┃
┃     - Delete Subscription                                                       ┃
┃     - Delete OperatorGroup                                                      ┃
┃     - Delete Namespace                                                          ┃
┃                                                                                  ┃
┃  ✅ "ZTWIM cleanup complete - cluster is clean"                                 ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                      │
                                      ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  PHASE 6: REPORTS (Generate output)                                             ┃
┃  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ┃
┃                                                                                  ┃
┃  7️⃣ pytest_sessionfinish() HOOK runs                                             ┃
┃                                                                                  ┃
┃  ┌─────────────────────────────────────────────────────────────────────────┐    ┃
┃  │  1. Generate HTML coverage report                                       │    ┃
┃  │     coverage.html_report(directory="test-reports/.../coverage/")       │    ┃
┃  │                                                                         │    ┃
┃  │  2. Update "latest" symlink                                            │    ┃
┃  │     test-reports/latest → test-reports/2025-12-18_11-30-00/           │    ┃
┃  │                                                                         │    ┃
┃  │  3. Print summary                                                       │    ┃
┃  └─────────────────────────────────────────────────────────────────────────┘    ┃
┃                                                                                  ┃
┃  Output:                                                                         ┃
┃  ════════════════════════════════════════════════════════════════               ┃
┃  📊 TEST REPORTS GENERATED                                                      ┃
┃  ════════════════════════════════════════════════════════════════               ┃
┃                                                                                  ┃
┃  📁 test-reports/2025-12-18_11-30-00/                                           ┃
┃     ├── test-report.html    ← Test results                                      ┃
┃     └── coverage/index.html ← Code coverage                                     ┃
┃                                                                                  ┃
┃  🔗 Quick access: test-reports/latest/test-report.html                          ┃
┃  ════════════════════════════════════════════════════════════════               ┃
┃                                                                                  ┃
┃  Results (286.79s):                                                              ┃
┃       44 passed                                                                  ┃
┃        1 skipped                                                                 ┃
┃                                                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## 🎯 Simple Timeline View

```
TIME        WHAT HAPPENS
─────────────────────────────────────────────────────────────────
0:00        pytest starts
0:01        Loads conftest.py, registers options & hooks
0:02        Collects 45 tests from tests/ folder
0:03        Creates session fixtures (ocp_client, settings)
            │
0:04        ┌─────────────────────────────────────────────────┐
   to       │  ztwim_setup fixture (autouse=True)             │
4:00        │  INSTALLS ZTWIM OPERATOR + ALL COMPONENTS       │
            │  (This is the long part ~4 minutes)             │
            └─────────────────────────────────────────────────┘
            │
4:01        ┌─────────────────────────────────────────────────┐
   to       │  RUNS ALL 45 TESTS                              │
5:00        │  test_operator_namespace_exists ✅              │
            │  test_subscription_exists ✅                     │
            │  test_spire_server_cr_exists ✅                  │
            │  ... (42 more tests) ...                        │
            └─────────────────────────────────────────────────┘
            │
5:01        ┌─────────────────────────────────────────────────┐
   to       │  ztwim_setup fixture TEARDOWN                   │
7:00        │  UNINSTALLS ZTWIM (cleanup)                     │
            │  (unless --keep-ztwim was used)                 │
            └─────────────────────────────────────────────────┘
            │
7:01        Generates reports
7:02        DONE! ✅
```

---

## 🧩 Fixture Dependency Chain

```
                    ┌─────────────────┐
                    │  kubeconfig_path │ ← Gets kubeconfig
                    │  scope=session   │
                    └────────┬────────┘
                             │ depends on
                             ▼
                    ┌─────────────────┐
                    │   ocp_client    │ ← Connects to cluster
                    │  scope=session   │
                    └────────┬────────┘
                             │ depends on
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │  settings   │ │ ztwim_setup │ │ app_domain  │
     │  session    │ │  session    │ │  session    │
     └─────────────┘ │  autouse!   │ └─────────────┘
                     └──────┬──────┘
                            │ enables
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  spire_server   │ │  spire_agent    │ │ spiffe_csi_driver│
│  scope=module   │ │  scope=module   │ │  scope=module   │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     TESTS       │
                    │  Can use any    │
                    │  fixture above  │
                    └─────────────────┘
```

---

## 📝 Key Pytest Concepts in This Framework

### 1️⃣ Fixture Scopes

```python
@pytest.fixture(scope="session")  # Lives for ENTIRE test run
def ocp_client():
    return OCPClient()  # Created once, used by all 45 tests

@pytest.fixture(scope="module")   # Lives for ONE test file
def spire_server():
    return get_spire_server()  # Created once per test file

@pytest.fixture(scope="function") # Lives for ONE test (default)
def unique_name():
    return f"test-{uuid.uuid4()}"  # Created fresh for each test
```

### 2️⃣ autouse=True

```python
@pytest.fixture(scope="session", autouse=True)  # ← THE MAGIC
def ztwim_setup():
    # This runs AUTOMATICALLY before any test
    # No test needs to request it!
    install_ztwim()
    yield
    cleanup_ztwim()
```

### 3️⃣ yield for Setup/Teardown

```python
@pytest.fixture
def my_fixture():
    # SETUP (before test)
    resource = create_resource()
    
    yield resource  # ← Test runs here, gets 'resource'
    
    # TEARDOWN (after test)
    resource.delete()
```

### 4️⃣ Hooks

```python
def pytest_configure(config):        # Runs at startup
def pytest_collection_modifyitems(): # Runs after collecting tests
def pytest_runtest_setup(item):      # Runs before each test
def pytest_runtest_teardown():       # Runs after each test
def pytest_sessionfinish():          # Runs at the very end
```

---

## 🎯 Phase Summary

| Phase | What Happens | Duration |
|-------|-------------|----------|
| **Startup** | Load conftest, parse options | ~1s |
| **Collection** | Find all test files/functions | ~1s |
| **Session Fixtures** | Connect to cluster, **INSTALL ZTWIM** | ~4 min |
| **Run Tests** | Execute all 45 tests | ~1 min |
| **Teardown** | **CLEANUP ZTWIM** | ~2 min |
| **Reports** | Generate HTML reports | ~1s |
| **TOTAL** | | **~7 min** |

---

## 🚀 Common Commands

| Command | Description |
|---------|-------------|
| `pytest tests/ -v` | Run all tests (install → test → cleanup) |
| `pytest tests/ -v --keep-ztwim` | Run tests, keep ZTWIM after |
| `pytest tests/ -v --skip-install` | Skip install (ZTWIM already deployed) |
| `pytest tests/ -v --cleanup-only` | Only cleanup, skip tests |
| `pytest tests/ -v --skip-install --keep-ztwim` | Run on existing, don't cleanup |

---

## 📁 Files Involved

| File | Role |
|------|------|
| `conftest.py` | All fixtures, hooks, CLI options |
| `pyproject.toml` | Pytest configuration, markers |
| `src/ocp_client/client.py` | OpenShift API client |
| `src/ocp_client/spire_crds.py` | ZTWIM installer & CRD managers |
| `tests/*/test_*.py` | Actual test files |

