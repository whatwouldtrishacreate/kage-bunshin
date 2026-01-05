#!/usr/bin/env python3
"""
Git Worktree Manager - Per-Session Architecture (CLI Council)
=============================================================

Each CLI session gets its own worktree:
- Worktree path: .cli-council/worktrees/session-{session_id}-{cli_name}/
- Branch name: cli-council/{task_id}/{cli_name}
- Ownership metadata: .cli-council/ownership.json

This allows:
1. Multiple CLIs to work on same task in parallel (each in isolated worktree)
2. Session-based isolation (1 CLI session = 1 worktree, can span multiple subtasks)
3. File-level locking to prevent race conditions
4. Clear ownership tracking for merge coordination

Differences from Auto-Claude:
- Auto-Claude: 1 spec → 1 worktree (sequential)
- CLI Council: 1 session → 1 worktree (parallel CLIs possible)
"""

import asyncio
import fcntl
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


class WorktreeError(Exception):
    """Error during worktree operations."""
    pass


@dataclass
class SessionWorktree:
    """Information about a CLI session's worktree."""

    session_id: str  # Unique session ID (e.g., "session-abc123")
    cli_name: str  # CLI name (e.g., "auto-claude", "ollama", "claude-code")
    task_id: str  # Task identifier (e.g., "002-implement-memory")
    worktree_path: Path  # Path to worktree directory
    branch_name: str  # Git branch name
    base_branch: str  # Base branch (e.g., "main")
    lock_fd: Optional[int] = None  # File descriptor for fcntl lock
    created_at: Optional[str] = None  # ISO timestamp
    is_active: bool = True

    # Statistics
    commit_count: int = 0
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


