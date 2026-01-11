#!/usr/bin/env python3
"""
Database Manager for Kage Bunshin no Jutsu
==========================================

Async PostgreSQL operations using asyncpg.
Manages tasks and progress_events tables in claude_memory database.
"""

import asyncio
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
import asyncpg

from api.models import TaskDB, ProgressEventDB, TaskStatus


class DatabaseManager:
    """
    Manages async PostgreSQL connections and operations.

    Connects to claude_memory database (same as claude-memory MCP server).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "claude_memory",
        user: str = "claude_mcp",
        password: str = "memory123"
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create connection pool."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=2,
                max_size=10,
                command_timeout=60
            )

    async def disconnect(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None

    # ========================================================================
    # Task Operations
    # ========================================================================

    async def create_task(
        self,
        description: str,
        config: Dict[str, Any],
        created_by: Optional[str] = None
    ) -> TaskDB:
        """
        Create a new task.

        Args:
            description: Task description
            config: ParallelTaskConfig as dict
            created_by: User/system identifier

        Returns:
            Created TaskDB object
        """
        query = """
            INSERT INTO tasks (description, status, config, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id, description, status, created_at, updated_at,
                      started_at, completed_at, config, result, error, created_by
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                description,
                TaskStatus.PENDING.value,
                json.dumps(config),
                created_by
            )

        return self._row_to_task(row)

    async def get_task(self, task_id: UUID) -> Optional[TaskDB]:
        """
        Get task by ID.

        Args:
            task_id: Task UUID

        Returns:
            TaskDB if found, None otherwise
        """
        query = """
            SELECT id, description, status, created_at, updated_at,
                   started_at, completed_at, config, result, error, created_by
            FROM tasks
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, task_id)

        return self._row_to_task(row) if row else None

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Optional[TaskDB]:
        """
        Update task status and optionally set result/error.

        Args:
            task_id: Task UUID
            status: New status
            started_at: Start timestamp (for RUNNING status)
            completed_at: Completion timestamp (for COMPLETED/FAILED)
            result: AggregatedResult as dict
            error: Error message (for FAILED status)

        Returns:
            Updated TaskDB if found
        """
        query = """
            UPDATE tasks
            SET status = $2,
                started_at = COALESCE($3, started_at),
                completed_at = COALESCE($4, completed_at),
                result = COALESCE($5, result),
                error = COALESCE($6, error)
            WHERE id = $1
            RETURNING id, description, status, created_at, updated_at,
                      started_at, completed_at, config, result, error, created_by
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                task_id,
                status.value,
                started_at,
                completed_at,
                json.dumps(result) if result else None,
                error
            )

        return self._row_to_task(row) if row else None

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[TaskDB]:
        """
        List tasks with optional filtering.

        Args:
            status: Filter by status
            limit: Max results
            offset: Pagination offset

        Returns:
            List of TaskDB objects
        """
        if status:
            query = """
                SELECT id, description, status, created_at, updated_at,
                       started_at, completed_at, config, result, error, created_by
                FROM tasks
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            params = [status.value, limit, offset]
        else:
            query = """
                SELECT id, description, status, created_at, updated_at,
                       started_at, completed_at, config, result, error, created_by
                FROM tasks
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            params = [limit, offset]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_task(row) for row in rows]

    async def count_tasks(self, status: Optional[TaskStatus] = None) -> int:
        """Count tasks, optionally filtered by status."""
        if status:
            query = "SELECT COUNT(*) FROM tasks WHERE status = $1"
            params = [status.value]
        else:
            query = "SELECT COUNT(*) FROM tasks"
            params = []

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    # ========================================================================
    # Progress Event Operations
    # ========================================================================

    async def create_progress_event(
        self,
        task_id: UUID,
        cli_name: str,
        session_id: str,
        status: str,
        message: str,
        files_modified: Optional[List[str]] = None,
        cost: Optional[float] = None,
        duration: Optional[float] = None
    ) -> ProgressEventDB:
        """
        Create a progress event for SSE streaming.

        Args:
            task_id: Task UUID
            cli_name: CLI tool name
            session_id: Session identifier
            status: Event status
            message: Progress message
            files_modified: Modified files list
            cost: Execution cost
            duration: Execution duration

        Returns:
            Created ProgressEventDB
        """
        query = """
            INSERT INTO progress_events
                (task_id, cli_name, session_id, status, message,
                 files_modified, cost, duration)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, task_id, cli_name, session_id, status, message,
                      files_modified, cost, duration, timestamp
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                task_id,
                cli_name,
                session_id,
                status,
                message,
                files_modified,
                cost,
                duration
            )

        return self._row_to_progress_event(row)

    async def get_task_events(
        self,
        task_id: UUID,
        since: Optional[datetime] = None
    ) -> List[ProgressEventDB]:
        """
        Get progress events for a task.

        Args:
            task_id: Task UUID
            since: Only return events after this timestamp

        Returns:
            List of ProgressEventDB objects
        """
        if since:
            query = """
                SELECT id, task_id, cli_name, session_id, status, message,
                       files_modified, cost, duration, timestamp
                FROM progress_events
                WHERE task_id = $1 AND timestamp > $2
                ORDER BY timestamp ASC
            """
            params = [task_id, since]
        else:
            query = """
                SELECT id, task_id, cli_name, session_id, status, message,
                       files_modified, cost, duration, timestamp
                FROM progress_events
                WHERE task_id = $1
                ORDER BY timestamp ASC
            """
            params = [task_id]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_progress_event(row) for row in rows]

    # ========================================================================
    # Development Documentation Operations
    # ========================================================================

    async def create_execution_result(
        self,
        task_id: UUID,
        cli_name: str,
        status: str,
        duration: float,
        cost: float,
        retries: int,
        files_modified: List[str],
        commits: List[str],
        output_summary: str,
        error_message: Optional[str] = None
    ) -> int:
        """
        Create execution result record in development_docs schema.

        Args:
            task_id: Task UUID
            cli_name: CLI tool name (ollama, claude-code, etc.)
            status: Execution status (success, failure, etc.)
            duration: Execution duration in seconds
            cost: Execution cost in dollars
            retries: Number of retries attempted
            files_modified: List of modified file paths
            commits: List of commit SHAs
            output_summary: First 500 chars of output
            error_message: Error message if failed

        Returns:
            Created execution_result ID
        """
        query = """
            INSERT INTO development_docs.execution_results
            (task_id, cli_name, status, duration, cost, retries,
             files_modified, commits, output_summary, error_message)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query, task_id, cli_name, status, duration, cost,
                retries, files_modified, commits, output_summary, error_message
            )

    async def create_execution_output(
        self,
        execution_result_id: int,
        output_type: str,
        content: str
    ) -> None:
        """
        Store large execution output (stdout/stderr) separately.

        Args:
            execution_result_id: Foreign key to execution_results
            output_type: Type of output (stdout, stderr, parsed)
            content: Full output content
        """
        query = """
            INSERT INTO development_docs.execution_outputs
            (execution_result_id, output_type, content, size_bytes)
            VALUES ($1, $2, $3, $4)
        """
        size_bytes = len(content.encode('utf-8'))

        async with self.pool.acquire() as conn:
            await conn.execute(query, execution_result_id, output_type, content, size_bytes)

    async def create_task_error(
        self,
        task_id: UUID,
        error_type: str,
        error_message: str,
        error_details: Optional[Dict] = None
    ) -> None:
        """
        Log task execution error to development_docs.

        Args:
            task_id: Task UUID
            error_type: Error class name
            error_message: Error message string
            error_details: JSONB containing traceback, context, etc.
        """
        query = """
            INSERT INTO development_docs.task_errors
            (task_id, error_type, error_message, error_details)
            VALUES ($1, $2, $3, $4)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query, task_id, error_type, error_message,
                json.dumps(error_details) if error_details else None
            )

    async def record_performance_metric(
        self,
        metric_name: str,
        metric_value: float,
        metric_unit: str,
        context: Optional[Dict] = None
    ) -> None:
        """
        Record performance metric for analytics.

        Args:
            metric_name: Metric identifier (e.g., 'parallel_execution_duration')
            metric_value: Numeric value
            metric_unit: Unit of measurement (seconds, dollars, count, etc.)
            context: Additional metadata as JSONB
        """
        query = """
            INSERT INTO development_docs.performance_metrics
            (metric_name, metric_value, metric_unit, context)
            VALUES ($1, $2, $3, $4)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query, metric_name, metric_value, metric_unit,
                json.dumps(context) if context else None
            )

    async def get_execution_results_for_task(self, task_id: UUID) -> List[Dict]:
        """
        Get all execution results for a task.

        Args:
            task_id: Task UUID

        Returns:
            List of execution result dictionaries
        """
        query = """
            SELECT id, cli_name, status, duration, cost, retries,
                   files_modified, commits, output_summary, error_message, created_at
            FROM development_docs.execution_results
            WHERE task_id = $1
            ORDER BY created_at ASC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, task_id)
            return [dict(row) for row in rows]

    async def get_execution_output(
        self, execution_result_id: int, output_type: str
    ) -> Optional[str]:
        """
        Retrieve full execution output.

        Args:
            execution_result_id: Execution result ID
            output_type: Type of output (stdout, stderr, parsed)

        Returns:
            Output content string or None
        """
        query = """
            SELECT content
            FROM development_docs.execution_outputs
            WHERE execution_result_id = $1 AND output_type = $2
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, execution_result_id, output_type)

    async def get_recent_errors(self, limit: int = 50) -> List[Dict]:
        """
        Get recent task errors for debugging.

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of error dictionaries with task descriptions
        """
        query = """
            SELECT e.*, t.description as task_description
            FROM development_docs.task_errors e
            JOIN public.tasks t ON e.task_id = t.id
            ORDER BY e.occurred_at DESC
            LIMIT $1
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
            result = []
            for row in rows:
                row_dict = dict(row)
                # Parse JSONB error_details from string back to dict
                if row_dict.get('error_details'):
                    row_dict['error_details'] = json.loads(row_dict['error_details'])
                result.append(row_dict)
            return result

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _row_to_task(self, row) -> TaskDB:
        """Convert asyncpg.Record to TaskDB."""
        return TaskDB(
            id=row['id'],
            description=row['description'],
            status=row['status'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            config=row['config'] if isinstance(row['config'], dict) else json.loads(row['config']),
            result=row['result'] if isinstance(row['result'], dict) else (
                json.loads(row['result']) if row['result'] else None
            ),
            error=row['error'],
            created_by=row['created_by']
        )

    def _row_to_progress_event(self, row) -> ProgressEventDB:
        """Convert asyncpg.Record to ProgressEventDB."""
        return ProgressEventDB(
            id=row['id'],
            task_id=row['task_id'],
            cli_name=row['cli_name'],
            session_id=row['session_id'],
            status=row['status'],
            message=row['message'],
            timestamp=row['timestamp'],
            files_modified=row['files_modified'],
            cost=float(row['cost']) if row['cost'] is not None else None,
            duration=float(row['duration']) if row['duration'] is not None else None
        )
