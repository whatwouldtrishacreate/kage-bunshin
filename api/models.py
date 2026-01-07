#!/usr/bin/env python3
"""
Pydantic Models for Kage Bunshin no Jutsu API
==============================================

Request/response schemas for the FastAPI REST API.
Converts between API representations and internal orchestrator models.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator

# ============================================================================
# Enums
# ============================================================================


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MergeStrategy(str, Enum):
    """Merge strategy for parallel execution results."""

    THEIRS = "theirs"  # Accept best result automatically
    AUTO = "auto"  # Auto-merge if no conflicts
    MANUAL = "manual"  # Require manual conflict resolution


# ============================================================================
# Request Models
# ============================================================================


class CLIAssignment(BaseModel):
    """Assignment of a task to a specific CLI."""

    cli_name: str = Field(
        ..., description="CLI tool name (auto-claude, ollama, claude-code, gemini)"
    )
    context: Dict[str, Any] = Field(
        default_factory=dict, description="CLI-specific context"
    )
    timeout: int = Field(
        default=600, description="Execution timeout in seconds", ge=60, le=3600
    )

    @validator("cli_name")
    def validate_cli_name(cls, v):
        allowed = ["auto-claude", "ollama", "claude-code", "gemini"]
        if v not in allowed:
            raise ValueError(f"CLI name must be one of: {allowed}")
        return v


class TaskSubmitRequest(BaseModel):
    """Request to submit a new task for parallel execution."""

    description: str = Field(
        ..., description="Task description for CLIs", min_length=10
    )
    cli_assignments: List[CLIAssignment] = Field(
        ..., description="CLI assignments (1-4)", min_items=1, max_items=4
    )

    # Optional parameters
    max_retries: int = Field(
        default=3, description="Max retry attempts per CLI", ge=0, le=5
    )
    retry_delay: float = Field(
        default=5.0, description="Base retry delay in seconds", ge=1.0, le=60.0
    )
    merge_strategy: MergeStrategy = Field(
        default=MergeStrategy.THEIRS, description="Merge strategy"
    )

    # Metadata
    created_by: Optional[str] = Field(None, description="User/system identifier")

    class Config:
        schema_extra = {
            "example": {
                "description": "Refactor authentication logic to use async/await pattern",
                "cli_assignments": [
                    {"cli_name": "auto-claude", "context": {"complexity": "standard"}},
                    {"cli_name": "ollama", "context": {}},
                    {"cli_name": "claude-code", "context": {}},
                ],
                "max_retries": 3,
                "merge_strategy": "auto",
            }
        }


class MergeRequest(BaseModel):
    """Request to merge task results into main branch."""

    task_id: UUID = Field(..., description="Task ID to merge")
    strategy: MergeStrategy = Field(..., description="Merge strategy to use")
    cli_name: Optional[str] = Field(
        None, description="Specific CLI result to merge (if manual)"
    )


# ============================================================================
# Response Models
# ============================================================================


class CLIResultSummary(BaseModel):
    """Summary of a single CLI execution result."""

    cli_name: str
    status: str
    files_modified: List[str] = Field(default_factory=list)
    cost: float = 0.0
    duration: float = 0.0
    retries: int = 0
    error: Optional[str] = None


class TaskResponse(BaseModel):
    """Response with task information."""

    id: UUID
    description: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Execution results (available when completed)
    cli_results: Optional[List[CLIResultSummary]] = None
    success_count: Optional[int] = None
    failure_count: Optional[int] = None
    total_cost: Optional[float] = None
    total_duration: Optional[float] = None
    best_cli: Optional[str] = None

    # Error tracking
    error: Optional[str] = None

    class Config:
        orm_mode = True
        schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "description": "Refactor auth logic",
                "status": "completed",
                "created_at": "2026-01-04T10:00:00Z",
                "updated_at": "2026-01-04T10:05:00Z",
                "started_at": "2026-01-04T10:00:01Z",
                "completed_at": "2026-01-04T10:05:00Z",
                "success_count": 3,
                "failure_count": 0,
                "total_cost": 3.0,
                "total_duration": 299.5,
                "best_cli": "ollama",
            }
        }


class TaskListResponse(BaseModel):
    """Response with list of tasks."""

    tasks: List[TaskResponse]
    total: int
    page: int = 1
    page_size: int = 50


class MergeResultResponse(BaseModel):
    """Response from merge operation."""

    task_id: UUID
    strategy: str
    success: bool
    merged_files: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    commit_hash: Optional[str] = None
    message: str


class ProgressEvent(BaseModel):
    """Real-time progress event."""

    task_id: UUID
    cli_name: str
    session_id: str
    status: str
    message: str
    timestamp: datetime
    files_modified: Optional[List[str]] = None
    cost: Optional[float] = None
    duration: Optional[float] = None

    class Config:
        schema_extra = {
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "cli_name": "auto-claude",
                "session_id": "task-001-auto-claude",
                "status": "working",
                "message": "Phase 1: Planning implementation",
                "timestamp": "2026-01-04T10:00:05Z",
            }
        }


# ============================================================================
# Error Responses
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    task_id: Optional[UUID] = Field(None, description="Related task ID if applicable")

    class Config:
        schema_extra = {
            "example": {
                "error": "Task not found",
                "detail": "No task with ID 550e8400-e29b-41d4-a716-446655440000",
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }


# ============================================================================
# Database Models (for internal use with asyncpg)
# ============================================================================


class TaskDB(BaseModel):
    """Database representation of a task."""

    id: UUID
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    config: Dict[str, Any]  # ParallelTaskConfig as JSON
    result: Optional[Dict[str, Any]] = None  # AggregatedResult as JSON
    error: Optional[str] = None
    created_by: Optional[str] = None

    def to_response(self) -> TaskResponse:
        """Convert to API response model."""
        response_data = {
            "id": self.id,
            "description": self.description,
            "status": TaskStatus(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

        # Add result data if available
        if self.result:
            response_data.update(
                {
                    "cli_results": [
                        CLIResultSummary(**r)
                        for r in self.result.get("cli_results", [])
                    ],
                    "success_count": self.result.get("success_count"),
                    "failure_count": self.result.get("failure_count"),
                    "total_cost": self.result.get("total_cost"),
                    "total_duration": self.result.get("total_duration"),
                    "best_cli": (
                        self.result.get("best_result", {}).get("cli_name")
                        if self.result.get("best_result")
                        else None
                    ),
                }
            )

        return TaskResponse(**response_data)


class ProgressEventDB(BaseModel):
    """Database representation of a progress event."""

    id: int
    task_id: UUID
    cli_name: str
    session_id: str
    status: str
    message: str
    timestamp: datetime
    files_modified: Optional[List[str]] = None
    cost: Optional[float] = None
    duration: Optional[float] = None

    def to_event(self) -> ProgressEvent:
        """Convert to API event model."""
        return ProgressEvent(
            task_id=self.task_id,
            cli_name=self.cli_name,
            session_id=self.session_id,
            status=self.status,
            message=self.message,
            timestamp=self.timestamp,
            files_modified=self.files_modified,
            cost=self.cost,
            duration=self.duration,
        )