class WorktreeManager:
    """
    Manages per-session Git worktrees for CLI Council.

    Each CLI execution session gets its own isolated worktree with file-level
    locking to prevent race conditions during parallel execution.
    """

    def __init__(self, project_dir: Path, base_branch: Optional[str] = None):
        self.project_dir = project_dir
        self.base_branch = base_branch or self._detect_base_branch()
        self.worktrees_dir = project_dir / ".cli-council" / "worktrees"
        self.metadata_dir = project_dir / ".cli-council"
        self.ownership_file = self.metadata_dir / "ownership.json"
        self._merge_lock = asyncio.Lock()

    def _detect_base_branch(self) -> str:
        """
        Detect the base branch for worktree creation.

        Priority order:
        1. DEFAULT_BRANCH environment variable
        2. Auto-detect main/master (if they exist)
        3. Fall back to current branch (with warning)

        Returns:
            The detected base branch name
        """
        # 1. Check for DEFAULT_BRANCH env var
        env_branch = os.getenv("DEFAULT_BRANCH")
        if env_branch:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", env_branch],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                return env_branch
            else:
                print(
                    f"Warning: DEFAULT_BRANCH '{env_branch}' not found, auto-detecting..."
                )

        # 2. Auto-detect main/master
        for branch in ["main", "master"]:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                return branch

        # 3. Fall back to current branch with warning
        current = self._get_current_branch()
        print("Warning: Could not find 'main' or 'master' branch.")
        print(f"Warning: Using current branch '{current}' as base for worktree.")
        print("Tip: Set DEFAULT_BRANCH=your-branch in .env to avoid this.")
        return current

    def _get_current_branch(self) -> str:
        """Get the current git branch."""
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise WorktreeError(f"Failed to get current branch: {result.stderr}")
        return result.stdout.strip()

    async def _run_git(
        self, args: List[str], cwd: Optional[Path] = None
    ) -> subprocess.CompletedProcess:
        """Run a git command asynchronously and return the result."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd or self.project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        return subprocess.CompletedProcess(
            args=["git"] + args,
            returncode=proc.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    def setup(self) -> None:
        """Create worktrees directory and metadata if needed."""
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ownership file if not exists
        if not self.ownership_file.exists():
            self._save_ownership({})

    # ==================== Ownership Tracking ====================

    def _load_ownership(self) -> Dict[str, Any]:
        """Load ownership metadata from JSON file."""
        if not self.ownership_file.exists():
            return {}
        try:
            with open(self.ownership_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_ownership(self, data: Dict[str, Any]) -> None:
        """Save ownership metadata to JSON file."""
        with open(self.ownership_file, "w") as f:
            json.dump(data, f, indent=2)

    def _register_session_ownership(self, session: SessionWorktree) -> None:
        """Register a session's ownership in metadata."""
        ownership = self._load_ownership()
        ownership[session.session_id] = {
            "cli_name": session.cli_name,
            "task_id": session.task_id,
            "worktree_path": str(session.worktree_path),
            "branch_name": session.branch_name,
            "created_at": session.created_at or datetime.now().isoformat(),
            "is_active": session.is_active,
        }
        self._save_ownership(ownership)

    def _unregister_session_ownership(self, session_id: str) -> None:
        """Remove a session's ownership from metadata."""
        ownership = self._load_ownership()
        if session_id in ownership:
            del ownership[session_id]
            self._save_ownership(ownership)

    # ==================== Per-Session Worktree Methods ====================

    def get_worktree_path(self, session_id: str, cli_name: str) -> Path:
        """Get the worktree path for a session."""
        return self.worktrees_dir / f"session-{session_id}-{cli_name}"

    def get_branch_name(self, task_id: str, cli_name: str) -> str:
        """Get the branch name for a task/CLI combination."""
        return f"cli-council/{task_id}/{cli_name}"

    async def create_session_worktree(
        self, session_id: str, cli_name: str, task_id: str
    ) -> SessionWorktree:
        """
        Create a worktree for a CLI session with file-level locking.

        Args:
            session_id: Unique session identifier
            cli_name: CLI name (e.g., "auto-claude", "ollama")
            task_id: Task identifier (e.g., "002-implement-memory")

        Returns:
            SessionWorktree with lock acquired

        Raises:
            WorktreeError: If worktree creation fails
        """
        worktree_path = self.get_worktree_path(session_id, cli_name)
        branch_name = self.get_branch_name(task_id, cli_name)

        # Remove existing if present (from crashed previous run)
        if worktree_path.exists():
            await self._run_git(["worktree", "remove", "--force", str(worktree_path)])

        # Delete branch if it exists (from previous attempt)
        await self._run_git(["branch", "-D", branch_name])

        # Create worktree with new branch from base
        result = await self._run_git(
            ["worktree", "add", "-b", branch_name, str(worktree_path), self.base_branch]
        )

        if result.returncode != 0:
            raise WorktreeError(
                f"Failed to create worktree for session {session_id}: {result.stderr}"
            )

        # Acquire fcntl lock on worktree directory
        lock_file = worktree_path / ".worktree.lock"
        lock_fd = open(lock_file, "w")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorktreeError(
                f"Worktree already locked by another process: {worktree_path}"
            )

        print(f"Created worktree: session-{session_id}-{cli_name} on branch {branch_name}")

        # Create session object
        session = SessionWorktree(
            session_id=session_id,
            cli_name=cli_name,
            task_id=task_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_branch=self.base_branch,
            lock_fd=lock_fd.fileno(),
            created_at=datetime.now().isoformat(),
            is_active=True,
        )

        # Register ownership
        self._register_session_ownership(session)

        return session

    async def remove_session_worktree(
        self, session: SessionWorktree, delete_branch: bool = False
    ) -> None:
        """
        Remove a session's worktree and release lock.

        Args:
            session: The session worktree to remove
            delete_branch: Whether to also delete the branch
        """
        # Release lock if held
        if session.lock_fd is not None:
            try:
                fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
                os.close(session.lock_fd)
            except OSError:
                pass

        # Remove worktree
        if session.worktree_path.exists():
            result = await self._run_git(
                ["worktree", "remove", "--force", str(session.worktree_path)]
            )
            if result.returncode == 0:
                print(f"Removed worktree: session-{session.session_id}-{session.cli_name}")
            else:
                print(f"Warning: Could not remove worktree: {result.stderr}")
                shutil.rmtree(session.worktree_path, ignore_errors=True)

        # Delete branch if requested
        if delete_branch:
            await self._run_git(["branch", "-D", session.branch_name])
            print(f"Deleted branch: {session.branch_name}")

        # Unregister ownership
        self._unregister_session_ownership(session.session_id)

        # Prune stale worktree references
        await self._run_git(["worktree", "prune"])

    async def get_session_stats(self, session: SessionWorktree) -> Dict[str, int]:
        """Get diff statistics for a session's worktree."""
        stats = {
            "commit_count": 0,
            "files_changed": 0,
            "additions": 0,
            "deletions": 0,
        }

        if not session.worktree_path.exists():
            return stats

        # Commit count
        result = await self._run_git(
            ["rev-list", "--count", f"{self.base_branch}..HEAD"],
            cwd=session.worktree_path,
        )
        if result.returncode == 0:
            stats["commit_count"] = int(result.stdout.strip() or "0")

        # Diff stats
        result = await self._run_git(
            ["diff", "--shortstat", f"{self.base_branch}...HEAD"],
            cwd=session.worktree_path,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse: "3 files changed, 50 insertions(+), 10 deletions(-)"
            match = re.search(r"(\d+) files? changed", result.stdout)
            if match:
                stats["files_changed"] = int(match.group(1))
            match = re.search(r"(\d+) insertions?", result.stdout)
            if match:
                stats["additions"] = int(match.group(1))
            match = re.search(r"(\d+) deletions?", result.stdout)
            if match:
                stats["deletions"] = int(match.group(1))

        return stats

    async def commit_in_worktree(self, session: SessionWorktree, message: str) -> bool:
        """Commit all changes in a session's worktree."""
        if not session.worktree_path.exists():
            return False

        await self._run_git(["add", "."], cwd=session.worktree_path)
        result = await self._run_git(
            ["commit", "-m", message], cwd=session.worktree_path
        )

        if result.returncode == 0:
            return True
        elif "nothing to commit" in result.stdout + result.stderr:
            return True
        else:
            print(f"Commit failed: {result.stderr}")
            return False

    async def get_changed_files(self, session: SessionWorktree) -> List[tuple]:
        """Get list of changed files in a session's worktree."""
        if not session.worktree_path.exists():
            return []

        result = await self._run_git(
            ["diff", "--name-status", f"{self.base_branch}...HEAD"],
            cwd=session.worktree_path,
        )

        files = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                files.append((parts[0], parts[1]))

        return files

    # ==================== Listing & Discovery ====================

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """List all active CLI sessions from ownership metadata."""
        ownership = self._load_ownership()
        return [
            {
                "session_id": session_id,
                **session_data,
            }
            for session_id, session_data in ownership.items()
            if session_data.get("is_active", False)
        ]

    async def cleanup_stale_worktrees(self) -> None:
        """Remove worktrees that aren't registered with git."""
        if not self.worktrees_dir.exists():
            return

        # Get list of registered worktrees
        result = await self._run_git(["worktree", "list", "--porcelain"])
        registered_paths = set()
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                registered_paths.add(Path(line.split(" ", 1)[1]))

        # Remove unregistered directories
        for item in self.worktrees_dir.iterdir():
            if item.is_dir() and item not in registered_paths:
                print(f"Removing stale worktree directory: {item.name}")
                shutil.rmtree(item, ignore_errors=True)

        await self._run_git(["worktree", "prune"])

    async def has_uncommitted_changes(self, session: Optional[SessionWorktree] = None) -> bool:
        """Check if there are uncommitted changes in a session's worktree."""
        cwd = session.worktree_path if session and session.worktree_path.exists() else None
        result = await self._run_git(["status", "--porcelain"], cwd=cwd)
        return bool(result.stdout.strip())
