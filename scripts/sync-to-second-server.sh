#!/bin/bash
################################################################################
# Kage Bunshin Server Synchronization Script
#
# Synchronizes Claude Code CLI configuration and Kage Bunshin orchestrator
# setup from this server (source) to a second Ubuntu Linux server (target).
#
# Usage:
#   ./sync-to-second-server.sh [OPTIONS] user@second-server
#
# Options:
#   --dry-run          Show what would be synced without making changes
#   --config-only      Sync only Claude Code configuration
#   --database-only    Sync only PostgreSQL database
#   --repo-only        Sync only Kage Bunshin repository
#   --secrets-only     Sync only secrets (.bashrc, .pgpass, .credentials)
#   --skip-backup      Skip creating backup on target server
#   --help             Show this help message
#
# Requirements:
#   - rsync, pg_dump, ssh, jq installed on source server
#   - SSH access with sudo to target server
#   - PostgreSQL 15+, Python 3.13+, Git 2.40+ on target server
#
# Author: Claude Sonnet 4.5
# Date: 2026-01-09
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

################################################################################
# CONFIGURATION
################################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default settings
DRY_RUN=false
SKIP_BACKUP=false
SYNC_CONFIG=true
SYNC_DATABASE=true
SYNC_REPO=true
SYNC_SECRETS=true

# Paths
SOURCE_CLAUDE_DIR="$HOME/.claude"
SOURCE_PROJECT_DIR="$HOME/projects/kage-bunshin"
LOG_FILE="/tmp/kage-bunshin-sync-$(date +%Y%m%d_%H%M%S).log"

# Database settings
DB_NAME="claude_memory"
DB_USER="claude_mcp"
DB_PASSWORD="memory123"

################################################################################
# HELPER FUNCTIONS
################################################################################

log() {
    local level="$1"
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    case "$level" in
        INFO)  echo -e "${BLUE}[INFO]${NC} $message" | tee -a "$LOG_FILE" ;;
        SUCCESS) echo -e "${GREEN}[SUCCESS]${NC} $message" | tee -a "$LOG_FILE" ;;
        WARN)  echo -e "${YELLOW}[WARN]${NC} $message" | tee -a "$LOG_FILE" ;;
        ERROR) echo -e "${RED}[ERROR]${NC} $message" | tee -a "$LOG_FILE" ;;
    esac
}

show_help() {
    grep '^#' "$0" | grep -v '#!/bin/bash' | sed 's/^# //; s/^#//'
    exit 0
}

check_command() {
    local cmd="$1"
    if ! command -v "$cmd" &> /dev/null; then
        log ERROR "Required command not found: $cmd"
        log ERROR "Please install $cmd and try again"
        exit 1
    fi
}

################################################################################
# PRE-FLIGHT CHECKS
################################################################################

preflight_checks() {
    local target="$1"

    log INFO "Running pre-flight checks..."

    # Check required commands on source
    log INFO "Checking required commands on source server..."
    check_command "rsync"
    check_command "pg_dump"
    check_command "ssh"
    check_command "jq"
    check_command "psql"

    # Test SSH connectivity
    log INFO "Testing SSH connectivity to $target..."
    if ! ssh -o ConnectTimeout=10 "$target" "echo 'SSH OK'" &> /dev/null; then
        log ERROR "Cannot connect to $target via SSH"
        log ERROR "Please check SSH keys and network connectivity"
        exit 1
    fi
    log SUCCESS "SSH connectivity verified"

    # Check disk space on target (need at least 1GB free)
    log INFO "Checking disk space on $target..."
    local free_space=$(ssh "$target" "df -BG ~ | tail -1 | awk '{print \$4}' | sed 's/G//'")
    if [ "$free_space" -lt 1 ]; then
        log ERROR "Insufficient disk space on $target (${free_space}GB free, need at least 1GB)"
        exit 1
    fi
    log SUCCESS "Disk space OK (${free_space}GB free)"

    # Check if PostgreSQL is installed on target
    log INFO "Checking PostgreSQL on $target..."
    if ! ssh "$target" "command -v psql" &> /dev/null; then
        log WARN "PostgreSQL not found on $target - will need manual installation"
    else
        log SUCCESS "PostgreSQL found on $target"
    fi

    # Check if Python 3.13+ is installed on target
    log INFO "Checking Python version on $target..."
    local python_version=$(ssh "$target" "python3 --version 2>&1 | awk '{print \$2}' | cut -d. -f1,2")
    if [ -z "$python_version" ]; then
        log ERROR "Python 3 not found on $target"
        exit 1
    fi
    log SUCCESS "Python $python_version found on $target"

    log SUCCESS "All pre-flight checks passed"
}

