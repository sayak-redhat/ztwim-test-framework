---
name: suggest
description: Get AI suggestions for test cases for a specific ZTWIM component
arguments:
  - name: component
    description: The ZTWIM component to suggest tests for
    required: true
    type: string
    options: [operator, spire_server, spire_agent, csi_driver, oidc_discovery]
  - name: --feature
    description: Specific feature to focus on
    required: false
    type: string
  - name: --type
    description: Type of tests to suggest
    required: false
    type: string
    options: [positive, negative, edge-cases, integration, all]
    default: all
  - name: --count
    description: Number of test suggestions to generate
    required: false
    type: integer
    default: 5
  - name: --generate
    description: Generate full test code (not just suggestions)
    required: false
    type: boolean
    default: false
---

# Suggest Test Cases

Get AI-powered test suggestions for ZTWIM components.

## Sections

### What This Command Does

This command analyzes a ZTWIM component and suggests test cases by:

1. **CRD Analysis**: Reviews the component's CRD spec fields
2. **Existing Test Review**: Avoids suggesting duplicates
3. **Best Practices**: Applies testing best practices
4. **Scenario Generation**: Creates realistic test scenarios
5. **Code Generation**: Optionally generates full test code

### Prerequisites

- Access to ZTWIM test framework
- Claude CLI or API key

### Input

Component name and optional filters.

**Examples:**
```
/ztwim-test:suggest spire_server
/ztwim-test:suggest spire_agent --feature "node attestation"
/ztwim-test:suggest csi_driver --type negative
/ztwim-test:suggest oidc_discovery --count 10 --generate
```

### Output Format

```markdown
## Test Suggestions for: spire_server

**Component:** SpireServer
**CRD:** spire.spiffe.io/v1alpha1/SpireServer
**Existing Tests:** 12

---

### Suggested Tests

#### 1. test_spire_server_high_availability_failover
**Type:** Integration  
**Priority:** 🔴 High  
**Feature:** High Availability

**Description:**
Test that SPIRE Server maintains availability when the leader pod fails.

**Acceptance Criteria:**
- GIVEN a SpireServer with 3 replicas running
- WHEN the leader pod is deleted
- THEN a new leader should be elected within 30 seconds
- AND workload attestation should continue without interruption

**Test Skeleton:**
```python
def test_spire_server_high_availability_failover(
    self, spire_server, ocp_client, operator_namespace
):
    """Test HA failover when leader pod is terminated."""
    # 1. Ensure 3 replicas are running
    # 2. Identify current leader
    # 3. Delete leader pod
    # 4. Wait for new leader election
    # 5. Verify cluster health
    # 6. Test workload attestation still works
```

**Why This Test:**
- HA is critical for production deployments
- Leader election is complex and failure-prone
- Current tests don't cover failover scenarios

---

#### 2. test_spire_server_trust_bundle_custom_ca
**Type:** Positive  
**Priority:** 🟡 Medium  
**Feature:** Trust Bundle

**Description:**
Test that a custom upstream CA can be configured for the trust bundle.

**Acceptance Criteria:**
- GIVEN a custom CA certificate
- WHEN SpireServer is configured with upstream CA
- THEN the trust bundle should include the custom CA
- AND workloads should trust certificates from the custom CA

**Test Skeleton:**
```python
def test_spire_server_trust_bundle_custom_ca(
    self, spire_server_manager, ocp_client, test_namespace
):
    """Test custom upstream CA configuration."""
    # 1. Create custom CA secret
    # 2. Configure SpireServer with upstream CA
    # 3. Deploy SpireServer
    # 4. Verify trust bundle includes custom CA
    # 5. Test workload trusts custom CA issued certs
```

---

#### 3. test_spire_server_invalid_replica_count
**Type:** Negative  
**Priority:** 🟡 Medium  
**Feature:** Validation

**Description:**
Test that invalid replica counts are rejected.

**Acceptance Criteria:**
- GIVEN a SpireServer CR with invalid replica count (0, negative, even number)
- WHEN the CR is applied
- THEN it should be rejected with appropriate error message

**Test Skeleton:**
```python
@pytest.mark.parametrize("replicas,expected_error", [
    (0, "replicas must be at least 1"),
    (-1, "replicas must be positive"),
    (2, "replicas must be odd for HA"),
])
def test_spire_server_invalid_replica_count(
    self, spire_server_manager, replicas, expected_error
):
    """Test validation of invalid replica counts."""
    # 1. Create SpireServer CR with invalid replicas
    # 2. Attempt to apply
    # 3. Verify rejection with expected error
