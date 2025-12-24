#!/usr/bin/env python3
"""
ZTWIM Test Generator - Claude Code Plugin Script

This script powers the /ztwim-test:* commands for generating pytest tests
from PRs that run against OpenShift clusters.

Usage:
    python ztwim_test_generator.py generate-from-pr <pr_number> [options]
    python ztwim_test_generator.py analyze-pr <pr_number>
    python ztwim_test_generator.py coverage-gap [--component COMPONENT]
    python ztwim_test_generator.py suggest <component>
    python ztwim_test_generator.py validate <path>
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# ============================================================================
# Configuration
# ============================================================================

GITHUB_REPO = "openshift/zero-trust-workload-identity-manager"
GITHUB_API = "https://api.github.com"

# Component detection patterns
COMPONENT_PATTERNS = {
    "spire_server": [
        r"pkg/controller/spireserver",
        r"api/v1alpha1/spireserver",
        r"config/crd.*spireserver",
        r"spire.*server",
    ],
    "spire_agent": [
        r"pkg/controller/spireagent",
        r"api/v1alpha1/spireagent",
        r"config/crd.*spireagent",
        r"spire.*agent",
    ],
    "oidc_discovery": [
        r"pkg/controller/oidc",
        r"api/v1alpha1/oidc",
        r"oidc.*provider",
        r"oidc.*discovery",
    ],
    "csi_driver": [
        r"pkg/controller/csidriver",
        r"pkg/controller/spiffecsidriver",
        r"api/v1alpha1/spiffecsidriver",
        r"csi.*driver",
    ],
    "operator": [
        r"pkg/controller/ztwim",
        r"cmd/manager",
        r"main\.go",
    ],
}

# Test directory mapping
COMPONENT_DIRS = {
    "spire_server": "spire_server",
    "spire_agent": "spire_agent",
    "oidc_discovery": "oidc_discovery",
    "csi_driver": "csi_driver",
    "operator": "operator",
}

# Framework fixtures reference
FIXTURES = {
    "session": [
        ("ocp_client", "OpenShift/Kubernetes client"),
        ("operator_namespace", "ZTWIM operator namespace"),
        ("settings", "Framework settings from config"),
        ("app_domain", "OpenShift apps domain"),
        ("cluster_name", "ZTWIM cluster name"),
    ],
    "module": [
        ("spire_server", "SpireServer CR object"),
        ("spire_agent", "SpireAgent CR object"),
        ("spiffe_csi_driver", "SpiffeCSIDriver CR object"),
        ("oidc_provider", "SpireOIDCDiscoveryProvider CR object"),
        ("test_namespace", "Ephemeral test namespace"),
    ],
    "function": [
        ("unique_name", "Generates unique resource names"),
        ("test_labels", "Standard labels for test resources"),
        ("wait_timeout", "Default timeout value (120s)"),
        ("poll_interval", "Default poll interval (5s)"),
    ],
}


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PRDetails:
    """Pull Request details."""
    number: int
    title: str
    description: str
    author: str
    labels: List[str]
    files: List[Dict[str, Any]]
    diff: str
    url: str
    state: str
    merged: bool = False


@dataclass
class PRAnalysis:
    """Analysis of a Pull Request."""
    pr: PRDetails
    components: List[str]
    change_type: str  # feature, bugfix, refactor, config
    affected_crds: List[str]
    key_changes: List[str]
    test_scenarios: List[Dict[str, Any]]


@dataclass
class TestCase:
    """A generated test case."""
    name: str
    description: str
    acceptance_criteria: List[str]
    component: str
    fixtures: List[str]
    markers: List[str]
    code: str


# ============================================================================
# GitHub API Functions
# ============================================================================

def github_request(endpoint: str, repo: str = GITHUB_REPO) -> Optional[Dict]:
    """Make a GitHub API request with retry logic."""
    url = f"{GITHUB_API}/repos/{repo}/{endpoint}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    
    for attempt in range(3):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 403:  # Rate limit
                print(f"⚠️  Rate limited, waiting...")
                time.sleep(60)
            else:
                print(f"⚠️  HTTP {e.code}, retrying...")
                time.sleep(2 ** attempt)
        except URLError as e:
            print(f"⚠️  Network error: {e}, retrying...")
            time.sleep(2 ** attempt)
    
    return None


def fetch_pr_details(pr_number: int, repo: str = GITHUB_REPO) -> Optional[PRDetails]:
    """Fetch complete PR details from GitHub."""
    print(f"🔍 Fetching PR #{pr_number}...")
    
    # Get PR metadata
    pr_data = github_request(f"pulls/{pr_number}", repo)
    if not pr_data:
        return None
    
    # Get files changed
    files_data = github_request(f"pulls/{pr_number}/files", repo) or []
    
    # Build diff from patches
    diff_parts = []
    for f in files_data:
        if f.get("patch"):
            diff_parts.append(f"--- {f['filename']}\n{f['patch']}")
    
    return PRDetails(
        number=pr_number,
        title=pr_data.get("title", ""),
        description=pr_data.get("body", "") or "",
        author=pr_data.get("user", {}).get("login", ""),
        labels=[l.get("name", "") for l in pr_data.get("labels", [])],
        files=files_data,
        diff="\n\n".join(diff_parts),
        url=pr_data.get("html_url", ""),
        state=pr_data.get("state", ""),
        merged=pr_data.get("merged", False),
    )


# ============================================================================
# PR Analysis Functions
# ============================================================================

def detect_components(pr: PRDetails) -> List[str]:
    """Detect which ZTWIM components are affected by the PR."""
    components = set()
    
    # Check file paths
    for file_info in pr.files:
        filepath = file_info.get("filename", "")
        for component, patterns in COMPONENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, filepath, re.IGNORECASE):
                    components.add(component)
    
    # Check PR title and description
    text = f"{pr.title} {pr.description}".lower()
    component_keywords = {
        "spire_server": ["spire server", "spireserver", "server"],
        "spire_agent": ["spire agent", "spireagent", "agent"],
        "oidc_discovery": ["oidc", "discovery", "jwt"],
        "csi_driver": ["csi", "driver", "mount"],
        "operator": ["operator", "controller", "manager"],
    }
    
    for component, keywords in component_keywords.items():
        for keyword in keywords:
            if keyword in text:
                components.add(component)
    
    return list(components) if components else ["operator"]


def detect_change_type(pr: PRDetails) -> str:
    """Detect the type of change in the PR."""
    title_lower = pr.title.lower()
    labels_lower = [l.lower() for l in pr.labels]
    
    if any(x in title_lower for x in ["fix", "bug", "issue", "patch"]):
        return "bugfix"
    if any(x in labels_lower for x in ["bug", "bugfix"]):
        return "bugfix"
    if any(x in title_lower for x in ["refactor", "cleanup", "reorganize"]):
        return "refactor"
    if any(x in title_lower for x in ["config", "yaml", "manifest"]):
        return "config"
    
    return "feature"


def extract_key_changes(pr: PRDetails) -> List[str]:
    """Extract key changes from the PR diff."""
    changes = []
    
    for file_info in pr.files:
        filename = file_info.get("filename", "")
        status = file_info.get("status", "")
        additions = file_info.get("additions", 0)
        deletions = file_info.get("deletions", 0)
        
        if status == "added":
            changes.append(f"Added new file: {filename}")
        elif status == "removed":
            changes.append(f"Removed file: {filename}")
        elif additions > 0 or deletions > 0:
            changes.append(f"Modified {filename} (+{additions}/-{deletions})")
        
        # Look for specific patterns in patch
        patch = file_info.get("patch", "")
        
        # New fields in CRD
        if "_types.go" in filename:
            new_fields = re.findall(r'\+\s+(\w+)\s+\w+\s+`json:"(\w+)', patch)
            for field_name, json_name in new_fields:
                changes.append(f"Added CRD field: {json_name}")
        
        # New functions
        new_funcs = re.findall(r'\+func\s+(\w+)\s*\(', patch)
        for func in new_funcs:
            if not func.startswith("Test"):
                changes.append(f"Added function: {func}")
    
    return changes[:10]  # Limit to 10 most relevant


def generate_test_scenarios(pr: PRDetails, components: List[str], change_type: str) -> List[Dict]:
    """Generate test scenarios based on PR analysis."""
    scenarios = []
    
    # Base scenarios for each change type
    if change_type == "feature":
        scenarios.append({
            "type": "positive",
            "name": "feature_works_correctly",
            "description": f"Verify the new feature from PR #{pr.number} works as expected",
            "priority": "high",
        })
        scenarios.append({
            "type": "negative",
            "name": "feature_handles_invalid_input",
            "description": "Verify proper error handling for invalid inputs",
            "priority": "medium",
        })
    
    elif change_type == "bugfix":
        scenarios.append({
            "type": "regression",
            "name": "bug_is_fixed",
            "description": f"Verify the bug from PR #{pr.number} is fixed",
            "priority": "high",
        })
        scenarios.append({
            "type": "regression",
            "name": "no_regression",
            "description": "Verify existing functionality still works",
            "priority": "high",
        })
    
    # Component-specific scenarios
    for component in components:
        if component == "spire_server":
            scenarios.extend([
                {"type": "deployment", "name": "server_deploys_correctly", "description": "SpireServer deploys and becomes ready", "priority": "high"},
                {"type": "integration", "name": "server_accepts_agent_connections", "description": "Server accepts agent attestation", "priority": "medium"},
            ])
        elif component == "spire_agent":
            scenarios.extend([
                {"type": "deployment", "name": "agent_runs_on_all_nodes", "description": "SpireAgent DaemonSet runs on all nodes", "priority": "high"},
                {"type": "integration", "name": "agent_attests_workloads", "description": "Agent can attest workloads", "priority": "medium"},
            ])
        elif component == "oidc_discovery":
            scenarios.extend([
                {"type": "deployment", "name": "oidc_endpoint_available", "description": "OIDC discovery endpoint is accessible", "priority": "high"},
                {"type": "integration", "name": "jwks_serves_keys", "description": "JWKS endpoint serves valid keys", "priority": "medium"},
            ])
        elif component == "csi_driver":
            scenarios.extend([
                {"type": "deployment", "name": "csi_driver_running", "description": "CSI driver pods are running", "priority": "high"},
                {"type": "integration", "name": "volumes_mount_correctly", "description": "SPIFFE volumes mount in pods", "priority": "medium"},
            ])
    
    return scenarios


def analyze_pr(pr: PRDetails) -> PRAnalysis:
    """Perform complete analysis of a PR."""
    components = detect_components(pr)
    change_type = detect_change_type(pr)
    key_changes = extract_key_changes(pr)
    
    # Detect affected CRDs
    affected_crds = []
    crd_patterns = {
        "SpireServer": r"spireserver",
        "SpireAgent": r"spireagent",
        "SpiffeCSIDriver": r"spiffecsidriver|csidriver",
        "SpireOIDCDiscoveryProvider": r"oidc|discovery",
        "ZeroTrustWorkloadIdentityManager": r"ztwim|zerotrust",
    }
    
    files_text = " ".join(f.get("filename", "") for f in pr.files)
    for crd, pattern in crd_patterns.items():
        if re.search(pattern, files_text, re.IGNORECASE):
            affected_crds.append(crd)
    
    # Generate test scenarios
    scenarios = generate_test_scenarios(pr, components, change_type)
    
    return PRAnalysis(
        pr=pr,
        components=components,
        change_type=change_type,
        affected_crds=affected_crds,
        key_changes=key_changes,
        test_scenarios=scenarios,
    )


# ============================================================================
# Test Generation Functions
# ============================================================================

def generate_test_name(pr: PRDetails, component: str) -> str:
    """Generate a meaningful test filename."""
    # Extract key words from title
    title = pr.title.lower()
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "is", "are", "was", "were", "add", "update", "fix"}
    
    words = re.findall(r'\b[a-z]+\b', title)
    key_words = [w for w in words if w not in stop_words and len(w) > 2][:3]
    
    if key_words:
        feature = "_".join(key_words)
    else:
        feature = "changes"
    
    return f"test_pr{pr.number}_{feature}.py"


def generate_test_code(analysis: PRAnalysis, component: str) -> str:
    """Generate complete test code for a component."""
    pr = analysis.pr
    
    # Determine which fixtures to use
    fixtures = ["ocp_client", "operator_namespace"]
    if component == "spire_server":
        fixtures.extend(["spire_server", "spire_server_manager"])
    elif component == "spire_agent":
        fixtures.extend(["spire_agent", "spire_agent_manager"])
    elif component == "oidc_discovery":
        fixtures.extend(["oidc_provider", "oidc_manager"])
    elif component == "csi_driver":
        fixtures.extend(["spiffe_csi_driver", "csi_driver_manager"])
    
    # Build test class
    class_name = "".join(word.capitalize() for word in component.split("_"))
    
    # Generate test methods based on scenarios
    test_methods = []
    for scenario in analysis.test_scenarios:
        method_name = f"test_{scenario['name']}"
        test_methods.append(generate_test_method(
            method_name=method_name,
            description=scenario["description"],
            component=component,
            fixtures=fixtures,
            pr=pr,
            scenario_type=scenario["type"],
        ))
    
    # If no scenarios, generate basic deployment test
    if not test_methods:
        test_methods.append(generate_test_method(
            method_name=f"test_{component}_pr{pr.number}_changes",
            description=f"Verify changes from PR #{pr.number}",
            component=component,
            fixtures=fixtures,
            pr=pr,
            scenario_type="deployment",
        ))
    
    code = f'''"""
