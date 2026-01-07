#!/usr/bin/env python3
"""
FastAPI Dependencies for Kage Bunshin no Jutsu
==============================================

Dependency injection for:
- Database connection
- Orchestrator service
- API key authentication
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, status
from fastapi.security import APIKeyHeader

from orchestrator.service import OrchestratorService
from storage.database import DatabaseManager

# ============================================================================
# Configuration
# ============================================================================

PROJECT_DIR = Path(__file__).parent.parent.resolve()
BASE_BRANCH = os.getenv("BASE_BRANCH", "main")

# API Key configuration
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
VALID_API_KEYS = (
    set(os.getenv("API_KEYS", "").split(","))
    if os.getenv("API_KEYS")
    else {"dev-key-12345"}
)


# ============================================================================
# Global Instances (initialized on startup)
# ============================================================================

_database: Optional[DatabaseManager] = None
_orchestrator: Optional[OrchestratorService] = None


async def get_database() -> DatabaseManager:
    """
    Get database manager instance.

    Dependency for routes that need database access.
    """
    if _database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )
    return _database


async def get_orchestrator() -> OrchestratorService:
    """
    Get orchestrator service instance.

    Dependency for routes that need task orchestration.
    """
    if _orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator not initialized",
        )
    return _orchestrator


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> str:
    """
    Verify API key from request header.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        API key if valid

    Raises:
        HTTPException: If API key invalid or missing
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if x_api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return x_api_key


# ============================================================================
# Startup/Shutdown Helpers
# ============================================================================


async def initialize_services():
    """
    Initialize global services on application startup.

    Called by FastAPI lifespan context manager.
    """
    global _database, _orchestrator

    # Initialize database
    _database = DatabaseManager()
    await _database.connect()

    # Initialize orchestrator
    _orchestrator = OrchestratorService(
        project_dir=PROJECT_DIR, database=_database, base_branch=BASE_BRANCH
    )


async def shutdown_services():
    """
    Shutdown global services on application shutdown.

    Called by FastAPI lifespan context manager.
    """
    if _database:
        await _database.disconnect()
