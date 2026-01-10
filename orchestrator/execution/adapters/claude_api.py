#!/usr/bin/env python3
"""
Claude API Adapter for CLI Council
===================================

API-based adapter using the Anthropic SDK instead of CLI subprocess.

This adapter provides a direct comparison point for evaluating:
- CLI subprocess approach (current ClaudeCodeAdapter)
- API SDK approach (this adapter)

Key differences:
- Token counting: Exact (from API response) vs estimated (chars ÷ 4)
- Cost tracking: Exact pricing vs approximation
- Latency: API network overhead vs subprocess overhead
- Tool use: Agentic loop vs CLI built-in tools

Architecture:
- Uses AsyncAnthropic client for async API calls
- Implements agentic loop with tool use (read_file, write_file, bash)
- Exact token counting from response.usage
- Rate limiting via RateLimiter

Usage:
    adapter = ClaudeAPIAdapter()
    result = await adapter.execute(task, worktree_path)
"""

import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None  # Handle missing dependency gracefully

from .base import CLIAdapter, ExecutionResult, ExecutionStatus, TaskAssignment

# Tool definitions for Claude API
TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file in the worktree",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file relative to worktree root"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the worktree",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file relative to worktree root"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "bash",
        "description": "Execute a bash command in the worktree",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Bash command to execute"
                }
            },
            "required": ["command"]
        }
    }
]


