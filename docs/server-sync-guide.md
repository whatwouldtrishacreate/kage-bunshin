# Kage Bunshin Server Synchronization Guide

**Version:** 1.0.0
**Date:** January 9, 2026
**Author:** Claude Sonnet 4.5

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Detailed Setup](#detailed-setup)
5. [Phase 2: Bidirectional Sync](#phase-2-bidirectional-sync)
6. [Troubleshooting](#troubleshooting)
7. [Security Best Practices](#security-best-practices)
8. [Maintenance](#maintenance)
9. [FAQ](#faq)

---

## Overview

This guide covers synchronizing Claude Code CLI configuration and Kage Bunshin orchestrator setup from one Ubuntu Linux server (source) to a second server (target).

### What Gets Synced

| Component | Size | Method |
|-----------|------|--------|
| Claude Code Config (.claude/) | ~150MB | rsync |
| PostgreSQL Database (claude_memory) | ~50MB | pg_dump |
| Kage Bunshin Git Repo | ~5MB | git clone |
| Python Environment | varies | requirements.txt |
| Secrets (API keys, OAuth tokens) | <1KB | secure transfer |

### Sync Modes

**Phase 1: Unidirectional** (Implemented)
- Source server → Target server
- On-demand manual sync
- Use case: Backup, testing, deployment

**Phase 2: Bidirectional** (Optional - see below)
- Both servers sync with each other
- Git-based config management
- Use case: Multi-LLM Dev Team, high availability

---

## Prerequisites

### Source Server (This Server)

**Required Software:**
- rsync
- pg_dump (PostgreSQL client)
- SSH client
- jq (JSON processor)
- psql (PostgreSQL client)

**Required Access:**
- Read access to ~/.claude/
- PostgreSQL database access (claude_mcp user)
- Git repository access

### Target Server (Second Server)

**Required Software:**
- SSH server
- PostgreSQL 15+
- Python 3.13+
- Git 2.40+

**Required Disk Space:**
- Minimum 250MB free for full sync
- Recommended 1GB+ for future growth

**Network:**
- SSH port (22) accessible from source server
- Outbound internet access for git clone, pip install

### SSH Access

You must have **SSH key-based authentication** set up between servers:

```bash
# On source server, generate SSH key if not exists
ssh-keygen -t ed25519 -C "kage-bunshin-sync"

# Copy public key to target server
ssh-copy-id user@second-server

# Test connection
ssh user@second-server "echo 'SSH OK'"
```

---

## Quick Start

### 1. Dry Run (Preview Changes)

```bash
cd ~/projects/kage-bunshin
./scripts/sync-to-second-server.sh --dry-run user@second-server
```

This shows what would be synced without making any changes.

### 2. Full Synchronization

```bash
./scripts/sync-to-second-server.sh user@second-server
```

This performs a complete sync:
- Creates backup on target server
- Syncs Claude Code config
- Replicates PostgreSQL database
- Clones/updates Kage Bunshin repository
- Deploys secrets
- Verifies all components

### 3. Verify on Target Server

SSH to target server and run:

```bash
cd ~/projects/kage-bunshin
./scripts/verify-second-server.sh
```

All checks should pass (green ✓).

### 4. Start Services on Target Server

```bash
cd ~/projects/kage-bunshin
source venv/bin/activate
BASE_BRANCH=master uvicorn api.main:app --host 0.0.0.0 --port 8003
```

### 5. Test API

```bash
curl -H 'X-API-Key: dev-key-12345' http://second-server:8003/health
```

Expected response: `{"status":"healthy"}`

---

## Detailed Setup

### Step 1: Pre-Sync Preparation

**On Source Server:**

1. **Verify current setup is working:**
   ```bash
   # Test Claude Code
   claude --version

   # Test database
   psql -U claude_mcp -d claude_memory -c 'SELECT COUNT(*) FROM tasks'

   # Test Kage Bunshin
   cd ~/projects/kage-bunshin
   source venv/bin/activate
   python -c "import fastapi, asyncpg; print('OK')"
   ```

2. **Check for uncommitted changes:**
   ```bash
   cd ~/projects/kage-bunshin
   git status
   # Commit any changes before syncing
   ```

3. **Review secrets to be copied:**
   ```bash
   # These will be transferred to target server:
   grep -E '(OPENAI|GEMINI|PERPLEXITY|BASE_BRANCH|API_KEYS)' ~/.bashrc
   ```

**On Target Server:**

1. **Ensure PostgreSQL is installed:**
   ```bash
   sudo apt update
   sudo apt install postgresql postgresql-contrib
   sudo systemctl start postgresql
   sudo systemctl enable postgresql
   ```

2. **Ensure Python 3.13+ is installed:**
   ```bash
   python3 --version
   # If < 3.13, install from deadsnakes PPA:
   sudo add-apt-repository ppa:deadsnakes/ppa
   sudo apt update
   sudo apt install python3.13 python3.13-venv python3.13-dev
   ```

3. **Ensure Git is installed:**
   ```bash
   git --version
   sudo apt install git  # if needed
   ```

### Step 2: Run Synchronization

**Full Sync:**
```bash
cd ~/projects/kage-bunshin
./scripts/sync-to-second-server.sh user@second-server
```

The script will:
1. Run pre-flight checks (SSH, disk space, software)
2. Create backup on target (`~/.claude.backup.TIMESTAMP`)
3. Sync .claude/ directory (excluding debug/, cache/, projects/)
4. Export and transfer database dump
5. Restore database on target
6. Clone/update Kage Bunshin repository
7. Set up Python virtual environment
8. Install Python dependencies
9. Deploy secrets to ~/.bashrc and ~/.pgpass
10. Verify all components

**Estimated Time:** 10-20 minutes depending on network speed

**Partial Sync (Specific Components):**

```bash
# Sync only Claude Code config
./scripts/sync-to-second-server.sh --config-only user@second-server

# Sync only database
./scripts/sync-to-second-server.sh --database-only user@second-server

# Sync only repository
./scripts/sync-to-second-server.sh --repo-only user@second-server

# Sync only secrets
./scripts/sync-to-second-server.sh --secrets-only user@second-server
```

**Skip Backup (Faster, but risky):**
```bash
./scripts/sync-to-second-server.sh --skip-backup user@second-server
```

### Step 3: Post-Sync Verification

**On Target Server:**

1. **Run verification script:**
   ```bash
   cd ~/projects/kage-bunshin
   ./scripts/verify-second-server.sh --verbose
   ```

2. **Manual verification:**
   ```bash
   # Claude Code
   claude --version
   jq '.enabledPlugins | length' ~/.claude/settings.json

   # Database
   psql -U claude_mcp -d claude_memory -c '\dt public.*'
   psql -U claude_mcp -d claude_memory -c 'SELECT COUNT(*) FROM tasks'

   # Kage Bunshin
   cd ~/projects/kage-bunshin
   source venv/bin/activate
   python -c "import fastapi; import asyncpg; print('Dependencies OK')"

   # Secrets
   source ~/.bashrc
   echo $BASE_BRANCH
   echo $OPENAI_API_KEY | head -c 20
   ```

3. **Start API server:**
   ```bash
   cd ~/projects/kage-bunshin
   source venv/bin/activate
   BASE_BRANCH=master uvicorn api.main:app --host 0.0.0.0 --port 8003
   ```

4. **Test API (from another terminal):**
   ```bash
   # Health check
   curl -H 'X-API-Key: dev-key-12345' http://localhost:8003/health

   # Submit test task
   curl -X POST http://localhost:8003/api/v1/tasks \
     -H 'X-API-Key: dev-key-12345' \
     -H 'Content-Type: application/json' \
     -d '{
       "description": "Test task: write hello world to test.txt",
       "cli_assignments": [{"cli_name": "ollama", "timeout": 60}],
       "merge_strategy": "theirs"
     }'
   ```

### Step 4: Configure Auto-Start (Optional)

**Create systemd service on target server:**

```bash
sudo tee /etc/systemd/system/kage-bunshin.service > /dev/null <<EOF
[Unit]
Description=Kage Bunshin Orchestrator API
After=network.target postgresql.service

[Service]
Type=notify
User=$USER
WorkingDirectory=$HOME/projects/kage-bunshin
Environment="PATH=$HOME/projects/kage-bunshin/venv/bin"
Environment="BASE_BRANCH=master"
Environment="DATABASE_URL=postgresql://claude_mcp:memory123@localhost/claude_memory"
Environment="API_KEYS=dev-key-12345"
ExecStart=$HOME/projects/kage-bunshin/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8003
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable kage-bunshin
sudo systemctl start kage-bunshin

# Check status
sudo systemctl status kage-bunshin
```

---

## Phase 2: Bidirectional Sync

### Should You Implement Bidirectional Sync?

**PROCEED with Phase 2 IF:**
- ✅ You plan to implement Multi-LLM Dev Team project
  - Different servers will run different LLM roles (Architect, Backend Dev, etc.)
  - Both servers need shared plugin configs, skills, hooks
- ✅ You need high availability (>99.9% uptime)
  - Automatic failover if primary server fails
- ✅ Multiple team members editing configs on different servers

**SKIP Phase 2 IF:**
- ❌ Target server is just a backup/test environment
- ❌ Source server is always primary
- ❌ Config changes are infrequent (<1/week)

### Cost/Benefit Analysis

**Costs:**
- Implementation time: 6-8 hours
- Testing time: 2-3 hours
- Ongoing maintenance: ~1 hour/month (handling merge conflicts)
- Risk: Potential config corruption if conflicts mishandled

**Benefits:**
- **Multi-LLM Dev Team:** CRITICAL - enables distributed role execution
- **High Availability:** Failover in ~5 minutes
- **Version Control:** Audit trail of all config changes
- **Rollback:** Easy revert to previous config state

### Implementation: Git-Based Config Sync

**Recommended approach:** Store `.claude/` config in git repository

**Step 1: Create Private Git Repository**

On GitHub/GitLab, create a private repository:
```
Repository name: claude-code-config
Visibility: Private (contains OAuth tokens)
```

**Step 2: Initialize on Source Server**

```bash
cd ~/.claude

# Initialize git repo
git init
git config user.name "Source Server"
git config user.email "source@example.com"

# Create .gitignore
cat > .gitignore <<EOF
# Exclude ephemeral/large directories
debug/
cache/
file-history/
projects/
session-env/
shell-snapshots/
telemetry/

# Exclude sensitive auto-generated files
stats-cache.json
*.log
EOF

# Initial commit
git add .
git commit -m "Initial Claude Code config from source server"

# Add remote and push
git remote add origin git@github.com:your-org/claude-code-config.git
git branch -M main
git push -u origin main
```

**Step 3: Clone on Target Server**

```bash
# Remove existing .claude/ (already backed up)
cd ~
rm -rf .claude

# Clone config repository
git clone git@github.com:your-org/claude-code-config.git .claude
cd .claude
git config user.name "Target Server"
git config user.email "target@example.com"
```

**Step 4: Set Up Sync Automation**

Create git hooks for automatic sync:

```bash
# On both servers: ~/.claude/.git/hooks/post-commit
cat > ~/.claude/.git/hooks/post-commit <<'EOF'
#!/bin/bash
# Auto-push config changes after commit
git push origin main &> /dev/null || echo "Warning: Failed to push config changes"
EOF
chmod +x ~/.claude/.git/hooks/post-commit

# On both servers: ~/.claude/.git/hooks/post-merge
cat > ~/.claude/.git/hooks/post-merge <<'EOF'
#!/bin/bash
# Notify after pulling config changes
echo "✓ Claude Code config updated from remote"
echo "  Restart Claude Code sessions if running"
EOF
chmod +x ~/.claude/.git/hooks/post-merge
```

**Step 5: Workflow for Config Changes**

```bash
# After making config changes (e.g., adding plugin):
cd ~/.claude
git add settings.json plugins/installed_plugins.json
git commit -m "Add new plugin: xyz"
# Auto-pushes via post-commit hook

# On other server, pull changes:
cd ~/.claude
git pull --rebase

# Handle conflicts (rare):
git status
# Edit conflicting files
git add .
git rebase --continue
```

**Step 6: Scheduled Auto-Sync (Optional)**

Add to crontab on both servers:

```bash
# Pull config changes every 5 minutes
*/5 * * * * cd ~/.claude && git pull --rebase &> /dev/null
```

### Monitoring Bidirectional Sync

**Check sync status:**
```bash
cd ~/.claude
git status
git log --oneline --graph --all -5
```

**View pending changes from other server:**
```bash
cd ~/.claude
git fetch
git log HEAD..origin/main
```

**Manually resolve conflicts:**
```bash
cd ~/.claude
git pull --rebase
# If conflicts:
git status  # Shows conflicting files
# Edit files to resolve
git add .
git rebase --continue
```

---

## Troubleshooting

### Sync Script Fails

**Error: "Cannot connect to target via SSH"**

Solution:
```bash
# Test SSH manually
ssh user@second-server "echo 'Test'"

# Check SSH keys
ls -la ~/.ssh/id_*
ssh-copy-id user@second-server

# Verify SSH config
cat ~/.ssh/config  # Should have Host entry for second-server
```

**Error: "Insufficient disk space"**

Solution:
```bash
# Check disk space on target
ssh user@second-server "df -h ~"

# Clean up if needed
ssh user@second-server "du -sh ~/.claude/debug ~/.claude/cache ~/.claude/file-history"
ssh user@second-server "rm -rf ~/.claude/debug/* ~/.claude/cache/*"
```

**Error: "PostgreSQL not found on target"**

Solution:
```bash
# Install PostgreSQL on target server
ssh user@second-server "sudo apt update && sudo apt install -y postgresql postgresql-contrib"
ssh user@second-server "sudo systemctl start postgresql"
```

### Database Issues

**Error: "Cannot connect to database"**

Solution:
```bash
# On target server, check PostgreSQL status
systemctl status postgresql

# Ensure database and user exist
sudo -u postgres psql -c "CREATE DATABASE claude_memory"
sudo -u postgres psql -c "CREATE USER claude_mcp WITH PASSWORD 'memory123'"

# Grant permissions
sudo -u postgres psql -d claude_memory -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO claude_mcp"
```

**Error: "pg_restore warnings"**

These are usually normal (objects already exist). Check if data was actually restored:
```bash
psql -U claude_mcp -d claude_memory -c 'SELECT COUNT(*) FROM tasks'
```

### Claude Code Issues

**Error: "claude: command not found"**

Solution:
```bash
# Install Claude Code CLI on target server
# Follow official installation: https://claude.ai/cli
```

**Error: ".credentials.json missing or empty"**

Solution:
```bash
# Re-run config sync
./scripts/sync-to-second-server.sh --config-only user@second-server

# Or manually copy from source
scp ~/.claude/.credentials.json user@second-server:~/.claude/
ssh user@second-server "chmod 600 ~/.claude/.credentials.json"
```

### Kage Bunshin Issues

**Error: "ModuleNotFoundError: No module named 'fastapi'"**

Solution:
```bash
# Reinstall dependencies
cd ~/projects/kage-bunshin
source venv/bin/activate
pip install -r requirements.txt
```

**Error: "BASE_BRANCH environment variable not set"**

Solution:
```bash
# Add to ~/.bashrc
echo 'export BASE_BRANCH="master"' >> ~/.bashrc
source ~/.bashrc

# Or set temporarily
export BASE_BRANCH=master
```

### Verification Script Fails

**Many checks failing**

Solution:
```bash
# Run sync again with verbose logging
./scripts/sync-to-second-server.sh user@second-server 2>&1 | tee sync.log

# Review log for specific errors
grep ERROR sync.log
```

---

## Security Best Practices

### Secrets Management

**⚠️ IMPORTANT: The current implementation stores secrets in plaintext:**
- API keys in ~/.bashrc
- Database password in ~/.pgpass and code
- OAuth tokens in ~/.claude/.credentials.json

**Production Recommendations:**

1. **Use environment variable files:**
   ```bash
   # Create .env file (not in git)
   cat > ~/projects/kage-bunshin/.env <<EOF
   OPENAI_API_KEY=your-key-here
   GEMINI_API_KEY=your-key-here
   BASE_BRANCH=master
   DATABASE_URL=postgresql://claude_mcp:memory123@localhost/claude_memory
   EOF
   chmod 600 ~/projects/kage-bunshin/.env
   ```

2. **Use HashiCorp Vault or AWS Secrets Manager:**
   - Store secrets encrypted
   - Retrieve at runtime
   - Rotate regularly

3. **Use different API keys per server:**
   - Easier to revoke if one server compromised
   - Better audit trail

### File Permissions

Ensure critical files have correct permissions:

```bash
# On both servers
chmod 600 ~/.claude/.credentials.json
chmod 600 ~/.pgpass
chmod 600 ~/projects/kage-bunshin/.env  # if using .env
chmod 755 ~/.claude/hooks/*.sh
chmod 644 ~/.claude/hooks/*.py
```

### Network Security

**SSH Hardening:**
```bash
# Disable password authentication (keys only)
# Edit /etc/ssh/sshd_config:
# PasswordAuthentication no
# PubkeyAuthentication yes

# Restart SSH
sudo systemctl restart sshd
```

**Firewall Rules:**
```bash
# Only allow source server IP to access target SSH
sudo ufw allow from <source-server-ip> to any port 22

# Allow Kage Bunshin API (if needed externally)
sudo ufw allow 8003/tcp

# Enable firewall
sudo ufw enable
```

### OAuth Token Security

**⚠️ The Claude Code OAuth token is very sensitive:**
- Has full access to your Claude AI account
- Can execute commands on your behalf
- Should never be committed to git (even private repos)

**Best practice for bidirectional sync:**
```bash
# Add .credentials.json to .gitignore in config repo
echo ".credentials.json" >> ~/.claude/.gitignore

# Each server maintains its own .credentials.json
# DO NOT sync this file via git
```

---

## Maintenance

### Regular Sync Updates

**How often to sync:**
- After major config changes (new plugins, hooks)
- After significant code changes in Kage Bunshin
- Before important production deployments
- Monthly for database backup

**Incremental sync (faster):**
```bash
# Sync only changed configs
./scripts/sync-to-second-server.sh --config-only user@second-server

# Sync only new database records
# (Manual SQL for incremental changes)
```

### Monitoring Sync Health

**Create monitoring script:**
```bash
# On source server: ~/scripts/check-sync-status.sh
#!/bin/bash
# Compare database record counts
source_count=$(psql -U claude_mcp -d claude_memory -t -c 'SELECT COUNT(*) FROM tasks' | tr -d ' ')
target_count=$(ssh user@second-server "psql -U claude_mcp -d claude_memory -t -c 'SELECT COUNT(*) FROM tasks'" | tr -d ' ')

echo "Source tasks: $source_count"
echo "Target tasks: $target_count"

if [ "$source_count" != "$target_count" ]; then
    echo "⚠️ WARNING: Task counts differ - consider re-syncing"
fi
```

### Backup Strategy

**Automated backups on target server:**

```bash
# Add to crontab: daily database backup at 2 AM
0 2 * * * pg_dump -U claude_mcp -d claude_memory -F c -f ~/backups/claude_memory_$(date +\%Y\%m\%d).dump

# Add to crontab: weekly .claude/ backup
0 3 * * 0 tar -czf ~/backups/claude_config_$(date +\%Y\%m\%d).tar.gz ~/.claude/

# Retain backups for 30 days
0 4 * * * find ~/backups/ -name "*.dump" -mtime +30 -delete
0 4 * * * find ~/backups/ -name "*.tar.gz" -mtime +30 -delete
```

### Updating Scripts

After modifying sync scripts on source server:

```bash
# Re-sync scripts to target
scp ~/projects/kage-bunshin/scripts/*.sh user@second-server:~/projects/kage-bunshin/scripts/
ssh user@second-server "chmod +x ~/projects/kage-bunshin/scripts/*.sh"
```

---

## FAQ

**Q: Can I sync to multiple target servers?**

A: Yes! Run the sync script multiple times with different targets:
```bash
./scripts/sync-to-second-server.sh user@server2
./scripts/sync-to-second-server.sh user@server3
```

**Q: What if source and target are on different networks?**

A: You'll need:
1. VPN connection between networks, OR
2. SSH tunnel/jump host, OR
3. Expose SSH on target via reverse proxy

**Q: Can I sync from target back to source?**

A: With Phase 2 (bidirectional sync), yes. Otherwise, you'd need to swap the script direction (not recommended).

**Q: How do I rollback a bad sync?**

A: Use the automatic backup:
```bash
# On target server
cd ~
rm -rf .claude
mv .claude.backup.TIMESTAMP .claude

# Restore database
psql -U postgres -c 'DROP DATABASE claude_memory'
psql -U postgres -c 'CREATE DATABASE claude_memory'
pg_restore -U claude_mcp -d claude_memory ~/backups/claude_memory_TIMESTAMP.dump
```

**Q: What happens if I run sync twice?**

A: Safe to run multiple times - rsync is idempotent:
- Files already synced are skipped
- Database restore will overwrite (which is fine)
- Backup is created each time

**Q: Can I sync different versions of Kage Bunshin?**

A: Not recommended. Both servers should run the same git commit:
```bash
# On source
cd ~/projects/kage-bunshin
git log -1 --format="%H"  # Get commit hash

# On target after sync
cd ~/projects/kage-bunshin
git log -1 --format="%H"  # Should match
```

**Q: Does sync preserve running tasks?**

A: No - database is fully replaced. Best practice:
1. Wait for all tasks to complete on source
2. Run sync
3. Start API on target

**Q: How do I sync only specific plugins?**

A: Currently not supported. You can manually:
```bash
# Sync specific plugin
rsync -avz ~/.claude/plugins/cache/plugin-name/ user@second-server:~/.claude/plugins/cache/plugin-name/
```

**Q: What about different Claude Code versions?**

A: Both servers should run the same Claude Code version:
```bash
# Check versions
claude --version  # On source
ssh user@second-server "claude --version"  # On target

# Update if different
# Follow official Claude Code upgrade guide
```

---

## Support and Feedback

**Issues:** https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/issues

**Documentation:** This file + plan at `/home/ndninja/.claude/plans/vectorized-swimming-meadow.md`

**Logs:** All sync operations logged to `/tmp/kage-bunshin-sync-TIMESTAMP.log`

---

**Version History:**
- 1.0.0 (2026-01-09): Initial release - Phase 1 unidirectional sync

---

**Next Steps:**
1. Run sync to target server
2. Verify all components working
3. Test API with sample tasks
4. Decide on Phase 2 based on Multi-LLM Dev Team project timeline
