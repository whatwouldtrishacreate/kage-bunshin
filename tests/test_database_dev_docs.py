#!/usr/bin/env python3
"""
Unit Tests for Development Documentation Database Operations
==============================================================

Tests the new development_docs schema methods in DatabaseManager.
"""

import pytest
from uuid import uuid4
from storage.database import DatabaseManager


@pytest.mark.asyncio
class TestExecutionResults:
    """Test execution_results table operations."""

    async def test_create_execution_result(self):
        """Test creating an execution result record."""
        db = DatabaseManager()
        await db.connect()

        try:
            # Create test task first
            task = await db.create_task(
                description="Test task for execution result",
                config={"test": True},
                created_by="test_suite"
            )

            # Create execution result
            exec_id = await db.create_execution_result(
                task_id=task.id,
                cli_name='ollama',
                status='success',
                duration=120.5,
                cost=0.0,
                retries=0,
                files_modified=['test.py', 'README.md'],
                commits=['abc123'],
                output_summary='Test output summary',
                error_message=None
            )

            assert exec_id is not None
            assert isinstance(exec_id, int)

            # Verify retrieval
            results = await db.get_execution_results_for_task(task.id)
            assert len(results) == 1
            assert results[0]['cli_name'] == 'ollama'
            assert results[0]['status'] == 'success'
            assert results[0]['duration'] == 120.5
            assert results[0]['cost'] == 0.0
            assert results[0]['files_modified'] == ['test.py', 'README.md']
            assert results[0]['commits'] == ['abc123']

        finally:
            await db.disconnect()

    async def test_multiple_execution_results(self):
        """Test multiple execution results for same task."""
        db = DatabaseManager()
        await db.connect()

        try:
            # Create test task
            task = await db.create_task(
                description="Test parallel execution",
                config={"test": True},
                created_by="test_suite"
            )

            # Create multiple execution results (parallel execution)
            exec_id_1 = await db.create_execution_result(
                task_id=task.id,
                cli_name='ollama',
                status='success',
                duration=100.0,
                cost=0.0,
                retries=0,
                files_modified=['test.py'],
                commits=['abc123'],
                output_summary='Ollama output'
            )

            exec_id_2 = await db.create_execution_result(
                task_id=task.id,
                cli_name='claude-code',
                status='success',
                duration=80.0,
                cost=0.50,
                retries=0,
                files_modified=['test.py'],
                commits=['def456'],
                output_summary='Claude Code output'
            )

            assert exec_id_1 != exec_id_2

            # Verify both results
            results = await db.get_execution_results_for_task(task.id)
            assert len(results) == 2

            cli_names = {r['cli_name'] for r in results}
            assert cli_names == {'ollama', 'claude-code'}

        finally:
            await db.disconnect()


@pytest.mark.asyncio
class TestExecutionOutputs:
    """Test execution_outputs table operations."""

    async def test_create_and_retrieve_output(self):
        """Test storing and retrieving large outputs."""
        db = DatabaseManager()
        await db.connect()

        try:
            # Create test task and execution result
            task = await db.create_task(
                description="Test output storage",
                config={"test": True}
            )

            exec_id = await db.create_execution_result(
                task_id=task.id,
                cli_name='ollama',
                status='success',
                duration=50.0,
                cost=0.0,
                retries=0,
                files_modified=[],
                commits=[],
                output_summary='First 500 chars...'
            )

            # Store full output
            large_output = "A" * 10000  # 10KB output
            await db.create_execution_output(
                execution_result_id=exec_id,
                output_type='stdout',
                content=large_output
            )

            # Retrieve output
            retrieved = await db.get_execution_output(exec_id, 'stdout')
            assert retrieved == large_output
            assert len(retrieved) == 10000

        finally:
            await db.disconnect()

    async def test_multiple_output_types(self):
        """Test storing stdout and stderr separately."""
        db = DatabaseManager()
        await db.connect()

        try:
            task = await db.create_task(
                description="Test multiple outputs",
                config={"test": True}
            )

            exec_id = await db.create_execution_result(
                task_id=task.id,
                cli_name='ollama',
                status='failure',
                duration=30.0,
                cost=0.0,
                retries=1,
                files_modified=[],
                commits=[],
                output_summary='',
                error_message='Command failed'
            )

            # Store both stdout and stderr
            await db.create_execution_output(
                execution_result_id=exec_id,
                output_type='stdout',
                content='Partial output before error'
            )

            await db.create_execution_output(
                execution_result_id=exec_id,
                output_type='stderr',
                content='Error: File not found'
            )

            # Retrieve both
            stdout = await db.get_execution_output(exec_id, 'stdout')
            stderr = await db.get_execution_output(exec_id, 'stderr')

            assert stdout == 'Partial output before error'
            assert stderr == 'Error: File not found'

        finally:
            await db.disconnect()


@pytest.mark.asyncio
class TestTaskErrors:
    """Test task_errors table operations."""

    async def test_create_task_error(self):
        """Test logging task errors."""
        db = DatabaseManager()
        await db.connect()

        try:
            task = await db.create_task(
                description="Test error logging",
                config={"test": True}
            )

            # Log error
            await db.create_task_error(
                task_id=task.id,
                error_type='RuntimeError',
                error_message='Test execution failed',
                error_details={
                    'traceback': 'Traceback (most recent call last):\n  File "test.py", line 10',
                    'context': {'retry': 3}
                }
            )

            # Retrieve recent errors
            errors = await db.get_recent_errors(limit=10)
            assert len(errors) >= 1

            # Find our error
            our_error = next((e for e in errors if e['task_id'] == task.id), None)
            assert our_error is not None
            assert our_error['error_type'] == 'RuntimeError'
            assert our_error['error_message'] == 'Test execution failed'
            assert 'Traceback' in our_error['error_details']['traceback']

        finally:
            await db.disconnect()


@pytest.mark.asyncio
class TestPerformanceMetrics:
    """Test performance_metrics table operations."""

    async def test_record_performance_metric(self):
        """Test recording performance metrics."""
        db = DatabaseManager()
        await db.connect()

        try:
            task = await db.create_task(
                description="Test metrics",
                config={"test": True}
            )

            # Record duration metric
            await db.record_performance_metric(
                metric_name='parallel_execution_duration',
                metric_value=150.5,
                metric_unit='seconds',
                context={'task_id': str(task.id), 'cli_count': 2}
            )

            # Record cost metric
            await db.record_performance_metric(
                metric_name='parallel_execution_cost',
                metric_value=0.50,
                metric_unit='dollars',
                context={'task_id': str(task.id)}
            )

            # Note: No retrieval method for metrics yet, just verify no errors

        finally:
            await db.disconnect()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
