"""
Orchestrator Configuration

Global configuration constants for the Kage Bunshin orchestrator.
"""

import os

# ============================================================================
# BUDGET LIMITS (LLM Council Phase 1 Recommendation)
# ============================================================================

# Maximum tokens allowed per task execution
# Prevents runaway costs from recursive loops or excessive generation
# Default: 50,000 tokens (~$0.75 for Claude, ~38 pages of text)
# Set via environment: EXPORT MAX_TOKENS_PER_TASK=100000
MAX_TOKENS_PER_TASK = int(os.getenv("MAX_TOKENS_PER_TASK", "50000"))

# Token counting threshold for warnings
# Log warning when task exceeds this percentage of budget
# Default: 80% (40,000 tokens if MAX=50,000)
TOKEN_WARNING_THRESHOLD = float(os.getenv("TOKEN_WARNING_THRESHOLD", "0.8"))

# ============================================================================
# RATE LIMITING (LLM Council Phase 1 Recommendation)
# ============================================================================

# Maximum requests per minute for API-based CLIs
# Default: 50 RPM (conservative, well below typical API limits)
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "50"))

# Exponential backoff configuration for 429 errors
# Base delay in seconds (will be multiplied by 2^attempt)
RATE_LIMIT_BACKOFF_BASE = float(os.getenv("RATE_LIMIT_BACKOFF_BASE", "1.0"))

# Maximum backoff delay in seconds (prevents infinite waits)
RATE_LIMIT_BACKOFF_MAX = float(os.getenv("RATE_LIMIT_BACKOFF_MAX", "60.0"))

# Maximum retry attempts for rate limit errors
RATE_LIMIT_MAX_RETRIES = int(os.getenv("RATE_LIMIT_MAX_RETRIES", "5"))

# ============================================================================
# EXECUTION SETTINGS
# ============================================================================

# Default timeout for CLI executions (seconds)
DEFAULT_CLI_TIMEOUT = int(os.getenv("DEFAULT_CLI_TIMEOUT", "300"))

# Maximum parallel CLI executions per task
MAX_PARALLEL_CLIS = int(os.getenv("MAX_PARALLEL_CLIS", "5"))

# ============================================================================
# WORKTREE SETTINGS
# ============================================================================

# Auto-cleanup worktrees older than N days
WORKTREE_CLEANUP_DAYS = int(os.getenv("WORKTREE_CLEANUP_DAYS", "7"))

# Maximum number of active worktrees (prevents disk bloat)
MAX_ACTIVE_WORKTREES = int(os.getenv("MAX_ACTIVE_WORKTREES", "50"))
