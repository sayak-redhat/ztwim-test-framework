#!/usr/bin/env python3
"""
🤖 ZTWIM Robust Test Generator

Production-grade test generation from any GitHub PR.
Handles all PR types: features, bug fixes, refactoring, configuration changes.

Usage:
    python scripts/auto_gen.py 72 --use-cli --save --all
    python scripts/auto_gen.py https://github.com/openshift/zero-trust-workload-identity-manager/pull/72

Features:
    ✅ Detects ALL affected components
    ✅ Analyzes PR type (feature/bugfix/refactor/config)
    ✅ Generates appropriate tests for each change type
    ✅ Robust error handling with retries
    ✅ Validates generated Python code
    ✅ Meaningful test file names

Environment Variables:
    ANTHROPIC_API_KEY - Required for API mode
    GITHUB_TOKEN - Optional, for private repos or rate limits
"""

import ast
import os
import re
import subprocess
import sys
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import List, Optional, Tuple

# Setup path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests
except ImportError:
    print("❌ pip install requests")
    sys.exit(1)


# =============================================================================
# Colors for terminal output
# =============================================================================

class C:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'


def log(msg: str, color: str = ""):
    print(f"{color}{msg}{C.END if color else ''}")


def header(msg: str):
    log(f"\n{'─'*60}", C.DIM)
    log(f"  {msg}", C.CYAN + C.BOLD)
    log(f"{'─'*60}", C.DIM)


# =============================================================================
# PR Data Model
# =============================================================================

@dataclass
class PRData:
    number: int
    title: str
    description: str
    author: str
    url: str
    files: List[str]
    diff: str
    repo: str
    # Computed fields
    pr_type: str = ""  # feature, bugfix, refactor, config, test, docs
    change_summary: str = ""
    affected_components: List[str] = field(default_factory=list)


# =============================================================================
# PR Fetching with Robust Retry
# =============================================================================

def fetch_pr(pr_input: str, token: str = None, retries: int = 3) -> PRData:
    """Fetch PR details from GitHub API with robust retry logic."""
    # Parse input
    match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_input)
    if match:
        repo, pr_num = match.group(1), int(match.group(2))
    elif pr_input.isdigit():
        repo = os.getenv("GITHUB_REPO", "openshift/zero-trust-workload-identity-manager")
        pr_num = int(pr_input)
    else:
        raise ValueError(f"Invalid PR input: {pr_input}")
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    # Fetch PR metadata with retry
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}"
    data = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            break
        except (requests.exceptions.RequestException, ValueError) as e:
            if attempt < retries - 1:
                log(f"   ⚠ Retry {attempt + 1}/{retries}: {type(e).__name__}", C.YELLOW)
                _time.sleep(2 ** attempt)
            else:
                raise
    
    if not data:
        raise ValueError("Failed to fetch PR data")
    
    # Fetch files with retry
    files = []
    for attempt in range(retries):
        try:
            files_r = requests.get(f"{url}/files", headers=headers, timeout=30)
            files_r.raise_for_status()
            files_data = files_r.json()
            files = [f["filename"] for f in files_data]
            break
        except (requests.exceptions.RequestException, ValueError):
            if attempt < retries - 1:
                _time.sleep(2 ** attempt)
    
    # Fetch diff with retry (limit size)
    diff = ""
    headers_diff = {**headers, "Accept": "application/vnd.github.v3.diff"}
    for attempt in range(retries):
        try:
            diff_r = requests.get(url, headers=headers_diff, timeout=30)
            if diff_r.ok:
                diff = diff_r.text[:25000]  # Limit to avoid token overflow
            break
        except requests.exceptions.RequestException:
            if attempt < retries - 1:
                _time.sleep(2 ** attempt)
    
    pr = PRData(
        number=pr_num,
        title=data["title"],
        description=data["body"] or "",
        author=data["user"]["login"],
        url=data["html_url"],
        files=files,
        diff=diff,
        repo=repo,
    )
    
    # Analyze PR
    pr.pr_type = detect_pr_type(pr)
    pr.change_summary = generate_change_summary(pr)
    pr.affected_components = detect_components(pr.files, pr.title, pr.description)
    
    return pr


# =============================================================================
# PR Type Detection
# =============================================================================

