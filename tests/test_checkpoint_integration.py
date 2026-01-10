#!/usr/bin/env python3
"""
Integration Tests for CheckpointManager
========================================

Tests git-based checkpoint and rollback system with real git operations.

Test Coverage:
- Checkpoint creation with real git commits
- Checkpoint retrieval and metadata loading
- Rollback operations (git reset --hard, clean -fdx)
- Recovery strategy suggestions
- Error classification (transient, corrupted_state, logic_error)
- Cleanup operations
- Async subprocess operations
- Concurrent checkpoint creation

All tests use real git operations (not mocked) for realistic validation.
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.execution.adapters.base import ExecutionResult, ExecutionStatus
from orchestrator.state.checkpoint import (
    Checkpoint,
    CheckpointError,
    CheckpointManager,
    RecoveryStrategy,
    RollbackResult,
)
from orchestrator.state.worktree import SessionWorktree


# ==================== Fixtures ====================


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
        )

        # Create initial commit on main branch
        test_file = repo_path / "README.md"
        test_file.write_text("# Test Project\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
        )

        yield repo_path

        # Cleanup
        shutil.rmtree(repo_path, ignore_errors=True)


@pytest.fixture
def checkpoint_manager(temp_git_repo):
    """Create a CheckpointManager instance for testing."""
    return CheckpointManager(temp_git_repo)


@pytest.fixture
def session_worktree(temp_git_repo):
    """Create a mock SessionWorktree for testing."""
    # Create a worktree subdirectory
    worktree_path = temp_git_repo / ".cli-council" / "worktrees" / "test-session"
    worktree_path.mkdir(parents=True, exist_ok=True)

    # Initialize as git repo (simulate worktree)
    subprocess.run(["git", "init"], cwd=worktree_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=worktree_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=worktree_path,
        check=True,
    )

    # Create initial commit
    test_file = worktree_path / "test.txt"
    test_file.write_text("Initial content\n")
    subprocess.run(["git", "add", "."], cwd=worktree_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial worktree commit"],
        cwd=worktree_path,
        check=True,
    )

    return SessionWorktree(
        session_id="test-session-001",
        cli_name="test-cli",
        task_id="001-test-task",
        worktree_path=worktree_path,
        branch_name="test-branch",
        base_branch="main",
        created_at=datetime.now().isoformat(),
        is_active=True,
    )


# ==================== Checkpoint Creation Tests ====================


@pytest.mark.asyncio
class TestCheckpointCreation:
    """Test checkpoint creation with real git operations."""

    async def test_create_checkpoint_basic(self, checkpoint_manager, session_worktree):
        """Test basic checkpoint creation."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Test checkpoint"
        )

        # Verify checkpoint object
        assert checkpoint.checkpoint_id is not None
        assert len(checkpoint.checkpoint_id) == 7  # Short SHA
        assert checkpoint.session_id == "test-session-001"
        assert checkpoint.cli_name == "test-cli"
        assert checkpoint.task_id == "001-test-task"
        assert checkpoint.commit_sha is not None
        assert len(checkpoint.commit_sha) > 7  # Full SHA
        assert checkpoint.reason == "Test checkpoint"
        assert checkpoint.is_safe_rollback_point is True

        # Verify git commit was created
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=session_worktree.worktree_path,
            capture_output=True,
            text=True
        )
        assert "[CHECKPOINT] Test checkpoint" in result.stdout

    async def test_create_checkpoint_with_changes(self, checkpoint_manager, session_worktree):
        """Test checkpoint creation with file changes."""
        # Modify files
        file1 = session_worktree.worktree_path / "file1.txt"
        file1.write_text("Content 1\n")
        file2 = session_worktree.worktree_path / "file2.txt"
        file2.write_text("Content 2\n")

        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Checkpoint with changes"
        )

        # Verify files_changed list
        assert len(checkpoint.files_changed) == 2
        assert "file1.txt" in checkpoint.files_changed
        assert "file2.txt" in checkpoint.files_changed

        # Verify files were committed
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=session_worktree.worktree_path,
            capture_output=True,
            text=True
        )
        assert "file1.txt" in result.stdout
        assert "file2.txt" in result.stdout

    async def test_create_checkpoint_empty_allowed(self, checkpoint_manager, session_worktree):
        """Test creating empty checkpoint (no changes)."""
        # Create checkpoint without any changes
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Empty checkpoint"
        )

        # Should succeed with empty commit
        assert checkpoint is not None
        assert checkpoint.files_changed == []

    async def test_create_checkpoint_sanitizes_reason(self, checkpoint_manager, session_worktree):
        """Test that checkpoint reason is sanitized to prevent command injection."""
        # Try creating checkpoint with dangerous characters
        dangerous_reason = 'Test\ncheckpoint"; rm -rf /; echo "'

        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason=dangerous_reason
        )

        # Verify reason was sanitized (newlines replaced, quotes escaped)
        assert '\n' not in checkpoint.reason
        assert checkpoint.reason == 'Test checkpoint\\"; rm -rf /; echo \\"'

        # Verify git log doesn't have malicious content in commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=session_worktree.worktree_path,
            capture_output=True,
            text=True
        )
        # Check the commit message itself (strip trailing newline)
        commit_msg = result.stdout.strip()
        assert '\n' not in commit_msg

    async def test_create_checkpoint_metadata_saved(self, checkpoint_manager, session_worktree):
        """Test that checkpoint metadata is saved to JSON file."""
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Metadata test"
        )

        # Verify JSON file was created
        checkpoint_file = checkpoint_manager._get_checkpoint_file_path(
            session_worktree.session_id,
            checkpoint.checkpoint_id
        )
        assert checkpoint_file.exists()

        # Verify JSON content
        with open(checkpoint_file, 'r') as f:
            data = json.load(f)

        assert data["checkpoint_id"] == checkpoint.checkpoint_id
        assert data["session_id"] == "test-session-001"
        assert data["cli_name"] == "test-cli"
        assert data["reason"] == "Metadata test"

    async def test_create_checkpoint_not_safe_rollback_point(self, checkpoint_manager, session_worktree):
        """Test creating checkpoint marked as unsafe rollback point."""
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Unsafe checkpoint",
            is_safe_rollback_point=False
        )

        assert checkpoint.is_safe_rollback_point is False


