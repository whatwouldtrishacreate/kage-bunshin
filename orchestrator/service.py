#!/usr/bin/env python3
"""
Orchestrator Service for Kage Bunshin no Jutsu
===============================================

Coordinates task execution using Week 1-2 components:
- ParallelExecutor (Week 2) for CLI coordination
- WorktreeManager, LockManager, ContextManager (Week 1) for state
- DatabaseManager (Week 3) for persistence

This is the main business logic layer between the API and execution engine.
"""

import asyncio
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from uuid import UUID

from api.models import CLIAssignment, TaskDB, TaskStatus
from storage.database import DatabaseManager

from .execution.adapters import (
    AutoClaudeAdapter,
    ClaudeCodeAdapter,
    GeminiAdapter,
    OllamaAdapter,
    TaskAssignment,
)
from .execution.parallel import AggregatedResult, ParallelExecutor, ParallelTaskConfig


class OrchestratorService:
    """
    Main orchestration service.

    Coordinates parallel execution across CLIs and manages task lifecycle:
    1. Task submission → database
    2. Parallel execution → Week 2 engine
    3. Progress events → database (for SSE)
    4. Result storage → database
    """

    def __init__(
        self, project_dir: Path, database: DatabaseManager, base_branch: str = "main"
    ):
        """
        Initialize orchestrator service.

        Args:
            project_dir: Project root directory
            database: Database manager instance
            base_branch: Base git branch
        """
        self.project_dir = project_dir
        self.database = database
        self.base_branch = base_branch

        # Initialize CLI adapters (only those that are available)
        self.adapters = {}

        # Try to initialize each adapter - skip if CLI not found
        adapter_classes = [
            ("auto-claude", AutoClaudeAdapter),
            ("ollama", OllamaAdapter),
            ("claude-code", ClaudeCodeAdapter),
            ("gemini", GeminiAdapter),
        ]

        for cli_name, adapter_class in adapter_classes:
            try:
                self.adapters[cli_name] = adapter_class()
            except Exception as e:
                # Skip adapters that can't initialize (CLI not installed, etc.)
                print(
                    f"Warning: Skipping {cli_name} adapter - {type(e).__name__}: {e}"
                )

        # Initialize parallel executor
        self.executor = ParallelExecutor(
            project_dir=project_dir, adapters=self.adapters, base_branch=base_branch
        )

        # Track running tasks (task_id → asyncio.Task)
        self._running_tasks: Dict[UUID, asyncio.Task] = {}

    async def submit_task(
        self,
        description: str,
        cli_assignments: list[CLIAssignment],
        max_retries: int = 3,
        retry_delay: float = 5.0,
        created_by: Optional[str] = None,
    ) -> TaskDB:
        """
        Submit a new task for parallel execution.

        Creates database record, starts execution in background.

        Args:
            description: Task description
            cli_assignments: CLI assignments list
            max_retries: Max retry attempts
            retry_delay: Base retry delay
            created_by: User/system identifier

        Returns:
            Created TaskDB object
        """
        # Convert API assignments to execution assignments
        task_assignments = [
            TaskAssignment(
                task_id="",  # Will be set after DB creation
                cli_name=a.cli_name,
                description=description,
                context=a.context,
                timeout=a.timeout,
            )
            for a in cli_assignments
        ]

        # Create parallel task config
        config = ParallelTaskConfig(
            task_id="",  # Will be set after DB creation
            description=description,
            assignments=task_assignments,
            max_retries=max_retries,
            retry_delay=retry_delay,
            use_exponential_backoff=True,
        )

        # Serialize config for database
        config_dict = {
            "description": description,
            "assignments": [
                {
                    "cli_name": a.cli_name,
                    "description": a.description,
                    "context": a.context,
                    "timeout": a.timeout,
                }
                for a in task_assignments
            ],
            "max_retries": max_retries,
            "retry_delay": retry_delay,
            "use_exponential_backoff": True,
        }

        # Create task in database
        task = await self.database.create_task(
            description=description, config=config_dict, created_by=created_by
        )

        # Update task IDs in config
        config.task_id = str(task.id)
        for assignment in config.assignments:
            assignment.task_id = str(task.id)

        # Start execution in background
        execution_task = asyncio.create_task(self._execute_task(task.id, config))
        self._running_tasks[task.id] = execution_task

        return task

    async def _execute_task(self, task_id: UUID, config: ParallelTaskConfig):
        """
        Execute task in background.

        Updates database with progress and results.

        Args:
            task_id: Task UUID
            config: Parallel task configuration
        """
        try:
            # Update status to running
            await self.database.update_task_status(
                task_id=task_id, status=TaskStatus.RUNNING, started_at=datetime.now()
            )

            # Log progress event
            await self.database.create_progress_event(
                task_id=task_id,
                cli_name="orchestrator",
                session_id=str(task_id),
                status="working",
                message=f"Starting parallel execution across {len(config.assignments)} CLIs",
            )

            # Execute in parallel using Week 2 executor
            result = await self.executor.execute_parallel(config)

            # === DEVELOPMENT DOCS: Capture execution results ===
            try:
                for cli_result in result.cli_results:
                    # Create execution result record
                    exec_id = await self.database.create_execution_result(
                        task_id=task_id,
                        cli_name=cli_result.cli_name,
                        status=cli_result.status.value,
                        duration=cli_result.duration,
                        cost=cli_result.cost,
                        retries=cli_result.retries,
                        files_modified=cli_result.files_modified,
                        commits=cli_result.commits,
                        output_summary=cli_result.output[:500] if cli_result.output else "",
                        error_message=cli_result.error
                    )

                    # Store full stdout if significant
                    if cli_result.output and len(cli_result.output) > 500:
                        await self.database.create_execution_output(
                            execution_result_id=exec_id,
                            output_type='stdout',
                            content=cli_result.output
                        )

                    # Store stderr if present
                    if cli_result.error:
                        await self.database.create_execution_output(
                            execution_result_id=exec_id,
                            output_type='stderr',
                            content=cli_result.error
                        )

                # Record performance metrics
                await self.database.record_performance_metric(
                    metric_name='parallel_execution_duration',
                    metric_value=result.total_duration,
                    metric_unit='seconds',
                    context={'task_id': str(task_id), 'cli_count': len(result.cli_results)}
                )

                await self.database.record_performance_metric(
                    metric_name='parallel_execution_cost',
                    metric_value=result.total_cost,
                    metric_unit='dollars',
                    context={'task_id': str(task_id)}
                )
            except Exception as db_error:
                # Log database error but don't fail the task
                print(f"Warning: Failed to log to development_docs: {db_error}")

            # Store result in database
            await self.database.update_task_status(
                task_id=task_id,
                status=(
                    TaskStatus.COMPLETED
                    if result.success_count > 0
                    else TaskStatus.FAILED
                ),
                completed_at=datetime.now(),
                result=result.to_dict(),
            )

            # Log completion event
            await self.database.create_progress_event(
                task_id=task_id,
                cli_name="orchestrator",
                session_id=str(task_id),
                status="done",
                message=f"Completed: {result.success_count}/{len(config.assignments)} CLIs succeeded",
                cost=result.total_cost,
                duration=result.total_duration,
            )

        except Exception as e:
            # === DEVELOPMENT DOCS: Log error ===
            try:
                await self.database.create_task_error(
                    task_id=task_id,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    error_details={'traceback': traceback.format_exc()}
                )
            except Exception as db_error:
                print(f"Warning: Failed to log error to development_docs: {db_error}")

            # Log error
            await self.database.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                completed_at=datetime.now(),
                error=str(e),
            )

            # Log error event
            await self.database.create_progress_event(
                task_id=task_id,
                cli_name="orchestrator",
                session_id=str(task_id),
                status="failed",
                message=f"Execution failed: {str(e)}",
            )

        finally:
            # Remove from running tasks
            self._running_tasks.pop(task_id, None)

    async def get_task(self, task_id: UUID) -> Optional[TaskDB]:
        """
        Get task by ID.

        Args:
            task_id: Task UUID

        Returns:
            TaskDB if found
        """
        return await self.database.get_task(task_id)

    async def list_tasks(
        self, status: Optional[TaskStatus] = None, page: int = 1, page_size: int = 50
    ) -> tuple[list[TaskDB], int]:
        """
        List tasks with pagination.

        Args:
            status: Filter by status
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (tasks list, total count)
        """
        offset = (page - 1) * page_size
        tasks = await self.database.list_tasks(
            status=status, limit=page_size, offset=offset
        )
        total = await self.database.count_tasks(status=status)
        return tasks, total

    async def cancel_task(self, task_id: UUID) -> bool:
        """
        Cancel a running task.

        Args:
            task_id: Task UUID

        Returns:
            True if cancelled, False if not running
        """
        execution_task = self._running_tasks.get(task_id)
        if not execution_task:
            return False

        # Cancel the asyncio task
        execution_task.cancel()

        # Update database
        await self.database.update_task_status(
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            completed_at=datetime.now(),
            error="Cancelled by user",
        )

        # Log event
        await self.database.create_progress_event(
            task_id=task_id,
            cli_name="orchestrator",
            session_id=str(task_id),
            status="failed",
            message="Task cancelled by user",
        )

        return True

    def get_stats(self) -> Dict:
        """
        Get orchestrator statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "running_tasks": len(self._running_tasks),
            "executor_stats": self.executor.get_stats(),
        }
