"""
VCR/Replay Configuration for API Testing

This module provides VCR (Video Cassette Recorder) functionality for recording
and replaying HTTP API interactions. This allows tests to:

1. Record real API responses once (in 'record' mode)
2. Replay recorded responses (in 'replay' mode) - fast, no API costs
3. Validate payload schemas against real API responses
4. Run without network access using cached cassettes

Usage:
    # Run tests in replay mode (default, uses cached cassettes)
    pytest tests/test_claude_api_adapter.py

    # Run tests in record mode (makes real API calls, saves cassettes)
    VCR_RECORD_MODE=all pytest tests/test_claude_api_adapter.py

    # Run specific test with recording
    VCR_RECORD_MODE=new_episodes pytest tests/test_claude_api_adapter.py::test_name

Environment Variables:
    VCR_RECORD_MODE: 'none' (default), 'new_episodes', 'all'
    ANTHROPIC_API_KEY: Required for record mode
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import vcr

# Cassettes directory - stores recorded API responses
CASSETTES_DIR = Path(__file__).parent / "cassettes"
CASSETTES_DIR.mkdir(exist_ok=True)

# VCR record modes
RECORD_MODES = {
    "none": vcr.mode.VCRMode.None_,        # Only replay, fail if no cassette
    "new_episodes": vcr.mode.VCRMode.NEW_EPISODES,  # Record new, replay existing
    "all": vcr.mode.VCRMode.ALL,           # Always record
}


def get_record_mode() -> str:
    """Get VCR record mode from environment."""
    return os.environ.get("VCR_RECORD_MODE", "none")


def filter_anthropic_headers(request):
    """Filter sensitive headers from recorded requests."""
    # Remove API key from headers
    if "x-api-key" in request.headers:
        request.headers["x-api-key"] = "FILTERED"
    if "authorization" in request.headers:
        request.headers["authorization"] = "FILTERED"
    return request


def filter_anthropic_response(response):
    """Filter sensitive data from recorded responses."""
    # Nothing to filter by default, but can be extended
    return response


def create_vcr(**kwargs) -> vcr.VCR:
    """
    Create a configured VCR instance for Anthropic API testing.

    Args:
        **kwargs: Additional VCR configuration options

    Returns:
        Configured VCR instance
    """
    record_mode = get_record_mode()

    vcr_config = vcr.VCR(
        cassette_library_dir=str(CASSETTES_DIR),
        record_mode=RECORD_MODES.get(record_mode, vcr.mode.VCRMode.None_),
        match_on=["method", "scheme", "host", "port", "path", "query", "body"],
        filter_headers=["x-api-key", "authorization"],
        before_record_request=filter_anthropic_headers,
        before_record_response=filter_anthropic_response,
        decode_compressed_response=True,
    )

    # Apply any additional configuration
    for key, value in kwargs.items():
        setattr(vcr_config, key, value)

    return vcr_config


# Default VCR instance
anthropic_vcr = create_vcr()


def vcr_cassette(name: str, **kwargs):
    """
    Decorator to use a VCR cassette for a test.

    Args:
        name: Cassette name (without .yaml extension)
        **kwargs: Additional VCR options

    Example:
        @vcr_cassette("test_simple_completion")
        def test_simple_completion():
            ...
    """
    cassette_path = f"{name}.yaml"
    return anthropic_vcr.use_cassette(cassette_path, **kwargs)


class VCRTestCase:
    """
    Mixin class for test cases that use VCR.

    Provides convenience methods for working with cassettes.
    """

    vcr: vcr.VCR = anthropic_vcr

    @classmethod
    def cassette_path(cls, name: str) -> Path:
        """Get the full path to a cassette file."""
        return CASSETTES_DIR / f"{name}.yaml"

    @classmethod
    def cassette_exists(cls, name: str) -> bool:
        """Check if a cassette exists."""
        return cls.cassette_path(name).exists()

    @classmethod
    def delete_cassette(cls, name: str) -> bool:
        """Delete a cassette file."""
        path = cls.cassette_path(name)
        if path.exists():
            path.unlink()
            return True
        return False


# Pytest fixtures (can be imported in conftest.py)
def pytest_vcr_cassette_dir():
    """Return the cassette directory for pytest-recording."""
    return str(CASSETTES_DIR)


# Export commonly used items
__all__ = [
    "anthropic_vcr",
    "vcr_cassette",
    "VCRTestCase",
    "create_vcr",
    "get_record_mode",
    "CASSETTES_DIR",
]