class ClaudeAPIAdapter(CLIAdapter):
    """
    Anthropic API-based adapter for direct Claude API access.

    Provides comparison point for CLI subprocess approach.
    Uses agentic loop with tool use for file operations.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20251218"):
        """
        Initialize Claude API adapter.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use

        Raises:
            ImportError: If anthropic package not installed
            ValueError: If API key not provided
        """
        super().__init__("claude-api")

        if AsyncAnthropic is None:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install anthropic>=0.40.0"
            )

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.client = AsyncAnthropic(api_key=self.api_key)
        self.model = model

        # Comparison metrics
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tool_uses = 0
        self._execution_count = 0

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Claude API with agentic loop.

        Args:
            task: Task to execute
            worktree_path: Path to isolated worktree

        Returns:
            ExecutionResult with exact token counts and cost
        """
        start_time = datetime.now()

        try:
            # Run agentic loop
            result = await self._agentic_loop(task, worktree_path)

            # Get modified files (reuse base class helper)
            files_modified = await self._get_modified_files(worktree_path)

            # Calculate exact cost
            cost = self._calculate_cost(
                result["total_input_tokens"],
                result["total_output_tokens"]
            )

            # Determine status (must have files modified to be success)
            # Similar to claude_code adapter: no files modified = false success
            if not files_modified:
                status = ExecutionStatus.FAILURE
                error_msg = "Task completed but no files were modified"
            else:
                status = ExecutionStatus.SUCCESS
                error_msg = None

            # Track metrics
            self.total_input_tokens += result["total_input_tokens"]
            self.total_output_tokens += result["total_output_tokens"]
            self.total_tool_uses += result["total_tool_uses"]
            self._execution_count += 1

            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=status,
                output=result["final_output"],
                error=result.get("error") or error_msg,
                files_modified=files_modified,
                cost=cost,
                duration=(datetime.now() - start_time).total_seconds()
            )

        except Exception as e:
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.FAILURE,
                output="",
                error=str(e),
                cost=0.0,
                duration=(datetime.now() - start_time).total_seconds()
            )

    async def _agentic_loop(
        self,
        task: TaskAssignment,
        worktree_path: Path,
        max_iterations: int = 20
    ) -> Dict[str, Any]:
        """
        Run agentic loop with tool use until task completion.

        Args:
            task: Task to execute
            worktree_path: Path to worktree
            max_iterations: Max conversation turns

        Returns:
            Dictionary with:
                - final_output: Last text output from Claude
                - total_input_tokens: Exact input token count
                - total_output_tokens: Exact output token count
                - total_tool_uses: Number of tool calls
                - iterations: Number of loop iterations
                - completed: Whether task completed successfully
                - error: Error message if failed
        """
        messages = [{"role": "user", "content": self._build_prompt(task, worktree_path)}]
        tool_uses = []
        total_input = 0
        total_output = 0
        final_text = ""

        for iteration in range(max_iterations):
            try:
                # Call Claude API with tools
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    tools=TOOLS,
                    messages=messages
                )

                # Track exact tokens
                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens

                # Extract text content
                text_content = self._extract_text(response)
                if text_content:
                    final_text = text_content

                # Check stop reason
                if response.stop_reason == "end_turn":
                    return {
                        "final_output": final_text,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                        "total_tool_uses": len(tool_uses),
                        "iterations": iteration + 1,
                        "completed": True
                    }

                # Execute tools
                has_tool_use = False
                tool_results = []

                for content in response.content:
                    if content.type == "tool_use":
                        has_tool_use = True
                        tool_uses.append(content.name)

                        result = await self._execute_tool(
                            content.name,
                            content.input,
                            worktree_path
                        )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": content.id,
                            "content": result
                        })

                if not has_tool_use:
                    # No more tools to execute
                    return {
                        "final_output": final_text,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                        "total_tool_uses": len(tool_uses),
                        "iterations": iteration + 1,
                        "completed": True
                    }

                # Continue conversation with tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            except Exception as e:
                return {
                    "final_output": final_text or "",
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_tool_uses": len(tool_uses),
                    "iterations": iteration + 1,
                    "completed": False,
                    "error": str(e)
                }

        # Max iterations reached
        return {
            "final_output": final_text or "Max iterations reached",
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tool_uses": len(tool_uses),
            "iterations": max_iterations,
            "completed": False,
            "error": "Max iterations reached without completion"
        }

    def _build_prompt(self, task: TaskAssignment, worktree_path: Path) -> str:
        """
        Build initial prompt for Claude.

        Args:
            task: Task assignment
            worktree_path: Path to worktree

        Returns:
            Prompt string
        """
        context_str = ""
        if task.context:
            context_str = "\n\nContext:\n" + "\n".join(
                f"- {k}: {v}" for k, v in task.context.items()
            )

        return f"""You are working in an isolated git worktree at: {worktree_path}

Task: {task.description}{context_str}

You have access to these tools:
- read_file: Read file contents
- write_file: Create or overwrite files
- bash: Execute bash commands

Complete the task by using these tools. When finished, provide a summary of what you did."""

    def _extract_text(self, response: Any) -> str:
        """
        Extract text content from API response.

        Args:
            response: Anthropic API response

        Returns:
            Concatenated text content
        """
        text_parts = []
        for content in response.content:
            if content.type == "text":
                text_parts.append(content.text)
        return "\n".join(text_parts)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        worktree_path: Path
    ) -> str:
        """
        Execute a tool call.

        Args:
            tool_name: Name of tool (read_file, write_file, bash)
            tool_input: Tool input parameters
            worktree_path: Path to worktree

        Returns:
            Tool result as string
        """
        try:
            if tool_name == "read_file":
                return await self._tool_read_file(tool_input, worktree_path)
            elif tool_name == "write_file":
                return await self._tool_write_file(tool_input, worktree_path)
            elif tool_name == "bash":
                return await self._tool_bash(tool_input, worktree_path)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    async def _tool_read_file(
        self, tool_input: Dict[str, Any], worktree_path: Path
    ) -> str:
        """Read file tool implementation."""
        path = tool_input.get("path", "")
        file_path = worktree_path / path

        if not file_path.exists():
            return f"Error: File not found: {path}"

        try:
            content = file_path.read_text()
            return f"File: {path}\n\n{content}"
        except Exception as e:
            return f"Error reading file: {str(e)}"

    async def _tool_write_file(
        self, tool_input: Dict[str, Any], worktree_path: Path
    ) -> str:
        """Write file tool implementation."""
        path = tool_input.get("path", "")
        content = tool_input.get("content", "")
        file_path = worktree_path / path

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            file_path.write_text(content)

            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    async def _tool_bash(
        self, tool_input: Dict[str, Any], worktree_path: Path
    ) -> str:
        """Bash command tool implementation."""
        command = tool_input.get("command", "")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                timeout=60  # 1 minute timeout for bash commands
            )

            output = f"Exit code: {result.returncode}\n"
            if result.stdout:
                output += f"stdout:\n{result.stdout}\n"
            if result.stderr:
                output += f"stderr:\n{result.stderr}\n"

            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (60s limit)"
        except Exception as e:
            return f"Error executing bash command: {str(e)}"

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate exact cost from API usage.

        Claude Sonnet 4.5 pricing (as of 2026-01-09):
        - Input: $3.00 / million tokens
        - Output: $15.00 / million tokens

        Args:
            input_tokens: Input token count
            output_tokens: Output token count

        Returns:
            Cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * 3.0
        output_cost = (output_tokens / 1_000_000) * 15.0
        return round(input_cost + output_cost, 4)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get adapter metrics for comparison.

        Returns:
            Dictionary with token and cost metrics
        """
        total_cost = self._calculate_cost(
            self.total_input_tokens,
            self.total_output_tokens
        )

        return {
            "adapter": self.cli_name,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_uses": self.total_tool_uses,
            "total_cost_usd": total_cost,
            "executions": self._execution_count
        }

    # Abstract methods from CLIAdapter (not used for API approach)
    def _construct_command(self, task: TaskAssignment, worktree_path: Path) -> List[str]:
        """Not used for API adapter."""
        return []

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """Not used for API adapter."""
        return {}
