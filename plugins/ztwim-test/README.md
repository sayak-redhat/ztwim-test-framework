# ZTWIM Test Generation Plugin

AI-powered test generation for Zero Trust Workload Identity Manager (ZTWIM) using Claude.

## Overview

This plugin automates the creation of pytest test cases for ZTWIM by analyzing:
- **Pull Requests**: Generate tests based on code changes
- **Jira Issues**: Create tests from acceptance criteria
- **Coverage Gaps**: Identify untested functionality
- **Component Analysis**: Suggest tests for specific components

## Features

- 🤖 **AI-Powered Generation** - Uses Claude to understand code changes and generate meaningful tests
- 🎯 **Framework-Aware** - Understands ZTWIM test framework fixtures, markers, and patterns
- 📁 **Smart Placement** - Automatically places tests in the correct component directory
- ✅ **Syntax Validation** - Validates generated Python code before saving
- 🔄 **Multi-Component** - Handles PRs affecting multiple components

## Prerequisites

- Python 3.9+
- Git CLI installed
- GitHub CLI (`gh`) installed and authenticated
- Claude CLI or Anthropic API key
- Access to the ZTWIM test framework repository

### Optional
- Jira CLI for Jira integration

## Installation

### From ai-helpers Marketplace
```bash
# Add the marketplace (if not already added)
/plugin marketplace add openshift-eng/ai-helpers

# Install the plugin
/plugin install ztwim-test@ai-helpers
```

### Manual Installation
```bash
# Clone the repository
git clone https://github.com/your-org/ztwim-test-framework.git

# Link to Cursor commands directory
mkdir -p ~/.cursor/commands
ln -s /path/to/ztwim-test-framework/plugins/ztwim-test ~/.cursor/commands/ztwim-test
```

## Commands

### `/ztwim-test:generate-from-pr`

Generate tests from a GitHub Pull Request.

```bash
# Basic usage
/ztwim-test:generate-from-pr 72

# With options
/ztwim-test:generate-from-pr 72 --save --verbose

# Specify repository
/ztwim-test:generate-from-pr 72 --repo openshift/zero-trust-workload-identity-manager
```

**What it does:**
1. Fetches PR details (title, description, files changed, diff)
2. Detects affected ZTWIM components (spire_server, spire_agent, etc.)
3. Analyzes changes to understand what needs testing
4. Generates pytest test cases following framework patterns
5. Validates generated code syntax
6. Saves to appropriate `tests/{component}/` directory

**Output:**
- Test file(s) in `tests/{component}/test_pr{number}_{feature}.py`

---

### `/ztwim-test:generate-from-jira`

Generate tests from a Jira issue's acceptance criteria.

```bash
# Basic usage
/ztwim-test:generate-from-jira ZTWIM-123

# With component override
/ztwim-test:generate-from-jira ZTWIM-123 --component spire_server
```

**What it does:**
1. Fetches Jira issue details (summary, description, acceptance criteria)
2. Extracts testable requirements from acceptance criteria
3. Maps to ZTWIM component based on labels/components
4. Generates comprehensive test cases
5. Links generated tests back to Jira issue in docstrings

---

### `/ztwim-test:coverage-gap`

Identify areas lacking test coverage.

```bash
# Analyze all components
/ztwim-test:coverage-gap

# Specific component
/ztwim-test:coverage-gap --component spire_server

# Output suggestions
/ztwim-test:coverage-gap --suggest
```

**What it does:**
1. Analyzes existing test files
2. Compares against component capabilities
3. Reviews recent PRs for untested changes
4. Identifies coverage gaps
5. Suggests new test cases to fill gaps

---

### `/ztwim-test:suggest`

Get AI suggestions for test cases.

```bash
# Suggest tests for component
/ztwim-test:suggest spire_server

# Suggest for specific feature
/ztwim-test:suggest spire_server --feature "high-availability"

# Suggest edge cases
/ztwim-test:suggest spire_agent --type edge-cases
```

**What it does:**
1. Analyzes component's CRD and capabilities
2. Reviews existing tests to avoid duplication
3. Suggests new test scenarios based on:
   - Positive cases
   - Negative/error cases
   - Edge cases
   - Integration scenarios

---

### `/ztwim-test:validate`

Validate test files for correctness.

```bash
# Validate specific file
/ztwim-test:validate tests/spire_server/test_new_feature.py

# Validate all tests
/ztwim-test:validate --all

# Check framework compliance
/ztwim-test:validate --check-fixtures --check-markers
```

