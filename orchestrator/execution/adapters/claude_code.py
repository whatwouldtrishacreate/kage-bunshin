#!/usr/bin/env python3
"""
Claude Code CLI Adapter
========================

Adapter for Claude Code CLI - Anthropic's official CLI for Claude.

Claude Code provides:
- Interactive coding assistance
- Tool use capabilities (file operations, bash, etc.)
- Context awareness of codebase
- Frontend/UI specialization

Best for:
- Frontend/UI implementation
- Complex multi-file refactoring
- Tasks requiring codebase understanding
- Interactive problem-solving

Cost Model: $0.50-2.00 per task (Sonnet 4.5)
"""

import json
import re
import tempfile
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


class ClaudeCodeAdapter(CLIAdapter):
    """
    Adapter for Claude Code CLI.

    Uses Claude Code's non-interactive mode to execute tasks
    with full tool access (file operations, bash, etc.).
    """

    def __init__(self):
        """Initialize Claude Code adapter."""
        super().__init__("claude-code")

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Claude Code.

        Workflow:
        1. Write task prompt to temporary file
        2. Run Claude Code in non-interactive mode
        3. Parse output and extract results
        4. Track files modified

        Args:
            task: Task to execute
            worktree_path: Isolated worktree path

        Returns:
            ExecutionResult with status and output
        """
        import asyncio
        from datetime import datetime

        start_time = datetime.now()

        try:
            # Step 1: Build prompt content
            prompt_content = self._build_prompt(task)

            # Step 2: Run Claude Code with prompt via stdin
            command = self._construct_command(task, worktree_path)
            stdout, stderr, returncode = await self._run_subprocess_with_stdin(
                command, worktree_path, task.timeout, prompt_content
            )

            # Step 3: Parse output
            parsed = self._parse_output(stdout, stderr)

            # Step 4: Get modified files and commits
            files_modified = await self._get_modified_files(worktree_path)
            commits = await self._get_commits(worktree_path)

            # Step 5: Estimate cost
            cost = self._estimate_cost(parsed)

            # Determine status
            if returncode == 0:
                status = ExecutionStatus.SUCCESS
            elif returncode == 124:
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
                error=f"Claude Code execution timed out after {task.timeout}s",
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

    def _build_prompt(self, task: TaskAssignment) -> str:
        """
        Build prompt for Claude Code.

        Args:
            task: Task to execute

        Returns:
            Formatted prompt
        """
        prompt = f"""# Task: {task.description}

## Context
{json.dumps(task.context, indent=2)}

## Instructions
Please complete this task following these guidelines:
1. Read relevant files to understand the current implementation
2. Make necessary changes to implement the task
3. Ensure code follows existing patterns and conventions
4. Test your changes if applicable
5. Create a git commit with the changes

Please proceed with implementing this task.
"""
        return prompt

    def _construct_command(
        self, task: TaskAssignment, worktree_path: Path
    ) -> List[str]:
        """
        Construct Claude Code command.

        Uses non-interactive mode with prompt via stdin.

        Note: Claude Code doesn't have a --prompt flag. Instead, we use
        --print mode and pipe the prompt via stdin.

        Args:
            task: Task to execute
            worktree_path: Worktree path

        Returns:
            Command as list of strings
        """
        return ["claude", "--print", "--no-session-persistence"]

    async def _run_subprocess_with_stdin(
        self, command: List[str], cwd: Path, timeout: int, stdin_content: str
    ) -> tuple[str, str, int]:
        """
        Run command as async subprocess with stdin input.

        Args:
            command: Command to execute
            cwd: Working directory
            timeout: Timeout in seconds
            stdin_content: Content to pipe to stdin

        Returns:
            Tuple of (stdout, stderr, returncode)

        Raises:
            asyncio.TimeoutError: If command times out
        """
        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._get_env_vars(),
            )

            # Write prompt to stdin and communicate
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_content.encode("utf-8")), timeout=timeout
            )

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

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse Claude Code output.

        Claude Code outputs:
        - Tool use results
        - File modifications
        - Reasoning/explanations

        Args:
            stdout: Standard output
            stderr: Standard error

        Returns:
            Parsed results
        """
        result = {
            "success": False,
            "tool_uses": [],
            "files_touched": [],
            "commits_made": [],
            "tokens_used": 0,
            "errors": [],
        }

        # Extract tool use information
        tool_pattern = r"Tool: (\w+)"
        tool_matches = re.findall(tool_pattern, stdout)
        result["tool_uses"] = tool_matches

        # Extract file operations
        file_pattern = r"(?:Read|Write|Edit)\s+file:\s*(.+)"
        file_matches = re.findall(file_pattern, stdout)
        result["files_touched"] = file_matches

        # Extract commit information
        commit_pattern = r"Created commit:\s*([a-f0-9]{7,})"
        commit_matches = re.findall(commit_pattern, stdout)
        result["commits_made"] = commit_matches

        # Extract token usage if available
        token_pattern = r"Tokens used:\s*(\d+)"
        token_match = re.search(token_pattern, stdout)
        if token_match:
            result["tokens_used"] = int(token_match.group(1))

        # Check for errors
        if stderr:
            result["errors"].append(stderr)

        # Check for success indicators
        if "Task completed" in stdout or result["commits_made"]:
            result["success"] = True

        return result

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate Claude Code execution cost.

        Cost model based on Sonnet 4.5 pricing:
        - Input: $3/MTok
        - Output: $15/MTok

        Typical task: 10K input + 2K output = $0.06
        With overhead: ~$0.50-2.00 per task

        Args:
            parsed_output: Parsed output

        Returns:
            Estimated cost in USD
        """
        tokens_used = parsed_output.get("tokens_used", 0)

        if tokens_used > 0:
            # Assume 80/20 split (input/output)
            input_tokens = tokens_used * 0.8
            output_tokens = tokens_used * 0.2

            cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)
            return round(cost, 2)

        # Fallback estimate based on tool uses
        tool_count = len(parsed_output.get("tool_uses", []))
        if tool_count > 10:
            return 1.50
        elif tool_count > 5:
            return 1.00
        else:
            return 0.50

    def _get_env_vars(self) -> Dict[str, str]:
        """
        Get environment variables for Claude Code.

        Returns:
            Environment variables including OAuth token
        """
        import os

        env = os.environ.copy()

        # Claude Code specific env vars
        if "CLAUDE_CODE_OAUTH_TOKEN" not in env:
            print("Warning: CLAUDE_CODE_OAUTH_TOKEN not set")

        return env
