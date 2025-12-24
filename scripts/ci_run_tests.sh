#!/bin/bash
# =============================================================================
# ZTWIM Test Framework - CI Runner Script
# =============================================================================
# Designed for CI tools like Conflux, Jenkins, GitLab CI, Tekton
#
# Required Environment Variables:
#   KUBECONFIG       - Path to kubeconfig file (or kubeconfig content)
#
# Optional Environment Variables:
#   APP_DOMAIN       - OpenShift apps domain (auto-detected if not set)
#   CLUSTER_NAME     - ZTWIM cluster name (default: test01)
#   SKIP_INSTALL     - Set to "true" to skip ZTWIM installation
#   TEST_MARKERS     - Pytest markers to filter tests (e.g., "spire_server")
#   PARALLEL_WORKERS - Number of parallel workers (default: auto)
#   OPERATOR_TIMEOUT - Timeout for operator installation (default: 300)
#   COMPONENT_TIMEOUT - Timeout per component verification (default: 120)
#
# Exit Codes:
#   0 - All tests passed
#   1 - Some tests failed
#   2 - Setup/configuration error
#   3 - ZTWIM installation failed
#
# Artifacts Generated:
#   - test-reports/         : HTML test reports (timestamped)
#   - reports/junit.xml     : JUnit XML for CI parsing
#   - logs/                 : Test execution logs
# =============================================================================

set -o pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values
SKIP_INSTALL="${SKIP_INSTALL:-false}"
PARALLEL_WORKERS="${PARALLEL_WORKERS:-auto}"
OPERATOR_TIMEOUT="${OPERATOR_TIMEOUT:-300}"
COMPONENT_TIMEOUT="${COMPONENT_TIMEOUT:-120}"
TEST_MARKERS="${TEST_MARKERS:-}"

# Output directories
REPORTS_DIR="${PROJECT_ROOT}/reports"
TEST_REPORTS_DIR="${PROJECT_ROOT}/test-reports"
LOGS_DIR="${PROJECT_ROOT}/logs"

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

# =============================================================================
# Pre-flight Checks
# =============================================================================

log_section "ZTWIM Test Framework - CI Runner"

# Check KUBECONFIG
if [ -z "$KUBECONFIG" ]; then
    log_error "KUBECONFIG environment variable is not set"
    log_error "Please set KUBECONFIG=/path/to/kubeconfig"
    exit 2
fi

# If KUBECONFIG is content (starts with apiVersion), write to file
if [[ "$KUBECONFIG" == apiVersion* ]] || [[ "$KUBECONFIG" == "{\"apiVersion"* ]]; then
    log_info "KUBECONFIG contains content, writing to temporary file..."
    KUBECONFIG_FILE="/tmp/kubeconfig-$$"
    echo "$KUBECONFIG" > "$KUBECONFIG_FILE"
    export KUBECONFIG="$KUBECONFIG_FILE"
    trap "rm -f $KUBECONFIG_FILE" EXIT
fi

if [ ! -f "$KUBECONFIG" ]; then
    log_error "KUBECONFIG file not found: $KUBECONFIG"
    exit 2
fi

log_info "Using KUBECONFIG: $KUBECONFIG"

# Check Python
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    log_error "Python is not installed"
    exit 2
fi

PYTHON_CMD=$(command -v python3 || command -v python)
log_info "Using Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# =============================================================================
# Setup
# =============================================================================

log_section "Setting Up Test Environment"

cd "$PROJECT_ROOT" || exit 2

# Create output directories
mkdir -p "$REPORTS_DIR" "$LOGS_DIR" "$TEST_REPORTS_DIR"

# Install dependencies (if not already installed)
if ! $PYTHON_CMD -c "import pytest" 2>/dev/null; then
    log_info "Installing Python dependencies..."
    $PYTHON_CMD -m pip install -r requirements.txt --quiet
fi

# =============================================================================
# Build Pytest Command
# =============================================================================

log_section "Configuring Test Run"

PYTEST_ARGS=(
    "tests/"
    "-v"
    "--tb=short"
    "--junitxml=${REPORTS_DIR}/junit.xml"
    "--operator-timeout=${OPERATOR_TIMEOUT}"
    "--component-timeout=${COMPONENT_TIMEOUT}"
)

# Skip installation if requested
if [ "$SKIP_INSTALL" = "true" ]; then
    log_info "Skipping ZTWIM installation (SKIP_INSTALL=true)"
    PYTEST_ARGS+=("--skip-install")
fi

# Add test markers if specified
if [ -n "$TEST_MARKERS" ]; then
    log_info "Running tests with markers: $TEST_MARKERS"
    PYTEST_ARGS+=("-m" "$TEST_MARKERS")
fi

# Add parallel workers
if [ "$PARALLEL_WORKERS" != "auto" ] && [ "$PARALLEL_WORKERS" -gt 1 ] 2>/dev/null; then
    log_info "Running with $PARALLEL_WORKERS parallel workers"
    PYTEST_ARGS+=("-n" "$PARALLEL_WORKERS")
fi

# Add app domain if set
if [ -n "$APP_DOMAIN" ]; then
    log_info "Using APP_DOMAIN: $APP_DOMAIN"
    PYTEST_ARGS+=("--app-domain=${APP_DOMAIN}")
fi

# Add cluster name if set
if [ -n "$CLUSTER_NAME" ]; then
    log_info "Using CLUSTER_NAME: $CLUSTER_NAME"
    PYTEST_ARGS+=("--cluster-name=${CLUSTER_NAME}")
fi

log_info "Pytest command: pytest ${PYTEST_ARGS[*]}"

# =============================================================================
# Run Tests
# =============================================================================

log_section "Running Tests"

# Run pytest and capture exit code
$PYTHON_CMD -m pytest "${PYTEST_ARGS[@]}" 2>&1 | tee "${LOGS_DIR}/test_output.log"
TEST_EXIT_CODE=${PIPESTATUS[0]}

# =============================================================================
# Summary
# =============================================================================

log_section "Test Run Summary"

echo ""
log_info "Reports generated:"
echo "  - JUnit XML:    ${REPORTS_DIR}/junit.xml"
echo "  - HTML Reports: ${TEST_REPORTS_DIR}/"
echo "  - Logs:         ${LOGS_DIR}/test_output.log"
echo ""

# List HTML reports
if [ -d "$TEST_REPORTS_DIR" ]; then
    LATEST_REPORT=$(ls -t "$TEST_REPORTS_DIR"/test-report-*.html 2>/dev/null | head -1)
    if [ -n "$LATEST_REPORT" ]; then
        echo "  - Latest HTML:  $LATEST_REPORT"
    fi
fi
echo ""

# Final status
if [ $TEST_EXIT_CODE -eq 0 ]; then
    log_success "All tests passed!"
else
    log_error "Some tests failed (exit code: $TEST_EXIT_CODE)"
fi

exit $TEST_EXIT_CODE
