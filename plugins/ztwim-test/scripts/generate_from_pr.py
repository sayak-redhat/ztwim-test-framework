#!/usr/bin/env python3
"""
Generate tests from GitHub Pull Request.

This script wraps the main auto_gen.py functionality for the Claude plugin.

Usage:
    python generate_from_pr.py <pr_number> [options]
    
Options:
    --repo REPO         GitHub repository (default: openshift/zero-trust-workload-identity-manager)
    --save              Auto-save without prompting
    --verbose           Show detailed output
    --use-cli           Use Claude CLI instead of API
    --output-dir DIR    Output directory (default: auto-detect from component)
"""

import argparse
import os
import sys
import json
from pathlib import Path

# Add the scripts directory to path to import auto_gen
SCRIPT_DIR = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from auto_gen import (
        fetch_pr_details,
        detect_components,
        generate_filename,
        build_prompt,
        generate_with_claude_cli,
        generate_with_claude_api,
        validate_python_code,
        get_framework_context,
        COMPONENT_DIRS,
    )
    AUTO_GEN_AVAILABLE = True
except ImportError:
    AUTO_GEN_AVAILABLE = False


def print_status(message: str, status: str = "info"):
    """Print formatted status message."""
    icons = {
        "success": "✅",
        "error": "❌",
        "warning": "⚠️",
        "info": "📝",
        "fetch": "🔍",
        "component": "📦",
        "generate": "🤖",
        "save": "💾",
    }
    icon = icons.get(status, "•")
    print(f"{icon} {message}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate pytest tests from a GitHub Pull Request"
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="PR number to generate tests from"
    )
    parser.add_argument(
        "--repo",
        default="openshift/zero-trust-workload-identity-manager",
        help="GitHub repository (owner/repo)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Auto-save generated tests"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--use-cli",
        action="store_true",
        default=True,
        help="Use Claude CLI instead of API"
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for generated tests"
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    if not AUTO_GEN_AVAILABLE:
        print_status("auto_gen.py not found. Please ensure the script is in the scripts/ directory.", "error")
        sys.exit(1)
    
    results = {
        "pr_number": args.pr_number,
        "repo": args.repo,
        "success": False,
        "components": [],
        "files_generated": [],
        "errors": []
    }
    
    try:
        # Fetch PR details
        print_status(f"Fetching PR #{args.pr_number} from {args.repo}...", "fetch")
        pr_details = fetch_pr_details(args.pr_number, args.repo)
        
        if not pr_details:
            print_status(f"Could not fetch PR #{args.pr_number}", "error")
            results["errors"].append("PR not found")
            if args.json_output:
                print(json.dumps(results, indent=2))
            sys.exit(1)
        
        print_status(f"PR #{args.pr_number}: {pr_details['title']}", "success")
        if args.verbose:
            print(f"   Author: @{pr_details.get('author', 'unknown')}")
            print(f"   Labels: {', '.join(pr_details.get('labels', []))}")
            print(f"   Files changed: {len(pr_details.get('files', []))}")
        
        # Detect components
        components = detect_components(pr_details)
        results["components"] = components
        
        if not components:
            print_status("No testable components detected in this PR", "warning")
            results["errors"].append("No components detected")
            if args.json_output:
                print(json.dumps(results, indent=2))
            sys.exit(1)
        
        print_status(f"Detected components: {', '.join(components)}", "component")
        
        # Get framework context
        framework_context = get_framework_context()
        
        # Generate tests for each component
        for component in components:
            print_status(f"Generating tests for {component}...", "generate")
            
            # Build prompt
            prompt = build_prompt(pr_details, component, framework_context)
            
            # Generate with Claude
            if args.use_cli:
                generated_code = generate_with_claude_cli(prompt)
            else:
                generated_code = generate_with_claude_api(prompt)
            
            if not generated_code:
                print_status(f"Failed to generate tests for {component}", "error")
                results["errors"].append(f"Generation failed for {component}")
                continue
            
            # Validate syntax
            is_valid, error = validate_python_code(generated_code)
            if not is_valid:
                print_status(f"Generated code has syntax errors: {error}", "error")
                results["errors"].append(f"Syntax error in {component}: {error}")
                continue
            
            print_status("Syntax validation passed", "success")
            
            # Determine output path
            if args.output_dir:
                output_dir = Path(args.output_dir)
            else:
                output_dir = Path("tests") / COMPONENT_DIRS.get(component, component)
            
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            filename = generate_filename(pr_details, component)
            output_path = output_dir / filename
            
            # Save or prompt
            if args.save:
                output_path.write_text(generated_code)
                print_status(f"Saved: {output_path}", "save")
                results["files_generated"].append(str(output_path))
            else:
                print(f"\n--- Generated Test ({component}) ---\n")
                print(generated_code)
                print(f"\n--- End ---\n")
                print(f"Would save to: {output_path}")
                
                response = input("Save this file? [y/N]: ").strip().lower()
                if response == 'y':
                    output_path.write_text(generated_code)
                    print_status(f"Saved: {output_path}", "save")
                    results["files_generated"].append(str(output_path))
        
        results["success"] = len(results["files_generated"]) > 0
        
        # Summary
        print("\n" + "=" * 50)
        print_status(f"Generated {len(results['files_generated'])} test file(s)", "success" if results["success"] else "warning")
        for f in results["files_generated"]:
            print(f"   • {f}")
        
        if results["errors"]:
            print_status(f"{len(results['errors'])} error(s) occurred", "warning")
            for e in results["errors"]:
                print(f"   • {e}")
        
        if args.json_output:
            print(json.dumps(results, indent=2))
        
        sys.exit(0 if results["success"] else 1)
        
    except KeyboardInterrupt:
        print_status("Interrupted by user", "warning")
        sys.exit(130)
    except Exception as e:
        print_status(f"Error: {e}", "error")
        results["errors"].append(str(e))
        if args.json_output:
            print(json.dumps(results, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()

