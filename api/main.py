#!/usr/bin/env python3
"""
Kage Bunshin no Jutsu - Main FastAPI Application
=================================================

Shadow Clone Technique for AI Development 🥷

A semi-supervised multi-CLI orchestration framework that coordinates
Claude Code, Auto-Claude, Ollama, and Gemini in parallel execution
with real-time progress tracking and intelligent result aggregation.

API Version: v1
Base Path: /api/v1
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencies import initialize_services, shutdown_services
from api.routes import merge_router, progress_router, tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Handles startup and shutdown of services.
    """
    # Startup
    print("🥷 Kage Bunshin no Jutsu - Starting up...")
    await initialize_services()
    print("✅ Services initialized")

    yield

    # Shutdown
    print("🥷 Kage Bunshin no Jutsu - Shutting down...")
    await shutdown_services()
    print("✅ Services shut down")


# Create FastAPI application
app = FastAPI(
    title="Kage Bunshin no Jutsu",
    description="""
    # Shadow Clone Technique for AI Development 🥷

    A multi-CLI orchestration framework that coordinates parallel execution across:
    - **Auto-Claude**: Spec-based autonomous coding
    - **Ollama**: Local zero-cost execution (RTX 4090)
    - **Claude Code**: Interactive-style tasks with tool use
    - **Gemini 2.0 Flash**: Fast, cheap documentation & research

    ## Features

    - **Parallel Execution**: Multiple CLIs work simultaneously in isolated git worktrees
    - **Real-time Progress**: SSE streaming for live execution updates
    - **Intelligent Aggregation**: Cost-based result selection with fallback strategies
    - **Merge Strategies**: THEIRS (auto), AUTO (conflict-aware), MANUAL (supervised)
    - **Cost Optimization**: 75% savings using Ollama for simple tasks

    ## Architecture

    Built on three layers:
    1. **Week 1**: State management (worktrees, locks, contexts)
    2. **Week 2**: Execution engine (CLI adapters, parallel executor)
    3. **Week 3**: Orchestration API (this API layer)

    ## Authentication

    All endpoints require API key authentication via `X-API-Key` header.

    ## Version

    API Version: v1
    """,
    version="1.0.0",
    contact={
        "name": "Kage Bunshin Development Team",
        "url": "https://github.com/yourusername/kage-bunshin",
    },
    license_info={
        "name": "MIT",
    },
    lifespan=lifespan,
)

# CORS middleware (configure as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(tasks_router)
app.include_router(progress_router)
app.include_router(merge_router)


# Root endpoint
@app.get("/", tags=["root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Kage Bunshin no Jutsu",
        "emoji": "🥷",
        "description": "Shadow Clone Technique for AI Development",
        "version": "1.0.0",
        "api_version": "v1",
        "endpoints": {
            "tasks": "/api/v1/tasks",
            "progress": "/api/v1/tasks/{task_id}/progress",
            "merge": "/api/v1/tasks/{task_id}/merge",
            "docs": "/docs",
            "openapi": "/openapi.json",
        },
    }


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "kage-bunshin", "emoji": "🥷"}


# Custom exception handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "detail": "The requested resource was not found",
            "path": str(request.url),
        },
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred",
            "emoji": "💥",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