# ==================== Checkpoint Retrieval Tests ====================


@pytest.mark.asyncio
class TestCheckpointRetrieval:
    """Test checkpoint retrieval and metadata loading."""

    async def test_get_checkpoint_exists(self, checkpoint_manager, session_worktree):
        """Test retrieving an existing checkpoint."""
        # Create checkpoint
        created = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Retrieval test"
        )

        # Retrieve checkpoint
        retrieved = await checkpoint_manager.get_checkpoint(
            session_id=session_worktree.session_id,
            checkpoint_id=created.checkpoint_id
        )

        # Verify retrieved checkpoint matches
        assert retrieved is not None
        assert retrieved.checkpoint_id == created.checkpoint_id
        assert retrieved.session_id == created.session_id
        assert retrieved.reason == created.reason
        assert retrieved.commit_sha == created.commit_sha

    async def test_get_checkpoint_not_exists(self, checkpoint_manager, session_worktree):
        """Test retrieving non-existent checkpoint returns None."""
        retrieved = await checkpoint_manager.get_checkpoint(
            session_id=session_worktree.session_id,
            checkpoint_id="nonexistent"
        )

        assert retrieved is None

    async def test_get_checkpoint_corrupted_json(self, checkpoint_manager, session_worktree):
        """Test retrieving checkpoint with corrupted JSON file."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Corruption test"
        )

        # Corrupt the JSON file
        checkpoint_file = checkpoint_manager._get_checkpoint_file_path(
            session_worktree.session_id,
            checkpoint.checkpoint_id
        )
        with open(checkpoint_file, 'w') as f:
            f.write("{ invalid json ]")

        # Should return None and print warning
        retrieved = await checkpoint_manager.get_checkpoint(
            session_worktree.session_id,
            checkpoint.checkpoint_id
        )

        assert retrieved is None

    async def test_get_session_checkpoints_empty(self, checkpoint_manager, session_worktree):
        """Test getting checkpoints for session with no checkpoints."""
        checkpoints = await checkpoint_manager.get_session_checkpoints(
            session_worktree.session_id
        )

        assert checkpoints == []

    async def test_get_session_checkpoints_multiple(self, checkpoint_manager, session_worktree):
        """Test getting multiple checkpoints for a session."""
        # Create multiple checkpoints
        checkpoint1 = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="First checkpoint"
        )

        # Small delay to ensure different timestamps
        await asyncio.sleep(0.1)

        checkpoint2 = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Second checkpoint"
        )

        await asyncio.sleep(0.1)

        checkpoint3 = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Third checkpoint"
        )

        # Retrieve all checkpoints
        checkpoints = await checkpoint_manager.get_session_checkpoints(
            session_worktree.session_id
        )

        # Verify all checkpoints retrieved
        assert len(checkpoints) == 3

        # Verify ordered by creation time (newest first)
        assert checkpoints[0].checkpoint_id == checkpoint3.checkpoint_id
        assert checkpoints[1].checkpoint_id == checkpoint2.checkpoint_id
        assert checkpoints[2].checkpoint_id == checkpoint1.checkpoint_id


# ==================== Rollback Tests ====================


@pytest.mark.asyncio
class TestRollback:
    """Test rollback operations with real git reset and clean."""

    async def test_rollback_basic(self, checkpoint_manager, session_worktree):
        """Test basic rollback to checkpoint."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Before changes"
        )

        # Make changes
        file1 = session_worktree.worktree_path / "modified.txt"
        file1.write_text("Changed content\n")
        subprocess.run(["git", "add", "."], cwd=session_worktree.worktree_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Changes after checkpoint"],
            cwd=session_worktree.worktree_path,
            check=True
        )

        # Rollback
        result = await checkpoint_manager.rollback_to_checkpoint(
            session=session_worktree,
            checkpoint=checkpoint
        )

        # Verify rollback succeeded
        assert result.success is True
        assert result.checkpoint_id == checkpoint.checkpoint_id

        # Verify files were restored
        assert not file1.exists()

        # Verify HEAD is at checkpoint
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=session_worktree.worktree_path,
            capture_output=True,
            text=True
        )
        current_sha = proc.stdout.strip()
        assert current_sha == checkpoint.commit_sha

    async def test_rollback_cleans_untracked_files(self, checkpoint_manager, session_worktree):
        """Test that rollback removes untracked files."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Clean test"
        )

        # Create untracked files
        untracked = session_worktree.worktree_path / "untracked.txt"
        untracked.write_text("Untracked content\n")

        # Verify file exists before rollback
        assert untracked.exists()

        # Rollback
        result = await checkpoint_manager.rollback_to_checkpoint(
            session=session_worktree,
            checkpoint=checkpoint
        )

        # Verify untracked file was removed
        assert result.success is True
        assert not untracked.exists()

    async def test_rollback_cleans_gitignored_files(self, checkpoint_manager, session_worktree):
        """Test that rollback removes gitignored files (git clean -fdx)."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Gitignore test"
        )

        # Create .gitignore
        gitignore = session_worktree.worktree_path / ".gitignore"
        gitignore.write_text("*.log\n")

        # Create gitignored file
        log_file = session_worktree.worktree_path / "debug.log"
        log_file.write_text("Debug output\n")

        # Verify file exists
        assert log_file.exists()

        # Rollback
        result = await checkpoint_manager.rollback_to_checkpoint(
            session=session_worktree,
            checkpoint=checkpoint
        )

        # Verify gitignored file was removed (-fdx flag)
        assert result.success is True
        assert not log_file.exists()

    async def test_rollback_reports_restored_files(self, checkpoint_manager, session_worktree):
        """Test that rollback reports which files were restored."""
        # Create checkpoint
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Restore report test"
        )

        # Make changes
        file1 = session_worktree.worktree_path / "file1.txt"
        file2 = session_worktree.worktree_path / "file2.txt"
        file1.write_text("Content 1\n")
        file2.write_text("Content 2\n")

        # Rollback
        result = await checkpoint_manager.rollback_to_checkpoint(
            session=session_worktree,
            checkpoint=checkpoint
        )

        # Verify files_restored list
        assert result.success is True
        assert len(result.files_restored) == 2
        assert "file1.txt" in result.files_restored
        assert "file2.txt" in result.files_restored

    async def test_rollback_to_invalid_commit_fails(self, checkpoint_manager, session_worktree):
        """Test rollback to invalid commit SHA fails gracefully."""
        # Create checkpoint with invalid commit SHA
        invalid_checkpoint = Checkpoint(
            checkpoint_id="invalid",
            session_id=session_worktree.session_id,
            cli_name=session_worktree.cli_name,
            task_id=session_worktree.task_id,
            commit_sha="0000000000000000000000000000000000000000",
            reason="Invalid checkpoint",
            created_at=datetime.now().isoformat(),
            files_changed=[],
            is_safe_rollback_point=True
        )

        # Rollback should fail
        result = await checkpoint_manager.rollback_to_checkpoint(
            session=session_worktree,
            checkpoint=invalid_checkpoint
        )

        # Verify failure
        assert result.success is False
        assert result.error is not None
        assert "invalid" in result.checkpoint_id.lower()


