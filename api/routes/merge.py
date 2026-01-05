#!/usr/bin/env python3
"""
Merge Routes for Kage Bunshin no Jutsu API
===========================================

Endpoints for merging parallel execution results back into main branch.

Endpoints:
- POST /api/v1/tasks/{task_id}/merge - Merge task results
- GET /api/v1/tasks/{task_id}/conflicts - Check for merge conflicts
"""

from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from api.models import (
    MergeRequest,
    MergeResultResponse,
    MergeStrategy,
    ErrorResponse
)
from api.dependencies import get_database, get_orchestrator, verify_api_key, PROJECT_DIR, BASE_BRANCH
from storage.database import DatabaseManager
from orchestrator.service import OrchestratorService
from orchestrator.merge import MergeExecutor


router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["merge"],
    dependencies=[Depends(verify_api_key)]
)


@router.post(
    "/{task_id}/merge",
    response_model=MergeResultResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Task not found"},
        409: {"model": ErrorResponse, "description": "Task not ready for merge"},
    },
    summary="Merge task results into main branch",
    description="""
    Merge the results from a completed task back into the main branch.

    Three strategies available:
    - **THEIRS**: Accept best result automatically (no conflict check)
    - **AUTO**: Auto-merge if no conflicts, fail otherwise
    - **MANUAL**: Detect conflicts and require manual resolution
    """
)
async def merge_task(
    task_id: UUID,
    strategy: MergeStrategy,
    cli_name: str = None,
    database: DatabaseManager = Depends(get_database),
    orchestrator: OrchestratorService = Depends(get_orchestrator)
) -> MergeResultResponse:
    """Merge task results into main branch."""
    # Get task
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )

    # Check task is completed
    if task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is {task.status}, must be completed to merge"
        )

    # Get best result CLI name (or use specified)
    if cli_name is None:
        if not task.result or not task.result.get("best_result"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task {task_id} has no successful results to merge"
            )
        cli_name = task.result["best_result"]["cli_name"]

    # Determine source branch from task config
    # Branch naming: task-{task_id}-{cli_name}
    source_branch = f"task-{task_id}-{cli_name}"

    # Create merge executor
    merger = MergeExecutor(project_dir=PROJECT_DIR, base_branch=BASE_BRANCH)

    # Execute merge based on strategy
    try:
        if strategy == MergeStrategy.THEIRS:
            result = merger.merge_theirs(
                source_branch=source_branch,
                commit_message=f"Merge task {task_id} results from {cli_name} 🥷"
            )
        elif strategy == MergeStrategy.AUTO:
            result = merger.merge_auto(
                source_branch=source_branch,
                commit_message=f"Auto-merge task {task_id} results from {cli_name} 🥷"
            )
        elif strategy == MergeStrategy.MANUAL:
            result = merger.merge_manual(source_branch=source_branch)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid merge strategy: {strategy}"
            )

        return MergeResultResponse(
            task_id=task_id,
            strategy=result.strategy,
            success=result.success,
            merged_files=result.merged_files,
            conflicts=result.conflicts,
            commit_hash=result.commit_hash,
            message=result.message
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Merge failed: {str(e)}"
        )


@router.get(
    "/{task_id}/conflicts",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
    summary="Check for merge conflicts",
    description="""
    Check if merging this task's results would cause conflicts.

    Returns conflict information without performing the merge.
    """
)
async def check_conflicts(
    task_id: UUID,
    cli_name: str = None,
    database: DatabaseManager = Depends(get_database)
) -> dict:
    """Check for merge conflicts."""
    # Get task
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )

    # Check task is completed
    if task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is {task.status}, must be completed to check conflicts"
        )

    # Get CLI name (best result or specified)
    if cli_name is None:
        if not task.result or not task.result.get("best_result"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task {task_id} has no successful results"
            )
        cli_name = task.result["best_result"]["cli_name"]

    # Determine source branch
    source_branch = f"task-{task_id}-{cli_name}"

    # Create merge executor
    merger = MergeExecutor(project_dir=PROJECT_DIR, base_branch=BASE_BRANCH)

    try:
        # Run manual merge (just detection, no actual merge)
        result = merger.merge_manual(source_branch=source_branch)

        return {
            "task_id": str(task_id),
            "cli_name": cli_name,
            "source_branch": source_branch,
            "can_auto_merge": result.success,
            "conflicts": result.conflicts,
            "files_changed": result.merged_files,
            "message": result.message
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Conflict check failed: {str(e)}"
        )
