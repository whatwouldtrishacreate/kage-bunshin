#!/usr/bin/env python3
"""
Integration Tests for Ollama Adapter
=====================================

Tests the Ollama adapter functionality including:
- ANSI escape code stripping
- Output parsing flexibility
- Task execution with real Ollama
- Error handling
- File creation and commits
- Simple and complex tasks

These are integration tests that require:
- Ollama installed and running
- qwen2.5-coder:32b model available
"""

import asyncio
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.execution.adapters import (
    ExecutionResult,
    ExecutionStatus,
    OllamaAdapter,
    TaskAssignment,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit
        test_file = repo_path / "README.md"
        test_file.write_text("# Test Project\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        yield repo_path


@pytest.fixture
def ollama_adapter():
    """Create an Ollama adapter instance."""
    return OllamaAdapter(model="qwen2.5-coder:32b")


@pytest.fixture
def simple_task():
    """Create a simple task assignment."""
    return TaskAssignment(
        task_id="test-simple-123",
        cli_name="ollama",
        description="Write a Python function to add two numbers",
        context={},
        timeout=300,
    )


@pytest.fixture
def complex_task():
    """Create a complex task assignment."""
    return TaskAssignment(
        task_id="test-complex-456",
        cli_name="ollama",
        description="Implement a binary search function in Python with type hints, error handling, and docstring",
        context={},
        timeout=300,
    )


# ============================================================================
# Unit Tests - ANSI Code Stripping
# ============================================================================


class TestAnsiCodeStripping:
    """Test ANSI escape code stripping functionality."""

    def test_strip_basic_ansi_codes(self, ollama_adapter):
        """Test stripping basic ANSI color codes."""
        text_with_ansi = "\x1B[31mRed text\x1B[0m Normal text"
        clean_text = ollama_adapter._strip_ansi_codes(text_with_ansi)
        assert clean_text == "Red text Normal text"
        assert "\x1B" not in clean_text

    def test_strip_cursor_movement_codes(self, ollama_adapter):
        """Test stripping ANSI cursor movement codes."""
        text_with_ansi = "Loading\x1B[2K\x1B[1G100%"
        clean_text = ollama_adapter._strip_ansi_codes(text_with_ansi)
        assert clean_text == "Loading100%"
        assert "\x1B" not in clean_text

    def test_strip_complex_ansi_sequences(self, ollama_adapter):
        """Test stripping complex ANSI sequences (like Ollama spinners)."""
        # Simulate Ollama spinner output
        text_with_ansi = "⠋ \x1B[?25l\x1B[2K\r⠙ \x1B[?25lGenerating code...\x1B[0m"
        clean_text = ollama_adapter._strip_ansi_codes(text_with_ansi)
        assert "Generating code..." in clean_text
        assert "\x1B" not in clean_text
        assert "\x1B[?25l" not in clean_text
        assert "\x1B[2K" not in clean_text

    def test_strip_empty_string(self, ollama_adapter):
        """Test stripping ANSI codes from empty string."""
        clean_text = ollama_adapter._strip_ansi_codes("")
        assert clean_text == ""

    def test_strip_no_ansi_codes(self, ollama_adapter):
        """Test stripping when no ANSI codes present."""
        text = "This is plain text with no ANSI codes"
        clean_text = ollama_adapter._strip_ansi_codes(text)
        assert clean_text == text


# ============================================================================
# Unit Tests - Output Parsing
# ============================================================================


class TestOutputParsing:
    """Test output parsing flexibility."""

    def test_parse_markdown_code_blocks(self, ollama_adapter):
        """Test parsing markdown code blocks."""
        stdout = """Here's a Python function:

```python
def add(a, b):
    return a + b
```

This function adds two numbers."""

        parsed = ollama_adapter._parse_output(stdout, "")
        assert parsed["success"] is True
        assert "def add(a, b):" in parsed["code_content"]
        assert "return a + b" in parsed["code_content"]

    def test_parse_multiple_code_blocks(self, ollama_adapter):
        """Test parsing multiple code blocks."""
        stdout = """Here are two functions:

```python
def add(a, b):
    return a + b
```

And another:

```python
def subtract(a, b):
    return a - b
```"""

        parsed = ollama_adapter._parse_output(stdout, "")
        assert parsed["success"] is True
        assert "def add(a, b):" in parsed["code_content"]
        assert "def subtract(a, b):" in parsed["code_content"]

    def test_parse_code_with_language_specifier(self, ollama_adapter):
        """Test parsing code blocks with language specifiers."""
        stdout = """```python
def hello():
    print("Hello, World!")
```"""

        parsed = ollama_adapter._parse_output(stdout, "")
        assert parsed["success"] is True
        assert 'print("Hello, World!")' in parsed["code_content"]

    def test_parse_plain_text_without_code_blocks(self, ollama_adapter):
        """Test parsing plain text without code blocks."""
        stdout = "This is a plain text response without code blocks."

        parsed = ollama_adapter._parse_output(stdout, "")
        assert parsed["success"] is True
        assert parsed["code_content"] == stdout

    def test_parse_empty_output(self, ollama_adapter):
        """Test parsing empty output."""
        parsed = ollama_adapter._parse_output("", "")
        assert parsed["success"] is False
        assert parsed["code_content"] == ""

    def test_parse_with_stderr(self, ollama_adapter):
        """Test parsing with stderr (should ignore timing logs)."""
        stdout = "Code output"
        stderr = "time=123ms"

        parsed = ollama_adapter._parse_output(stdout, stderr)
        assert parsed["success"] is True
        assert len(parsed["errors"]) == 0  # Timing logs ignored


# ============================================================================
# Unit Tests - Command Construction
# ============================================================================


class TestCommandConstruction:
    """Test command construction."""

    def test_construct_simple_command(self, ollama_adapter, simple_task):
        """Test constructing command with simple task."""
        command = ollama_adapter._construct_command(simple_task, Path("/tmp"))

        assert command[0] == "ollama"
        assert command[1] == "run"
        assert command[2] == "qwen2.5-coder:32b"
        assert command[3] == simple_task.description

    def test_construct_command_with_context(self, ollama_adapter):
        """Test constructing command with file context."""
        task = TaskAssignment(
            task_id="test-123",
            cli_name="ollama",
            description="Fix the bug",
            context={"files": ["file1.py", "file2.py"]},
            timeout=300,
        )

        command = ollama_adapter._construct_command(task, Path("/tmp"))

        assert "file1.py" in command[3]
        assert "file2.py" in command[3]
        assert "Context files:" in command[3]


# ============================================================================
# Integration Tests - Task Execution
# ============================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not Path("/usr/local/bin/ollama").exists() and not Path("/usr/bin/ollama").exists(),
    reason="Ollama not installed"
)
class TestTaskExecution:
    """Integration tests for actual task execution.

    These tests require Ollama to be installed and running.
    """

    @pytest.mark.asyncio
    async def test_execute_simple_task(self, ollama_adapter, simple_task, temp_git_repo):
        """Test executing a simple coding task."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.task_id == simple_task.task_id
        assert result.cli_name == "ollama"
        assert result.cost == 0.0
        assert result.duration > 0
        assert result.output is not None
        assert len(result.output) > 0

        # Should have created output file
        output_files = list(temp_git_repo.glob("ollama_result_*.md"))
        assert len(output_files) > 0

        # Check if commit was created (verify via git log)
        import subprocess
        git_log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )
        # Should have at least 2 commits (initial + ollama result)
        assert len(git_log.stdout.strip().split("\n")) >= 2

    @pytest.mark.asyncio
    async def test_execute_complex_task(self, ollama_adapter, complex_task, temp_git_repo):
        """Test executing a complex coding task."""
        result = await ollama_adapter.execute(complex_task, temp_git_repo)

        assert result.status == ExecutionStatus.SUCCESS
        assert result.cost == 0.0
        assert result.output is not None

        # Complex task should take longer
        assert result.duration > 60  # At least 1 minute

        # Should contain type hints and error handling
        assert "def " in result.output

    @pytest.mark.asyncio
    async def test_output_file_creation(self, ollama_adapter, simple_task, temp_git_repo):
        """Test that output file is created with correct format."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        output_files = list(temp_git_repo.glob("ollama_result_*.md"))
        assert len(output_files) == 1

        output_file = output_files[0]
        content = output_file.read_text()

        # Check markdown structure
        assert "# Ollama Result" in content
        assert "**Task:**" in content
        assert "**Model:**" in content
        assert "## Output" in content
        assert simple_task.description in content

    @pytest.mark.asyncio
    async def test_git_commit_creation(self, ollama_adapter, simple_task, temp_git_repo):
        """Test that git commit is created properly."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        # Check git log
        git_log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        assert "Ollama" in git_log.stdout
        assert "qwen2.5-coder:32b" in git_log.stdout

    @pytest.mark.asyncio
    async def test_ansi_codes_stripped_from_output(self, ollama_adapter, simple_task, temp_git_repo):
        """Test that ANSI codes are stripped from final output."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        # Output should not contain ANSI escape sequences
        assert "\x1B[" not in result.output
        assert "\x1B" not in result.output

    @pytest.mark.asyncio
    async def test_timeout_handling(self, ollama_adapter, temp_git_repo):
        """Test timeout handling for long-running tasks."""
        timeout_task = TaskAssignment(
            task_id="test-timeout-789",
            cli_name="ollama",
            description="Write a very complex machine learning model implementation",
            context={},
            timeout=5,  # Very short timeout
        )

        result = await ollama_adapter.execute(timeout_task, temp_git_repo)

        # Should timeout gracefully
        assert result.status in [ExecutionStatus.TIMEOUT, ExecutionStatus.SUCCESS]
        assert result.duration <= timeout_task.timeout + 5  # Allow small buffer


# ============================================================================
# Integration Tests - Error Handling
# ============================================================================


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_model(self, temp_git_repo, simple_task):
        """Test handling of invalid model name."""
        adapter = OllamaAdapter(model="nonexistent-model:999")
        result = await adapter.execute(simple_task, temp_git_repo)

        # Should fail gracefully
        assert result.status == ExecutionStatus.FAILURE
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_empty_task_description(self, ollama_adapter, temp_git_repo):
        """Test handling of empty task description."""
        empty_task = TaskAssignment(
            task_id="test-empty",
            cli_name="ollama",
            description="",
            context={},
            timeout=300,
        )

        result = await ollama_adapter.execute(empty_task, temp_git_repo)

        # Should complete but may produce minimal output
        assert result.status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILURE]


# ============================================================================
# Performance Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.performance
class TestPerformance:
    """Performance-related tests."""

    @pytest.mark.asyncio
    async def test_simple_task_performance(self, ollama_adapter, simple_task, temp_git_repo):
        """Test that simple tasks complete in reasonable time."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        assert result.status == ExecutionStatus.SUCCESS
        # Simple tasks should complete in under 5 minutes
        assert result.duration < 300

    @pytest.mark.asyncio
    async def test_cost_is_zero(self, ollama_adapter, simple_task, temp_git_repo):
        """Test that local execution has zero cost."""
        result = await ollama_adapter.execute(simple_task, temp_git_repo)

        assert result.cost == 0.0
