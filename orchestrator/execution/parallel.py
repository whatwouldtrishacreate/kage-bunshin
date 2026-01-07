#!/usr/bin/env python3
"""
Parallel Executor for CLI Council
==================================

Coordinates parallel execution of multiple CLI tools on the same task.

Key features:
- Async parallel execution using asyncio.gather
- Retry logic with exponential backoff
- Result aggregation across CLIs
- Error handling and recovery
- Resource cleanup (worktrees, locks, contexts)

Execution flow:
1. Create session worktrees for each CLI
2. Acquire necessary locks
3. Update contexts
4. Execute CLIs in parallel
5. Aggregate results
6. Cleanup resources
"""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..state.context import ContextManager
from ..state.locks import LockManager
from ..state.worktree import SessionWorktree, WorktreeManager
from .adapters import (CLIAdapter, ExecutionResult, ExecutionStatus,
                       TaskAssignment)


@dataclass
class ParallelTaskConfig:
    """Configuration for parallel task execution."""

    task_id: str
    description: str
    assignments: List[TaskAssignment]  # One per CLI
    max_retries: int = 3
    retry_delay: float = 5.0  # Base delay in seconds
    use_exponential_backoff: bool = True


@dataclass
class AggregatedResult:
    """Aggregated results from parallel CLI execution."""

    task_id: str
    cli_results: List[ExecutionResult]
    success_count: int
    failure_count: int
    total_cost: float
    total_duration: float
    best_result: Optional[ExecutionResult] = None
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "cli_results": [r.to_dict() for r in self.cli_results],
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_cost": self.total_cost,
            "total_duration": self.total_duration,
            "best_result": self.best_result.to_dict() if self.best_result else None,
            "timestamp": self.timestamp,
        }