def detect_pr_type(pr: PRData) -> str:
    """Detect the type of PR based on title, description, and files."""
    title_lower = pr.title.lower()
    desc_lower = pr.description.lower() if pr.description else ""
    
    # Check for explicit type indicators
    type_patterns = {
        "bugfix": ["fix", "bug", "issue", "error", "crash", "broken", "repair", "patch", "hotfix"],
        "feature": ["add", "implement", "feature", "new", "introduce", "create", "support"],
        "refactor": ["refactor", "move", "rename", "restructure", "reorganize", "clean", "improve"],
        "config": ["config", "configuration", "setting", "option", "parameter", "env"],
        "test": ["test", "testing", "spec", "coverage"],
        "docs": ["doc", "readme", "comment", "documentation"],
        "security": ["security", "vulnerability", "cve", "auth", "permission"],
        "performance": ["performance", "optimize", "speed", "memory", "cache"],
    }
    
    scores = {t: 0 for t in type_patterns}
    
    for pr_type, keywords in type_patterns.items():
        for keyword in keywords:
            if keyword in title_lower:
                scores[pr_type] += 3
            if keyword in desc_lower:
                scores[pr_type] += 1
    
    # Check file patterns
    for f in pr.files:
        f_lower = f.lower()
        if "_test.go" in f_lower or "test_" in f_lower:
            scores["test"] += 2
        if "config" in f_lower or "setting" in f_lower:
            scores["config"] += 2
        if ".md" in f_lower or "doc" in f_lower:
            scores["docs"] += 2
    
    best_type = max(scores, key=scores.get)
    return best_type if scores[best_type] > 0 else "feature"


def generate_change_summary(pr: PRData) -> str:
    """Generate a concise summary of what the PR changes."""
    # Extract key information
    title = pr.title
    
    # Remove ticket prefix
    title = re.sub(r'^[A-Z]+-\d+:\s*', '', title)
    
    # Identify key verbs and objects
    verbs = ["add", "fix", "remove", "update", "move", "implement", "refactor", "change", "support"]
    
    for verb in verbs:
        if verb in title.lower():
            return f"PR {verb}s {title.lower().split(verb)[-1].strip()}"
    
    return f"PR changes: {title}"


# =============================================================================
# Component Detection (Robust Multi-Component)
# =============================================================================

COMPONENT_PATTERNS = {
    "spire_server": {
        "keywords": ["spire-server", "spireserver", "spire_server"],
        "paths": ["spire-server/", "spire/server", "controller/spire-server", "spireserver"],
        "files": ["spire_server", "spireserver", "server.conf", "server.go"],
        "crds": ["spireservers"],
        "threshold": 3,
    },
    "spire_agent": {
        "keywords": ["spire-agent", "spireagent", "spire_agent"],
        "paths": ["spire-agent/", "spire/agent", "controller/spire-agent", "spireagent"],
        "files": ["spire_agent", "spireagent", "agent.conf", "agent.go"],
        "crds": ["spireagents"],
        "threshold": 3,
    },
    "csi_driver": {
        "keywords": ["csi", "spiffe-csi", "csidriver", "spiffecsi"],
        "paths": ["csi/", "spiffecsidriver", "controller/spiffe-csi", "csi-driver"],
        "files": ["csi_driver", "csidriver", "spiffe_csi"],
        "crds": ["spiffecsidriver"],
        "threshold": 3,
    },
    "oidc_discovery": {
        "keywords": ["oidc", "discovery", "oidcdiscovery", "jwt"],
        "paths": ["oidc/", "spireoidc", "controller/spire-oidc", "oidc-discovery"],
        "files": ["oidc_discovery", "oidcdiscovery", "discovery_provider"],
        "crds": ["spireoidcdiscoveryproviders"],
        "threshold": 3,
    },
    "operator": {
        "keywords": ["operator", "ztwim", "zero-trust", "manager", "controller"],
        "paths": ["cmd/", "main.go", "zero-trust-workload-identity-manager/", "pkg/operator"],
        "files": ["zero_trust_workload_identity", "ztwim", "manager"],
        "crds": ["zerotrustworkloadidentitymanagers"],
        "threshold": 2,
    },
    "workload_identity": {
        "keywords": ["workload", "identity", "svid", "spiffe-id", "attestation"],
        "paths": ["workload/", "identity/", "svid/"],
        "files": ["workload", "identity", "svid"],
        "crds": [],
        "threshold": 5,
    },
}


