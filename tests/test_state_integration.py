#!/usr/bin/env python3
"""
Integration Tests for CLI Council State Management (Week 1)
============================================================

Tests the integration of:
- WorktreeManager (session-based worktrees)
- LockManager (3-layer locking)
- ContextManager (Layer 1 context sharing)

Test scenarios:
1. Parallel session creation (multiple CLIs on same task)
2. File locking and conflict resolution
3. Context awareness across sessions
4. Cleanup and resource management
"""

import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.state.worktree import WorktreeManager, SessionWorktree
from orchestrator.state.locks import LockManager, LockError
from orchestrator.state.context import ContextManager, ContextFile


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()

        # Initialize git repo
        import subprocess
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


class TestWorktreeManager:
    """Test WorktreeManager session-based worktrees."""

    @pytest.mark.asyncio
    async def test_create_session_worktree(self, temp_git_repo):
        """Test creating a session worktree."""
        manager = WorktreeManager(temp_git_repo)
        manager.setup()

        session = await manager.create_session_worktree(
            session_id="test-session-001",
            cli_name="auto-claude",
            task_id="001-test-task",
        )

        assert session.session_id == "test-session-001"
        assert session.cli_name == "auto-claude"
        assert session.task_id == "001-test-task"
        assert session.worktree_path.exists()
        assert session.lock_fd is not None

        # Cleanup
        await manager.remove_session_worktree(session)

    @pytest.mark.asyncio
    async def test_parallel_sessions_same_task(self, temp_git_repo):
        """Test multiple CLIs working on same task in parallel."""
        manager = WorktreeManager(temp_git_repo)
        manager.setup()

        # Create 3 sessions for same task (different CLIs)
        sessions = []
        for cli_name in ["auto-claude", "ollama", "claude-code"]:
            session = await manager.create_session_worktree(
                session_id=f"session-{cli_name}",
                cli_name=cli_name,
                task_id="001-test-task",
            )
            sessions.append(session)

        # Verify all have isolated worktrees
        assert len(sessions) == 3
        paths = [s.worktree_path for s in sessions]
        assert len(set(paths)) == 3  # All unique

        # Verify ownership metadata
        ownership = manager._load_ownership()
        assert len(ownership) == 3
        assert all(s.session_id in ownership for s in sessions)

        # Cleanup
        for session in sessions:
            await manager.remove_session_worktree(session)

    @pytest.mark.asyncio
    async def test_commit_in_worktree(self, temp_git_repo):
        """Test committing changes in a session's worktree."""
        manager = WorktreeManager(temp_git_repo)
        manager.setup()

        session = await manager.create_session_worktree(
            session_id="test-commit",
            cli_name="auto-claude",
            task_id="001-test",
        )

        # Make a change
        test_file = session.worktree_path / "test.txt"
        test_file.write_text("Test content\n")

        # Commit
        success = await manager.commit_in_worktree(session, "Add test file")
        assert success is True

        # Verify stats
        stats = await manager.get_session_stats(session)
        assert stats["commit_count"] == 1
        assert stats["files_changed"] >= 1

        # Cleanup
        await manager.remove_session_worktree(session)