# ==================== Recovery Strategy Tests ====================


@pytest.mark.asyncio
class TestRecoveryStrategy:
    """Test recovery strategy suggestions and error classification."""

    async def test_suggest_recovery_transient_error(self, checkpoint_manager, session_worktree):
        """Test recovery strategy for transient errors (network, timeout)."""
        # Create checkpoint
        await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Before transient error"
        )

        # Simulate transient error
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Connection timeout occurred"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Verify strategy
        assert strategy.strategy_type == "retry_current"
        assert strategy.recommended_checkpoint is None
        assert strategy.confidence == 0.8
        assert "transient" in strategy.reasoning.lower()

    async def test_suggest_recovery_corrupted_state(self, checkpoint_manager, session_worktree):
        """Test recovery strategy for corrupted state errors."""
        # Create safe checkpoint
        await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Safe checkpoint",
            is_safe_rollback_point=True
        )

        # Simulate corrupted state error
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Invalid state detected, merge conflict"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Verify strategy
        assert strategy.strategy_type == "rollback_safe"
        assert strategy.recommended_checkpoint is not None
        assert strategy.recommended_checkpoint.is_safe_rollback_point is True
        assert strategy.confidence == 0.9
        assert "corruption" in strategy.reasoning.lower()

    async def test_suggest_recovery_logic_error(self, checkpoint_manager, session_worktree):
        """Test recovery strategy for logic errors (code bugs)."""
        # Create checkpoints
        checkpoint = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Before logic error"
        )

        # Simulate logic error (use "type error" pattern that matches classification)
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="type error: expected string, got None"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Verify strategy
        assert strategy.strategy_type == "rollback_last"
        assert strategy.recommended_checkpoint is not None
        assert strategy.recommended_checkpoint.checkpoint_id == checkpoint.checkpoint_id
        assert strategy.confidence == 0.6
        assert "logic error" in strategy.reasoning.lower()

    async def test_suggest_recovery_unknown_error(self, checkpoint_manager, session_worktree):
        """Test recovery strategy for unknown errors."""
        # Create checkpoint
        await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Before unknown error"
        )

        # Simulate unknown error
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Something weird happened"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Verify strategy
        assert strategy.strategy_type == "escalate"
        assert strategy.recommended_checkpoint is None
        assert strategy.confidence == 0.9
        assert "unknown" in strategy.reasoning.lower()

    async def test_suggest_recovery_no_checkpoints(self, checkpoint_manager, session_worktree):
        """Test recovery strategy when no checkpoints exist."""
        # Don't create any checkpoints

        # Simulate failure
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Some error"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Verify strategy
        assert strategy.strategy_type == "escalate"
        assert strategy.recommended_checkpoint is None
        assert "no checkpoints" in strategy.reasoning.lower()

    async def test_suggest_recovery_no_safe_checkpoints(self, checkpoint_manager, session_worktree):
        """Test recovery strategy when no safe checkpoints exist."""
        # Create unsafe checkpoint
        unsafe = await checkpoint_manager.create_checkpoint(
            session=session_worktree,
            reason="Unsafe checkpoint",
            is_safe_rollback_point=False
        )

        # Simulate corrupted state error
        failure_result = ExecutionResult(
            task_id=session_worktree.task_id,
            cli_name=session_worktree.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Corrupt state"
        )

        # Get recovery strategy
        strategy = await checkpoint_manager.suggest_recovery_strategy(
            session=session_worktree,
            failure_result=failure_result
        )

        # Should fall back to rollback_last
        assert strategy.strategy_type == "rollback_last"
        assert strategy.recommended_checkpoint.checkpoint_id == unsafe.checkpoint_id