**What it does:**
1. Python syntax validation
2. Import verification
3. Fixture usage validation
4. Marker compliance check
5. Docstring format verification

---

## ZTWIM Test Framework Integration

This plugin is designed to work with the ZTWIM test framework structure:

```
tests/
├── operator/           # Operator installation tests
├── spire_server/       # SpireServer tests
├── spire_agent/        # SpireAgent tests
├── csi_driver/         # CSI Driver tests
├── oidc_discovery/     # OIDC Discovery tests
└── workload_identity/  # Workload identity tests
```

### Available Fixtures (auto-detected)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `ocp_client` | session | OpenShift/Kubernetes client |
| `operator_namespace` | session | ZTWIM operator namespace |
| `spire_server` | module | SpireServer CR object |
| `spire_agent` | module | SpireAgent CR object |
| `test_namespace` | module | Ephemeral test namespace |

### Pytest Markers

- `@pytest.mark.operator`
- `@pytest.mark.spire_server`
- `@pytest.mark.spire_agent`
- `@pytest.mark.csi_driver`
- `@pytest.mark.oidc_discovery`

---

## Configuration

### Environment Variables

```bash
# GitHub token (for PR access)
export GITHUB_TOKEN="ghp_xxxx"

# Anthropic API key (if not using Claude CLI)
export ANTHROPIC_API_KEY="sk-ant-xxxx"

# Jira credentials (optional)
export JIRA_TOKEN="your-jira-token"
export JIRA_URL="https://issues.redhat.com"
```

### Configuration File

Create `.ztwim-test.yaml` in your project root:

```yaml
# Default repository
repository: openshift/zero-trust-workload-identity-manager

# Test framework path
framework_path: /path/to/ztwim-test-framework

# Default options
defaults:
  save: true
  verbose: false
  use_cli: true  # Use Claude CLI vs API

# Component mappings
components:
  spire_server:
    paths: ["pkg/controller/spireserver", "api/v1alpha1/spireserver"]
    markers: ["spire_server"]
  spire_agent:
    paths: ["pkg/controller/spireagent", "api/v1alpha1/spireagent"]
    markers: ["spire_agent"]
```

---

## Examples

### Example 1: Generate from PR

```bash
/ztwim-test:generate-from-pr 72

# Output:
✅ Fetched PR #72: "Add configurable trust bundle rotation interval"
📦 Detected components: spire_server
🔍 Analyzing changes...
📝 Generating tests for spire_server...
✅ Validated Python syntax
💾 Saved: tests/spire_server/test_pr72_bundle_rotation.py

Generated test file contains:
- test_trust_bundle_rotation_interval_default
- test_trust_bundle_rotation_interval_custom
- test_trust_bundle_rotation_interval_invalid
```

### Example 2: Generate from Jira

```bash
/ztwim-test:generate-from-jira ZTWIM-456

# Output:
✅ Fetched ZTWIM-456: "SPIRE Agent should auto-recover after node restart"
📋 Extracted 4 acceptance criteria
📦 Component: spire_agent
📝 Generating tests...
💾 Saved: tests/spire_agent/test_jira456_agent_recovery.py
```

### Example 3: Find Coverage Gaps

```bash
/ztwim-test:coverage-gap --component spire_server --suggest

# Output:
## Coverage Gap Analysis: spire_server

### Existing Coverage
✅ Deployment basics (3 tests)
✅ StatefulSet scaling (2 tests)
✅ Service connectivity (2 tests)

### Gaps Identified
❌ High availability failover
❌ Trust bundle rotation
❌ Federation configuration
❌ Custom annotations

### Suggested Tests
1. test_spire_server_ha_leader_election
2. test_spire_server_ha_failover_recovery
3. test_trust_bundle_auto_rotation
4. test_federation_bundle_sync
```

---

## Development

### Running Tests
```bash
cd plugins/ztwim-test
pytest tests/ -v
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Add/modify commands in `commands/`
4. Update README
5. Submit PR

---

## Troubleshooting

### "Claude CLI not found"
```bash
# Install Claude CLI
npm install -g @anthropic-ai/claude-code
# Or use API mode with ANTHROPIC_API_KEY
```

### "GitHub rate limit exceeded"
```bash
# Authenticate with GitHub CLI
gh auth login
```

### "Generated tests have syntax errors"
The plugin validates syntax before saving. If errors persist:
```bash
/ztwim-test:validate tests/path/to/file.py --verbose
```

---

## License

Apache License 2.0

---

## Author

**Sayan Das**  
Red Hat  
December 2025