class TestLockManager:
    """Test LockManager 3-layer locking."""

    @pytest.mark.asyncio
    async def test_file_lock_acquisition(self, temp_git_repo):
        """Test acquiring and releasing file locks."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        lock_manager = LockManager(temp_git_repo)

        session = await wt_manager.create_session_worktree(
            session_id="lock-test",
            cli_name="auto-claude",
            task_id="001-test",
        )

        file_path = Path("src/api.py")

        # Acquire lock
        acquired = await lock_manager.acquire_file_lock(session, file_path)
        assert acquired is True

        # Verify ownership
        owner = lock_manager.get_file_owner(file_path)
        assert owner is not None
        assert owner.session_id == session.session_id

        # Release lock
        released = await lock_manager.release_file_lock(session, file_path)
        assert released is True

        # Verify released
        owner = lock_manager.get_file_owner(file_path)
        assert owner is None

        # Cleanup
        await wt_manager.remove_session_worktree(session)

    @pytest.mark.asyncio
    async def test_lock_conflict_detection(self, temp_git_repo):
        """Test that second session cannot acquire locked file."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        lock_manager = LockManager(temp_git_repo)

        # Create two sessions
        session1 = await wt_manager.create_session_worktree(
            session_id="session1",
            cli_name="auto-claude",
            task_id="001-test",
        )
        session2 = await wt_manager.create_session_worktree(
            session_id="session2",
            cli_name="ollama",
            task_id="001-test",
        )

        file_path = Path("src/api.py")

        # Session1 acquires lock
        acquired1 = await lock_manager.acquire_file_lock(session1, file_path, timeout=1.0)
        assert acquired1 is True

        # Session2 tries to acquire (should timeout)
        acquired2 = await lock_manager.acquire_file_lock(session2, file_path, timeout=1.0)
        assert acquired2 is False

        # Release session1's lock
        await lock_manager.release_file_lock(session1, file_path)

        # Now session2 can acquire
        acquired2 = await lock_manager.acquire_file_lock(session2, file_path, timeout=1.0)
        assert acquired2 is True

        # Cleanup
        await lock_manager.release_file_lock(session2, file_path)
        await wt_manager.remove_session_worktree(session1)
        await wt_manager.remove_session_worktree(session2)

    @pytest.mark.asyncio
    async def test_merge_lock_coordination(self, temp_git_repo):
        """Test merge lock prevents simultaneous merges."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        lock_manager = LockManager(temp_git_repo)

        session1 = await wt_manager.create_session_worktree(
            session_id="merge1",
            cli_name="auto-claude",
            task_id="001-test",
        )
        session2 = await wt_manager.create_session_worktree(
            session_id="merge2",
            cli_name="ollama",
            task_id="001-test",
        )

        # Session1 acquires merge lock
        acquired1 = await lock_manager.acquire_merge_lock(session1, timeout=1.0)
        assert acquired1 is True
        assert lock_manager.is_merge_in_progress() is True

        # Session2 tries to acquire (should timeout)
        acquired2 = await lock_manager.acquire_merge_lock(session2, timeout=1.0)
        assert acquired2 is False

        # Release session1's merge lock
        lock_manager.release_merge_lock(session1)
        assert lock_manager.is_merge_in_progress() is False

        # Now session2 can acquire
        acquired2 = await lock_manager.acquire_merge_lock(session2, timeout=1.0)
        assert acquired2 is True

        # Cleanup
        lock_manager.release_merge_lock(session2)
        await wt_manager.remove_session_worktree(session1)
        await wt_manager.remove_session_worktree(session2)


class TestContextManager:
    """Test ContextManager Layer 1 context sharing."""

    @pytest.mark.asyncio
    async def test_update_and_read_context(self, temp_git_repo):
        """Test updating and reading session context."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        ctx_manager = ContextManager(temp_git_repo)

        session = await wt_manager.create_session_worktree(
            session_id="ctx-test",
            cli_name="auto-claude",
            task_id="001-test",
        )

        # Update context
        await ctx_manager.update_context(
            session=session,
            current_file="src/api.py",
            status="working",
            message="Implementing auth endpoint",
        )

        # Read context
        context = await ctx_manager.get_context(session.session_id)
        assert context is not None
        assert context.session_id == session.session_id
        assert context.current_file == "src/api.py"
        assert context.status == "working"

        # Cleanup
        await ctx_manager.remove_context(session.session_id)
        await wt_manager.remove_session_worktree(session)

    @pytest.mark.asyncio
    async def test_conflict_detection(self, temp_git_repo):
        """Test detecting multiple sessions working on same file."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        ctx_manager = ContextManager(temp_git_repo)

        # Create two sessions working on same file
        session1 = await wt_manager.create_session_worktree(
            session_id="conflict1",
            cli_name="auto-claude",
            task_id="001-test",
        )
        session2 = await wt_manager.create_session_worktree(
            session_id="conflict2",
            cli_name="ollama",
            task_id="001-test",
        )

        await ctx_manager.update_context(
            session=session1,
            current_file="src/api.py",
            status="working",
        )
        await ctx_manager.update_context(
            session=session2,
            current_file="src/api.py",
            status="working",
        )

        # Detect conflict
        conflicts = await ctx_manager.find_file_conflicts("src/api.py")
        assert len(conflicts) == 2
        assert any(c.session_id == "conflict1" for c in conflicts)
        assert any(c.session_id == "conflict2" for c in conflicts)

        # Cleanup
        await ctx_manager.remove_context(session1.session_id)
        await ctx_manager.remove_context(session2.session_id)
        await wt_manager.remove_session_worktree(session1)
        await wt_manager.remove_session_worktree(session2)

    @pytest.mark.asyncio
    async def test_task_summary(self, temp_git_repo):
        """Test getting task summary across multiple sessions."""
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        ctx_manager = ContextManager(temp_git_repo)

        # Create 3 sessions for same task
        sessions = []
        for i, cli_name in enumerate(["auto-claude", "ollama", "claude-code"]):
            session = await wt_manager.create_session_worktree(
                session_id=f"summary-{i}",
                cli_name=cli_name,
                task_id="001-test",
            )
            sessions.append(session)

            status = "working" if i < 2 else "done"
            await ctx_manager.update_context(
                session=session,
                status=status,
            )

        # Get task summary
        summary = await ctx_manager.get_task_summary("001-test")
        assert summary["total_sessions"] == 3
        assert summary["by_status"]["working"] == 2
        assert summary["by_status"]["done"] == 1
        assert len(summary["by_cli"]) == 3

        # Cleanup
        for session in sessions:
            await ctx_manager.remove_context(session.session_id)
            await wt_manager.remove_session_worktree(session)


class TestIntegration:
    """Test full integration of worktree + locks + context."""

    @pytest.mark.asyncio
    async def test_parallel_execution_workflow(self, temp_git_repo):
        """
        Test complete workflow: parallel sessions with locking and context.

        Scenario:
        1. Two CLIs start working on same task
        2. They lock different files
        3. Context shows their progress
        4. Clean completion and cleanup
        """
        wt_manager = WorktreeManager(temp_git_repo)
        wt_manager.setup()
        lock_manager = LockManager(temp_git_repo)
        ctx_manager = ContextManager(temp_git_repo)

        # Create two sessions
        auto_claude = await wt_manager.create_session_worktree(
            session_id="auto-claude-001",
            cli_name="auto-claude",
            task_id="001-auth",
        )
        ollama = await wt_manager.create_session_worktree(
            session_id="ollama-001",
            cli_name="ollama",
            task_id="001-auth",
        )

        # Auto-Claude works on api.py
        await ctx_manager.update_context(
            session=auto_claude,
            current_file="src/api.py",
            status="working",
            message="Implementing auth endpoints",
        )
        await lock_manager.acquire_file_lock(auto_claude, Path("src/api.py"))

        # Ollama works on utils.py
        await ctx_manager.update_context(
            session=ollama,
            current_file="src/utils.py",
            status="working",
            message="Adding auth utilities",
        )
        await lock_manager.acquire_file_lock(ollama, Path("src/utils.py"))

        # Verify parallel execution
        contexts = await ctx_manager.get_all_contexts()
        assert len(contexts) == 2
        assert all(c.status == "working" for c in contexts)

        # Verify no conflicts (different files)
        api_conflicts = await ctx_manager.find_file_conflicts("src/api.py")
        assert len(api_conflicts) == 1
        assert api_conflicts[0].cli_name == "auto-claude"

        # Complete sessions
        await ctx_manager.mark_done(auto_claude, "Auth endpoints complete")
        await ctx_manager.mark_done(ollama, "Auth utilities complete")

        # Release locks
        await lock_manager.release_all_session_locks(auto_claude)
        await lock_manager.release_all_session_locks(ollama)

        # Verify completion
        done_contexts = await ctx_manager.get_contexts_by_status("done")
        assert len(done_contexts) == 2

        # Cleanup
        await wt_manager.remove_session_worktree(auto_claude)
        await wt_manager.remove_session_worktree(ollama)
        await ctx_manager.remove_context(auto_claude.session_id)
        await ctx_manager.remove_context(ollama.session_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
