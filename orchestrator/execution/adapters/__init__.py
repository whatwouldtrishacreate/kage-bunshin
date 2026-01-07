"""CLI Adapters for CLI Council."""

from .auto_claude import AutoClaudeAdapter
from .base import (
    CLIAdapter,
    CLIExecutionError,
    CLINotFoundError,
    CLITimeoutError,
    ExecutionResult,
    ExecutionStatus,
    TaskAssignment,
)
from .claude_code import ClaudeCodeAdapter
from .gemini import GeminiAdapter
from .ollama import OllamaAdapter

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
