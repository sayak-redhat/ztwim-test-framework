---
name: coverage-gap
description: Identify test coverage gaps for ZTWIM components
arguments:
  - name: --component
    description: Specific component to analyze
    required: false
    type: string
    options: [operator, spire_server, spire_agent, csi_driver, oidc_discovery, all]
    default: all
  - name: --suggest
    description: Generate test suggestions for gaps
    required: false
    type: boolean
    default: false
  - name: --recent-prs
    description: Number of recent PRs to check for untested changes
    required: false
    type: integer
    default: 10
  - name: --output
    description: Output format
    required: false
    type: string
    options: [text, markdown, json]
    default: markdown
---

# Coverage Gap Analysis

Identify areas of ZTWIM functionality that lack test coverage.

## Sections

### What This Command Does

This command performs a comprehensive analysis to find untested functionality:

1. **Existing Test Analysis**: Catalogs all current tests by feature area
2. **CRD Capability Mapping**: Maps CRD fields to expected test coverage
3. **Recent PR Review**: Checks if recent PRs have corresponding tests
4. **Feature Matrix**: Compares implemented features vs tested features
5. **Gap Identification**: Highlights untested areas
6. **Suggestions**: Optionally generates test suggestions

### Prerequisites

- Access to the ZTWIM test framework repository
- Git CLI for PR history
- Claude CLI or API for suggestions

### Input

Optional component filter and analysis options.

**Examples:**
```
/ztwim-test:coverage-gap
/ztwim-test:coverage-gap --component spire_server
/ztwim-test:coverage-gap --component spire_agent --suggest
/ztwim-test:coverage-gap --recent-prs 20 --output json
```

### Output Format

```markdown
## ZTWIM Test Coverage Gap Analysis

**Generated:** 2025-12-24
**Framework Version:** 1.0.0

---

### Summary

| Component | Tests | Coverage Areas | Gaps | Score |
|-----------|-------|----------------|------|-------|
| operator | 5 | 3 | 1 | 75% |
| spire_server | 12 | 8 | 3 | 73% |
| spire_agent | 8 | 5 | 2 | 71% |
| csi_driver | 6 | 4 | 2 | 67% |
| oidc_discovery | 7 | 5 | 1 | 83% |

---

### Component: spire_server

#### ✅ Covered Areas
| Feature | Test Count | Test Files |
|---------|------------|------------|
| Deployment basics | 3 | test_spire_server_deployment.py |
| StatefulSet scaling | 2 | test_spire_server_deployment.py |
| Service creation | 2 | test_spire_server_deployment.py |
| Pod readiness | 2 | test_spire_server_deployment.py |
| ConfigMap generation | 1 | test_spire_server_deployment.py |
| PVC creation | 1 | test_spire_server_deployment.py |
| Log verification | 1 | test_spire_server_deployment.py |

#### ❌ Coverage Gaps

1. **High Availability / Failover**
   - No tests for leader election
   - No tests for failover scenarios
   - No tests for quorum loss recovery
   - CRD field: `spec.replicas` (scaling behavior untested)

2. **Trust Bundle Management**
   - No tests for bundle rotation
   - No tests for custom CA injection
   - No tests for bundle propagation to agents
   - CRD field: `spec.trustDomain` variations

3. **Federation Configuration**
   - No tests for federation setup
   - No tests for cross-cluster trust
   - No tests for bundle endpoint exposure

4. **Advanced Configuration**
   - `spec.controllerManagerConfig` untested
   - Custom annotations/labels untested
   - Resource limits/requests validation untested

#### 📊 Recent Untested PRs

| PR | Title | Merged | Has Tests? |
|----|-------|--------|------------|
| #92 | Add server metrics endpoint | 2025-12-20 | ❌ No |
| #89 | Implement bundle rotation | 2025-12-18 | ❌ No |
| #85 | Add HA leader election | 2025-12-15 | ❌ No |

---

### Component: spire_agent

#### ✅ Covered Areas
| Feature | Test Count |
|---------|------------|
| DaemonSet deployment | 2 |
| Node attestation | 1 |
| Workload API socket | 2 |
| Server connectivity | 2 |
| Basic health check | 1 |

#### ❌ Coverage Gaps

1. **Workload Attestation**
   - No tests for k8s workload attestor
   - No tests for selector matching
   - No tests for SVID issuance to workloads

2. **Recovery Scenarios**
   - No tests for agent restart recovery
   - No tests for server connection loss handling
   - No tests for node drain behavior

---

### Suggested Test Priorities

| Priority | Component | Gap | Suggested Test |
|----------|-----------|-----|----------------|
| 🔴 High | spire_server | HA failover | test_server_leader_failover |
| 🔴 High | spire_agent | Workload attestation | test_workload_svid_issuance |
| 🟡 Medium | spire_server | Bundle rotation | test_trust_bundle_rotation |
| 🟡 Medium | csi_driver | Mount failures | test_csi_mount_error_handling |
| 🟢 Low | oidc_discovery | Token validation | test_jwt_svid_validation |
```

### Coverage Scoring Methodology

The coverage score is calculated based on:

```
Score = (Covered Features / Total Expected Features) × 100

Where Expected Features include:
- CRD spec fields requiring validation
- Standard Kubernetes resource verification
- Error handling scenarios
- Integration points
```

### Gap Categories

| Category | Description | Priority |
|----------|-------------|----------|
| **Core Functionality** | Basic CRUD operations | 🔴 High |
| **Error Handling** | Negative test cases | 🔴 High |
| **Scaling/HA** | Multi-replica scenarios | 🟡 Medium |
| **Integration** | Cross-component tests | 🟡 Medium |
| **Edge Cases** | Boundary conditions | 🟢 Low |
| **Performance** | Load/stress tests | 🟢 Low |

### Using with --suggest

When `--suggest` is enabled, the command generates actionable test suggestions:

```
/ztwim-test:coverage-gap --component spire_server --suggest

## Suggested Tests for spire_server

### 1. test_server_leader_election
```python
def test_server_leader_election(self, spire_server, ocp_client):
    """Test that leader election works with multiple replicas."""
    # Scale to 3 replicas
    # Verify one pod becomes leader
    # Kill leader pod
    # Verify new leader elected
```

### 2. test_trust_bundle_rotation
```python
def test_trust_bundle_rotation(self, spire_server, ocp_client):
    """Test trust bundle automatic rotation."""
    # Configure rotation interval
    # Wait for rotation
    # Verify new bundle is propagated
```
```

### Tips

1. **Start with high-priority gaps**: Focus on core functionality first
2. **Use with CI**: Run periodically to track coverage trends
3. **Export JSON**: Use `--output json` for programmatic processing
4. **Recent PRs**: Increase `--recent-prs` for thorough audit

### Related Commands

- `/ztwim-test:suggest` - Get detailed test suggestions
- `/ztwim-test:generate-from-pr` - Generate tests for specific PR
- `/ztwim-test:validate` - Validate existing tests

