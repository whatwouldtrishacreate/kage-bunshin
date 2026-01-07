#!/usr/bin/env python3
"""
Auto-Claude CLI Adapter
========================

Adapter for Auto-Claude's spec-based autonomous coding framework.

Auto-Claude workflow:
1. Create spec from task description
2. Run autonomous build
3. QA validation
4. Merge to project

This adapter wraps Auto-Claude's spec_runner.py and run.py to execute
tasks in isolated worktrees, then extracts results.

Cost Model:
- Simple tasks: $0.50-1.00
- Standard tasks: $1.00-3.00
- Complex tasks: $3.00-8.00
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    CLIAdapter,
    CLIExecutionError,
    CLINotFoundError,
    CLITimeoutError,
    ExecutionResult,
    ExecutionStatus,
    TaskAssignment,
)


class AutoClaudeAdapter(CLIAdapter):
    """
    Adapter for Auto-Claude CLI.

    Auto-Claude uses a spec-based workflow where tasks are converted to
    specifications, then autonomously implemented.
    """

    def __init__(self, auto_claude_path: Optional[Path] = None):
        """
        Initialize Auto-Claude adapter.

        Args:
            auto_claude_path: Path to Auto-Claude installation
                             (defaults to ~/projects/Auto-Claude)
        """
        super().__init__("auto-claude")

        if auto_claude_path is None:
            auto_claude_path = Path.home() / "projects" / "Auto-Claude"

        self.auto_claude_path = auto_claude_path
        self.backend_path = auto_claude_path / "apps" / "backend"

        # Verify installation
        if not self.backend_path.exists():
            raise CLINotFoundError(
                f"Auto-Claude not found at {auto_claude_path}",
                cli_name="auto-claude",
                task_id="init",
            )

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Auto-Claude.

        Workflow:
        1. Create spec from task description
        2. Run autonomous build in worktree
        3. Parse results and extract files modified

        Args:
            task: Task to execute
            worktree_path: Isolated worktree path

        Returns:
            ExecutionResult with status and output
        """
        start_time = datetime.now()

        try:
            # Step 1: Create spec from task description
            spec_id = await self._create_spec(task, worktree_path)

            # Step 2: Run autonomous build
            stdout, stderr, returncode = await self._run_build(
                spec_id, worktree_path, task.timeout
            )

            # Step 3: Parse output
            parsed = self._parse_output(stdout, stderr)

            # Step 4: Get modified files and commits
            files_modified = await self._get_modified_files(worktree_path)
            commits = await self._get_commits(worktree_path)

            # Step 5: Estimate cost
            cost = self._estimate_cost(parsed)

            # Determine status
            if returncode == 0 and parsed.get("success", False):
                status = ExecutionStatus.SUCCESS
            elif returncode == 124:  # timeout
                status = ExecutionStatus.TIMEOUT
            else:
                status = ExecutionStatus.FAILURE

            duration = (datetime.now() - start_time).total_seconds()

            # Update stats
            self._execution_count += 1
            self._total_cost += cost

            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=status,
                output=stdout,
                error=stderr if status == ExecutionStatus.FAILURE else None,
                files_modified=files_modified,
                commits=commits,
                cost=cost,
                duration=duration,
                retries=0,
            )

        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.TIMEOUT,
                output="",
                error=f"Execution timed out after {task.timeout}s",
                cost=0.0,
                duration=duration,
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.FAILURE,
                output="",
                error=str(e),
                cost=0.0,
                duration=duration,
            )

    async def _create_spec(self, task: TaskAssignment, worktree_path: Path) -> str:
        """
        Create Auto-Claude spec from task description.

        Args:
            task: Task to create spec for
            worktree_path: Worktree path

        Returns:
            Spec ID (e.g., "001-task-name")
        """
        # Use spec_runner.py to create spec
        command = [
            "python3",
            str(self.backend_path / "spec_runner.py"),
            "--task",
            task.description,
            "--complexity",
            task.context.get("complexity", "simple"),
        ]

        stdout, stderr, returncode = await self._run_subprocess(
            command, worktree_path, timeout=300  # 5 min for spec creation
        )

        if returncode != 0:
            raise CLIExecutionError(
                f"Failed to create spec: {stderr}",
                cli_name=self.cli_name,
                task_id=task.task_id,
                returncode=returncode,
                stderr=stderr,
            )

        # Extract spec ID from output
        # Output format: "Created spec: 001-task-name"
        match = re.search(r"Created spec: ([\w-]+)", stdout)
        if match:
            return match.group(1)

        # Fallback: use task_id
        return task.task_id.split("-")[0] if "-" in task.task_id else "001"

    async def _run_build(
        self, spec_id: str, worktree_path: Path, timeout: int
    ) -> tuple[str, str, int]:
        """
        Run Auto-Claude autonomous build.

        Args:
            spec_id: Spec identifier
            worktree_path: Worktree path
            timeout: Timeout in seconds

        Returns:
            Tuple of (stdout, stderr, returncode)
        """
        command = ["python3", str(self.backend_path / "run.py"), "--spec", spec_id]

        return await self._run_subprocess(command, worktree_path, timeout)

    def _construct_command(
        self, task: TaskAssignment, worktree_path: Path
    ) -> List[str]:
        """
        Construct Auto-Claude command.

        Note: This is not used directly since Auto-Claude requires
        two-step execution (create spec, then run). Kept for interface
        compliance.
        """
        return ["python3", str(self.backend_path / "run.py"), "--spec", task.task_id]

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse Auto-Claude output.

        Auto-Claude outputs:
        - Task completion status
        - QA validation results
        - Files modified
        - Commit information

        Args:
            stdout: Standard output
            stderr: Standard error

        Returns:
            Parsed results
        """
        result = {
            "success": False,
            "qa_passed": False,
            "phases_completed": [],
            "errors": [],
        }

        # Check for success indicators
        if "Build complete" in stdout or "QA validation passed" in stdout:
            result["success"] = True

        if "QA validation passed" in stdout:
            result["qa_passed"] = True

        # Extract phase information
        phase_matches = re.findall(r"Phase (\d+): (.+?) - (COMPLETE|FAILED)", stdout)
        for phase_num, phase_name, status in phase_matches:
            result["phases_completed"].append(
                {"phase": int(phase_num), "name": phase_name, "status": status}
            )

        # Extract errors
        if stderr:
            result["errors"].append(stderr)

        error_matches = re.findall(r"ERROR: (.+)", stdout)
        result["errors"].extend(error_matches)

        return result

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate Auto-Claude execution cost.

        Cost model based on complexity:
        - Simple: $0.50-1.00 (mostly sonnet)
        - Standard: $1.00-3.00 (mix of sonnet/opus)
        - Complex: $3.00-8.00 (multiple opus sessions)

        Args:
            parsed_output: Parsed output from execution

        Returns:
            Estimated cost in USD
        """
        # Count phases completed
        phases = len(parsed_output.get("phases_completed", []))

        # Base cost estimates
        if phases <= 2:
            # Simple task (spec creation + basic implementation)
            return 0.75
        elif phases <= 5:
            # Standard task (full pipeline)
            return 2.00
        else:
            # Complex task (multiple iterations, QA fixes)
            return 5.00

    def _get_env_vars(self) -> Dict[str, str]:
        """
        Get environment variables for Auto-Claude.

        Returns:
            Environment variables including API keys
        """
        import os

        env = os.environ.copy()

        # Auto-Claude specific env vars
        # These should be set in the system environment
        required_vars = [
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ]

        missing = [var for var in required_vars if var not in env]
        if missing:
            print(f"Warning: Missing Auto-Claude env vars: {missing}")

        return env


import asyncio

# Import datetime for start_time
from datetime import datetime