class ParallelExecutor:
    """
    Executes tasks in parallel across multiple CLI tools.

    Manages worktrees, locks, contexts, and coordinates execution
    with retry logic and result aggregation.
    """

    def __init__(
        self,
        project_dir: Path,
        adapters: Dict[str, CLIAdapter],
        base_branch: str = "main",
    ):
        """
        Initialize parallel executor.

        Args:
            project_dir: Project root directory
            adapters: Map of CLI name → adapter instance
            base_branch: Base git branch for worktrees
        """
        self.project_dir = project_dir
        self.adapters = adapters
        self.base_branch = base_branch

        # State managers
        self.worktree_manager = WorktreeManager(project_dir, base_branch)
        self.lock_manager = LockManager(project_dir)
        self.context_manager = ContextManager(project_dir)

        # Setup
        self.worktree_manager.setup()

        # Execution stats
        self._total_executions = 0
        self._total_cost = 0.0

    async def execute_parallel(self, config: ParallelTaskConfig) -> AggregatedResult:
        """
        Execute task in parallel across multiple CLIs.

        Args:
            config: Task configuration with assignments

        Returns:
            AggregatedResult with outcomes from all CLIs
        """
        start_time = datetime.now()

        # Create session worktrees for each CLI
        sessions = await self._create_sessions(config)

        try:
            # Execute in parallel with retries
            results = await asyncio.gather(
                *[
                    self._execute_with_retry(
                        session=session,
                        task=task,
                        adapter=self.adapters[task.cli_name],
                        max_retries=config.max_retries,
                        retry_delay=config.retry_delay,
                        use_backoff=config.use_exponential_backoff,
                    )
                    for session, task in zip(sessions, config.assignments)
                ],
                return_exceptions=True,
            )

            # Handle any exceptions that occurred
            results = [
                (
                    self._handle_exception(config.assignments[i], r)
                    if isinstance(r, Exception)
                    else r
                )
                for i, r in enumerate(results)
            ]

            # Aggregate results
            aggregated = self._aggregate_results(
                task_id=config.task_id, results=results, start_time=start_time
            )

            # Update stats
            self._total_executions += 1
            self._total_cost += aggregated.total_cost

            return aggregated

        finally:
            # Cleanup: Release locks and mark contexts as done
            await self._cleanup_sessions(sessions)

    async def _create_sessions(
        self, config: ParallelTaskConfig
    ) -> List[SessionWorktree]:
        """
        Create isolated worktrees for each CLI.

        Args:
            config: Task configuration

        Returns:
            List of SessionWorktree objects
        """
        sessions = []

        for task in config.assignments:
            session_id = f"{config.task_id}-{task.cli_name}"

            # Create worktree
            session = await self.worktree_manager.create_session_worktree(
                session_id=session_id, cli_name=task.cli_name, task_id=config.task_id
            )

            # Initialize context
            await self.context_manager.update_context(
                session=session,
                status="working",
                message=f"Starting task: {config.description}",
            )

            sessions.append(session)

        return sessions

    async def _execute_with_retry(
        self,
        session: SessionWorktree,
        task: TaskAssignment,
        adapter: CLIAdapter,
        max_retries: int,
        retry_delay: float,
        use_backoff: bool,
    ) -> ExecutionResult:
        """
        Execute task with retry logic.

        Args:
            session: Session worktree
            task: Task to execute
            adapter: CLI adapter
            max_retries: Maximum retry attempts
            retry_delay: Base delay between retries
            use_backoff: Use exponential backoff

        Returns:
            ExecutionResult (possibly after retries)
        """
        retries = 0

        while retries <= max_retries:
            try:
                # Update context
                await self.context_manager.update_context(
                    session=session,
                    status="working",
                    message=f"Attempt {retries + 1}/{max_retries + 1}",
                )

                # Execute
                result = await adapter.execute(task, session.worktree_path)

                # Check if successful
                if result.status == ExecutionStatus.SUCCESS:
                    await self.context_manager.mark_done(
                        session, f"Completed successfully"
                    )
                    result.retries = retries
                    return result

                # Check if should retry
                if retries < max_retries and self._should_retry(result):
                    retries += 1

                    # Calculate delay with exponential backoff
                    if use_backoff:
                        delay = retry_delay * (2 ** (retries - 1))
                    else:
                        delay = retry_delay

                    # Update context
                    await self.context_manager.update_context(
                        session=session,
                        status="blocked",
                        message=f"Retrying in {delay}s after {result.status.value}",
                    )

                    # Wait before retry
                    await asyncio.sleep(delay)
                else:
                    # Max retries reached or non-retryable failure
                    result.retries = retries
                    return result

            except Exception as e:
                # Unexpected error during execution
                if retries < max_retries:
                    retries += 1
                    delay = (
                        retry_delay * (2 ** (retries - 1))
                        if use_backoff
                        else retry_delay
                    )
                    await asyncio.sleep(delay)
                else:
                    # Return failure result
                    return ExecutionResult(
                        task_id=task.task_id,
                        cli_name=task.cli_name,
                        status=ExecutionStatus.FAILURE,
                        output="",
                        error=str(e),
                        retries=retries,
                    )

        # Should never reach here, but just in case
        return ExecutionResult(
            task_id=task.task_id,
            cli_name=task.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error="Max retries exceeded",
            retries=retries,
        )

    def _should_retry(self, result: ExecutionResult) -> bool:
        """
        Determine if execution should be retried.

        Args:
            result: Execution result

        Returns:
            True if should retry
        """
        # Retry on timeout or transient failures
        if result.status == ExecutionStatus.TIMEOUT:
            return True

        # Don't retry on success or cancellation
        if result.status in [ExecutionStatus.SUCCESS, ExecutionStatus.CANCELLED]:
            return False

        # Retry on failure if error looks transient
        if result.error:
            transient_errors = [
                "connection",
                "network",
                "timeout",
                "rate limit",
                "429",
                "503",
            ]
            error_lower = result.error.lower()
            if any(e in error_lower for e in transient_errors):
                return True

        # Default: don't retry
        return False

    def _handle_exception(
        self, task: TaskAssignment, exception: Exception
    ) -> ExecutionResult:
        """
        Handle exception that occurred during execution.

        Args:
            task: Task that was being executed
            exception: Exception that occurred

        Returns:
            ExecutionResult representing the failure
        """
        return ExecutionResult(
            task_id=task.task_id,
            cli_name=task.cli_name,
            status=ExecutionStatus.FAILURE,
            output="",
            error=f"Exception: {str(exception)}",
            retries=0,
        )

    def _aggregate_results(
        self, task_id: str, results: List[ExecutionResult], start_time: datetime
    ) -> AggregatedResult:
        """
        Aggregate results from parallel execution.

        Args:
            task_id: Task identifier
            results: Results from all CLIs
            start_time: Execution start time

        Returns:
            AggregatedResult summary
        """
        success_count = sum(1 for r in results if r.status == ExecutionStatus.SUCCESS)
        failure_count = len(results) - success_count

        total_cost = sum(r.cost for r in results)
        total_duration = (datetime.now() - start_time).total_seconds()

        # Select best result (prefer success, then lowest cost)
        successful = [r for r in results if r.status == ExecutionStatus.SUCCESS]
        if successful:
            best = min(successful, key=lambda r: r.cost)
        else:
            # All failed, pick one with most output
            best = max(results, key=lambda r: len(r.output)) if results else None

        return AggregatedResult(
            task_id=task_id,
            cli_results=results,
            success_count=success_count,
            failure_count=failure_count,
            total_cost=total_cost,
            total_duration=total_duration,
            best_result=best,
        )

    async def _cleanup_sessions(self, sessions: List[SessionWorktree]) -> None:
        """
        Cleanup session resources.

        Args:
            sessions: Sessions to cleanup
        """
        for session in sessions:
            try:
                # Release all locks
                await self.lock_manager.release_all_session_locks(session)

                # Remove context
                await self.context_manager.remove_context(session.session_id)

                # Note: Don't remove worktree yet - may need for merge

            except Exception as e:
                print(f"Warning: Error during cleanup for {session.session_id}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get executor statistics.

        Returns:
            Dictionary with execution stats
        """
        return {
            "total_executions": self._total_executions,
            "total_cost": self._total_cost,
            "average_cost": (
                self._total_cost / self._total_executions
                if self._total_executions > 0
                else 0.0
            ),
            "adapter_stats": {
                name: adapter.get_stats() for name, adapter in self.adapters.items()
            },
        }
