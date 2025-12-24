---
name: validate
description: Validate test files for syntax and framework compliance
arguments:
  - name: path
    description: Path to test file or directory to validate
    required: false
    type: string
    default: tests/
  - name: --all
    description: Validate all test files in the framework
    required: false
    type: boolean
    default: false
  - name: --check-fixtures
    description: Verify fixture usage is correct
    required: false
    type: boolean
    default: true
  - name: --check-markers
    description: Verify pytest markers are valid
    required: false
    type: boolean
    default: true
  - name: --check-docstrings
    description: Verify docstring format (GIVEN/WHEN/THEN)
    required: false
    type: boolean
    default: true
  - name: --fix
    description: Attempt to auto-fix simple issues
    required: false
    type: boolean
    default: false
  - name: --verbose
    description: Show detailed validation output
    required: false
    type: boolean
    default: false
---

# Validate Test Files

Validate generated or existing test files for correctness and framework compliance.

## Sections

### What This Command Does

This command performs comprehensive validation of test files:

1. **Python Syntax**: Validates Python syntax using `ast.parse()`
2. **Import Check**: Verifies all imports can be resolved
3. **Fixture Validation**: Checks fixture usage against available fixtures
4. **Marker Validation**: Verifies pytest markers are valid
5. **Docstring Check**: Validates GIVEN/WHEN/THEN format
6. **Style Check**: Basic style/convention compliance
7. **Auto-Fix**: Optionally fixes simple issues

### Prerequisites

- Python 3.9+
- Access to ZTWIM test framework

### Input

Path to a test file or directory.

**Examples:**
```
/ztwim-test:validate tests/spire_server/test_new_feature.py
/ztwim-test:validate tests/spire_server/
/ztwim-test:validate --all
/ztwim-test:validate tests/ --check-fixtures --verbose
/ztwim-test:validate tests/spire_agent/ --fix
```

### Output Format

```markdown
## Test Validation Report

**Path:** tests/spire_server/test_new_feature.py
**Validated:** 2025-12-24 10:30:00

---

### Summary

| Check | Status | Issues |
|-------|--------|--------|
| Python Syntax | ✅ Pass | 0 |
| Imports | ✅ Pass | 0 |
| Fixtures | ⚠️ Warning | 2 |
| Markers | ✅ Pass | 0 |
| Docstrings | ❌ Fail | 1 |

**Overall:** ⚠️ 3 issues found

---

### Issues

#### ⚠️ Warning: Unknown Fixture (Line 25)
```python
def test_something(self, spire_server, unknown_fixture):
                                       ^^^^^^^^^^^^^^
```
**Issue:** `unknown_fixture` is not a known framework fixture.
**Available fixtures:** ocp_client, operator_namespace, spire_server, spire_agent, ...
**Suggestion:** Remove or define this fixture.

---

#### ⚠️ Warning: Fixture Scope Mismatch (Line 42)
```python
def test_another(self, test_namespace, spire_server):
```
**Issue:** `test_namespace` (module-scoped) used with `spire_server` (module-scoped) - OK
**Note:** Both fixtures have compatible scopes.

---

#### ❌ Error: Missing Acceptance Criteria (Line 58)
```python
def test_missing_ac(self, spire_server):
    """Test something without proper docstring."""
```
**Issue:** Docstring missing GIVEN/WHEN/THEN acceptance criteria.
**Expected format:**
```python
"""
Test description.

Acceptance Criteria:
- GIVEN some precondition
- WHEN some action occurs
- THEN expected result happens
"""
```

---

### Validation Details

#### Python Syntax ✅
- File parses successfully
- No syntax errors detected

#### Imports ✅
All imports resolved:
- `pytest` ✅
- `src.utils.logger` ✅
- `kubernetes.client` ✅

#### Fixtures ⚠️
| Fixture | Status | Scope |
|---------|--------|-------|
| ocp_client | ✅ Valid | session |
| spire_server | ✅ Valid | module |
| unknown_fixture | ❌ Unknown | - |

#### Markers ✅
| Marker | Status |
|--------|--------|
| @pytest.mark.spire_server | ✅ Valid |

#### Docstrings ❌
| Test | Has AC? | Format OK? |
|------|---------|------------|
| test_something | ✅ Yes | ✅ Yes |
| test_another | ✅ Yes | ✅ Yes |
| test_missing_ac | ❌ No | - |

---

### Auto-Fix Available

The following issues can be auto-fixed with `--fix`:

1. **Add missing logger import** (if logger.info used without import)
2. **Add missing marker** (based on test file location)
3. **Format docstring** (convert bullet points to GIVEN/WHEN/THEN)

Run: `/ztwim-test:validate tests/spire_server/test_new_feature.py --fix`
```

