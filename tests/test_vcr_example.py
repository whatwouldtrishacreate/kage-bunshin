"""
Example VCR Tests for API Recording/Replay

This file demonstrates how to use VCR for testing API integrations.
Tests can be run in two modes:

1. Replay mode (default): Uses cached cassettes, no API calls
   pytest tests/test_vcr_example.py

2. Record mode: Makes real API calls and saves responses
   VCR_RECORD_MODE=new_episodes pytest tests/test_vcr_example.py

Prerequisites for recording:
- ANTHROPIC_API_KEY environment variable set
- Network access to api.anthropic.com
"""

import os
import pytest

# Import VCR configuration
from .vcr_config import vcr_cassette, VCRTestCase, CASSETTES_DIR


class TestVCRBasics(VCRTestCase):
    """Basic VCR functionality tests."""

    @vcr_cassette("test_ollama_tags")
    def test_ollama_tags(self):
        """
        Test that we can record/replay Ollama API calls.

        This test demonstrates VCR with a local API.
        """
        import requests

        response = requests.get("http://localhost:11434/api/tags", timeout=5)

        # In replay mode, this uses the cached response
        # In record mode, this makes a real call and caches it
        assert response.status_code == 200
        data = response.json()
        assert "models" in data

    def test_cassette_exists_check(self):
        """Test cassette existence checking."""
        # This cassette doesn't exist
        assert not self.cassette_exists("nonexistent_cassette")

        # After running test_ollama_tags with recording, it would exist
        # assert self.cassette_exists("test_ollama_tags")


@pytest.mark.integration
class TestAnthropicVCR:
    """
    Anthropic API tests with VCR.

    These tests are marked as integration tests and require:
    - ANTHROPIC_API_KEY for recording
    - Existing cassettes for replay
    """

    @vcr_cassette("anthropic_simple_completion")
    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and
        not (CASSETTES_DIR / "anthropic_simple_completion.yaml").exists(),
        reason="No API key and no cassette available"
    )
    def test_simple_completion(self):
        """
        Test a simple Claude API completion.

        First run: Records actual API response to cassette
        Subsequent runs: Replays cached response (no API call)
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            pytest.skip("anthropic package not installed")

        client = Anthropic()

        # This call is recorded/replayed via VCR
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[
                {"role": "user", "content": "Say 'Hello VCR test' and nothing else."}
            ]
        )

        assert message.content[0].text is not None
        assert len(message.content[0].text) > 0

    @vcr_cassette("anthropic_tool_use")
    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and
        not (CASSETTES_DIR / "anthropic_tool_use.yaml").exists(),
        reason="No API key and no cassette available"
    )
    def test_tool_use(self):
        """
        Test Claude API with tool use.

        Demonstrates recording complex multi-turn conversations.
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            pytest.skip("anthropic package not installed")

        client = Anthropic()

        tools = [
            {
                "name": "get_weather",
                "description": "Get current weather for a location",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    },
                    "required": ["location"]
                }
            }
        ]

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=200,
            tools=tools,
            messages=[
                {"role": "user", "content": "What's the weather in Tokyo?"}
            ]
        )

        # Claude should request to use the tool
        assert message.stop_reason in ["tool_use", "end_turn"]


class TestVCRRecordModes:
    """Test different VCR record modes."""

    def test_record_mode_none(self, monkeypatch):
        """In 'none' mode, missing cassettes should fail."""
        from .vcr_config import get_record_mode

        monkeypatch.setenv("VCR_RECORD_MODE", "none")
        assert get_record_mode() == "none"

    def test_record_mode_new_episodes(self, monkeypatch):
        """In 'new_episodes' mode, new requests are recorded."""
        from .vcr_config import get_record_mode

        monkeypatch.setenv("VCR_RECORD_MODE", "new_episodes")
        assert get_record_mode() == "new_episodes"

    def test_record_mode_all(self, monkeypatch):
        """In 'all' mode, everything is re-recorded."""
        from .vcr_config import get_record_mode

        monkeypatch.setenv("VCR_RECORD_MODE", "all")
        assert get_record_mode() == "all"


# ==================== Usage Documentation ====================
"""
VCR Testing Workflow
====================

1. Initial Recording:
   - Set ANTHROPIC_API_KEY
   - Run: VCR_RECORD_MODE=new_episodes pytest tests/test_vcr_example.py
   - Cassettes saved to tests/cassettes/

2. CI/Replay Mode:
   - Run: pytest tests/test_vcr_example.py
   - Uses cached cassettes, no API calls
   - Fast, free, deterministic

3. Re-recording:
   - To update cassettes: VCR_RECORD_MODE=all pytest tests/test_vcr_example.py
   - Or delete specific cassette and run with new_episodes

4. Schema Validation:
   - Cassettes contain full request/response
   - Can validate payload schemas haven't changed
   - Detect API breaking changes

Benefits:
- No API costs for repeated test runs
- Fast CI execution
- Deterministic responses
- Offline testing capability
- Schema validation against real API
"""