################################################################################
# BACKUP FUNCTIONS
################################################################################

create_backup() {
    local target="$1"

    if [ "$SKIP_BACKUP" = true ]; then
        log INFO "Skipping backup (--skip-backup flag set)"
        return 0
    fi

    log INFO "Creating backup on $target..."
    local backup_timestamp=$(date +%Y%m%d_%H%M%S)

    # Backup .claude/ directory
    if ssh "$target" "[ -d ~/.claude ]"; then
        log INFO "Backing up existing .claude/ directory..."
        ssh "$target" "cp -r ~/.claude ~/.claude.backup.$backup_timestamp" || log WARN "Failed to backup .claude/"
    fi

    # Backup database
    if ssh "$target" "psql -U $DB_USER -d $DB_NAME -c '\\q' 2>/dev/null"; then
        log INFO "Backing up existing database..."
        ssh "$target" "mkdir -p ~/backups && pg_dump -U $DB_USER -d $DB_NAME -F c -f ~/backups/claude_memory_$backup_timestamp.dump" || log WARN "Failed to backup database"
    fi

    log SUCCESS "Backup created with timestamp: $backup_timestamp"
}

################################################################################
# SYNC FUNCTIONS
################################################################################

sync_claude_config() {
    local target="$1"

    log INFO "Syncing Claude Code configuration..."

    if [ ! -d "$SOURCE_CLAUDE_DIR" ]; then
        log ERROR "Source .claude directory not found: $SOURCE_CLAUDE_DIR"
        exit 1
    fi

    # Build rsync command with exclusions
    local rsync_cmd="rsync -avz --progress"
    rsync_cmd="$rsync_cmd --exclude 'debug/'"
    rsync_cmd="$rsync_cmd --exclude 'cache/'"
    rsync_cmd="$rsync_cmd --exclude 'file-history/'"
    rsync_cmd="$rsync_cmd --exclude 'projects/'"
    rsync_cmd="$rsync_cmd --exclude 'session-env/'"
    rsync_cmd="$rsync_cmd --exclude 'shell-snapshots/'"

    if [ "$DRY_RUN" = true ]; then
        rsync_cmd="$rsync_cmd --dry-run"
    fi

    log INFO "Running: $rsync_cmd"
    eval "$rsync_cmd $SOURCE_CLAUDE_DIR/ $target:~/.claude/" | tee -a "$LOG_FILE"

    if [ "$DRY_RUN" = false ]; then
        # Fix permissions on critical files
        log INFO "Fixing file permissions on $target..."
        ssh "$target" "chmod 600 ~/.claude/.credentials.json 2>/dev/null || true"
        ssh "$target" "chmod 644 ~/.claude/settings.json 2>/dev/null || true"
        ssh "$target" "chmod 755 ~/.claude/hooks/*.sh 2>/dev/null || true"
        ssh "$target" "chmod 644 ~/.claude/hooks/*.py 2>/dev/null || true"

        # Verify sync
        log INFO "Verifying Claude Code config sync..."
        if ssh "$target" "[ -f ~/.claude/settings.json ]"; then
            local plugin_count=$(ssh "$target" "jq '.enabledPlugins | length' ~/.claude/settings.json 2>/dev/null || echo 0")
            log SUCCESS "Claude Code config synced ($plugin_count plugins)"
        else
            log ERROR "Verification failed: settings.json not found on $target"
            return 1
        fi
    else
        log INFO "DRY RUN: Claude Code config would be synced"
    fi
}

