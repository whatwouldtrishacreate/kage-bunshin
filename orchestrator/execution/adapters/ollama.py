#!/usr/bin/env python3
"""
Ollama CLI Adapter
==================

Adapter for Ollama local LLM execution using Qwen 2.5 Coder.

Ollama provides local model inference on RTX 4090, enabling:
- Zero API cost ($0.00 per execution)
- Fast local execution
- Good for simple, well-defined tasks

Recommended for:
- Simple bug fixes
- Documentation updates
- Code formatting
- Unit test generation
- Repetitive refactoring

Model: Qwen 2.5 Coder (32B or 14B depending on VRAM)
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from .base import (
    CLIAdapter,
    ExecutionResult,
    ExecutionStatus,
    TaskAssignment,
)

# Configure logging
logger = logging.getLogger(__name__)


class OllamaAdapter(CLIAdapter):
    """
    Adapter for Ollama local LLM execution.

    Uses Qwen 2.5 Coder model running on local RTX 4090 for
    cost-free code generation.
    """

    def __init__(self, model: str = "qwen2.5-coder:32b"):
        """
        Initialize Ollama adapter.

        Args:
            model: Ollama model to use (default: qwen2.5-coder:32b)
        """
        super().__init__("ollama")
        self.model = model

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Ollama.

        Workflow:
        1. Construct simple prompt with task description
        2. Run Ollama with the model
        3. Parse and clean model output
        4. Save output to file in worktree
        5. Commit changes

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
            # Step 1: Construct command (simple prompt, just like direct testing)
            command = self._construct_command(task, worktree_path)
            logger.info(f"Executing Ollama command: {' '.join(command[:3])}... (prompt length: {len(command[3])} chars)")

            # Step 2: Run Ollama
            stdout, stderr, returncode = await self._run_subprocess(
                command, worktree_path, task.timeout
            )

            logger.info(f"Ollama completed: returncode={returncode}, stdout_length={len(stdout)}, stderr_length={len(stderr)}")

            # Step 3: Clean output (remove ANSI codes)
            clean_output = self._strip_ansi_codes(stdout)
            logger.debug(f"Cleaned output (first 200 chars): {clean_output[:200]}")

            # Step 4: Parse output
            parsed = self._parse_output(clean_output, stderr)
            logger.info(f"Parsed result: success={parsed.get('success')}, has_code={bool(parsed.get('code_content'))}")

            # Step 5: Save output to file
            if parsed.get("code_content") or clean_output.strip():
                await self._save_output(task, clean_output, worktree_path)
                files_modified = await self._get_modified_files(worktree_path)
                commits = await self._get_commits(worktree_path)
            else:
                files_modified = []
                commits = []

            # Determine status
            if returncode == 0 and (parsed.get("success") or clean_output.strip()):
                status = ExecutionStatus.SUCCESS
            elif returncode == 124:
                status = ExecutionStatus.TIMEOUT
            else:
                status = ExecutionStatus.FAILURE

            duration = (datetime.now() - start_time).total_seconds()

            # Update stats
            self._execution_count += 1

            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=status,
                output=clean_output,
                error=stderr if status == ExecutionStatus.FAILURE else None,
                files_modified=files_modified,
                commits=commits,
                cost=0.0,  # Local execution = $0
                duration=duration,
                retries=0,
            )

        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Ollama execution timed out after {task.timeout}s")
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.TIMEOUT,
                output="",
                error=f"Ollama execution timed out after {task.timeout}s",
                cost=0.0,
                duration=duration,
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.exception(f"Ollama execution failed with exception: {e}")
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.FAILURE,
                output="",
                error=str(e),
                cost=0.0,
                duration=duration,
            )

    def _construct_command(
        self, task: TaskAssignment, worktree_path: Path
    ) -> List[str]:
        """
        Construct Ollama command.

        Uses simple prompt format that worked in direct testing.

        Args:
            task: Task to execute
            worktree_path: Worktree path (unused - required by base class)

        Returns:
            Command as list of strings
        """
        # Simple prompt - just the task description, like direct testing
        prompt = task.description

        # Add context if provided
        if task.context and task.context.get("files"):
            prompt += f"\n\nContext files: {', '.join(task.context['files'])}"

        return ["ollama", "run", self.model, prompt]

    def _strip_ansi_codes(self, text: str) -> str:
        """
        Strip ANSI escape codes from text.

        Ollama outputs spinner animations and formatting codes
        that need to be removed.

        Args:
            text: Text with ANSI codes

        Returns:
            Clean text without ANSI codes
        """
        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse Ollama output.

        More flexible parsing that handles various output formats.

        Args:
            stdout: Cleaned standard output
            stderr: Standard error

        Returns:
            Parsed results
        """
        result = {
            "success": False,
            "code_content": "",
            "explanation": "",
            "errors": []
        }

        # Check for errors in stderr
        if stderr and not stderr.strip().startswith("time="):
            # Ignore Ollama timing logs in stderr
            result["errors"].append(stderr)

        # Extract any code blocks (markdown format)
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', stdout, re.DOTALL)
        if code_blocks:
            result["code_content"] = "\n\n".join(code_blocks)
            result["success"] = True
            logger.info(f"Found {len(code_blocks)} code blocks")
        elif stdout.strip():
            # If no code blocks but we have output, consider it success
            result["code_content"] = stdout.strip()
            result["success"] = True
            logger.info("No code blocks found, using full output")

        return result

    async def _save_output(
        self, task: TaskAssignment, output: str, worktree_path: Path
    ) -> None:
        """
        Save Ollama output to file in worktree.

        Args:
            task: The task that was executed
            output: The model output
            worktree_path: Worktree path
        """
        # Save to ollama_output.txt or task-specific file
        output_file = worktree_path / f"ollama_result_{task.task_id[:8]}.md"

        with open(output_file, "w") as f:
            f.write(f"# Ollama Result\n\n")
            f.write(f"**Task:** {task.description}\n\n")
            f.write(f"**Model:** {self.model}\n\n")
            f.write(f"## Output\n\n")
            f.write(output)

        # Commit the result
        await self._commit_changes(
            worktree_path,
            f"Ollama ({self.model}): {task.description[:50]}"
        )

        logger.info(f"Saved Ollama output to {output_file}")

    async def _commit_changes(self, worktree_path: Path, message: str) -> None:
        """
        Commit changes in worktree.

        Args:
            worktree_path: Worktree path
            message: Commit message
        """
        import asyncio

        # Add all changes
        proc = await asyncio.create_subprocess_exec(
            "git",
            "add",
            ".",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Commit
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            message,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        logger.debug(f"Committed changes: {message}")

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate Ollama execution cost.

        Local execution = $0.00 always.

        Args:
            parsed_output: Parsed output (unused - required by base class)

        Returns:
            0.0 (local execution is free)
        """
        return 0.0
