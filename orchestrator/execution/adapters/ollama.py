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

        # Verify Ollama is installed
        # This will be checked during first execution

    async def execute(
        self, task: TaskAssignment, worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Ollama.

        Workflow:
        1. Construct prompt with task description and context
        2. Run Ollama generate command
        3. Parse model output
        4. Apply code changes to worktree
        5. Verify and commit

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
            # Step 1: Construct prompt
            prompt = self._build_prompt(task, worktree_path)

            # Step 2: Run Ollama
            command = self._construct_command(task, worktree_path)
            stdout, stderr, returncode = await self._run_subprocess(
                command, worktree_path, task.timeout
            )

            # Step 3: Parse output
            parsed = self._parse_output(stdout, stderr)

            # Step 4: Apply code changes (if model provided them)
            await self._apply_changes(parsed, worktree_path)

            # Step 5: Get modified files and commits
            files_modified = await self._get_modified_files(worktree_path)
            commits = await self._get_commits(worktree_path)

            # Determine status
            if returncode == 0 and parsed.get("success", False):
                status = ExecutionStatus.SUCCESS
            elif returncode == 124:
                status = ExecutionStatus.TIMEOUT
            else:
                status = ExecutionStatus.FAILURE

            duration = (datetime.now() - start_time).total_seconds()

            # Update stats (cost is always $0 for local models)
            self._execution_count += 1

            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=status,
                output=stdout,
                error=stderr if status == ExecutionStatus.FAILURE else None,
                files_modified=files_modified,
                commits=commits,
                cost=0.0,  # Local execution = $0
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
                error=f"Ollama execution timed out after {task.timeout}s",
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

    def _build_prompt(self, task: TaskAssignment, worktree_path: Path) -> str:
        """
        Build prompt for Ollama model.

        Args:
            task: Task to execute
            worktree_path: Worktree path

        Returns:
            Formatted prompt string
        """
        prompt = f"""You are a coding assistant working on a development task.

Task: {task.description}

Context:
{json.dumps(task.context, indent=2)}

Please provide:
1. Code changes needed (with file paths)
2. Explanation of changes
3. Any potential issues or considerations

Format your response as:
```
FILE: <file_path>
<code changes>
```

Explanation: <explanation>
"""
        return prompt

    def _construct_command(
        self, task: TaskAssignment, worktree_path: Path
    ) -> List[str]:
        """
        Construct Ollama command.

        Args:
            task: Task to execute
            worktree_path: Worktree path

        Returns:
            Command as list of strings
        """
        prompt = self._build_prompt(task, worktree_path)

        return ["ollama", "run", self.model, prompt]

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse Ollama output.

        Ollama outputs:
        - Model response with code blocks
        - Explanations
        - File modifications

        Args:
            stdout: Standard output
            stderr: Standard error

        Returns:
            Parsed results with code changes
        """
        result = {"success": False, "code_changes": [], "explanation": "", "errors": []}

        # Extract code blocks with file paths
        # Format: FILE: <path>\n```\n<code>\n```
        file_pattern = r"FILE:\s*(.+?)\n```(?:\w+)?\n(.+?)\n```"
        matches = re.findall(file_pattern, stdout, re.DOTALL)

        for file_path, code in matches:
            result["code_changes"].append(
                {"file": file_path.strip(), "code": code.strip()}
            )

        # Extract explanation
        explanation_match = re.search(
            r"Explanation:\s*(.+?)(?:\n\n|\Z)", stdout, re.DOTALL
        )
        if explanation_match:
            result["explanation"] = explanation_match.group(1).strip()

        # Check for errors
        if stderr:
            result["errors"].append(stderr)

        # Consider success if we got code changes
        if result["code_changes"]:
            result["success"] = True

        return result

    async def _apply_changes(self, parsed: Dict[str, Any], worktree_path: Path) -> None:
        """
        Apply code changes to worktree files.

        Args:
            parsed: Parsed model output
            worktree_path: Worktree path
        """
        for change in parsed.get("code_changes", []):
            file_path = worktree_path / change["file"]

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write code to file
            with open(file_path, "w") as f:
                f.write(change["code"])

        # Commit changes if any
        if parsed.get("code_changes"):
            await self._commit_changes(
                worktree_path, f"Ollama: {parsed.get('explanation', 'Code changes')}"
            )

    async def _commit_changes(self, worktree_path: Path, message: str) -> None:
        """
        Commit changes in worktree.

        Args:
            worktree_path: Worktree path
            message: Commit message
        """
        import asyncio

        # Add all changes
        await asyncio.create_subprocess_exec(
            "git",
            "add",
            ".",
            cwd=worktree_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Commit
        await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            message,
            cwd=worktree_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate Ollama execution cost.

        Local execution = $0.00 always.

        Args:
            parsed_output: Parsed output (unused)

        Returns:
            0.0 (local execution is free)
        """
        return 0.0
