#!/usr/bin/env python3
"""
Progress Routes for Kage Bunshin no Jutsu API
==============================================

Real-time progress streaming using Server-Sent Events (SSE).

Endpoints:
- GET /api/v1/tasks/{task_id}/progress - Stream progress events
"""

import asyncio
from datetime import datetime
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from api.dependencies import get_database, verify_api_key
from api.models import ErrorResponse
from storage.database import DatabaseManager

router = APIRouter(
    prefix="/api/v1/tasks", tags=["progress"], dependencies=[Depends(verify_api_key)]
)


@router.get(
    "/{task_id}/progress",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
    summary="Stream real-time progress events",
    description="""
    Stream real-time progress updates for a task using Server-Sent Events (SSE).

    Connect to this endpoint to receive progress events as they occur during
    parallel CLI execution.

    The stream will automatically close when the task completes or fails.
    """,
)
async def stream_progress(
    task_id: UUID, database: DatabaseManager = Depends(get_database)
):
    """
    Stream progress events via SSE.

    Returns an EventSourceResponse that streams progress events.
    """
    # Verify task exists
    task = await database.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found"
        )

    async def event_generator() -> AsyncGenerator[dict, None]:
        """
        Generate SSE events from database progress_events table.

        Polls database for new events and yields them to client.
        """
        last_event_time = datetime.now()

        # Send initial connection event
        yield {
            "event": "connected",
            "data": {
                "task_id": str(task_id),
                "message": "Connected to progress stream",
                "timestamp": datetime.now().isoformat(),
            },
        }

        # Poll for progress events
        while True:
            try:
                # Get task status
                task = await database.get_task(task_id)

                # Check if task is done
                if task.status in ["completed", "failed", "cancelled"]:
                    # Send final event
                    yield {
                        "event": "task_complete",
                        "data": {
                            "task_id": str(task_id),
                            "status": task.status,
                            "message": f"Task {task.status}",
                            "timestamp": datetime.now().isoformat(),
                        },
                    }
                    break

                # Get new progress events since last poll
                events = await database.get_task_events(
                    task_id=task_id, since=last_event_time
                )

                # Send each new event
                for event in events:
                    yield {"event": "progress", "data": event.to_event().dict()}
                    last_event_time = event.timestamp

                # Send heartbeat if no events
                if not events:
                    yield {
                        "event": "heartbeat",
                        "data": {"timestamp": datetime.now().isoformat()},
                    }

                # Wait before next poll (adjust based on your needs)
                await asyncio.sleep(1.0)

            except Exception as e:
                # Send error event
                yield {
                    "event": "error",
                    "data": {"error": str(e), "timestamp": datetime.now().isoformat()},
                }
                break

    return EventSourceResponse(event_generator())