Tests for {component} changes from PR #{pr.number}.

Generated from: PR #{pr.number}
PR Title: {pr.title}
PR URL: {pr.url}
Component: {component}
Change Type: {analysis.change_type}

Key Changes:
{chr(10).join(f"- {c}" for c in analysis.key_changes[:5])}
"""

import pytest
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.{component}
class Test{class_name}PR{pr.number}:
    """
    Tests for {component} changes from PR #{pr.number}.
    
    PR: {pr.title}
    """

{chr(10).join(test_methods)}
'''
    
    return code


def generate_test_method(
    method_name: str,
    description: str,
    component: str,
    fixtures: List[str],
    pr: PRDetails,
    scenario_type: str,
) -> str:
    """Generate a single test method."""
    
    # Build fixture parameters
    fixture_params = ", ".join(fixtures)
    
    # Generate implementation based on component and scenario type
    impl = generate_test_implementation(component, scenario_type, fixtures)
    
    return f'''    def {method_name}(self, {fixture_params}):
        """
        {description}

        Acceptance Criteria:
        - GIVEN the {component} is deployed in the cluster
        - WHEN we verify the changes from PR #{pr.number}
        - THEN the expected behavior should be observed
        
        PR: #{pr.number}
        """
        logger.info("Starting test: {method_name}")
        
{impl}
        
        logger.info("✅ Test passed: {method_name}")
'''


def generate_test_implementation(component: str, scenario_type: str, fixtures: List[str]) -> str:
    """Generate test implementation code based on component and scenario."""
    
    indent = "        "
    
    if component == "spire_server":
        if scenario_type == "deployment":
            return f'''{indent}# Verify SpireServer StatefulSet is ready
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-server"
{indent})
{indent}assert len(pods) > 0, "No SpireServer pods found"
{indent}
{indent}for pod in pods:
{indent}    assert pod.status.phase == "Running", f"Pod {{pod.metadata.name}} is not running"
{indent}    logger.info(f"SpireServer pod {{pod.metadata.name}} is running")
{indent}
{indent}# Verify StatefulSet
{indent}sts_list = ocp_client.apps_v1.list_namespaced_stateful_set(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-server"
{indent})
{indent}assert len(sts_list.items) > 0, "SpireServer StatefulSet not found"
{indent}sts = sts_list.items[0]
{indent}assert sts.status.ready_replicas == sts.spec.replicas, "Not all replicas ready"'''
        
        elif scenario_type == "integration":
            return f'''{indent}# Verify SpireServer is accepting connections
{indent}service = ocp_client.core_v1.read_namespaced_service(
{indent}    name="spire-server",
{indent}    namespace=operator_namespace
{indent})
{indent}assert service is not None, "SpireServer service not found"
{indent}
{indent}# Check server logs for successful startup
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-server"
{indent})
{indent}if pods:
{indent}    logs = ocp_client.get_pod_logs(
{indent}        name=pods[0].metadata.name,
{indent}        namespace=operator_namespace,
{indent}        container="spire-server"
{indent}    )
{indent}    assert "Starting Server APIs" in logs or "listening" in logs.lower(), "Server not started properly"'''
    
    elif component == "spire_agent":
        if scenario_type == "deployment":
            return f'''{indent}# Verify SpireAgent DaemonSet is running on all nodes
{indent}ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-agent"
{indent})
{indent}assert len(ds_list.items) > 0, "SpireAgent DaemonSet not found"
{indent}ds = ds_list.items[0]
{indent}
{indent}logger.info(f"DaemonSet desired: {{ds.status.desired_number_scheduled}}, ready: {{ds.status.number_ready}}")
{indent}assert ds.status.number_ready == ds.status.desired_number_scheduled, \\
{indent}    f"Not all agents ready: {{ds.status.number_ready}}/{{ds.status.desired_number_scheduled}}"
{indent}
{indent}# Verify agent pods
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-agent"
{indent})
{indent}for pod in pods:
{indent}    assert pod.status.phase == "Running", f"Agent pod {{pod.metadata.name}} not running"'''
        
        elif scenario_type == "integration":
            return f'''{indent}# Verify agent can communicate with server
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-agent"
{indent})
{indent}assert len(pods) > 0, "No SpireAgent pods found"
{indent}
{indent}# Check agent logs for successful attestation
{indent}logs = ocp_client.get_pod_logs(
{indent}    name=pods[0].metadata.name,
{indent}    namespace=operator_namespace,
{indent}    container="spire-agent"
{indent})
{indent}assert "Successfully attested" in logs or "SVID" in logs, \\
{indent}    "Agent attestation not successful"'''
    
    elif component == "oidc_discovery":
        if scenario_type == "deployment":
            return f'''{indent}# Verify OIDC Discovery Provider is running
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-oidc-discovery-provider"
{indent})
{indent}assert len(pods) > 0, "No OIDC Discovery pods found"
{indent}
{indent}for pod in pods:
{indent}    assert pod.status.phase == "Running", f"OIDC pod {{pod.metadata.name}} not running"
{indent}
{indent}# Verify service exists
{indent}services = ocp_client.core_v1.list_namespaced_service(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spire-oidc-discovery-provider"
{indent})
{indent}assert len(services.items) > 0, "OIDC Discovery service not found"'''
        
        elif scenario_type == "integration":
            return f'''{indent}# Verify OIDC endpoint is accessible
{indent}# Note: This requires route/ingress to be configured
{indent}routes = ocp_client.get_routes(namespace=operator_namespace)
{indent}oidc_routes = [r for r in routes if "oidc" in r.metadata.name.lower()]
{indent}
{indent}if oidc_routes:
{indent}    route = oidc_routes[0]
{indent}    logger.info(f"OIDC Route: {{route.spec.host}}")
{indent}    # Additional verification can be done via HTTP request'''
    
    elif component == "csi_driver":
        if scenario_type == "deployment":
            return f'''{indent}# Verify SPIFFE CSI Driver is running
{indent}ds_list = ocp_client.apps_v1.list_namespaced_daemon_set(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/name=spiffe-csi-driver"
{indent})
{indent}assert len(ds_list.items) > 0, "SPIFFE CSI Driver DaemonSet not found"
{indent}ds = ds_list.items[0]
{indent}
{indent}assert ds.status.number_ready == ds.status.desired_number_scheduled, \\
{indent}    f"Not all CSI driver pods ready: {{ds.status.number_ready}}/{{ds.status.desired_number_scheduled}}"
{indent}
{indent}# Verify CSI driver registration
{indent}csi_drivers = ocp_client.storage_v1.list_csi_driver()
{indent}spiffe_drivers = [d for d in csi_drivers.items if "spiffe" in d.metadata.name.lower()]
{indent}assert len(spiffe_drivers) > 0, "SPIFFE CSI Driver not registered"'''
    
    # Default implementation
    return f'''{indent}# Verify component is deployed and running
{indent}pods = ocp_client.get_pods(
{indent}    namespace=operator_namespace,
{indent}    label_selector="app.kubernetes.io/part-of=ztwim"
{indent})
{indent}assert len(pods) > 0, "No ZTWIM pods found"
{indent}
{indent}running_pods = [p for p in pods if p.status.phase == "Running"]
{indent}logger.info(f"Found {{len(running_pods)}} running pods")
{indent}assert len(running_pods) > 0, "No running pods found"'''


def validate_python_code(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Python code syntax."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"


# ============================================================================
# CLI Commands
# ============================================================================

def cmd_analyze_pr(args):
    """Analyze a PR and show results."""
    pr = fetch_pr_details(args.pr_number, args.repo)
    if not pr:
        print(f"❌ Could not fetch PR #{args.pr_number}")
        return 1
    
    analysis = analyze_pr(pr)
    
    print(f"\n{'='*60}")
    print(f"📋 PR ANALYSIS: #{pr.number}")
    print(f"{'='*60}")
    print(f"\n📌 Title: {pr.title}")
    print(f"👤 Author: @{pr.author}")
    print(f"🏷️  Labels: {', '.join(pr.labels) or 'None'}")
    print(f"🔗 URL: {pr.url}")
    print(f"\n📦 Components Affected: {', '.join(analysis.components)}")
    print(f"📝 Change Type: {analysis.change_type}")
    print(f"📄 CRDs Affected: {', '.join(analysis.affected_crds) or 'None'}")
    
    print(f"\n🔍 Key Changes:")
    for change in analysis.key_changes:
        print(f"   • {change}")
    
    print(f"\n🧪 Test Scenarios:")
    for scenario in analysis.test_scenarios:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(scenario["priority"], "⚪")
        print(f"   {priority_icon} [{scenario['type']}] {scenario['name']}")
        print(f"      {scenario['description']}")
    
    return 0


def cmd_generate_from_pr(args):
    """Generate tests from a PR."""
    pr = fetch_pr_details(args.pr_number, args.repo)
    if not pr:
        print(f"❌ Could not fetch PR #{args.pr_number}")
        return 1
    
    print(f"✅ Fetched PR #{pr.number}: {pr.title}")
    
    analysis = analyze_pr(pr)
    
    print(f"📦 Components: {', '.join(analysis.components)}")
    print(f"📝 Change type: {analysis.change_type}")
    
    generated_files = []
    
    for component in analysis.components:
        print(f"\n🤖 Generating tests for {component}...")
        
        # Generate test code
        code = generate_test_code(analysis, component)
        
        # Validate syntax
        is_valid, error = validate_python_code(code)
        if not is_valid:
            print(f"❌ Syntax error in generated code: {error}")
            continue
        
        print(f"✅ Syntax validation passed")
        
        # Determine output path
        output_dir = Path("tests") / COMPONENT_DIRS.get(component, component)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = generate_test_name(pr, component)
        output_path = output_dir / filename
        
        if args.save:
            output_path.write_text(code)
            print(f"💾 Saved: {output_path}")
            generated_files.append(str(output_path))
        else:
            print(f"\n{'='*60}")
            print(f"Generated Test: {output_path}")
            print(f"{'='*60}")
            print(code)
            print(f"{'='*60}")
            
            if not args.dry_run:
                response = input("\nSave this file? [y/N]: ").strip().lower()
                if response == 'y':
                    output_path.write_text(code)
                    print(f"💾 Saved: {output_path}")
                    generated_files.append(str(output_path))
    
    print(f"\n{'='*60}")
    print(f"✅ Generated {len(generated_files)} test file(s)")
    for f in generated_files:
        print(f"   • {f}")
    
    return 0


def cmd_coverage_gap(args):
    """Analyze test coverage gaps."""
    print("🔍 Analyzing test coverage gaps...")
    
    tests_dir = Path("tests")
    if not tests_dir.exists():
        print("❌ Tests directory not found")
        return 1
    
    # Count tests per component
    coverage = {}
    for component in COMPONENT_DIRS.values():
        component_dir = tests_dir / component
        if component_dir.exists():
            test_files = list(component_dir.glob("test_*.py"))
            coverage[component] = {
                "files": len(test_files),
                "test_count": 0,
            }
            for tf in test_files:
                content = tf.read_text()
                coverage[component]["test_count"] += len(re.findall(r'def test_', content))
    
    print(f"\n{'='*60}")
    print("TEST COVERAGE ANALYSIS")
    print(f"{'='*60}")
    print(f"\n{'Component':<20} {'Files':<10} {'Tests':<10}")
    print("-" * 40)
    
    for comp, data in coverage.items():
        print(f"{comp:<20} {data['files']:<10} {data['test_count']:<10}")
    
    # Identify gaps
    print(f"\n🔍 Coverage Gaps Identified:")
    gaps = {
        "spire_server": ["HA failover", "Trust bundle rotation", "Federation"],
        "spire_agent": ["Workload attestation", "Recovery scenarios", "Node drain"],
        "oidc_discovery": ["Token validation", "Key rotation", "Cloud federation"],
        "csi_driver": ["Mount failures", "Volume lifecycle", "Permissions"],
    }
    
    for comp, gap_list in gaps.items():
        if args.component and comp != args.component:
            continue
        print(f"\n  {comp}:")
        for gap in gap_list:
            print(f"    ❌ {gap}")
    
    return 0


def cmd_suggest(args):
    """Suggest test cases for a component."""
    print(f"💡 Suggesting tests for {args.component}...")
    
    suggestions = {
        "spire_server": [
            ("test_server_ha_leader_election", "Verify leader election with multiple replicas"),
            ("test_server_trust_bundle_rotation", "Verify automatic trust bundle rotation"),
            ("test_server_federation_setup", "Verify federation bundle configuration"),
            ("test_server_graceful_shutdown", "Verify clean shutdown handling"),
            ("test_server_resource_limits", "Verify resource limits are applied"),
        ],
        "spire_agent": [
            ("test_agent_workload_attestation", "Verify workload SVID issuance"),
            ("test_agent_recovery_after_restart", "Verify agent recovery after restart"),
            ("test_agent_server_reconnection", "Verify reconnection after server restart"),
            ("test_agent_socket_permissions", "Verify workload API socket permissions"),
        ],
        "oidc_discovery": [
            ("test_oidc_endpoint_accessibility", "Verify OIDC endpoints are accessible"),
            ("test_oidc_jwks_validity", "Verify JWKS contains valid keys"),
            ("test_oidc_token_verification", "Verify JWT-SVIDs can be verified"),
        ],
        "csi_driver": [
            ("test_csi_volume_mount", "Verify SPIFFE volumes mount correctly"),
            ("test_csi_svid_delivery", "Verify SVIDs are delivered via CSI"),
            ("test_csi_volume_unmount", "Verify clean volume unmounting"),
        ],
    }
    
    comp_suggestions = suggestions.get(args.component, [])
    
    print(f"\n{'='*60}")
    print(f"SUGGESTED TESTS: {args.component}")
    print(f"{'='*60}")
    
    for name, desc in comp_suggestions:
        print(f"\n📝 {name}")
        print(f"   {desc}")
    
    return 0


def cmd_validate(args):
    """Validate test files."""
    path = Path(args.path)
    
    if not path.exists():
        print(f"❌ Path not found: {path}")
        return 1
    
    files = [path] if path.is_file() else list(path.rglob("test_*.py"))
    
    print(f"🔍 Validating {len(files)} file(s)...")
    
    errors = 0
    warnings = 0
    
    for filepath in files:
        print(f"\n  {filepath}")
        content = filepath.read_text()
        
        # Syntax check
        is_valid, error = validate_python_code(content)
        if not is_valid:
            print(f"    ❌ Syntax error: {error}")
            errors += 1
            continue
        
        print(f"    ✅ Syntax OK")
        
        # Check for required imports
        if "import pytest" not in content:
            print(f"    ⚠️  Missing: import pytest")
            warnings += 1
        
        if "get_logger" in content and "from src.utils.logger" not in content:
            print(f"    ⚠️  Missing logger import")
            warnings += 1
        
        # Check for markers
        if "@pytest.mark." not in content:
            print(f"    ⚠️  Missing pytest markers")
            warnings += 1
    
    print(f"\n{'='*60}")
    print(f"Validation complete: {errors} errors, {warnings} warnings")
    
    return 1 if errors > 0 else 0


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ZTWIM Test Generator - Claude Code Plugin"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # analyze-pr command
    analyze_parser = subparsers.add_parser("analyze-pr", help="Analyze a PR")
    analyze_parser.add_argument("pr_number", type=int, help="PR number")
    analyze_parser.add_argument("--repo", default=GITHUB_REPO, help="GitHub repo")
    
    # generate-from-pr command
    gen_parser = subparsers.add_parser("generate-from-pr", help="Generate tests from PR")
    gen_parser.add_argument("pr_number", type=int, help="PR number")
    gen_parser.add_argument("--repo", default=GITHUB_REPO, help="GitHub repo")
    gen_parser.add_argument("--save", action="store_true", help="Auto-save files")
    gen_parser.add_argument("--dry-run", action="store_true", help="Don't prompt to save")
    
    # coverage-gap command
    cov_parser = subparsers.add_parser("coverage-gap", help="Analyze coverage gaps")
    cov_parser.add_argument("--component", help="Specific component to analyze")
    
    # suggest command
    suggest_parser = subparsers.add_parser("suggest", help="Suggest test cases")
    suggest_parser.add_argument("component", help="Component to suggest tests for")
    
    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate test files")
    validate_parser.add_argument("path", help="Path to validate")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    commands = {
        "analyze-pr": cmd_analyze_pr,
        "generate-from-pr": cmd_generate_from_pr,
        "coverage-gap": cmd_coverage_gap,
        "suggest": cmd_suggest,
        "validate": cmd_validate,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