def detect_components(files: list, title: str = "", description: str = "") -> List[str]:
    """Detect ALL affected components with confidence scoring."""
    scores = {comp: 0 for comp in COMPONENT_PATTERNS}
    
    # Score based on files
    for f in files:
        f_lower = f.lower()
        for comp, patterns in COMPONENT_PATTERNS.items():
            # Keywords in path
            for kw in patterns["keywords"]:
                if kw in f_lower:
                    scores[comp] += 3
            # Path patterns
            for path in patterns["paths"]:
                if path in f_lower:
                    scores[comp] += 5
            # File patterns
            for file_pattern in patterns.get("files", []):
                if file_pattern in f_lower:
                    scores[comp] += 4
            # CRD patterns (strongest indicator)
            for crd in patterns.get("crds", []):
                if crd in f_lower:
                    scores[comp] += 10
    
    # Score based on title/description
    text = f"{title} {description}".lower()
    for comp, patterns in COMPONENT_PATTERNS.items():
        for kw in patterns["keywords"]:
            kw_variants = [kw, kw.replace("-", " "), kw.replace("_", " ")]
            for variant in kw_variants:
                if variant in text:
                    scores[comp] += 4
    
    # Return components meeting threshold, sorted by score
    affected = []
    for comp, patterns in COMPONENT_PATTERNS.items():
        if scores[comp] >= patterns["threshold"]:
            affected.append((comp, scores[comp]))
    
    affected.sort(key=lambda x: x[1], reverse=True)
    result = [comp for comp, _ in affected]
    
    return result if result else ["operator"]


def detect_component(files: list, title: str = "", description: str = "") -> str:
    """Detect primary component (backward compatibility)."""
    components = detect_components(files, title, description)
    return components[0] if components else "operator"


# =============================================================================
# Smart Filename Generation
# =============================================================================

STOP_WORDS = {
    'the', 'a', 'an', 'to', 'from', 'for', 'and', 'or', 'of', 'in', 'is', 'are',
    'this', 'that', 'it', 'be', 'as', 'at', 'by', 'on', 'with', 'was', 'were',
    'has', 'have', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
    'not', 'but', 'if', 'so', 'than', 'just', 'also', 'now', 'when', 'where',
    'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'only',
    'spire', 'ztwim', 'operator', 'openshift', 'kubernetes', 'pr', 'cr',
}

ACTION_WORDS = {
    'validate', 'verify', 'check', 'ensure', 'create', 'delete', 'update',
    'configure', 'deploy', 'install', 'migrate', 'upgrade', 'scale',
    'handle', 'process', 'manage', 'rotate', 'refresh', 'sync', 'connect',
    'register', 'attest', 'authorize', 'authenticate', 'fix', 'add', 'remove',
    'move', 'refactor', 'implement', 'support', 'enable', 'disable',
}


def generate_smart_filename(pr: PRData, component: str) -> str:
    """Generate distinct, short test filename per component."""
    # Component short names for distinct filenames
    COMPONENT_SHORT = {
        "spire_server": "server",
        "spire_agent": "agent",
        "csi_driver": "csi",
        "oidc_discovery": "oidc",
        "operator": "ztwim",
        "workload_identity": "workload",
    }
    
    # Remove JIRA prefix
    title = re.sub(r'^[A-Z]+-\d+:\s*', '', pr.title)
    
    # Extract words
    words = re.findall(r'[a-zA-Z]+', title.lower())
    
    # Filter stop words and component-related words
    component_words = set(component.split('_') + ['spire', 'ztwim', 'operator', 'spiffe'])
    meaningful_words = []
    
    for word in words:
        if len(word) < 3:
            continue
        if word in STOP_WORDS:
            continue
        if word in component_words:
            continue
        
        # Prioritize action words
        if word in ACTION_WORDS:
            meaningful_words.insert(0, word)
        elif len(meaningful_words) < 2:
            meaningful_words.append(word)
    
    # Get component short name
    comp_short = COMPONENT_SHORT.get(component, component.split('_')[-1])
    
    # Build filename: test_pr{N}_{component}_{feature}.py
    if meaningful_words:
        feature = '_'.join(meaningful_words[:2])
    else:
        feature = pr.pr_type if pr.pr_type else 'changes'
    
    # Clean and validate
    feature = re.sub(r'[^a-z0-9_]', '', feature)
    if not feature:
        feature = 'config'
    
    # Keep it short: test_pr72_server_config.py
    return f"test_pr{pr.number}_{comp_short}_{feature}.py"


