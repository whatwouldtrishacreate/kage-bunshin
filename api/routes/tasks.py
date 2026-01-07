#!/usr/bin/env python3
"""
Task Routes for Kage Bunshin no Jutsu API
==========================================

Endpoints:
- POST /api/v1/tasks - Submit new task
- GET /api/v1/tasks - List tasks
- GET /api/v1/tasks/{task_id} - Get task status
- DELETE /api/v1/tasks/{task_id} - Cancel task
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.dependencies import get_orchestrator, verify_api_key
from api.models import (ErrorResponse, TaskListResponse, TaskResponse,
                        TaskStatus, TaskSubmitRequest)
from orchestrator.service import OrchestratorService

router = APIRouter(
    prefix="/api/v1/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)]
)


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
    },
    summary="Submit a new task for parallel execution",
    description="""
    Submit a new task to be executed in parallel across multiple CLI tools.

    The task will be queued and executed asynchronously. Use the returned task ID
    to track progress via the SSE endpoint or poll the status endpoint.
    """,
)
async def submit_task(
    request: TaskSubmitRequest,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
    api_key: str = Depends(verify_api_key),
) -> TaskResponse:
    """Submit a new task for parallel execution."""
    try:
        task = await orchestrator.submit_task(
            description=request.description,
            cli_assignments=request.cli_assignments,
            max_retries=request.max_retries,
            retry_delay=request.retry_delay,
            created_by=request.created_by or f"api-key-{api_key[:8]}",
        )
        return task.to_response()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit task: {str(e)}",
        )


@router.get(
    "",
    response_model=TaskListResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    },
    summary="List tasks with optional filtering",
    description="""
    List all tasks with optional status filtering and pagination.

    Use query parameters to filter by status and paginate results.
    """,
)
async def list_tasks(
    status_filter: Optional[TaskStatus] = Query(
        None, alias="status", description="Filter by task status"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> TaskListResponse:
    """List tasks with optional filtering."""
    try:
        tasks, total = await orchestrator.list_tasks(
            status=status_filter, page=page, page_size=page_size
        )

        return TaskListResponse(
            tasks=[task.to_response() for task in tasks],
            total=total,
            page=page,
            page_size=page_size,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}",
        )


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
    summary="Get task status and results",
    description="""
    Get detailed information about a specific task including status,
    execution results, and any errors.
    """,
)
async def get_task(
    task_id: UUID, orchestrator: OrchestratorService = Depends(get_orchestrator)
) -> TaskResponse:
    """Get task by ID."""
    task = await orchestrator.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found"
        )

    return task.to_response()


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Task not found"},
        409: {"model": ErrorResponse, "description": "Task cannot be cancelled"},
    },
    summary="Cancel a running task",
    description="""
    Cancel a task that is currently running or pending.

    Completed or failed tasks cannot be cancelled.
    """,
)
async def cancel_task(
    task_id: UUID, orchestrator: OrchestratorService = Depends(get_orchestrator)
) -> dict:
    """Cancel a running task."""
    # Check task exists
    task = await orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found"
        )

    # Check task is cancellable
    if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is {task.status.value} and cannot be cancelled",
        )

    # Attempt to cancel
    cancelled = await orchestrator.cancel_task(task_id)

    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} could not be cancelled (not currently running)",
        )

    return {
        "message": f"Task {task_id} cancelled successfully",
        "task_id": str(task_id),
        "status": "cancelled",
    }


@router.get(
    "/stats",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    },
    summary="Get orchestrator statistics",
    description="Get runtime statistics about the orchestrator and CLI adapters.",
)
async def get_stats(
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> dict:
    """Get orchestrator statistics."""
    return orchestrator.get_stats()
