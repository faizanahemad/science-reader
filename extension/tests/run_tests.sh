#!/bin/bash
#
# Run Extension Server Integration Tests
#
# This script:
# 1. Activates the conda environment
# 2. Starts the extension server
# 3. Waits for it to be ready
# 4. Runs the integration tests
# 5. Shuts down the server
#
# Usage:
#   ./run_tests.sh                    # Run with defaults
#   ./run_tests.sh --no-server        # Use existing server
#   ./run_tests.sh -v                 # Verbose output
#   ./run_tests.sh --port 5002        # Custom port
#

set -e  # Exit on error

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXTENSION_SERVER="$PROJECT_ROOT/extension_server.py"
TEST_SCRIPT="$SCRIPT_DIR/test_extension_api.py"

# Defaults
PORT="${EXT_PORT:-5001}"
HOST="0.0.0.0"
EMAIL="${TEST_EMAIL:-test@example.com}"
PASSWORD="${PASSWORD:-XXXX}"
CONDA_ENV="science-reader"
TIMEOUT=30
NO_SERVER=false
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# =============================================================================
# Argument Parsing
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --password)
            PASSWORD="$2"
            shift 2
            ;;
        --no-server)
            NO_SERVER=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --port PORT       Server port (default: 5001)"
            echo "  --email EMAIL     Test user email"
            echo "  --password PASS   Test user password"
            echo "  --no-server       Use existing server"
            echo "  -v, --verbose     Verbose output"
            echo "  -h, --help        Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

BASE_URL="http://localhost:$PORT"

# =============================================================================
# Functions
# =============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_health() {
    curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/ext/health" 2>/dev/null
}

wait_for_server() {
    log_info "Waiting for server to be ready..."
    local elapsed=0
    
    while [ $elapsed -lt $TIMEOUT ]; do
        if [ "$(check_health)" = "200" ]; then
            log_info "Server is ready after ${elapsed}s"
            return 0
        fi
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
    
    log_error "Server failed to start within ${TIMEOUT}s"
    return 1
}

cleanup() {
    log_info "Cleaning up..."
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        log_info "Stopping server (PID: $SERVER_PID)..."
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

# Set up cleanup on exit
trap cleanup EXIT

# =============================================================================
# Main
# =============================================================================

echo "=========================================="
echo "Extension Server Integration Tests"
echo "=========================================="
echo ""

# Check conda environment
if command -v conda &> /dev/null; then
    log_info "Activating conda environment: $CONDA_ENV"
    eval "$(conda shell.bash hook)"
    conda activate "$CONDA_ENV" 2>/dev/null || {
        log_warn "Could not activate conda environment '$CONDA_ENV', using current environment"
    }
fi

cd "$PROJECT_ROOT"

if [ "$NO_SERVER" = true ]; then
    # Use existing server
    log_info "Using existing server at $BASE_URL"
    
    if [ "$(check_health)" != "200" ]; then
        log_error "Cannot connect to server at $BASE_URL"
        log_error "Make sure the server is running:"
        log_error "  python extension_server.py --port $PORT"
        exit 1
    fi
    
    log_info "Server is healthy"
else
    # Start server
    log_info "Starting extension server on port $PORT..."
    
    python "$EXTENSION_SERVER" --port "$PORT" --host "$HOST" &
    SERVER_PID=$!
    
    log_info "Server started with PID: $SERVER_PID"
    
    # Wait for server
    if ! wait_for_server; then
        log_error "Server startup failed"
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "Running Tests"
echo "=========================================="
echo ""

# Export environment for tests
export EXT_SERVER_URL="$BASE_URL"
export TEST_EMAIL="$EMAIL"
export TEST_PASSWORD="$PASSWORD"

# Run tests
TEST_ARGS=""
if [ "$VERBOSE" = true ]; then
    TEST_ARGS="-v"
fi

# Try pytest first, fall back to direct execution
if command -v pytest &> /dev/null; then
    log_info "Running tests with pytest..."
    pytest "$TEST_SCRIPT" $TEST_ARGS --tb=short -x
    TEST_EXIT_CODE=$?
else
    log_info "Running tests directly..."
    python "$TEST_SCRIPT"
    TEST_EXIT_CODE=$?
fi

echo ""
echo "=========================================="

if [ $TEST_EXIT_CODE -eq 0 ]; then
    log_info "All tests passed!"
else
    log_error "Some tests failed"
fi

exit $TEST_EXIT_CODE