# =============================================================================
# Framework Context (Comprehensive)
# =============================================================================

def build_framework_context(component: str, pr: PRData) -> str:
    """Build comprehensive, component-specific framework context."""
    
    # Component-specific guidance
    component_guidance = {
        "spire_server": """
### SpireServer-Specific Testing Guidance
Focus areas for SpireServer tests:
- StatefulSet deployment and pod health
- ConfigMap (server.conf) configuration values
- Service and ServiceAccount setup
- Trust domain and cluster name in configuration
- Bundle ConfigMap references
- Pod logs for errors
- Server registration entries""",
        
        "spire_agent": """
### SpireAgent-Specific Testing Guidance
Focus areas for SpireAgent tests:
- DaemonSet deployment across nodes
- ConfigMap (agent.conf) configuration values
- Node attestation configuration
- Trust domain and server address in config
- Agent-to-server connectivity
- Workload API socket availability
- Agent pod logs for attestation errors""",
        
        "csi_driver": """
### CSI Driver-Specific Testing Guidance
Focus areas for CSI Driver tests:
- CSIDriver resource registration
- DaemonSet deployment
- Volume mount capabilities
- SPIFFE workload API integration
- Pod security context requirements
- Driver pod logs for mount errors""",
        
        "oidc_discovery": """
### OIDC Discovery Provider Testing Guidance
Focus areas for OIDC tests:
- Deployment and pod health
- Service and Route configuration
- JWKS endpoint availability
- JWT issuer configuration
- Trust domain in OIDC config
- Route TLS termination
- Discovery document validity""",
        
        "operator": """
### Operator Testing Guidance
Focus areas for Operator tests:
- Operator pod deployment and health
- CRD creation and validation
- Reconciliation of all operands
- Configuration propagation to components
- OwnerReferences between CRs
- Status conditions on CRs
- Operator logs for reconciliation errors""",
        
        "workload_identity": """
### Workload Identity Testing Guidance
Focus areas for Workload Identity tests:
- SVID issuance to workloads
- SPIFFE ID format validation
- Workload attestation flow
- CSI volume mount verification
- Certificate rotation
- mTLS connectivity between workloads""",
    }
    
    # PR type specific guidance
    pr_type_guidance = {
        "bugfix": """
### Bug Fix Testing Strategy
For bug fix PRs, focus on:
1. Reproducing the original bug scenario (negative test)
2. Verifying the fix works (positive test)
3. Regression testing related functionality
4. Edge cases that might have similar issues""",
        
        "feature": """
### Feature Testing Strategy
For feature PRs, focus on:
1. Happy path - feature works as designed
2. Error handling - invalid inputs, missing dependencies
3. Integration - feature works with existing components
4. Configuration - all options work correctly""",
        
        "refactor": """
### Refactor Testing Strategy
For refactor PRs, focus on:
1. Behavior preservation - old functionality still works
2. Configuration migration - old configs still valid
3. API compatibility - existing integrations work
4. Performance - no regressions""",
        
        "config": """
### Configuration Change Testing Strategy
For config PRs, focus on:
1. New config fields are properly applied
2. Default values work correctly
3. Invalid config is rejected
4. Config changes propagate to components""",
    }
    
    comp_guide = component_guidance.get(component, "")
    type_guide = pr_type_guidance.get(pr.pr_type, pr_type_guidance["feature"])
    
    return dedent(f"""
## ZTWIM Test Framework Architecture

### Directory Structure
```
tests/
├── operator/           # Operator installation & lifecycle
├── spire_server/       # SpireServer CR tests  
├── spire_agent/        # SpireAgent DaemonSet tests
├── csi_driver/         # SPIFFE CSI Driver tests
├── oidc_discovery/     # OIDC Discovery Provider tests
└── workload_identity/  # End-to-end workload identity tests
```

### Available Fixtures

**Session-scoped (shared across all tests):**
- `ocp_client` - OpenShift client with helper methods
- `operator_namespace` - ZTWIM namespace ("zero-trust-workload-identity-manager")
- `settings` - Framework settings
- `app_domain` - OpenShift apps domain
- `jwt_issuer_endpoint` - JWT issuer URL
- `cluster_name` - ZTWIM cluster name

**CRD Managers (for CRUD operations):**
- `ztwim_manager` - ZeroTrustWorkloadIdentityManager manager
- `spire_server_manager` - SpireServer manager
- `spire_agent_manager` - SpireAgent manager  
- `csi_driver_manager` - SpiffeCSIDriver manager
- `oidc_manager` - SpireOIDCDiscoveryProvider manager

**Module-scoped (get existing CRs):**
- `ztwim_cr` - Gets ZeroTrustWorkloadIdentityManager "cluster"
- `spire_server` - Gets SpireServer "cluster"
- `spire_agent` - Gets SpireAgent "cluster"
- `spiffe_csi_driver` - Gets SpiffeCSIDriver "cluster"
- `oidc_provider` - Gets SpireOIDCDiscoveryProvider "cluster"
- `test_namespace` - Creates ephemeral test namespace

**Function-scoped:**
- `unique_name` - Generates "test-<random>" name
- `test_labels` - Standard test resource labels
- `wait_timeout` - Default timeout value
- `poll_interval` - Default poll interval

### OCP Client Methods
```python
# Get pods with selector
pods = ocp_client.get_pods(namespace=ns, label_selector="app=spire-server")

# Wait for pods ready
pods = ocp_client.wait_for_pods_ready(
    namespace=ns, label_selector="app=name", 
    expected_count=1, timeout=120
)

# Get pod logs
logs = ocp_client.get_pod_logs(name="pod", namespace=ns, container="main")

# K8s API access
deployment = ocp_client.apps_v1.read_namespaced_deployment(name, ns)
configmap = ocp_client.core_v1.read_namespaced_config_map(name, ns)
service = ocp_client.core_v1.read_namespaced_service(name, ns)

# Custom resources
cr = ocp_client.custom_objects_api.get_namespaced_custom_object(
    group="operator.openshift.io", version="v1alpha1",
    namespace=ns, plural="spireservers", name="cluster"
)
```
{comp_guide}
{type_guide}

### Required Test Format
```python
@pytest.mark.{component}
class TestFeatureName:
    \"\"\"Tests for feature description.\"\"\"
    
    def test_specific_behavior(self, ocp_client, operator_namespace):
        \"\"\"
        Test description.
        
        Acceptance Criteria:
        - GIVEN precondition
        - WHEN action performed
        - THEN expected result
        \"\"\"
        logger.info("Starting test: description")
        
        # Test implementation
        result = ocp_client.some_method()
        
        assert result is not None, "Descriptive error message"
        logger.info("✅ Test passed: description")
```
""").strip()