### Validation Rules

#### Python Syntax
```python
# ✅ Valid
def test_example(self, fixture):
    assert True

# ❌ Invalid - syntax error
def test_example(self, fixture)  # Missing colon
    assert True
```

#### Fixture Usage
```python
# ✅ Valid - known fixtures
def test_example(self, ocp_client, spire_server):
    pass

# ⚠️ Warning - unknown fixture
def test_example(self, ocp_client, my_custom_fixture):
    pass  # my_custom_fixture not in conftest.py
```

#### Marker Validation
```python
# ✅ Valid markers
@pytest.mark.spire_server
@pytest.mark.spire_agent
@pytest.mark.csi_driver
@pytest.mark.oidc_discovery
@pytest.mark.operator

# ❌ Invalid marker
@pytest.mark.spire  # Should be spire_server or spire_agent
```

#### Docstring Format
```python
# ✅ Valid docstring
def test_example(self):
    """
    Test that something works.

    Acceptance Criteria:
    - GIVEN a precondition exists
    - WHEN an action is performed
    - THEN the expected result occurs
    """

# ❌ Invalid - missing acceptance criteria
def test_example(self):
    """Test that something works."""

# ⚠️ Warning - informal format (can be auto-fixed)
def test_example(self):
    """
    Test that something works.
    
    * Precondition exists
    * Action is performed  
    * Result occurs
    """
```

### Available Fixtures Reference

| Fixture | Scope | Description |
|---------|-------|-------------|
| `ocp_client` | session | OpenShift client |
| `operator_namespace` | session | Operator namespace |
| `settings` | session | Framework settings |
| `app_domain` | session | Apps domain |
| `cluster_name` | session | Cluster name |
| `ztwim_manager` | session | ZTWIM CRD manager |
| `spire_server_manager` | session | SpireServer manager |
| `spire_agent_manager` | session | SpireAgent manager |
| `csi_driver_manager` | session | CSI driver manager |
| `oidc_manager` | session | OIDC manager |
| `spire_server` | module | SpireServer CR |
| `spire_agent` | module | SpireAgent CR |
| `spiffe_csi_driver` | module | CSI Driver CR |
| `oidc_provider` | module | OIDC Provider CR |
| `test_namespace` | module | Test namespace |
| `unique_name` | function | Unique name generator |
| `test_labels` | function | Standard labels |
| `wait_timeout` | function | Timeout value |
| `poll_interval` | function | Poll interval |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All validations passed |
| 1 | Warnings only |
| 2 | Errors found |

### Using --fix

The `--fix` flag attempts to auto-correct issues:

```
/ztwim-test:validate tests/spire_server/test_new.py --fix

## Auto-Fix Report

### Fixed Issues

1. ✅ Added missing import: `from src.utils.logger import get_logger`
2. ✅ Added missing marker: `@pytest.mark.spire_server`
3. ✅ Converted docstring to GIVEN/WHEN/THEN format

### Remaining Issues (manual fix required)

1. ❌ Unknown fixture `custom_fixture` - define in conftest.py or remove

### Changes Made

--- a/tests/spire_server/test_new.py
+++ b/tests/spire_server/test_new.py
@@ -1,5 +1,8 @@
+import pytest
+from src.utils.logger import get_logger
+
+logger = get_logger(__name__)

+@pytest.mark.spire_server
 class TestNewFeature:
```

### Tips

1. **Run before commit**: Validate all changes before committing
2. **CI Integration**: Add to CI pipeline for automated checks
3. **Use --verbose**: See detailed analysis for debugging
4. **Fix iteratively**: Run --fix, then re-validate

### Related Commands

- `/ztwim-test:generate-from-pr` - Generate tests
- `/ztwim-test:suggest` - Get test suggestions
- `/ztwim-test:coverage-gap` - Find coverage gaps

