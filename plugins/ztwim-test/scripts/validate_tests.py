#!/usr/bin/env python3
"""
Validate test files for syntax and framework compliance.

Usage:
    python validate_tests.py <path> [options]
    
Options:
    --all               Validate all test files
    --check-fixtures    Verify fixture usage
    --check-markers     Verify pytest markers
    --check-docstrings  Verify docstring format
    --fix               Attempt to auto-fix issues
    --verbose           Show detailed output
    --json              Output as JSON
"""

import argparse
import ast
import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


# Known framework fixtures from conftest.py
KNOWN_FIXTURES = {
    # Session-scoped
    "ocp_client": {"scope": "session", "description": "OpenShift client"},
    "operator_namespace": {"scope": "session", "description": "Operator namespace"},
    "settings": {"scope": "session", "description": "Framework settings"},
    "app_domain": {"scope": "session", "description": "Apps domain"},
    "jwt_issuer_endpoint": {"scope": "session", "description": "JWT issuer URL"},
    "cluster_name": {"scope": "session", "description": "Cluster name"},
    "ztwim_manager": {"scope": "session", "description": "ZTWIM CRD manager"},
    "spire_server_manager": {"scope": "session", "description": "SpireServer manager"},
    "spire_agent_manager": {"scope": "session", "description": "SpireAgent manager"},
    "csi_driver_manager": {"scope": "session", "description": "CSI driver manager"},
    "oidc_manager": {"scope": "session", "description": "OIDC manager"},
    # Module-scoped
    "spire_server": {"scope": "module", "description": "SpireServer CR"},
    "spire_agent": {"scope": "module", "description": "SpireAgent CR"},
    "spiffe_csi_driver": {"scope": "module", "description": "CSI Driver CR"},
    "oidc_provider": {"scope": "module", "description": "OIDC Provider CR"},
    "test_namespace": {"scope": "module", "description": "Test namespace"},
    # Function-scoped
    "unique_name": {"scope": "function", "description": "Unique name generator"},
    "test_labels": {"scope": "function", "description": "Standard labels"},
    "wait_timeout": {"scope": "function", "description": "Timeout value"},
    "poll_interval": {"scope": "function", "description": "Poll interval"},
    # Built-in pytest fixtures
    "request": {"scope": "function", "description": "Pytest request"},
    "tmp_path": {"scope": "function", "description": "Temp directory"},
    "capsys": {"scope": "function", "description": "Capture stdout/stderr"},
    "caplog": {"scope": "function", "description": "Capture logging"},
    "monkeypatch": {"scope": "function", "description": "Monkeypatch"},
}

# Valid pytest markers for ZTWIM
VALID_MARKERS = {
    "operator",
    "spire_server", 
    "spire_agent",
    "csi_driver",
    "oidc_discovery",
    "slow",
    "integration",
    "smoke",
    "parametrize",  # Built-in
    "skip",
    "skipif",
    "xfail",
    "usefixtures",
}


class ValidationIssue:
    """Represents a validation issue."""
    
    def __init__(
        self,
        level: str,  # "error", "warning", "info"
        message: str,
        line: Optional[int] = None,
        code: Optional[str] = None,
        suggestion: Optional[str] = None,
        fixable: bool = False
    ):
        self.level = level
        self.message = message
        self.line = line
        self.code = code
        self.suggestion = suggestion
        self.fixable = fixable
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "line": self.line,
            "code": self.code,
            "suggestion": self.suggestion,
            "fixable": self.fixable,
        }


