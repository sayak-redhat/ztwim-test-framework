---
name: generate-from-pr
description: Generate pytest test cases from a GitHub Pull Request
arguments:
  - name: pr_number
    description: The PR number to generate tests from
    required: true
    type: integer
  - name: --repo
    description: GitHub repository (owner/repo format)
    required: false
    default: openshift/zero-trust-workload-identity-manager
  - name: --save
    description: Automatically save generated tests without prompting
    required: false
    type: boolean
    default: false
  - name: --verbose
    description: Show detailed output during generation
    required: false
    type: boolean
    default: false
  - name: --use-cli
    description: Use Claude CLI instead of API
    required: false
    type: boolean
    default: true
---

# Generate Tests from Pull Request

Generate comprehensive pytest test cases by analyzing a GitHub Pull Request.

## Sections

### What This Command Does

This command analyzes a Pull Request to understand what code changes were made, then generates appropriate test cases that validate the new functionality.

**Process:**
1. Fetch PR metadata (title, description, labels)
2. Retrieve all changed files and their diffs
3. Detect which ZTWIM components are affected
4. Analyze the nature of changes (feature, bugfix, refactor)
5. Generate test cases following framework patterns
6. Validate generated Python syntax
7. Save to the appropriate test directory

### Prerequisites

- `git` CLI installed
- `gh` (GitHub CLI) installed and authenticated, OR `GITHUB_TOKEN` environment variable set
- Claude CLI installed, OR `ANTHROPIC_API_KEY` environment variable set
- Access to the target repository

### Input

The PR number from the ZTWIM operator repository (or specified repo).

**Examples:**
```
/ztwim-test:generate-from-pr 72
/ztwim-test:generate-from-pr 72 --save
/ztwim-test:generate-from-pr 72 --repo openshift/zero-trust-workload-identity-manager --verbose
```

### Output Format

The command outputs progress information and generates test file(s):

```
✅ Fetched PR #72: "Add configurable trust bundle rotation interval"
   Author: @developer
   Labels: enhancement, spire-server
   Files changed: 5

📦 Detected components:
   - spire_server (primary)

🔍 Analyzing changes...
   - api/v1alpha1/spireserver_types.go: Added TrustBundleRotationInterval field
   - pkg/controller/spireserver/controller.go: Implemented rotation logic
   - config/crd/bases/...: Updated CRD

📝 Generating tests for spire_server...

✅ Syntax validation passed

💾 Generated: tests/spire_server/test_pr72_bundle_rotation.py

📋 Test Summary:
   - test_trust_bundle_rotation_interval_default
   - test_trust_bundle_rotation_interval_custom_value
   - test_trust_bundle_rotation_interval_invalid_value
   - test_trust_bundle_rotation_triggers_update
```

### Generated Test Structure

```python
"""
Tests for trust bundle rotation interval configuration.

Generated from: PR #72
Component: spire_server
PR Title: Add configurable trust bundle rotation interval
"""

import pytest
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_server
class TestTrustBundleRotationInterval:
    """Tests for SpireServer trust bundle rotation interval configuration."""

    def test_trust_bundle_rotation_interval_default(
        self, spire_server, ocp_client, operator_namespace
    ):
        """
        Test that default trust bundle rotation interval is applied.

        Acceptance Criteria:
        - GIVEN a SpireServer is deployed without explicit rotation interval
        - WHEN the server starts
        - THEN the default rotation interval should be used
        """
        logger.info("Verifying default trust bundle rotation interval")
        # Test implementation...
        logger.info("✅ Default rotation interval verified")
```

### Component Detection

The command automatically detects affected components based on file paths:

| Path Pattern | Component |
|--------------|-----------|
| `pkg/controller/spireserver/*` | spire_server |
| `api/v1alpha1/spireserver*` | spire_server |
| `pkg/controller/spireagent/*` | spire_agent |
| `api/v1alpha1/spireagent*` | spire_agent |
| `pkg/controller/oidc/*` | oidc_discovery |
| `pkg/controller/csidriver/*` | csi_driver |
| `pkg/controller/ztwim/*` | operator |

### Multi-Component PRs

If a PR affects multiple components, separate test files are generated for each:

```
/ztwim-test:generate-from-pr 85

# Output:
📦 Detected components:
   - spire_server
   - spire_agent

💾 Generated:
   - tests/spire_server/test_pr85_shared_config.py
   - tests/spire_agent/test_pr85_shared_config.py
```

### Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| "PR not found" | Invalid PR number | Verify PR exists in the repository |
| "Rate limit exceeded" | GitHub API limit | Authenticate with `gh auth login` |
| "No components detected" | PR doesn't affect testable code | Review PR manually |
| "Syntax validation failed" | Generated code has errors | Regenerate or fix manually |

### Tips

1. **Review before committing**: Always review generated tests before committing
2. **Add context**: If PR description is sparse, tests may be generic
3. **Use verbose mode**: `--verbose` shows detailed analysis for debugging
4. **Multi-component PRs**: Check all generated files for consistency

### Related Commands

- `/ztwim-test:validate` - Validate generated test files
- `/ztwim-test:suggest` - Get additional test suggestions
- `/ztwim-test:coverage-gap` - Find untested areas