# =============================================================================
# Prompt Builder (Robust)
# =============================================================================

def build_prompt(pr: PRData, component: str) -> str:
    """Build comprehensive prompt for robust test generation."""
    files_list = "\n".join(f"  - {f}" for f in pr.files[:40])
    framework_context = build_framework_context(component, pr)
    
    # Truncate diff if too long
    diff = pr.diff
    if len(diff) > 15000:
        diff = diff[:15000] + "\n... (diff truncated for brevity)"
    
    return dedent(f"""
You are an expert Python test engineer generating production-quality pytest tests for OpenShift/Kubernetes operators.

# Pull Request #{pr.number}

**Title:** {pr.title}
**Author:** @{pr.author}
**URL:** {pr.url}
**Type:** {pr.pr_type}
**Component:** {component}

## Description
{pr.description[:4000] if pr.description else "No description provided."}

## Change Summary
{pr.change_summary}

## Files Changed ({len(pr.files)} files)
{files_list}

## Code Diff
```diff
{diff}
```

{framework_context}

# TEST GENERATION REQUIREMENTS

Generate a complete pytest test file for the `{component}` component.

## Mandatory Requirements:
1. Module docstring with PR reference and test coverage description
2. Import: `from src.utils.logger import get_logger; logger = get_logger(__name__)`
3. Use decorator: `@pytest.mark.{component}` on test class
4. GIVEN/WHEN/THEN acceptance criteria in every test docstring
5. Descriptive assertion messages
6. Use appropriate fixtures from the framework
7. Include both positive tests and error/edge case tests where applicable

## Test Categories to Include:
1. **Deployment/Health Tests** - Verify pods/deployments are running
2. **Configuration Tests** - Verify configs are correctly applied
3. **Integration Tests** - Verify component integrates with others
4. **Validation Tests** - Verify invalid inputs are rejected (if applicable)

## For {pr.pr_type.upper()} PRs specifically:
{"- Test that the bug is fixed and doesn't regress" if pr.pr_type == "bugfix" else ""}
{"- Test all new functionality paths" if pr.pr_type == "feature" else ""}
{"- Test backward compatibility and behavior preservation" if pr.pr_type == "refactor" else ""}
{"- Test new configuration options and defaults" if pr.pr_type == "config" else ""}

Generate 8-15 meaningful test methods covering the PR changes.
Output ONLY valid Python code. No markdown fences. No explanations.
""").strip()


