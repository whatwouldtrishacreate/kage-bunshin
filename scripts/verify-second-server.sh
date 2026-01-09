#!/bin/bash
################################################################################
# Kage Bunshin Server Verification Script
#
# Verifies that the server synchronization was successful and all components
# are properly configured.
#
# This script should be run on the TARGET server after synchronization.
#
# Usage:
#   ./verify-second-server.sh [OPTIONS]
#
# Options:
#   --verbose        Show detailed output for each check
#   --help           Show this help message
#
# Exit codes:
#   0 = All checks passed
#   1 = One or more checks failed
#
# Author: Claude Sonnet 4.5
# Date: 2026-01-09
################################################################################

set -e
set -u
set -o pipefail

################################################################################
# CONFIGURATION
################################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Settings
VERBOSE=false
CHECKS_PASSED=0
CHECKS_FAILED=0

# Database settings
DB_NAME="claude_memory"
DB_USER="claude_mcp"

################################################################################
# HELPER FUNCTIONS
################################################################################

log_check() {
    local status="$1"
    local message="$2"
    local details="${3:-}"

    case "$status" in
        PASS)
            echo -e "${GREEN}✓${NC} $message"
            ((CHECKS_PASSED++))
            ;;
        FAIL)
            echo -e "${RED}✗${NC} $message"
            ((CHECKS_FAILED++))
            ;;
        WARN)
            echo -e "${YELLOW}⚠${NC} $message"
            ;;
        INFO)
            echo -e "${BLUE}ℹ${NC} $message"
            ;;
    esac

    if [ "$VERBOSE" = true ] && [ -n "$details" ]; then
        echo "  $details"
    fi
}

show_header() {
    echo ""
    echo "=================================================================="
    echo "$1"
    echo "=================================================================="
    echo ""
}

show_help() {
    grep '^#' "$0" | grep -v '#!/bin/bash' | sed 's/^# //; s/^#//'
    exit 0
}

################################################################################
# VERIFICATION CHECKS
################################################################################

