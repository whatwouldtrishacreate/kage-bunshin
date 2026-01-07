#!/usr/bin/env python3
"""
Integration Tests for CLI Council Execution Engine (Week 2)
============================================================

Tests the integration of:
- CLI Adapters (Auto-Claude, Ollama, Claude Code, Gemini)
- Parallel Executor
- Retry logic
- Result aggregation

Test scenarios:
1. Individual adapter execution
2. Parallel execution across multiple CLIs
3. Retry logic with exponential backoff
4. Result aggregation and best result selection
5. Resource cleanup after execution
"""

import asyncio
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.execution.adapters import (AutoClaudeAdapter,
                                             ClaudeCodeAdapter,
                                             ExecutionResult, ExecutionStatus,
                                             GeminiAdapter, OllamaAdapter,
                                             TaskAssignment)
from orchestrator.execution.parallel import (AggregatedResult,
                                             ParallelExecutor,
                                             ParallelTaskConfig)


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

        # Create initial commit
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


class MockAdapter:
    """Mock adapter for testing without actual CLI execution."""

    def __init__(self, cli_name: str, should_fail: bool = False, delay: float = 0.1):
        self.cli_name = cli_name
        self.should_fail = should_fail
        self.delay = delay
        self._execution_count = 0
        self._total_cost = 0.0

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """Mock execution."""
        await asyncio.sleep(self.delay)
        self._execution_count += 1

        # Create a test file to simulate work
        test_file = worktree_path / "test.txt"
        test_file.write_text(f"Output from {self.cli_name}\n")

        status = (
            ExecutionStatus.FAILURE if self.should_fail else ExecutionStatus.SUCCESS
        )
        cost = 0.0 if self.cli_name == "ollama" else 1.50

        self._total_cost += cost

        return ExecutionResult(
            task_id=task.task_id,
            cli_name=self.cli_name,
            status=status,
            output=f"Output from {self.cli_name}",
            error="Simulated failure" if self.should_fail else None,
            files_modified=["test.txt"] if not self.should_fail else [],
            cost=cost,
            duration=self.delay,
        )

    def get_stats(self):
        return {
            "cli_name": self.cli_name,
            "execution_count": self._execution_count,
            "total_cost": self._total_cost,
        }


class TestAdapters:
    """Test individual CLI adapters."""

    @pytest.mark.asyncio
    async def test_task_assignment_creation(self):
        """Test creating task assignments."""
        task = TaskAssignment(
            task_id="001-test-task",
            cli_name="auto-claude",
            description="Test task",
            context={"complexity": "simple"},
            timeout=300,
        )

        assert task.task_id == "001-test-task"
        assert task.cli_name == "auto-claude"
        assert task.timeout == 300

    @pytest.mark.asyncio
    async def test_execution_result_serialization(self):
        """Test ExecutionResult serialization."""
        result = ExecutionResult(
            task_id="001-test",
            cli_name="ollama",
            status=ExecutionStatus.SUCCESS,
            output="Test output",
            files_modified=["file1.py", "file2.py"],
            cost=0.0,
            duration=5.2,
        )

        result_dict = result.to_dict()

        assert result_dict["task_id"] == "001-test"
        assert result_dict["cli_name"] == "ollama"
        assert result_dict["status"] == "success"
        assert result_dict["cost"] == 0.0