```

---

#### 4. test_spire_server_resource_limits_applied
**Type:** Positive  
**Priority:** 🟢 Low  
**Feature:** Resource Management

**Description:**
Test that custom resource limits are applied to server pods.

**Test Skeleton:**
```python
def test_spire_server_resource_limits_applied(
    self, spire_server_manager, ocp_client, operator_namespace
):
    """Test custom resource limits are applied."""
    # 1. Configure SpireServer with custom resources
    # 2. Deploy and wait for ready
    # 3. Verify pod resource limits match spec
```

---

#### 5. test_spire_server_graceful_shutdown
**Type:** Edge Case  
**Priority:** 🟢 Low  
**Feature:** Lifecycle

**Description:**
Test that server gracefully handles shutdown signals.

**Test Skeleton:**
```python
def test_spire_server_graceful_shutdown(
    self, spire_server, ocp_client, operator_namespace
):
    """Test graceful shutdown behavior."""
    # 1. Ensure server is running with active connections
    # 2. Send SIGTERM to pod
    # 3. Verify graceful termination
    # 4. Check logs for clean shutdown
```

---

### Test Type Distribution

| Type | Count | Examples |
|------|-------|----------|
| Positive | 2 | Custom CA, Resource limits |
| Negative | 1 | Invalid replicas |
| Edge Cases | 1 | Graceful shutdown |
| Integration | 1 | HA failover |

### Next Steps

1. Run `/ztwim-test:suggest spire_server --generate` to get full test code
2. Use `/ztwim-test:coverage-gap` to see what else is missing
3. Review and customize suggestions before implementing
```

### Test Types Explained

| Type | Description | When to Use |
|------|-------------|-------------|
| **Positive** | Happy path tests | Verify features work as expected |
| **Negative** | Error handling tests | Verify graceful failure |
| **Edge Cases** | Boundary conditions | Test limits and unusual scenarios |
| **Integration** | Cross-component tests | Verify component interactions |

### Feature Areas by Component

**spire_server:**
- Deployment, Scaling, HA
- Trust Bundle, Federation
- Configuration, Validation
- Metrics, Logging

**spire_agent:**
- DaemonSet, Node Coverage
- Attestation, Workload API
- Server Connectivity, Recovery
- Socket Permissions

**csi_driver:**
- Mount Operations
- Volume Lifecycle
- Error Handling
- Permissions

**oidc_discovery:**
- Endpoint Availability
- JWKS Serving
- Token Validation
- Route/Ingress

### Using --generate

With `--generate`, full test code is produced:

```
/ztwim-test:suggest spire_server --feature "high availability" --generate

## Generated Test: test_spire_server_ha_failover.py

```python
"""
Tests for SpireServer high availability and failover.

Generated by: /ztwim-test:suggest
Component: spire_server
Feature: High Availability
"""

import pytest
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.spire_server
class TestSpireServerHA:
    """Tests for SpireServer high availability scenarios."""

    def test_leader_election_on_startup(
        self, spire_server, ocp_client, operator_namespace
    ):
        """
        Test that leader election occurs on cluster startup.

        Acceptance Criteria:
        - GIVEN a SpireServer with 3 replicas
        - WHEN all pods start
        - THEN exactly one pod should become leader
        """
        logger.info("Verifying leader election on startup")
        
        # Get all server pods
        pods = ocp_client.get_pods(
            namespace=operator_namespace,
            label_selector="app=spire-server"
        )
        assert len(pods) == 3, f"Expected 3 pods, got {len(pods)}"
        
        # Check for leader
        # Implementation depends on how SPIRE exposes leader info
        logger.info("✅ Leader election verified")

    # ... more tests ...
```
```

### Tips

1. **Be specific**: Use `--feature` to get targeted suggestions
2. **Review carefully**: AI suggestions need human review
3. **Combine with coverage**: Use after `/ztwim-test:coverage-gap`
4. **Iterate**: Generate, review, refine, repeat

### Related Commands

- `/ztwim-test:coverage-gap` - Find what needs testing
- `/ztwim-test:generate-from-pr` - Generate from actual changes
- `/ztwim-test:validate` - Validate generated code