sync_database() {
    local target="$1"

    log INFO "Syncing PostgreSQL database..."

    # Create database dump
    local dump_file="/tmp/claude_memory_$(date +%Y%m%d_%H%M%S).dump"
    log INFO "Creating database dump: $dump_file"

    if [ "$DRY_RUN" = false ]; then
        pg_dump -U "$DB_USER" -d "$DB_NAME" -F c -b -v -f "$dump_file" | tee -a "$LOG_FILE"

        # Transfer dump to target
        log INFO "Transferring database dump to $target..."
        scp "$dump_file" "$target:/tmp/" | tee -a "$LOG_FILE"

        # Restore on target
        log INFO "Restoring database on $target..."

        # Create database if not exists
        ssh "$target" "sudo -u postgres psql -c \"CREATE DATABASE $DB_NAME\" 2>/dev/null || echo 'Database already exists'"

        # Create user if not exists
        ssh "$target" "sudo -u postgres psql -c \"CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD'\" 2>/dev/null || echo 'User already exists'"

        # Restore dump
        ssh "$target" "pg_restore -U $DB_USER -d $DB_NAME -v /tmp/$(basename $dump_file)" 2>&1 | tee -a "$LOG_FILE" || log WARN "Some restore warnings (may be normal)"

        # Grant permissions
        ssh "$target" "sudo -u postgres psql -d $DB_NAME -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER\""
        ssh "$target" "sudo -u postgres psql -d $DB_NAME -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA development_docs TO $DB_USER\" 2>/dev/null || echo 'development_docs schema may not exist'"

        # Clean up
        rm -f "$dump_file"
        ssh "$target" "rm -f /tmp/$(basename $dump_file)"

        # Verify
        log INFO "Verifying database sync..."
        local task_count=$(ssh "$target" "psql -U $DB_USER -d $DB_NAME -t -c 'SELECT COUNT(*) FROM tasks' 2>/dev/null | tr -d ' '")
        log SUCCESS "Database synced ($task_count tasks in database)"
    else
        log INFO "DRY RUN: Database would be dumped and restored"
    fi
}

sync_repo() {
    local target="$1"

    log INFO "Syncing Kage Bunshin repository..."

    if [ ! -d "$SOURCE_PROJECT_DIR" ]; then
        log ERROR "Source project directory not found: $SOURCE_PROJECT_DIR"
        exit 1
    fi

    if [ "$DRY_RUN" = false ]; then
        # Check if repo exists on target
        if ssh "$target" "[ -d ~/projects/kage-bunshin/.git ]"; then
            log INFO "Repository exists on $target, pulling latest changes..."
            ssh "$target" "cd ~/projects/kage-bunshin && git pull origin master" | tee -a "$LOG_FILE"
        else
            log INFO "Cloning repository to $target..."
            ssh "$target" "mkdir -p ~/projects && git clone https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin.git ~/projects/kage-bunshin" | tee -a "$LOG_FILE"
        fi

        # Set up Python virtual environment
        log INFO "Setting up Python virtual environment on $target..."
        ssh "$target" "cd ~/projects/kage-bunshin && python3 -m venv venv" | tee -a "$LOG_FILE"

        # Install dependencies
        log INFO "Installing Python dependencies on $target..."
        ssh "$target" "cd ~/projects/kage-bunshin && source venv/bin/activate && pip install -r requirements.txt" | tee -a "$LOG_FILE"

        # Copy migrations if database is already set up
        log INFO "Ensuring migrations are available on $target..."
        scp "$SOURCE_PROJECT_DIR/migrations/"*.sql "$target:~/projects/kage-bunshin/migrations/" 2>/dev/null || log WARN "Could not copy migrations"

        log SUCCESS "Kage Bunshin repository synced"
    else
        log INFO "DRY RUN: Repository would be cloned/updated on $target"
    fi
}