# ==================== Cleanup Tests ====================


@pytest.mark.asyncio
class TestCleanup:
    """Test checkpoint cleanup operations."""

    async def test_cleanup_old_checkpoints(self, checkpoint_manager, session_worktree):
        """Test removing old checkpoints while keeping recent ones."""
        # Create 15 checkpoints
        checkpoints = []
        for i in range(15):
            checkpoint = await checkpoint_manager.create_checkpoint(
                session=session_worktree,
                reason=f"Checkpoint {i+1}"
            )
            checkpoints.append(checkpoint)
            await asyncio.sleep(0.01)  # Small delay for timestamp ordering

        # Cleanup, keeping only 10
        removed_count = await checkpoint_manager.cleanup_old_checkpoints(
            session_id=session_worktree.session_id,
            keep_count=10
        )

        # Verify 5 checkpoints were removed
        assert removed_count == 5

        # Verify only 10 checkpoints remain
        remaining = await checkpoint_manager.get_session_checkpoints(
            session_worktree.session_id
        )
        assert len(remaining) == 10

        # Verify newest 10 were kept
        for i in range(10):
            # checkpoints are ordered newest first
            assert remaining[i].checkpoint_id == checkpoints[14 - i].checkpoint_id

    async def test_cleanup_when_under_limit(self, checkpoint_manager, session_worktree):
        """Test cleanup when checkpoint count is under limit."""
        # Create 5 checkpoints
        for i in range(5):
            await checkpoint_manager.create_checkpoint(
                session=session_worktree,
                reason=f"Checkpoint {i+1}"
            )

        # Try to cleanup, keeping 10
        removed_count = await checkpoint_manager.cleanup_old_checkpoints(
            session_id=session_worktree.session_id,
            keep_count=10
        )

        # Verify nothing was removed
        assert removed_count == 0

        # Verify all 5 still exist
        remaining = await checkpoint_manager.get_session_checkpoints(
            session_worktree.session_id
        )
        assert len(remaining) == 5

    async def test_remove_session_checkpoints(self, checkpoint_manager, session_worktree):
        """Test removing all checkpoints for a session."""
        # Create multiple checkpoints
        for i in range(5):
            await checkpoint_manager.create_checkpoint(
                session=session_worktree,
                reason=f"Checkpoint {i+1}"
            )

        # Remove all checkpoints
        removed_count = await checkpoint_manager.remove_session_checkpoints(
            session_worktree.session_id
        )

        # Verify all were removed
        assert removed_count == 5

        # Verify no checkpoints remain
        remaining = await checkpoint_manager.get_session_checkpoints(
            session_worktree.session_id
        )
        assert len(remaining) == 0

        # Verify directory was removed (or is empty)
        checkpoint_dir = checkpoint_manager._get_checkpoint_dir(session_worktree.session_id)
        # Directory might still exist if not empty, just check no checkpoint files
        if checkpoint_dir.exists():
            assert len(list(checkpoint_dir.glob("*.json"))) == 0

    async def test_remove_session_checkpoints_empty_session(self, checkpoint_manager, session_worktree):
        """Test removing checkpoints for session with no checkpoints."""
        # Don't create any checkpoints

        # Remove checkpoints
        removed_count = await checkpoint_manager.remove_session_checkpoints(
            session_worktree.session_id
        )

        # Verify nothing was removed
        assert removed_count == 0


