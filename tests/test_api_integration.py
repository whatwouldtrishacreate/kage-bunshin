#!/usr/bin/env python3
"""
Integration Tests for Kage Bunshin no Jutsu API (Week 3)
=========================================================

Tests the complete API layer including:
- Task submission and retrieval
- SSE progress streaming
- Merge operations
- Authentication

Requires:
- PostgreSQL database (claude_memory)
- Git repository initialized
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.dependencies import initialize_services, shutdown_services
from api.main import app
from storage.database import DatabaseManager

# Test API key
TEST_API_KEY = "dev-key-12345"


@pytest_asyncio.fixture
async def client():
    """Create test client with initialized services."""
    # Initialize services
    await initialize_services()

    # Create async client
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    # Shutdown services
    await shutdown_services()


@pytest_asyncio.fixture
async def database():
    """Get database instance for cleanup."""
    db = DatabaseManager()
    await db.connect()
    yield db
    await db.disconnect()


class TestAuthentication:
    """Test API key authentication."""

    @pytest.mark.asyncio
    async def test_missing_api_key(self, client):
        """Test that requests without API key are rejected."""
        response = await client.get("/api/v1/tasks")
        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, client):
        """Test that invalid API keys are rejected."""
        response = await client.get(
            "/api/v1/tasks", headers={"X-API-Key": "invalid-key"}
        )
        assert response.status_code == 403
        assert "Invalid API key" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_api_key(self, client):
        """Test that valid API keys are accepted."""
        response = await client.get(
            "/api/v1/tasks", headers={"X-API-Key": TEST_API_KEY}
        )
        assert response.status_code == 200


class TestTaskEndpoints:
    """Test task submission and retrieval endpoints."""

    @pytest.mark.asyncio
    async def test_submit_task(self, client):
        """Test submitting a new task."""
        task_data = {
            "description": "Test task for API integration",
            "cli_assignments": [{"cli_name": "ollama", "context": {}, "timeout": 600}],
            "max_retries": 3,
            "merge_strategy": "theirs",
        }

        response = await client.post(
            "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["description"] == task_data["description"]
        assert data["status"] in ["pending", "running"]

    @pytest.mark.asyncio
    async def test_list_tasks(self, client):
        """Test listing tasks."""
        response = await client.get(
            "/api/v1/tasks", headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
        assert isinstance(data["tasks"], list)

    @pytest.mark.asyncio
    async def test_get_task(self, client):
        """Test getting a specific task."""
        # First create a task
        task_data = {
            "description": "Test task for GET endpoint",
            "cli_assignments": [{"cli_name": "ollama", "context": {}, "timeout": 600}],
        }

        create_response = await client.post(
            "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["id"]

        # Now get the task
        get_response = await client.get(
            f"/api/v1/tasks/{task_id}", headers={"X-API-Key": TEST_API_KEY}
        )

        assert get_response.status_code == 200
        data = get_response.json()
        assert data["id"] == task_id
        assert data["description"] == task_data["description"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, client):
        """Test getting a task that doesn't exist."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/api/v1/tasks/{fake_uuid}", headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_pagination(self, client):
        """Test task list pagination."""
        # Create multiple tasks
        for i in range(5):
            task_data = {
                "description": f"Pagination test task {i}",
                "cli_assignments": [
                    {"cli_name": "ollama", "context": {}, "timeout": 600}
                ],
            }
            await client.post(
                "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
            )

        # Test pagination
        response = await client.get(
            "/api/v1/tasks?page=1&page_size=3", headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) <= 3
        assert data["page"] == 1
        assert data["page_size"] == 3


class TestProgressStreaming:
    """Test SSE progress streaming."""

    @pytest.mark.asyncio
    async def test_progress_stream_connection(self, client):
        """Test connecting to progress stream."""
        # Create a task first
        task_data = {
            "description": "Test task for progress streaming",
            "cli_assignments": [{"cli_name": "ollama", "context": {}, "timeout": 600}],
        }

        create_response = await client.post(
            "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
        )
        task_id = create_response.json()["id"]

        # Connect to progress stream (this will stream events)
        # Note: In real tests, you'd need to handle SSE stream parsing
        # For now, just verify endpoint exists and returns 200
        async with client.stream(
            "GET",
            f"/api/v1/tasks/{task_id}/progress",
            headers={"X-API-Key": TEST_API_KEY},
        ) as response:
            assert response.status_code == 200
            assert (
                response.headers["content-type"] == "text/event-stream; charset=utf-8"
            )


class TestMergeEndpoints:
    """Test merge operation endpoints."""

    @pytest.mark.asyncio
    async def test_check_conflicts_nonexistent_task(self, client):
        """Test checking conflicts for nonexistent task."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/api/v1/tasks/{fake_uuid}/conflicts", headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 404


class TestHealthEndpoints:
    """Test health and info endpoints."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Kage Bunshin no Jutsu"
        assert data["emoji"] == "🥷"
        assert "endpoints" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["emoji"] == "🥷"


class TestValidation:
    """Test request validation."""

    @pytest.mark.asyncio
    async def test_invalid_cli_name(self, client):
        """Test that invalid CLI names are rejected."""
        task_data = {
            "description": "Test task with invalid CLI",
            "cli_assignments": [
                {"cli_name": "invalid-cli", "context": {}, "timeout": 600}
            ],
        }

        response = await client.post(
            "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_missing_description(self, client):
        """Test that tasks without description are rejected."""
        task_data = {
            "cli_assignments": [{"cli_name": "ollama", "context": {}, "timeout": 600}]
        }

        response = await client.post(
            "/api/v1/tasks", json=task_data, headers={"X-API-Key": TEST_API_KEY}
        )

        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