sync_secrets() {
    local target="$1"

    log INFO "Syncing secrets to $target..."

    if [ "$DRY_RUN" = false ]; then
        # Create secrets file
        local secrets_file="/tmp/kage_bunshin_secrets.sh"
        cat > "$secrets_file" << 'EOF'
# Kage Bunshin Secrets - Auto-generated
# Source: sync-to-second-server.sh

# API Keys
export OPENAI_API_KEY="$(grep OPENAI_API_KEY ~/.bashrc | cut -d'"' -f2)"
export GEMINI_API_KEY="$(grep GEMINI_API_KEY ~/.bashrc | cut -d'"' -f2)"
export GOOGLE_API_KEY="$(grep GOOGLE_API_KEY ~/.bashrc | cut -d'"' -f2)"
export PERPLEXITY_API_KEY="$(grep PERPLEXITY_API_KEY ~/.bashrc | cut -d'"' -f2)"

# Kage Bunshin Configuration
export BASE_BRANCH="master"
export API_KEYS="dev-key-12345"

# Orchestrator Configuration (Optional)
export MAX_TOKENS_PER_TASK=50000
export MAX_REQUESTS_PER_MINUTE=50
EOF

        # Transfer secrets file
        log INFO "Transferring secrets to $target..."
        scp "$secrets_file" "$target:/tmp/" | tee -a "$LOG_FILE"

        # Append to .bashrc if not already present
        ssh "$target" "grep -q 'Kage Bunshin Secrets' ~/.bashrc || cat /tmp/kage_bunshin_secrets.sh >> ~/.bashrc"
        ssh "$target" "rm -f /tmp/kage_bunshin_secrets.sh"

        # Clean up local secrets file
        rm -f "$secrets_file"

        # Copy .pgpass
        log INFO "Setting up .pgpass on $target..."
        echo "localhost:5432:*:$DB_USER:$DB_PASSWORD" | ssh "$target" "cat > ~/.pgpass && chmod 600 ~/.pgpass"

        # Verify .credentials.json permissions (already synced with .claude/)
        ssh "$target" "chmod 600 ~/.claude/.credentials.json 2>/dev/null || echo 'credentials.json not yet synced'"

        log SUCCESS "Secrets synced to $target"
    else
        log INFO "DRY RUN: Secrets would be copied to $target"
    fi
}

################################################################################
# VERIFICATION
################################################################################

