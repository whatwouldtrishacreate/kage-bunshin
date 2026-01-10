#!/usr/bin/env python3
"""
Checkpoint Manager for CLI Council
===================================

Git-based checkpoint and rollback system for failure recovery.

Architecture:
- Checkpoints = Git commits + JSON metadata
- Recovery strategies: rollback_last, rollback_safe, retry_current, escalate
- Target: >80% recovery rate for transient failures

Checkpoint Flow:
1. Before task execution → create baseline checkpoint
2. Before each retry → create retry checkpoint
3. On failure → suggest recovery strategy
4. Apply recovery → rollback to checkpoint or retry

File Structure:
    .cli-council/checkpoints/{session_id}/{checkpoint_id}.json:
    {
        "checkpoint_id": "a1b2c3d",
        "session_id": "session-abc123",
        "cli_name": "claude-code",
        "task_id": "task-xyz",
        "commit_sha": "a1b2c3d4e5f6...",
        "reason": "Pre-execution baseline",
        "created_at": "2026-01-09T12:00:00Z",
        "files_changed": ["src/api.py", "src/auth.py"],
        "is_safe_rollback_point": true
    }

Usage:
    checkpoint_mgr = CheckpointManager(project_dir)

    # Create checkpoint before execution
    checkpoint = await checkpoint_mgr.create_checkpoint(
        session=session,
        reason="Pre-execution baseline"
    )

    # On failure, get recovery strategy
    strategy = await checkpoint_mgr.suggest_recovery_strategy(
        session=session,
        failure_result=result
    )

    # Apply rollback if recommended
    if strategy.recommended_checkpoint:
        await checkpoint_mgr.rollback_to_checkpoint(
            session=session,
            checkpoint=strategy.recommended_checkpoint
        )
"""

import asyncio
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .worktree import SessionWorktree


class CheckpointError(Exception):
    """Error during checkpoint operations."""
    pass


@dataclass
class Checkpoint:
    """
    A git commit-based checkpoint for rollback.

    Represents a safe point in the worktree history that can be
    restored if execution fails.
    """
    checkpoint_id: str  # Short commit SHA (first 7 chars)
    session_id: str
    cli_name: str
    task_id: str
    commit_sha: str  # Full commit SHA for rollback
    reason: str  # Why this checkpoint was created
    created_at: str
    files_changed: List[str]  # Files modified since previous checkpoint
    is_safe_rollback_point: bool  # Whether safe to rollback to this point

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class RecoveryStrategy:
    """
    Recommended recovery strategy after a failure.

    Based on error analysis and checkpoint history.
    """
    strategy_type: str  # "rollback_last", "rollback_safe", "retry_current", "escalate"
    recommended_checkpoint: Optional[Checkpoint]
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Explanation for this recommendation

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "strategy_type": self.strategy_type,
            "recommended_checkpoint": (
                self.recommended_checkpoint.checkpoint_id
                if self.recommended_checkpoint
                else None
            ),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


@dataclass
class RollbackResult:
    """
    Result of a rollback operation.
    """
    success: bool
    checkpoint_id: str
    files_restored: List[str]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return asdict(self)