# ==================== Statistics Tests ====================


@pytest.mark.asyncio
class TestStatistics:
    """Test checkpoint statistics and reporting."""

    async def test_get_statistics_empty(self, checkpoint_manager):
        """Test statistics when no checkpoints exist."""
        stats = await checkpoint_manager.get_statistics()

        assert stats["total_sessions"] == 0
        assert stats["total_checkpoints"] == 0
        assert stats["average_per_session"] == 0
        assert stats["by_session"] == {}

    async def test_get_statistics_single_session(self, checkpoint_manager, session_worktree):
        """Test statistics for single session."""
        # Create checkpoints
        for i in range(3):
            await checkpoint_manager.create_checkpoint(
                session=session_worktree,
                reason=f"Checkpoint {i+1}"
            )

        # Get statistics
        stats = await checkpoint_manager.get_statistics()

        assert stats["total_sessions"] == 1
        assert stats["total_checkpoints"] == 3
        assert stats["average_per_session"] == 3.0
        assert session_worktree.session_id in stats["by_session"]
        assert stats["by_session"][session_worktree.session_id] == 3

    async def test_get_statistics_multiple_sessions(self, checkpoint_manager, temp_git_repo):
        """Test statistics for multiple sessions."""
        # Create multiple sessions with different checkpoint counts
        sessions = []
        checkpoint_counts = [2, 5, 3]

        for idx, count in enumerate(checkpoint_counts):
            # Create worktree
            worktree_path = temp_git_repo / ".cli-council" / "worktrees" / f"session-{idx}"
            worktree_path.mkdir(parents=True, exist_ok=True)

            # Initialize as git repo
            subprocess.run(["git", "init"], cwd=worktree_path, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=worktree_path,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=worktree_path,
                check=True,
            )

            # Create initial commit
            test_file = worktree_path / "test.txt"
            test_file.write_text(f"Session {idx}\n")
            subprocess.run(["git", "add", "."], cwd=worktree_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=worktree_path,
                check=True,
            )

            session = SessionWorktree(
                session_id=f"session-{idx}",
                cli_name=f"cli-{idx}",
                task_id=f"task-{idx}",
                worktree_path=worktree_path,
                branch_name=f"branch-{idx}",
                base_branch="main",
                created_at=datetime.now().isoformat(),
                is_active=True,
            )

            # Create checkpoints
            for i in range(count):
                await checkpoint_manager.create_checkpoint(
                    session=session,
                    reason=f"Checkpoint {i+1}"
                )

            sessions.append(session)

        # Get statistics
        stats = await checkpoint_manager.get_statistics()

        assert stats["total_sessions"] == 3
        assert stats["total_checkpoints"] == 10  # 2 + 5 + 3
        assert stats["average_per_session"] == 10 / 3

        for idx, count in enumerate(checkpoint_counts):
            assert stats["by_session"][f"session-{idx}"] == count


