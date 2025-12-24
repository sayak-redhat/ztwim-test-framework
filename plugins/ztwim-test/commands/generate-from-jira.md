---
name: generate-from-jira
description: Generate pytest test cases from a Jira issue's acceptance criteria
arguments:
  - name: issue_key
    description: The Jira issue key (e.g., ZTWIM-123, OCPBUGS-456)
    required: true
    type: string
  - name: --component
    description: Override detected component
    required: false
    type: string
    options: [operator, spire_server, spire_agent, csi_driver, oidc_discovery]
  - name: --save
    description: Automatically save generated tests without prompting
    required: false
    type: boolean
    default: false
  - name: --include-comments
    description: Include Jira comments in analysis
    required: false
    type: boolean
    default: false
---

# Generate Tests from Jira Issue

Generate comprehensive pytest test cases by analyzing a Jira issue's acceptance criteria and description.

## Sections

### What This Command Does

This command fetches a Jira issue and extracts testable requirements from:
- Issue summary and description
- Acceptance criteria (GIVEN/WHEN/THEN format)
- Linked PRs and their changes
- Issue comments (optional)

**Process:**
1. Fetch Jira issue details via Jira API/CLI
2. Parse acceptance criteria into test scenarios
3. Detect ZTWIM component from labels/components
4. Analyze linked PRs for implementation context
5. Generate test cases matching acceptance criteria
6. Add Jira reference in docstrings for traceability
7. Validate and save test files

### Prerequisites

- Jira access configured:
  - Option 1: Jira MCP server running (recommended)
  - Option 2: `jira-cli` installed and configured
  - Option 3: `JIRA_TOKEN` and `JIRA_URL` environment variables
- Claude CLI or `ANTHROPIC_API_KEY`

### Setting Up Jira Access

**Option 1: Jira MCP Server (Recommended)**
```bash
# Start the Jira MCP server
podman run -i --rm -p 8080:8080 \
  -e "JIRA_URL=https://issues.redhat.com" \
  -e "JIRA_USERNAME=$JIRA_USERNAME" \
  -e "JIRA_PERSONAL_TOKEN=$JIRA_TOKEN" \
  ghcr.io/sooperset/mcp-atlassian:latest --transport sse --port 8080

# Add to Claude
claude mcp add --transport sse atlassian http://localhost:8080/sse
```

**Option 2: Environment Variables**
```bash
export JIRA_URL="https://issues.redhat.com"
export JIRA_TOKEN="your-personal-access-token"
```

### Input

A Jira issue key from supported projects.

**Examples:**
```
/ztwim-test:generate-from-jira ZTWIM-123
/ztwim-test:generate-from-jira OCPBUGS-45678 --save
/ztwim-test:generate-from-jira ZTWIM-123 --component spire_server
/ztwim-test:generate-from-jira ZTWIM-123 --include-comments
```

### Output Format

```
✅ Fetched ZTWIM-123: "SPIRE Agent should auto-recover after node restart"
   Type: Story
   Status: In Progress
   Component: spire-agent
   Labels: qe-needed, automated-testing

📋 Extracted Acceptance Criteria:
   1. GIVEN a SPIRE Agent is running on a node
      WHEN the node is restarted
      THEN the agent should automatically reconnect to the server
   
   2. GIVEN a SPIRE Agent loses connection
      WHEN connection is restored
      THEN existing workload SVIDs should remain valid

🔗 Linked PRs:
   - PR #89: "Implement agent recovery mechanism"

📦 Detected component: spire_agent

📝 Generating tests...

✅ Syntax validation passed

💾 Generated: tests/spire_agent/test_jira123_agent_recovery.py

📋 Test Summary:
   - test_agent_reconnects_after_node_restart
   - test_agent_preserves_svids_after_reconnection
   - test_agent_recovery_timeout_handling
```

### Generated Test Structure

```python
"""
Tests for SPIRE Agent auto-recovery functionality.

Generated from: ZTWIM-123
Jira URL: https://issues.redhat.com/browse/ZTWIM-123
Component: spire_agent
Summary: SPIRE Agent should auto-recover after node restart
"""

import pytest
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_agent
class TestAgentRecovery:
    """
    Tests for SpireAgent auto-recovery after disruptions.
    
    Jira: ZTWIM-123
    """

    def test_agent_reconnects_after_node_restart(
        self, spire_agent, ocp_client, operator_namespace
    ):
        """
        Test that agent automatically reconnects after node restart.

        Acceptance Criteria:
        - GIVEN a SPIRE Agent is running on a node
        - WHEN the node is restarted
        - THEN the agent should automatically reconnect to the server
        
        Jira: ZTWIM-123 (AC #1)
        """
        logger.info("Testing agent recovery after node restart")
        # Test implementation...
        logger.info("✅ Agent reconnection verified")

    def test_agent_preserves_svids_after_reconnection(
        self, spire_agent, ocp_client, test_namespace
    ):
        """
        Test that existing SVIDs remain valid after reconnection.

        Acceptance Criteria:
        - GIVEN a SPIRE Agent loses connection
        - WHEN connection is restored
        - THEN existing workload SVIDs should remain valid
        
        Jira: ZTWIM-123 (AC #2)
        """
        logger.info("Testing SVID preservation after reconnection")
        # Test implementation...
        logger.info("✅ SVID preservation verified")
```

### Acceptance Criteria Parsing

The command recognizes various AC formats:

**Format 1: GIVEN/WHEN/THEN**
```
AC:
- GIVEN the operator is installed
- WHEN a SpireServer CR is created
- THEN a StatefulSet should be created
```

**Format 2: Numbered List**
```
Acceptance Criteria:
1. SpireServer creates StatefulSet with correct replicas
2. Service is created for agent communication
3. ConfigMap contains server configuration
```

**Format 3: Bullet Points**
```
* Server should start within 60 seconds
* Health endpoint returns 200
* Logs show successful initialization
```

### Component Detection from Jira

| Jira Field | Detection |
|------------|-----------|
| Component: spire-server | spire_server |
| Component: spire-agent | spire_agent |
| Component: oidc-provider | oidc_discovery |
| Component: csi-driver | csi_driver |
| Label: spire-server | spire_server |
| Summary contains "server" | spire_server |

### Tips

1. **Well-written ACs**: Better acceptance criteria = better tests
2. **Link PRs**: Linked PRs provide implementation context
3. **Use --include-comments**: Include if AC clarifications are in comments
4. **Override component**: Use `--component` if detection is wrong

### Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| "Issue not found" | Invalid key or no access | Verify issue exists and you have access |
| "No acceptance criteria" | Issue lacks AC | Add AC to issue or use `/ztwim-test:suggest` |
| "Jira connection failed" | Auth/network issue | Check JIRA_TOKEN and network |

### Related Commands

- `/ztwim-test:generate-from-pr` - Generate from PR instead
- `/jira:analyze-bug` - Analyze Jira issue context
- `/ztwim-test:validate` - Validate generated tests

