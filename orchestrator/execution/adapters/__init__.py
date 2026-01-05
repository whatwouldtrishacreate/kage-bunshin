"""CLI Adapters for CLI Council."""

from .base import (
    CLIAdapter,
    TaskAssignment,
    ExecutionResult,
    ExecutionStatus,
    CLIExecutionError,
    CLINotFoundError,
    CLITimeoutError,
)
from .auto_claude import AutoClaudeAdapter
from .ollama import OllamaAdapter
from .claude_code import ClaudeCodeAdapter
from .gemini import GeminiAdapter

__all__ = [
    # Base classes
    "CLIAdapter",
    "TaskAssignment",
    "ExecutionResult",
    "ExecutionStatus",
    # Exceptions
    "CLIExecutionError",
    "CLINotFoundError",
    "CLITimeoutError",
    # Adapters
    "AutoClaudeAdapter",
    "OllamaAdapter",
    "ClaudeCodeAdapter",
    "GeminiAdapter",
]