verify_sync() {
    local target="$1"

    log INFO "Verifying synchronization..."

    local errors=0

    # Check Claude Code
    log INFO "Checking Claude Code configuration..."
    if ssh "$target" "claude --version" &> /dev/null; then
        log SUCCESS "✓ Claude Code CLI is working"
    else
        log WARN "✗ Claude Code CLI not found or not working"
        ((errors++))
    fi

    if ssh "$target" "[ -f ~/.claude/settings.json ]"; then
        log SUCCESS "✓ Claude Code settings.json exists"
    else
        log ERROR "✗ Claude Code settings.json missing"
        ((errors++))
    fi

    # Check database
    log INFO "Checking database..."
    if ssh "$target" "psql -U $DB_USER -d $DB_NAME -c '\\q'" &> /dev/null; then
        log SUCCESS "✓ Database connection working"
        local task_count=$(ssh "$target" "psql -U $DB_USER -d $DB_NAME -t -c 'SELECT COUNT(*) FROM tasks' 2>/dev/null | tr -d ' '")
        log INFO "  Database has $task_count tasks"
    else
        log ERROR "✗ Cannot connect to database"
        ((errors++))
    fi

    # Check repository
    log INFO "Checking Kage Bunshin repository..."
    if ssh "$target" "[ -d ~/projects/kage-bunshin/.git ]"; then
        log SUCCESS "✓ Git repository exists"
    else
        log ERROR "✗ Git repository missing"
        ((errors++))
    fi

    if ssh "$target" "[ -f ~/projects/kage-bunshin/venv/bin/activate ]"; then
        log SUCCESS "✓ Python virtual environment exists"
    else
        log ERROR "✗ Python virtual environment missing"
        ((errors++))
    fi

    # Check secrets
    log INFO "Checking secrets..."
    if ssh "$target" "grep -q 'OPENAI_API_KEY' ~/.bashrc"; then
        log SUCCESS "✓ API keys configured in .bashrc"
    else
        log WARN "✗ API keys not found in .bashrc"
        ((errors++))
    fi

    if ssh "$target" "[ -f ~/.pgpass ]"; then
        log SUCCESS "✓ .pgpass file exists"
    else
        log WARN "✗ .pgpass file missing"
        ((errors++))
    fi

    # Summary
    if [ $errors -eq 0 ]; then
        log SUCCESS "All verification checks passed!"
    else
        log WARN "$errors verification check(s) failed - review above"
    fi

    return $errors
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    log INFO "==================================================================="
    log INFO "Kage Bunshin Server Synchronization"
    log INFO "==================================================================="
    log INFO "Log file: $LOG_FILE"
    log INFO ""

    # Parse arguments
    if [ $# -eq 0 ]; then
        show_help
    fi

    local target=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                log INFO "DRY RUN MODE: No changes will be made"
                ;;
            --config-only)
                SYNC_DATABASE=false
                SYNC_REPO=false
                SYNC_SECRETS=false
                ;;
            --database-only)
                SYNC_CONFIG=false
                SYNC_REPO=false
                SYNC_SECRETS=false
                ;;
            --repo-only)
                SYNC_CONFIG=false
                SYNC_DATABASE=false
                SYNC_SECRETS=false
                ;;
            --secrets-only)
                SYNC_CONFIG=false
                SYNC_DATABASE=false
                SYNC_REPO=false
                ;;
            --skip-backup)
                SKIP_BACKUP=true
                ;;
            --help)
                show_help
                ;;
            *)
                target="$1"
                ;;
        esac
        shift
    done

    if [ -z "$target" ]; then
        log ERROR "No target server specified"
        show_help
    fi

    log INFO "Target server: $target"
    log INFO "Sync config: $SYNC_CONFIG"
    log INFO "Sync database: $SYNC_DATABASE"
    log INFO "Sync repository: $SYNC_REPO"
    log INFO "Sync secrets: $SYNC_SECRETS"
    log INFO ""

    # Run pre-flight checks
    preflight_checks "$target"
    log INFO ""

    # Create backup
    create_backup "$target"
    log INFO ""

    # Perform synchronization
    if [ "$SYNC_CONFIG" = true ]; then
        sync_claude_config "$target"
        log INFO ""
    fi

    if [ "$SYNC_DATABASE" = true ]; then
        sync_database "$target"
        log INFO ""
    fi

    if [ "$SYNC_REPO" = true ]; then
        sync_repo "$target"
        log INFO ""
    fi

    if [ "$SYNC_SECRETS" = true ]; then
        sync_secrets "$target"
        log INFO ""
    fi

    # Verify sync
    if [ "$DRY_RUN" = false ]; then
        verify_sync "$target"
        log INFO ""
    fi

    log SUCCESS "==================================================================="
    log SUCCESS "Synchronization complete!"
    log SUCCESS "==================================================================="
    log INFO "Log file saved to: $LOG_FILE"

    if [ "$DRY_RUN" = false ]; then
        log INFO ""
        log INFO "Next steps:"
        log INFO "1. SSH to $target and verify services"
        log INFO "2. Start Kage Bunshin API: cd ~/projects/kage-bunshin && source venv/bin/activate && BASE_BRANCH=master uvicorn api.main:app --host 0.0.0.0 --port 8003"
        log INFO "3. Test with: curl -H 'X-API-Key: dev-key-12345' http://$target:8003/health"
    fi
}

# Run main function
main "$@"
