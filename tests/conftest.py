"""
Pytest Configuration and Fixtures

Provides common fixtures for Kage Bunshin tests including:
- VCR cassette fixtures for API recording/replay
- Mock adapters and clients
- Temporary directories and worktrees
"""

import os
import pytest
from pathlib import Path

# Import VCR configuration
from .vcr_config import anthropic_vcr, CASSETTES_DIR, get_record_mode


# ==================== VCR Fixtures ====================


@pytest.fixture(scope="session")
def vcr_config():
    """
    Pytest-recording VCR configuration.

    This fixture configures pytest-recording to use our custom VCR setup.
    """
    return {
        "cassette_library_dir": str(CASSETTES_DIR),
        "record_mode": get_record_mode(),
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        "filter_headers": ["x-api-key", "authorization"],
        "decode_compressed_response": True,
    }


@pytest.fixture
def vcr_cassette(request):
    """
    Fixture that provides a VCR cassette for each test.

    The cassette name is derived from the test name.
    Uses pytest-recording if available, falls back to vcrpy.

    Example:
        def test_api_call(vcr_cassette):
            with vcr_cassette:
                # API call will be recorded/replayed
                response = api.call()
    """
    # Get test name for cassette
    test_name = request.node.name
    cassette_path = f"{test_name}.yaml"

    return anthropic_vcr.use_cassette(cassette_path)


@pytest.fixture
def anthropic_vcr_cassette(request):
    """
    Fixture specifically for Anthropic API tests.

    Includes additional filtering for Anthropic-specific headers.
    """
    test_name = request.node.name
    cassette_path = f"anthropic_{test_name}.yaml"

    return anthropic_vcr.use_cassette(
        cassette_path,
        filter_post_data_parameters=["messages"],  # Don't match on exact messages
    )


# ==================== Markers ====================


def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "vcr: mark test to use VCR cassette recording/replay"
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test requiring real API"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (takes > 30 seconds)"
    )


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection based on environment.

    Skip integration tests if no API key is available and not in record mode.
    """
    record_mode = get_record_mode()
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    skip_integration = pytest.mark.skip(
        reason="No ANTHROPIC_API_KEY and VCR_RECORD_MODE is 'none'"
    )

    for item in items:
        # Skip integration tests without API key in replay mode
        if "integration" in item.keywords:
            if not has_api_key and record_mode == "none":
                # Check if cassette exists
                cassette_name = f"anthropic_{item.name}.yaml"
                cassette_path = CASSETTES_DIR / cassette_name

                if not cassette_path.exists():
                    item.add_marker(skip_integration)


# ==================== Common Fixtures ====================


@pytest.fixture
def mock_api_key(monkeypatch):
    """Set a mock API key for testing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-for-testing")


@pytest.fixture
def clean_cassette(request):
    """
    Fixture that ensures a clean cassette for recording.

    Deletes existing cassette before test runs.
    Useful for re-recording tests.
    """
    test_name = request.node.name
    cassette_path = CASSETTES_DIR / f"{test_name}.yaml"

    if cassette_path.exists():
        cassette_path.unlink()

    yield cassette_path

    # Optionally clean up after test
    # cassette_path.unlink(missing_ok=True)


# ==================== Environment Helpers ====================


@pytest.fixture
def require_anthropic_key():
    """Skip test if ANTHROPIC_API_KEY is not set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")


@pytest.fixture
def require_ollama():
    """Skip test if Ollama is not running."""
    import requests

    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code != 200:
            pytest.skip("Ollama not responding")
    except requests.RequestException:
        pytest.skip("Ollama not available")