check_claude_code() {
    show_header "Claude Code Configuration"

    # Check Claude Code CLI
    if command -v claude &> /dev/null; then
        local version=$(claude --version 2>&1 | head -1)
        log_check PASS "Claude Code CLI installed" "$version"
    else
        log_check FAIL "Claude Code CLI not found"
        return 1
    fi

    # Check settings.json
    if [ -f ~/.claude/settings.json ]; then
        log_check PASS "settings.json exists"

        if command -v jq &> /dev/null; then
            local plugin_count=$(jq '.enabledPlugins | length' ~/.claude/settings.json 2>/dev/null || echo 0)
            log_check INFO "$plugin_count plugins enabled"
        fi
    else
        log_check FAIL "settings.json missing"
    fi

    # Check .credentials.json
    if [ -f ~/.claude/.credentials.json ]; then
        local perms=$(stat -c '%a' ~/.claude/.credentials.json)
        if [ "$perms" = "600" ]; then
            log_check PASS ".credentials.json exists with correct permissions (600)"
        else
            log_check WARN ".credentials.json exists but permissions are $perms (should be 600)"
        fi

        # Check if OAuth token exists
        if command -v jq &> /dev/null; then
            if jq -e '.["Claude AI OAuth - Access Token"]' ~/.claude/.credentials.json &> /dev/null; then
                log_check PASS "Claude AI OAuth token configured"
            else
                log_check FAIL "Claude AI OAuth token missing"
            fi
        fi
    else
        log_check FAIL ".credentials.json missing"
    fi

    # Check skills directory
    if [ -d ~/.claude/skills ]; then
        local skill_count=$(ls -1 ~/.claude/skills/*.md 2>/dev/null | wc -l)
        log_check PASS "Skills directory exists ($skill_count skills)"
    else
        log_check WARN "Skills directory missing"
    fi

    # Check hooks directory
    if [ -d ~/.claude/hooks ]; then
        local hook_count=$(ls -1 ~/.claude/hooks/* 2>/dev/null | wc -l)
        log_check PASS "Hooks directory exists ($hook_count hooks)"
    else
        log_check WARN "Hooks directory missing"
    fi

    # Check plugins
    if [ -f ~/.claude/plugins/installed_plugins.json ]; then
        if command -v jq &> /dev/null; then
            local installed_count=$(jq '.plugins | length' ~/.claude/plugins/installed_plugins.json 2>/dev/null || echo 0)
            log_check PASS "Plugin registry exists ($installed_count plugins installed)"
        else
            log_check PASS "Plugin registry exists"
        fi
    else
        log_check WARN "Plugin registry missing"
    fi
}

check_database() {
    show_header "PostgreSQL Database"

    # Check PostgreSQL installation
    if command -v psql &> /dev/null; then
        local pg_version=$(psql --version | awk '{print $3}')
        log_check PASS "PostgreSQL installed" "Version: $pg_version"
    else
        log_check FAIL "PostgreSQL not installed"
        return 1
    fi

    # Check database exists
    if psql -U "$DB_USER" -d "$DB_NAME" -c '\q' &> /dev/null; then
        log_check PASS "Database '$DB_NAME' exists and is accessible"
    else
        log_check FAIL "Cannot connect to database '$DB_NAME'"
        return 1
    fi

    # Check public schema tables
    local public_tables=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null | tr -d ' ')
    if [ -n "$public_tables" ] && [ "$public_tables" -gt 0 ]; then
        log_check PASS "Public schema has $public_tables tables"
    else
        log_check WARN "Public schema has no tables"
    fi

    # Check development_docs schema
    local dev_docs_tables=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'development_docs'" 2>/dev/null | tr -d ' ')
    if [ -n "$dev_docs_tables" ] && [ "$dev_docs_tables" -gt 0 ]; then
        log_check PASS "development_docs schema has $dev_docs_tables tables"
    else
        log_check WARN "development_docs schema missing or empty"
    fi

    # Check tasks table
    if psql -U "$DB_USER" -d "$DB_NAME" -c '\d tasks' &> /dev/null; then
        local task_count=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c 'SELECT COUNT(*) FROM tasks' 2>/dev/null | tr -d ' ')
        log_check PASS "tasks table exists ($task_count tasks)"
    else
        log_check FAIL "tasks table missing"
    fi

    # Check .pgpass
    if [ -f ~/.pgpass ]; then
        local perms=$(stat -c '%a' ~/.pgpass)
        if [ "$perms" = "600" ]; then
            log_check PASS ".pgpass exists with correct permissions (600)"
        else
            log_check WARN ".pgpass exists but permissions are $perms (should be 600)"
        fi
    else
        log_check WARN ".pgpass missing (will need password for database access)"
    fi
}

check_kage_bunshin() {
    show_header "Kage Bunshin Orchestrator"

    # Check repository
    if [ -d ~/projects/kage-bunshin/.git ]; then
        log_check PASS "Git repository exists"

        cd ~/projects/kage-bunshin
        local current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
        log_check INFO "Current branch: $current_branch"

        local remote_url=$(git config --get remote.origin.url 2>/dev/null)
        log_check INFO "Remote: $remote_url"
    else
        log_check FAIL "Git repository missing"
        return 1
    fi

    # Check Python virtual environment
    if [ -f ~/projects/kage-bunshin/venv/bin/activate ]; then
        log_check PASS "Python virtual environment exists"

        # Activate venv and check Python version
        source ~/projects/kage-bunshin/venv/bin/activate
        local python_version=$(python --version 2>&1 | awk '{print $2}')
        log_check INFO "Python version: $python_version"
    else
        log_check FAIL "Python virtual environment missing"
        return 1
    fi

    # Check requirements.txt
    if [ -f ~/projects/kage-bunshin/requirements.txt ]; then
        log_check PASS "requirements.txt exists"
    else
        log_check WARN "requirements.txt missing"
    fi

    # Check key Python packages
    source ~/projects/kage-bunshin/venv/bin/activate 2>/dev/null || true
    for package in fastapi uvicorn asyncpg pydantic; do
        if python -c "import $package" &> /dev/null; then
            local version=$(python -c "import $package; print($package.__version__)" 2>/dev/null || echo "unknown")
            log_check PASS "Package '$package' installed" "Version: $version"
        else
            log_check FAIL "Package '$package' not installed"
        fi
    done

    # Check migrations
    if [ -f ~/projects/kage-bunshin/migrations/001_create_tasks_tables.sql ]; then
        log_check PASS "Database migrations exist"
    else
        log_check WARN "Database migrations missing"
    fi

    # Check API entry point
    if [ -f ~/projects/kage-bunshin/api/main.py ]; then
        log_check PASS "API entry point exists (api/main.py)"
    else
        log_check FAIL "API entry point missing"
    fi
}

check_secrets() {
    show_header "Secrets and Environment Variables"

    # Check .bashrc for API keys
    if grep -q "OPENAI_API_KEY" ~/.bashrc; then
        log_check PASS "OPENAI_API_KEY configured in .bashrc"
    else
        log_check WARN "OPENAI_API_KEY not found in .bashrc"
    fi

    if grep -q "GEMINI_API_KEY" ~/.bashrc; then
        log_check PASS "GEMINI_API_KEY configured in .bashrc"
    else
        log_check WARN "GEMINI_API_KEY not found in .bashrc"
    fi

    if grep -q "BASE_BRANCH" ~/.bashrc; then
        log_check PASS "BASE_BRANCH configured in .bashrc"
    else
        log_check WARN "BASE_BRANCH not found in .bashrc"
    fi

    if grep -q "API_KEYS" ~/.bashrc; then
        log_check PASS "API_KEYS configured in .bashrc"
    else
        log_check WARN "API_KEYS not found in .bashrc"
    fi

    # Check if environment variables are actually loaded
    source ~/.bashrc 2>/dev/null || true

    if [ -n "${OPENAI_API_KEY:-}" ]; then
        log_check PASS "OPENAI_API_KEY loaded in current environment"
    else
        log_check WARN "OPENAI_API_KEY not loaded (run 'source ~/.bashrc')"
    fi

    if [ -n "${BASE_BRANCH:-}" ]; then
        log_check INFO "BASE_BRANCH=$BASE_BRANCH"
    fi
}

check_network() {
    show_header "Network and Connectivity"

    # Check if port 8003 is available
    if ! ss -lntu | grep -q ':8003 '; then
        log_check PASS "Port 8003 available for API server"
    else
        log_check WARN "Port 8003 already in use"
    fi

    # Check GitHub connectivity
    if ping -c 1 -W 2 github.com &> /dev/null; then
        log_check PASS "GitHub is reachable"
    else
        log_check WARN "Cannot reach GitHub"
    fi

    # Check if SSH is running (for future bidirectional sync)
    if systemctl is-active --quiet ssh || systemctl is-active --quiet sshd; then
        log_check PASS "SSH server is running"
    else
        log_check WARN "SSH server not running"
    fi
}

check_disk_space() {
    show_header "Disk Space"

    local free_gb=$(df -BG ~ | tail -1 | awk '{print $4}' | sed 's/G//')
    local used_pct=$(df -h ~ | tail -1 | awk '{print $5}')

    if [ "$free_gb" -gt 5 ]; then
        log_check PASS "Sufficient disk space" "$free_gb GB free ($used_pct used)"
    elif [ "$free_gb" -gt 1 ]; then
        log_check WARN "Low disk space" "$free_gb GB free ($used_pct used)"
    else
        log_check FAIL "Critical disk space" "$free_gb GB free ($used_pct used)"
    fi
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    # Parse arguments
    while [ $# -gt 0 ]; do
        case "$1" in
            --verbose)
                VERBOSE=true
                ;;
            --help)
                show_help
                ;;
            *)
                echo "Unknown option: $1"
                show_help
                ;;
        esac
        shift
    done

    echo ""
    echo "=================================================================="
    echo "Kage Bunshin Server Verification"
    echo "=================================================================="
    echo ""
    echo "Hostname: $(hostname)"
    echo "Date: $(date)"
    echo ""

    # Run all checks
    check_claude_code
    check_database
    check_kage_bunshin
    check_secrets
    check_network
    check_disk_space

    # Summary
    show_header "Summary"
    echo -e "${GREEN}Passed:${NC} $CHECKS_PASSED"
    echo -e "${RED}Failed:${NC} $CHECKS_FAILED"
    echo ""

    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed!${NC}"
        echo ""
        echo "Server is ready to run Kage Bunshin orchestrator."
        echo ""
        echo "To start the API server:"
        echo "  cd ~/projects/kage-bunshin"
        echo "  source venv/bin/activate"
        echo "  BASE_BRANCH=master uvicorn api.main:app --host 0.0.0.0 --port 8003"
        echo ""
        echo "To test the API:"
        echo "  curl -H 'X-API-Key: dev-key-12345' http://localhost:8003/health"
        echo ""
        return 0
    else
        echo -e "${RED}✗ $CHECKS_FAILED check(s) failed${NC}"
        echo ""
        echo "Please review the failures above and fix them before running the orchestrator."
        echo ""
        return 1
    fi
}

# Run main function
main "$@"