class CheckpointManager:
    """
    Manages git-based checkpoints for failure recovery.

    Creates checkpoints (git commits + metadata) before risky operations
    and provides rollback capabilities when failures occur.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize checkpoint manager.

        Args:
            project_dir: Project root directory
        """
        self.project_dir = project_dir
        self.checkpoint_dir = project_dir / ".cli-council" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_dir(self, session_id: str) -> Path:
        """Get checkpoint directory for a session."""
        checkpoint_session_dir = self.checkpoint_dir / session_id
        checkpoint_session_dir.mkdir(exist_ok=True)
        return checkpoint_session_dir

    def _get_checkpoint_file_path(self, session_id: str, checkpoint_id: str) -> Path:
        """Get path to checkpoint metadata file."""
        return self._get_checkpoint_dir(session_id) / f"{checkpoint_id}.json"

    async def _run_git_command(
        self,
        worktree_path: Path,
        command: List[str],
        check: bool = True
    ) -> tuple[str, str, int]:
        """
        Run a git command in the worktree (async).

        Args:
            worktree_path: Path to worktree
            command: Git command and arguments (without 'git' prefix)
            check: Raise exception on non-zero exit

        Returns:
            Tuple of (stdout, stderr, returncode)

        Raises:
            CheckpointError: If command fails and check=True
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *command,
                cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            if check and process.returncode != 0:
                raise CheckpointError(
                    f"Git command failed: {' '.join(command)}\n"
                    f"Error: {stderr_str}"
                )

            return (stdout_str, stderr_str, process.returncode)
        except Exception as e:
            if isinstance(e, CheckpointError):
                raise
            raise CheckpointError(
                f"Failed to execute git command: {' '.join(command)}\n"
                f"Error: {str(e)}"
            )

    async def _get_changed_files(self, worktree_path: Path) -> List[str]:
        """
        Get list of files changed since last commit.

        Args:
            worktree_path: Path to worktree

        Returns:
            List of changed file paths
        """
        stdout, _, _ = await self._run_git_command(
            worktree_path,
            ["diff", "--name-only", "HEAD"],
            check=False
        )

        # Also check untracked files
        untracked_stdout, _, _ = await self._run_git_command(
            worktree_path,
            ["ls-files", "--others", "--exclude-standard"],
            check=False
        )

        changed_files = []
        if stdout:
            changed_files.extend(stdout.strip().split('\n'))
        if untracked_stdout:
            changed_files.extend(untracked_stdout.strip().split('\n'))

        return [f for f in changed_files if f]  # Remove empty strings

    # ==================== Checkpoint Creation ====================

    async def create_checkpoint(
        self,
        session: SessionWorktree,
        reason: str,
        is_safe_rollback_point: bool = True
    ) -> Checkpoint:
        """
        Create a git commit checkpoint with metadata.

        Args:
            session: Session worktree to checkpoint
            reason: Reason for checkpoint (e.g., "Pre-execution baseline")
            is_safe_rollback_point: Whether this is a safe rollback point

        Returns:
            Created Checkpoint object

        Raises:
            CheckpointError: If checkpoint creation fails
        """
        worktree_path = session.worktree_path

        # Get files that would be committed
        files_changed = await self._get_changed_files(worktree_path)

        # Stage all changes
        await self._run_git_command(worktree_path, ["add", "."])

        # Create commit (sanitize reason to prevent command injection)
        safe_reason = reason.replace('\n', ' ').replace('"', '\\"')
        commit_message = f"[CHECKPOINT] {safe_reason}"
        await self._run_git_command(
            worktree_path,
            ["commit", "-m", commit_message, "--allow-empty"]
        )

        # Get commit SHA
        stdout, _, _ = await self._run_git_command(
            worktree_path,
            ["rev-parse", "HEAD"]
        )
        commit_sha = stdout.strip()
        checkpoint_id = commit_sha[:7]  # Short SHA

        # Create checkpoint object
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            session_id=session.session_id,
            cli_name=session.cli_name,
            task_id=session.task_id,
            commit_sha=commit_sha,
            reason=safe_reason,
            created_at=datetime.now().isoformat(),
            files_changed=files_changed,
            is_safe_rollback_point=is_safe_rollback_point
        )

        # Save metadata
        checkpoint_file = self._get_checkpoint_file_path(
            session.session_id,
            checkpoint_id
        )
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint.to_dict(), f, indent=2)

        return checkpoint

    async def get_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str
    ) -> Optional[Checkpoint]:
        """
        Load a checkpoint from metadata.

        Args:
            session_id: Session identifier
            checkpoint_id: Checkpoint identifier (short SHA)

        Returns:
            Checkpoint object if found, None otherwise
        """
        checkpoint_file = self._get_checkpoint_file_path(session_id, checkpoint_id)
        if not checkpoint_file.exists():
            return None

        try:
            with open(checkpoint_file, 'r') as f:
                data = json.load(f)
            return Checkpoint(**data)
        except (json.JSONDecodeError, IOError, TypeError) as e:
            print(f"Warning: Failed to load checkpoint {checkpoint_id}: {e}")
            return None

    async def get_session_checkpoints(
        self,
        session_id: str
    ) -> List[Checkpoint]:
        """
        Get all checkpoints for a session, ordered by creation time.

        Args:
            session_id: Session identifier

        Returns:
            List of Checkpoint objects (newest first)
        """
        checkpoint_dir = self._get_checkpoint_dir(session_id)
        checkpoints = []

        for checkpoint_file in checkpoint_dir.glob("*.json"):
            checkpoint_id = checkpoint_file.stem
            checkpoint = await self.get_checkpoint(session_id, checkpoint_id)
            if checkpoint:
                checkpoints.append(checkpoint)

        # Sort by creation time (newest first)
        checkpoints.sort(
            key=lambda c: c.created_at,
            reverse=True
        )

        return checkpoints

    # ==================== Rollback Operations ====================

    async def rollback_to_checkpoint(
        self,
        session: SessionWorktree,
        checkpoint: Checkpoint
    ) -> RollbackResult:
        """
        Rollback worktree to a checkpoint.

        Performs git reset --hard to restore worktree state.

        Args:
            session: Session worktree to rollback
            checkpoint: Checkpoint to rollback to

        Returns:
            RollbackResult with success status

        Raises:
            CheckpointError: If rollback fails
        """
        worktree_path = session.worktree_path

        try:
            # Get list of files before rollback (for reporting)
            files_before = await self._get_changed_files(worktree_path)

            # Perform hard reset to checkpoint commit
            await self._run_git_command(
                worktree_path,
                ["reset", "--hard", checkpoint.commit_sha]
            )

            # Clean untracked files (including gitignored files with -x)
            await self._run_git_command(
                worktree_path,
                ["clean", "-fdx"]
            )

            return RollbackResult(
                success=True,
                checkpoint_id=checkpoint.checkpoint_id,
                files_restored=files_before
            )

        except CheckpointError as e:
            return RollbackResult(
                success=False,
                checkpoint_id=checkpoint.checkpoint_id,
                files_restored=[],
                error=str(e)
            )

    # ==================== Recovery Strategy ====================

    async def suggest_recovery_strategy(
        self,
        session: SessionWorktree,
        failure_result: Any  # ExecutionResult
    ) -> RecoveryStrategy:
        """
        Analyze failure and suggest recovery strategy.

        Classifies error type and recommends appropriate recovery:
        - rollback_last: Rollback to most recent checkpoint
        - rollback_safe: Rollback to last safe checkpoint
        - retry_current: Retry without rollback (transient error)
        - escalate: Give up, report failure

        Args:
            session: Session that failed
            failure_result: ExecutionResult from failed execution

        Returns:
            RecoveryStrategy with recommendation
        """
        # Get checkpoint history
        checkpoints = await self.get_session_checkpoints(session.session_id)

        if not checkpoints:
            # No checkpoints available
            return RecoveryStrategy(
                strategy_type="escalate",
                recommended_checkpoint=None,
                confidence=1.0,
                reasoning="No checkpoints available for rollback"
            )

        # Classify error type
        error_type = self._classify_error(failure_result)

        if error_type == "transient":
            # Transient errors: retry without rollback
            return RecoveryStrategy(
                strategy_type="retry_current",
                recommended_checkpoint=None,
                confidence=0.8,
                reasoning="Transient error detected (network, timeout). Retry likely to succeed."
            )

        elif error_type == "corrupted_state":
            # Corrupted state: rollback to last safe checkpoint
            safe_checkpoints = [c for c in checkpoints if c.is_safe_rollback_point]
            if safe_checkpoints:
                return RecoveryStrategy(
                    strategy_type="rollback_safe",
                    recommended_checkpoint=safe_checkpoints[0],
                    confidence=0.9,
                    reasoning="State corruption detected. Rolling back to last safe checkpoint."
                )
            else:
                return RecoveryStrategy(
                    strategy_type="rollback_last",
                    recommended_checkpoint=checkpoints[0],
                    confidence=0.7,
                    reasoning="State corruption detected. Rolling back to most recent checkpoint."
                )

        elif error_type == "logic_error":
            # Logic error: rollback to last checkpoint
            return RecoveryStrategy(
                strategy_type="rollback_last",
                recommended_checkpoint=checkpoints[0],
                confidence=0.6,
                reasoning="Logic error detected. Rolling back to previous state for retry."
            )

        else:
            # Unknown error: escalate
            return RecoveryStrategy(
                strategy_type="escalate",
                recommended_checkpoint=None,
                confidence=0.9,
                reasoning=f"Unknown error type: {error_type}. Manual intervention required."
            )

    def _classify_error(self, failure_result: Any) -> str:
        """
        Classify error type from execution result.

        Args:
            failure_result: ExecutionResult from failed execution

        Returns:
            Error classification: "transient", "corrupted_state", "logic_error", "unknown"
        """
        if not hasattr(failure_result, 'error') or not failure_result.error:
            return "unknown"

        error_msg = failure_result.error.lower()

        # Transient errors (network, timeouts, rate limits)
        transient_patterns = [
            "timeout",
            "connection",
            "network",
            "rate limit",
            "temporary",
            "unavailable",
        ]
        if any(pattern in error_msg for pattern in transient_patterns):
            return "transient"

        # State corruption errors
        corruption_patterns = [
            "corrupt",
            "invalid state",
            "inconsistent",
            "merge conflict",
            "dirty worktree",
        ]
        if any(pattern in error_msg for pattern in corruption_patterns):
            return "corrupted_state"

        # Logic errors (code bugs, assertion failures)
        logic_patterns = [
            "assertion",
            "type error",
            "attribute error",
            "key error",
            "index error",
        ]
        if any(pattern in error_msg for pattern in logic_patterns):
            return "logic_error"

        return "unknown"

    # ==================== Cleanup ====================

    async def cleanup_old_checkpoints(
        self,
        session_id: str,
        keep_count: int = 10
    ) -> int:
        """
        Remove old checkpoints, keeping only the most recent.

        Args:
            session_id: Session identifier
            keep_count: Number of checkpoints to keep

        Returns:
            Number of checkpoints removed
        """
        checkpoints = await self.get_session_checkpoints(session_id)

        if len(checkpoints) <= keep_count:
            return 0

        # Remove oldest checkpoints
        to_remove = checkpoints[keep_count:]
        count = 0

        for checkpoint in to_remove:
            checkpoint_file = self._get_checkpoint_file_path(
                session_id,
                checkpoint.checkpoint_id
            )
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                count += 1

        return count

    async def remove_session_checkpoints(self, session_id: str) -> int:
        """
        Remove all checkpoints for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of checkpoints removed
        """
        checkpoint_dir = self._get_checkpoint_dir(session_id)
        count = 0

        for checkpoint_file in checkpoint_dir.glob("*.json"):
            checkpoint_file.unlink()
            count += 1

        # Remove directory if empty
        if checkpoint_dir.exists() and not any(checkpoint_dir.iterdir()):
            checkpoint_dir.rmdir()

        return count

    # ==================== Statistics ====================

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get checkpoint usage statistics.

        Returns:
            Statistics dictionary
        """
        total_sessions = 0
        total_checkpoints = 0
        by_session = {}

        for session_dir in self.checkpoint_dir.iterdir():
            if session_dir.is_dir():
                session_id = session_dir.name
                checkpoints = await self.get_session_checkpoints(session_id)
                total_sessions += 1
                total_checkpoints += len(checkpoints)
                by_session[session_id] = len(checkpoints)

        return {
            "total_sessions": total_sessions,
            "total_checkpoints": total_checkpoints,
            "average_per_session": (
                total_checkpoints / total_sessions if total_sessions > 0 else 0
            ),
            "by_session": by_session
        }
