#!/usr/bin/env python3
"""
Base CLI Adapter Interface for CLI Council
===========================================

Abstract base class for CLI adapters that execute AI CLI tools in parallel.

Each adapter wraps a specific CLI (Auto-Claude, Ollama, Claude Code, Gemini)
and provides a consistent interface for:
- Command construction
- Async subprocess execution
- Output parsing
- Error handling
- Cost tracking (where applicable)

Adapters are stateless - they receive a session worktree path and execute
commands in that isolated environment.
"""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ExecutionStatus(Enum):
    """Status of CLI execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"  # Waiting on external dependency


@dataclass
class TaskAssignment:
    """Task assigned to a CLI for execution."""

    task_id: str
    cli_name: str
    description: str
    context: Dict[str, Any]  # Additional context (files, patterns, etc.)
    timeout: int = 600  # 10 minutes default
    max_retries: int = 3


@dataclass
class ExecutionResult:
    """Result of CLI execution."""

    task_id: str
    cli_name: str
    status: ExecutionStatus
    output: str
    error: Optional[str] = None
    files_modified: List[str] = None
    commits: List[str] = None
    cost: float = 0.0  # In USD
    duration: float = 0.0  # In seconds
    retries: int = 0
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.files_modified is None:
            self.files_modified = []
        if self.commits is None:
            self.commits = []
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


class CLIAdapter(ABC):
    """
    Abstract base class for CLI adapters.

    Each CLI tool gets its own adapter that implements:
    - Command construction specific to that CLI
    - Output parsing to extract results
    - Error handling for CLI-specific issues
    """

    def __init__(self, cli_name: str):
        self.cli_name = cli_name
        self._execution_count = 0
        self._total_cost = 0.0

    @abstractmethod
    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute a task in the given worktree.

        Args:
            task: The task to execute
            worktree_path: Path to isolated git worktree

        Returns:
            ExecutionResult with status, output, and metadata

        Raises:
            CLIExecutionError: If execution fails unrecoverably
        """
        pass

    @abstractmethod
    def _construct_command(
        self, task: TaskAssignment, worktree_path: Path
    ) -> List[str]:
        """
        Construct CLI command for the task.

        Args:
            task: The task to execute
            worktree_path: Path to worktree

        Returns:
            Command as list of strings (for subprocess)
        """
        pass

    @abstractmethod
    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse CLI output to extract results.

        Args:
            stdout: Standard output from CLI
            stderr: Standard error from CLI

        Returns:
            Parsed results as dictionary
        """
        pass

    async def _run_subprocess(
        self, command: List[str], cwd: Path, timeout: int
    ) -> tuple[str, str, int]:
        """
        Run command as async subprocess.

        Args:
            command: Command to execute
            cwd: Working directory
            timeout: Timeout in seconds

        Returns:
            Tuple of (stdout, stderr, returncode)

        Raises:
            asyncio.TimeoutError: If command times out
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._get_env_vars(),
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                proc.returncode,
            )

        except asyncio.TimeoutError:
            # Kill the process
            try:
                proc.kill()
                await proc.wait()
            except:
                pass
            raise

    def _get_env_vars(self) -> Dict[str, str]:
        """
        Get environment variables for CLI execution.

        Override in subclass to add CLI-specific env vars.

        Returns:
            Dictionary of environment variables
        """
        import os

        return os.environ.copy()

    async def _get_modified_files(self, worktree_path: Path) -> List[str]:
        """
        Get list of modified files in worktree.

        Args:
            worktree_path: Path to worktree

        Returns:
            List of modified file paths
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--name-only",
                "HEAD",
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            files = stdout.decode("utf-8", errors="replace").strip().split("\n")
            return [f for f in files if f]

        except Exception as e:
            print(f"Warning: Could not get modified files: {e}")
            return []

    async def _get_commits(
        self, worktree_path: Path, base_branch: str = "main"
    ) -> List[str]:
        """
        Get list of commits made in worktree.

        Args:
            worktree_path: Path to worktree
            base_branch: Base branch to compare against

        Returns:
            List of commit SHAs
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "rev-list",
                f"{base_branch}..HEAD",
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            commits = stdout.decode("utf-8", errors="replace").strip().split("\n")
            return [c for c in commits if c]

        except Exception as e:
            print(f"Warning: Could not get commits: {e}")
            return []

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate cost of execution (if applicable).

        Override in subclass for CLIs with API costs.

        Args:
            parsed_output: Parsed CLI output

        Returns:
            Estimated cost in USD
        """
        return 0.0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get adapter statistics.

        Returns:
            Dictionary with execution stats
        """
        return {
            "cli_name": self.cli_name,
            "execution_count": self._execution_count,
            "total_cost": self._total_cost,
        }


class CLIExecutionError(Exception):
    """Error during CLI execution."""

    def __init__(
        self,
        message: str,
        cli_name: str,
        task_id: str,
        returncode: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
    ):
        super().__init__(message)
        self.cli_name = cli_name
        self.task_id = task_id
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CLINotFoundError(CLIExecutionError):
    """CLI executable not found on system."""

    pass


class CLITimeoutError(CLIExecutionError):
    """CLI execution timed out."""

    pass