class TestValidator:
    """Validates test files for ZTWIM framework compliance."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.issues: List[ValidationIssue] = []
    
    def validate_file(self, filepath: Path) -> List[ValidationIssue]:
        """Validate a single test file."""
        self.issues = []
        
        if not filepath.exists():
            self.issues.append(ValidationIssue(
                "error", f"File not found: {filepath}"
            ))
            return self.issues
        
        content = filepath.read_text()
        
        # 1. Python syntax check
        self._check_syntax(content, filepath)
        
        if any(i.level == "error" and "syntax" in i.message.lower() for i in self.issues):
            # Can't proceed with AST analysis if syntax is broken
            return self.issues
        
        # Parse AST for further checks
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self.issues
        
        # 2. Import check
        self._check_imports(tree, content)
        
        # 3. Fixture usage check
        self._check_fixtures(tree)
        
        # 4. Marker check
        self._check_markers(tree, content)
        
        # 5. Docstring check
        self._check_docstrings(tree)
        
        # 6. Logger check
        self._check_logger(tree, content)
        
        return self.issues
    
    def _check_syntax(self, content: str, filepath: Path):
        """Check Python syntax."""
        try:
            ast.parse(content)
            if self.verbose:
                print(f"  ✅ Syntax OK")
        except SyntaxError as e:
            self.issues.append(ValidationIssue(
                "error",
                f"Syntax error: {e.msg}",
                line=e.lineno,
                code=e.text,
            ))
    
    def _check_imports(self, tree: ast.AST, content: str):
        """Check imports are valid."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        
        # Check for required imports
        if "pytest" not in imports and "test_" in content:
            self.issues.append(ValidationIssue(
                "warning",
                "Missing pytest import",
                suggestion="Add: import pytest",
                fixable=True
            ))
        
        if "logger" in content.lower() and "src.utils.logger" not in imports:
            if "get_logger" in content:
                self.issues.append(ValidationIssue(
                    "warning",
                    "Using logger without import",
                    suggestion="Add: from src.utils.logger import get_logger",
                    fixable=True
                ))
        
        if self.verbose:
            print(f"  ✅ Imports OK ({len(imports)} imports)")
    
    def _check_fixtures(self, tree: ast.AST):
        """Check fixture usage."""
        unknown_fixtures = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith("test_"):
                    # Check function arguments (fixtures)
                    for arg in node.args.args:
                        fixture_name = arg.arg
                        if fixture_name == "self":
                            continue
                        if fixture_name not in KNOWN_FIXTURES:
                            unknown_fixtures.append((fixture_name, node.lineno))
        
        for fixture, line in unknown_fixtures:
            self.issues.append(ValidationIssue(
                "warning",
                f"Unknown fixture: {fixture}",
                line=line,
                suggestion=f"Define '{fixture}' in conftest.py or use a known fixture"
            ))
        
        if self.verbose and not unknown_fixtures:
            print(f"  ✅ Fixtures OK")
    
    def _check_markers(self, tree: ast.AST, content: str):
        """Check pytest markers."""
        # Find all @pytest.mark.* decorators
        marker_pattern = r'@pytest\.mark\.(\w+)'
        markers = re.findall(marker_pattern, content)
        
        invalid_markers = []
        for marker in markers:
            if marker not in VALID_MARKERS:
                # Find line number
                for i, line in enumerate(content.split('\n'), 1):
                    if f"@pytest.mark.{marker}" in line:
                        invalid_markers.append((marker, i))
                        break
        
        for marker, line in invalid_markers:
            self.issues.append(ValidationIssue(
                "warning",
                f"Unknown marker: @pytest.mark.{marker}",
                line=line,
                suggestion=f"Use one of: {', '.join(sorted(VALID_MARKERS))}"
            ))
        
        # Check if test class has component marker
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                has_component_marker = False
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Attribute):
                        if hasattr(decorator, 'attr'):
                            if decorator.attr in ['spire_server', 'spire_agent', 'csi_driver', 'oidc_discovery', 'operator']:
                                has_component_marker = True
                
                if not has_component_marker:
                    self.issues.append(ValidationIssue(
                        "warning",
                        f"Test class '{node.name}' missing component marker",
                        line=node.lineno,
                        suggestion="Add @pytest.mark.{component} decorator",
                        fixable=True
                    ))
        
        if self.verbose and not invalid_markers:
            print(f"  ✅ Markers OK")
    
    def _check_docstrings(self, tree: ast.AST):
        """Check docstring format."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                docstring = ast.get_docstring(node)
                
                if not docstring:
                    self.issues.append(ValidationIssue(
                        "warning",
                        f"Missing docstring for {node.name}",
                        line=node.lineno,
                        suggestion="Add docstring with GIVEN/WHEN/THEN acceptance criteria"
                    ))
                    continue
                
                # Check for acceptance criteria
                has_given = "given" in docstring.lower()
                has_when = "when" in docstring.lower()
                has_then = "then" in docstring.lower()
                
                if not (has_given and has_when and has_then):
                    self.issues.append(ValidationIssue(
                        "info",
                        f"Docstring for {node.name} missing GIVEN/WHEN/THEN format",
                        line=node.lineno,
                        suggestion="Add acceptance criteria in GIVEN/WHEN/THEN format",
                        fixable=True
                    ))
        
        if self.verbose:
            print(f"  ✅ Docstrings checked")
    
    def _check_logger(self, tree: ast.AST, content: str):
        """Check logger usage."""
        # Check if logger is defined
        has_logger_def = "logger = get_logger" in content or "logger = logging" in content
        uses_logger = "logger.info" in content or "logger.debug" in content or "logger.error" in content
        
        if uses_logger and not has_logger_def:
            self.issues.append(ValidationIssue(
                "error",
                "Using logger without defining it",
                suggestion="Add: logger = get_logger(__name__)",
                fixable=True
            ))
        
        if self.verbose:
            print(f"  ✅ Logger OK")


def validate_directory(
    directory: Path,
    validator: TestValidator
) -> Dict[str, List[ValidationIssue]]:
    """Validate all test files in a directory."""
    results = {}
    
    for filepath in directory.rglob("test_*.py"):
        print(f"\nValidating: {filepath}")
        issues = validator.validate_file(filepath)
        results[str(filepath)] = issues
        
        for issue in issues:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.level, "•")
            line_info = f" (line {issue.line})" if issue.line else ""
            print(f"  {icon} {issue.message}{line_info}")
            if issue.suggestion:
                print(f"     💡 {issue.suggestion}")
    
    return results


def print_summary(results: Dict[str, List[ValidationIssue]]):
    """Print validation summary."""
    total_files = len(results)
    total_errors = sum(1 for issues in results.values() for i in issues if i.level == "error")
    total_warnings = sum(1 for issues in results.values() for i in issues if i.level == "warning")
    total_info = sum(1 for issues in results.values() for i in issues if i.level == "info")
    
    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    print(f"Files validated: {total_files}")
    print(f"Errors:          {total_errors}")
    print(f"Warnings:        {total_warnings}")
    print(f"Info:            {total_info}")
    
    if total_errors > 0:
        print("\n❌ Validation FAILED")
        return 2
    elif total_warnings > 0:
        print("\n⚠️ Validation passed with warnings")
        return 1
    else:
        print("\n✅ Validation PASSED")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate ZTWIM test files"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="tests/",
        help="Path to test file or directory"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all test files"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--check-fixtures",
        action="store_true",
        default=True,
        help="Check fixture usage"
    )
    parser.add_argument(
        "--check-markers",
        action="store_true",
        default=True,
        help="Check pytest markers"
    )
    parser.add_argument(
        "--check-docstrings",
        action="store_true",
        default=True,
        help="Check docstring format"
    )
    
    args = parser.parse_args()
    
    validator = TestValidator(verbose=args.verbose)
    
    path = Path(args.path)
    
    if path.is_file():
        print(f"Validating: {path}")
        issues = validator.validate_file(path)
        results = {str(path): issues}
        
        for issue in issues:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.level, "•")
            line_info = f" (line {issue.line})" if issue.line else ""
            print(f"  {icon} {issue.message}{line_info}")
            if issue.suggestion:
                print(f"     💡 {issue.suggestion}")
    elif path.is_dir():
        results = validate_directory(path, validator)
    else:
        print(f"❌ Path not found: {path}")
        sys.exit(1)
    
    if args.json:
        json_results = {
            k: [i.to_dict() for i in v]
            for k, v in results.items()
        }
        print(json.dumps(json_results, indent=2))
    
    exit_code = print_summary(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