class TestParallelExecutor:
    """Test parallel executor."""

    @pytest.mark.asyncio
    async def test_parallel_execution_success(self, temp_git_repo):
        """Test successful parallel execution across multiple CLIs."""
        # Create mock adapters
        adapters = {
            "auto-claude": MockAdapter("auto-claude", should_fail=False, delay=0.1),
            "ollama": MockAdapter("ollama", should_fail=False, delay=0.1),
            "claude-code": MockAdapter("claude-code", should_fail=False, delay=0.1),
        }

        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        # Create task config
        config = ParallelTaskConfig(
            task_id="001-test",
            description="Test parallel execution",
            assignments=[
                TaskAssignment(
                    task_id="001-test",
                    cli_name="auto-claude",
                    description="Test task",
                    context={},
                ),
                TaskAssignment(
                    task_id="001-test",
                    cli_name="ollama",
                    description="Test task",
                    context={},
                ),
                TaskAssignment(
                    task_id="001-test",
                    cli_name="claude-code",
                    description="Test task",
                    context={},
                ),
            ],
        )

        # Execute
        result = await executor.execute_parallel(config)

        # Verify
        assert result.task_id == "001-test"
        assert len(result.cli_results) == 3
        assert result.success_count == 3
        assert result.failure_count == 0
        assert result.best_result is not None
        assert result.best_result.status == ExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_parallel_execution_with_failures(self, temp_git_repo):
        """Test parallel execution with some CLIs failing."""
        adapters = {
            "auto-claude": MockAdapter("auto-claude", should_fail=False),
            "ollama": MockAdapter("ollama", should_fail=True),
            "claude-code": MockAdapter("claude-code", should_fail=False),
        }

        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        config = ParallelTaskConfig(
            task_id="002-test",
            description="Test with failures",
            assignments=[
                TaskAssignment(
                    task_id="002-test",
                    cli_name=cli,
                    description="Test task",
                    context={},
                )
                for cli in ["auto-claude", "ollama", "claude-code"]
            ],
        )

        result = await executor.execute_parallel(config)

        # Verify
        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.best_result.status == ExecutionStatus.SUCCESS
        assert result.best_result.cli_name in ["auto-claude", "claude-code"]

    @pytest.mark.asyncio
    async def test_retry_logic(self, temp_git_repo):
        """Test retry logic with exponential backoff."""

        # Create adapter that fails first 2 times, then succeeds
        class RetryAdapter(MockAdapter):
            def __init__(self):
                super().__init__("test-adapter")
                self.attempt = 0

            async def execute(self, task, worktree_path):
                self.attempt += 1
                if self.attempt < 3:
                    # Fail first 2 attempts
                    return ExecutionResult(
                        task_id=task.task_id,
                        cli_name=self.cli_name,
                        status=ExecutionStatus.FAILURE,
                        output="",
                        error="Transient network error",
                        cost=0.0,
                        duration=0.1,
                    )
                else:
                    # Succeed on 3rd attempt
                    return await super().execute(task, worktree_path)

        adapters = {"test-adapter": RetryAdapter()}
        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        config = ParallelTaskConfig(
            task_id="003-retry",
            description="Test retry logic",
            assignments=[
                TaskAssignment(
                    task_id="003-retry",
                    cli_name="test-adapter",
                    description="Test task",
                    context={},
                )
            ],
            max_retries=3,
            retry_delay=0.1,
        )

        result = await executor.execute_parallel(config)

        # Verify
        assert result.success_count == 1
        assert (
            result.cli_results[0].retries == 2
        )  # Succeeded on 3rd attempt (2 retries)

    @pytest.mark.asyncio
    async def test_cost_tracking(self, temp_git_repo):
        """Test cost tracking across CLIs."""
        adapters = {
            "auto-claude": MockAdapter("auto-claude"),  # $1.50
            "ollama": MockAdapter("ollama"),  # $0.00
            "claude-code": MockAdapter("claude-code"),  # $1.50
        }

        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        config = ParallelTaskConfig(
            task_id="004-cost",
            description="Test cost tracking",
            assignments=[
                TaskAssignment(
                    task_id="004-cost",
                    cli_name=cli,
                    description="Test task",
                    context={},
                )
                for cli in ["auto-claude", "ollama", "claude-code"]
            ],
        )

        result = await executor.execute_parallel(config)

        # Verify total cost (Auto-Claude $1.50 + Ollama $0 + Claude Code $1.50 = $3.00)
        assert result.total_cost == pytest.approx(3.0, rel=0.01)

        # Verify best result is the cheapest success (Ollama at $0)
        assert result.best_result.cli_name == "ollama"
        assert result.best_result.cost == 0.0

    @pytest.mark.asyncio
    async def test_result_aggregation(self, temp_git_repo):
        """Test result aggregation logic."""
        adapters = {
            "auto-claude": MockAdapter("auto-claude", delay=0.2),
            "ollama": MockAdapter("ollama", delay=0.1),
        }

        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        config = ParallelTaskConfig(
            task_id="005-aggregation",
            description="Test aggregation",
            assignments=[
                TaskAssignment(
                    task_id="005-aggregation",
                    cli_name=cli,
                    description="Test task",
                    context={},
                )
                for cli in ["auto-claude", "ollama"]
            ],
        )

        result = await executor.execute_parallel(config)

        # Verify aggregation
        assert len(result.cli_results) == 2
        assert result.total_duration >= 0.2  # At least as long as longest task

        # Serialize and verify
        result_dict = result.to_dict()
        assert result_dict["task_id"] == "005-aggregation"
        assert len(result_dict["cli_results"]) == 2


class TestResourceCleanup:
    """Test resource cleanup after execution."""

    @pytest.mark.asyncio
    async def test_worktree_cleanup_after_execution(self, temp_git_repo):
        """Test that worktrees are properly managed."""
        adapters = {"test": MockAdapter("test")}
        executor = ParallelExecutor(temp_git_repo, adapters, base_branch="master")

        config = ParallelTaskConfig(
            task_id="006-cleanup",
            description="Test cleanup",
            assignments=[
                TaskAssignment(
                    task_id="006-cleanup",
                    cli_name="test",
                    description="Test task",
                    context={},
                )
            ],
        )

        await executor.execute_parallel(config)

        # Verify contexts were cleaned up
        contexts = await executor.context_manager.get_all_contexts()
        assert len(contexts) == 0  # Should be cleaned up


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