# =============================================================================
# Code Generation & Validation
# =============================================================================

def generate_with_cli(prompt: str, retries: int = 2) -> str:
    """Generate using Claude CLI with retry."""
    for attempt in range(retries):
        try:
            subprocess.run(["claude", "--version"], capture_output=True, check=True, timeout=10)
            break
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            if attempt == retries - 1:
                raise RuntimeError("Claude CLI not found. Install: npm install -g @anthropic-ai/claude-code")
    
    result = subprocess.run(
        ["claude", "--print"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=600  # 10 minute timeout
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI error: {result.stderr}")
    
    return result.stdout


def generate_with_api(prompt: str) -> str:
    """Generate using Anthropic Python API."""
    try:
        import anthropic
    except ImportError:
        raise ImportError("pip install anthropic")
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Set ANTHROPIC_API_KEY environment variable")
    
    client = anthropic.Anthropic(api_key=api_key)
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system="You are an expert Python test engineer. Generate only valid, runnable Python pytest code. No markdown. No explanations.",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return message.content[0].text


def clean_code(code: str) -> str:
    """Clean generated code - remove markdown, validate Python."""
    # Remove markdown fences
    code = re.sub(r'^```python\s*\n?', '', code)
    code = re.sub(r'^```\s*\n?', '', code, flags=re.MULTILINE)
    code = re.sub(r'\n?```\s*$', '', code)
    
    # Remove any leading/trailing whitespace
    code = code.strip()
    
    # Ensure trailing newline
    code = code + '\n'
    
    return code


def validate_python(code: str) -> Tuple[bool, str]:
    """Validate that code is syntactically correct Python."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"


def fix_common_issues(code: str) -> str:
    """Attempt to fix common generation issues."""
    # Fix missing imports
    if "logger = get_logger" in code and "from src.utils.logger import get_logger" not in code:
        code = "from src.utils.logger import get_logger\n\n" + code
    
    if "import pytest" not in code and "@pytest.mark" in code:
        code = "import pytest\n" + code
    
    # Fix indentation issues (tabs to spaces)
    code = code.replace('\t', '    ')
    
    return code


# =============================================================================
# Main Generation Logic
# =============================================================================

def generate_for_component(pr: PRData, component: str, args, is_multi: bool = False) -> Tuple[str, str, int]:
    """Generate tests for a single component."""
    # Generate filename
    filename = generate_smart_filename(pr, component)
    output_path = f"tests/{component}/{filename}"
    
    if not is_multi:
        log(f"📁 Output: {output_path}", C.CYAN)
        log("\n🧠 Building prompt...", C.YELLOW)
    
    # Build prompt
    prompt = build_prompt(pr, component)
    
    if not is_multi:
        log(f"   ✓ Prompt: {len(prompt)} chars", C.DIM)
        log("\n⚡ Generating tests...", C.YELLOW)
    
    # Generate
    if args.use_cli:
        code = generate_with_cli(prompt)
    else:
        code = generate_with_api(prompt)
    
    code = clean_code(code)
    code = fix_common_issues(code)
    
    # Validate
    is_valid, error = validate_python(code)
    if not is_valid:
        log(f"   ⚠ Syntax issue: {error} - attempting fix", C.YELLOW)
        code = fix_common_issues(code)
        is_valid, error = validate_python(code)
        if not is_valid:
            log(f"   ⚠ Code has syntax errors, may need manual review", C.YELLOW)
    
    test_count = code.count('def test_')
    
    return output_path, code, test_count


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="🤖 Robust test generator from GitHub PR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
Examples:
  %(prog)s 72                        Generate for primary component
  %(prog)s 72 --all                  Generate for ALL affected components
  %(prog)s 72 --use-cli --save       Use Claude CLI, auto-save
  %(prog)s 72 -c spire_server        Force specific component
  %(prog)s 72 --dry-run              Preview without saving
        """)
    )
    parser.add_argument("pr", help="PR number or full GitHub URL")
    parser.add_argument("--all", "-a", action="store_true", help="Generate for ALL affected components")
    parser.add_argument("--save", "-s", action="store_true", help="Save without prompting")
    parser.add_argument("--use-cli", action="store_true", help="Use Claude CLI")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview only")
    parser.add_argument("--component", "-c", help="Override component detection")
    parser.add_argument("--output", "-o", help="Override output path")
    args = parser.parse_args()
    
    header("🤖 ZTWIM Robust Test Generator")
    
    try:
        # Fetch PR
        log("\n📥 Fetching PR details...", C.YELLOW)
        token = os.getenv("GITHUB_TOKEN")
        pr = fetch_pr(args.pr, token)
        log(f"   ✓ PR #{pr.number}: {pr.title}", C.GREEN)
        log(f"   ✓ Type: {pr.pr_type} | Files: {len(pr.files)} | Author: @{pr.author}", C.DIM)
        
        # Detect components
        if args.component:
            components = [args.component]
        else:
            components = pr.affected_components
        
        log(f"\n🎯 Affected components: {', '.join(components)}", C.CYAN)
        
        # Determine target components
        if args.all:
            target_components = components
            log(f"   → Generating for ALL {len(target_components)} components", C.GREEN)
        else:
            target_components = [components[0]]
            if len(components) > 1:
                log(f"   → Using primary: {components[0]} (use --all for all)", C.YELLOW)
        
        # Generate
        generated_files = []
        total_tests = 0
        
        for i, component in enumerate(target_components):
            if len(target_components) > 1:
                log(f"\n{'─'*40}", C.DIM)
                log(f"📦 [{i+1}/{len(target_components)}] {component}", C.CYAN)
            
            try:
                output_path, code, test_count = generate_for_component(
                    pr, component, args, is_multi=(len(target_components) > 1)
                )
                
                log(f"   ✓ Generated {len(code)} chars, {test_count} tests", C.GREEN)
                
                if args.dry_run:
                    header(f"Generated: {component}")
                    print(code[:3500])
                    if len(code) > 3500:
                        log(f"\n... ({len(code) - 3500} more chars)", C.DIM)
                    continue
                
                full_path = PROJECT_ROOT / output_path
                
                if args.save or len(target_components) > 1:
                    do_save = True
                else:
                    header("Generated Code Preview")
                    print(code[:2500])
                    if len(code) > 2500:
                        log(f"\n... ({len(code) - 2500} more chars)", C.DIM)
                    response = input(f"\n💾 Save to {output_path}? [y/N]: ")
                    do_save = response.lower() in ('y', 'yes')
                
                if do_save:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(code)
                    generated_files.append(output_path)
                    total_tests += test_count
                    log(f"   💾 Saved: {output_path}", C.GREEN)
                    
            except Exception as e:
                log(f"   ❌ Failed for {component}: {e}", C.RED)
                continue
        
        # Summary
        if not args.dry_run and generated_files:
            header("✅ Generation Complete!")
            log(f"📊 Summary:", C.CYAN)
            log(f"   • PR Type: {pr.pr_type}")
            log(f"   • Files generated: {len(generated_files)}")
            log(f"   • Total tests: {total_tests}")
            log(f"\n📁 Generated:", C.GREEN)
            for f in generated_files:
                log(f"   • {f}")
            log(f"\n🧪 Run tests:", C.YELLOW)
            if len(generated_files) == 1:
                log(f"   pytest {generated_files[0]} -v")
            else:
                log(f"   pytest tests/*/test_pr{pr.number}_*.py -v")
            log(f"\n📝 Review generated tests before running.", C.DIM)
        elif args.dry_run:
            log("\n📝 Dry-run complete.", C.YELLOW)
            
    except requests.exceptions.HTTPError as e:
        if hasattr(e, 'response') and e.response.status_code == 404:
            log(f"\n❌ PR not found: {args.pr}", C.RED)
        else:
            log(f"\n❌ GitHub error: {e}", C.RED)
        sys.exit(1)
    except KeyboardInterrupt:
        log("\n\n⚠️ Interrupted by user", C.YELLOW)
        sys.exit(130)
    except Exception as e:
        log(f"\n❌ Error: {e}", C.RED)
        if os.getenv("DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