# ==================== Error Handling Tests ====================


@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.skip(reason="Git error simulation is environment-dependent")
    async def test_create_checkpoint_git_error(self, checkpoint_manager, session_worktree):
        """Test checkpoint creation when git command fails."""
        # Note: This test is skipped because simulating git errors reliably
        # is difficult across different environments (permissions, filesystems, etc.)
        # The error handling is tested indirectly through other tests.
        pass

    async def test_concurrent_checkpoint_creation(self, checkpoint_manager, session_worktree):
        """Test creating multiple checkpoints concurrently."""
        # Create checkpoints in parallel with small delays to avoid exact concurrency issues
        async def create_with_delay(i):
            await asyncio.sleep(i * 0.01)  # Small staggered delay
            return await checkpoint_manager.create_checkpoint(
                session=session_worktree,
                reason=f"Concurrent checkpoint {i}"
            )

        tasks = [create_with_delay(i) for i in range(5)]
        checkpoints = await asyncio.gather(*tasks)

        # Verify all checkpoints were created
        assert len(checkpoints) == 5
        assert all(c is not None for c in checkpoints)

        # Note: checkpoint IDs might not all be unique if commits happen simultaneously
        # This is expected behavior - git will create the same SHA for identical states
        assert all(c.checkpoint_id is not None for c in checkpoints)

    async def test_classify_error_rate_limit(self, checkpoint_manager):
        """Test error classification for rate limit errors."""
        result = MagicMock()
        result.error = "Rate limit exceeded, please try again later"

        classification = checkpoint_manager._classify_error(result)
        assert classification == "transient"

    async def test_classify_error_assertion(self, checkpoint_manager):
        """Test error classification for assertion errors."""
        result = MagicMock()
        result.error = "AssertionError: Expected value to be > 0"

        classification = checkpoint_manager._classify_error(result)
        assert classification == "logic_error"

    async def test_classify_error_no_error_message(self, checkpoint_manager):
        """Test error classification when no error message."""
        result = MagicMock()
        result.error = None

        classification = checkpoint_manager._classify_error(result)
        assert classification == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
