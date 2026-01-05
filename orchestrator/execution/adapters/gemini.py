#!/usr/bin/env python3
"""
Gemini CLI Adapter
==================

Adapter for Google's Gemini CLI (gemini-cli or similar wrapper).

Gemini 2.0 Flash provides:
- Fast inference
- Low cost ($0.10-0.30 per task)
- Good for research and documentation
- Multimodal capabilities

Best for:
- Documentation generation
- Code research and analysis
- API documentation
- Test case generation
- Code review and suggestions

Cost Model: ~$0.15-0.30 per task (Gemini 2.0 Flash)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from .base import (
    CLIAdapter,
    TaskAssignment,
    ExecutionResult,
    ExecutionStatus,
    CLIExecutionError,
    CLINotFoundError,
    CLITimeoutError,
)


class GeminiAdapter(CLIAdapter):
    """
    Adapter for Gemini CLI.

    Uses Gemini 2.0 Flash for fast, cost-effective code tasks,
    particularly documentation and research.
    """

    def __init__(self, model: str = "gemini-2.0-flash"):
        """
        Initialize Gemini adapter.

        Args:
            model: Gemini model to use (default: gemini-2.0-flash)
        """
        super().__init__("gemini")
        self.model = model

    async def execute(
        self,
        task: TaskAssignment,
        worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Gemini CLI.

        Workflow:
        1. Build prompt with task and context
        2. Run Gemini CLI
        3. Parse response
        4. Apply changes if applicable

        Args:
            task: Task to execute
            worktree_path: Isolated worktree path

        Returns:
            ExecutionResult with status and output
        """
        from datetime import datetime
        import asyncio

        start_time = datetime.now()

        try:
            # Step 1: Run Gemini
            command = self._construct_command(task, worktree_path)
            stdout, stderr, returncode = await self._run_subprocess(
                command, worktree_path, task.timeout
            )

            # Step 2: Parse output
            parsed = self._parse_output(stdout, stderr)

            # Step 3: Apply changes if any code provided
            if parsed.get("code_changes"):
                await self._apply_changes(parsed, worktree_path)

            # Step 4: Get modified files
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
                retries=0
            )

        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.TIMEOUT,
                output="",
                error=f"Gemini execution timed out after {task.timeout}s",
                cost=0.0,
                duration=duration
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
                duration=duration
            )

    def _build_prompt(
        self,
        task: TaskAssignment,
        worktree_path: Path
    ) -> str:
        """
        Build prompt for Gemini.

        Args:
            task: Task to execute
            worktree_path: Worktree path

        Returns:
            Formatted prompt
        """
        prompt = f"""You are a helpful coding assistant working on a software development task.

Task: {task.description}

Context:
{json.dumps(task.context, indent=2)}

Please provide a solution with:
1. Analysis of what needs to be done
2. Code changes (if applicable) with file paths
3. Explanation of your approach
4. Any recommendations or considerations

Format code changes as:
```language
// FILE: path/to/file.ext
<code>
```
"""
        return prompt

    def _construct_command(
        self,
        task: TaskAssignment,
        worktree_path: Path
    ) -> List[str]:
        """
        Construct Gemini CLI command.

        Uses gemini CLI if available, or falls back to API call.

        Args:
            task: Task to execute
            worktree_path: Worktree path

        Returns:
            Command as list of strings
        """
        prompt = self._build_prompt(task, worktree_path)

        # Try gemini-cli first (if installed)
        # Format: gemini --model <model> --prompt "<prompt>"
        return [
            "gemini",
            "--model", self.model,
            "--prompt", prompt
        ]

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse Gemini output.

        Gemini outputs:
        - Analysis and recommendations
        - Code changes with file paths
        - Explanations

        Args:
            stdout: Standard output
            stderr: Standard error

        Returns:
            Parsed results
        """
        result = {
            "success": False,
            "analysis": "",
            "code_changes": [],
            "recommendations": [],
            "tokens_used": 0,
            "errors": []
        }

        # Extract code blocks with file paths
        # Format: // FILE: path\n```language\n<code>\n```
        file_pattern = r"//\s*FILE:\s*(.+?)\n```(?:\w+)?\n(.+?)\n```"
        matches = re.findall(file_pattern, stdout, re.DOTALL)

        for file_path, code in matches:
            result["code_changes"].append({
                "file": file_path.strip(),
                "code": code.strip()
            })

        # Extract analysis section
        analysis_match = re.search(r"Analysis:(.+?)(?:\n\n|Code:|$)", stdout, re.DOTALL)
        if analysis_match:
            result["analysis"] = analysis_match.group(1).strip()

        # Extract recommendations
        rec_pattern = r"(?:Recommendation|Consider|Note):\s*(.+)"
        rec_matches = re.findall(rec_pattern, stdout)
        result["recommendations"] = rec_matches

        # Extract token usage if provided
        token_pattern = r"Tokens:\s*(\d+)"
        token_match = re.search(token_pattern, stdout)
        if token_match:
            result["tokens_used"] = int(token_match.group(1))

        # Check for errors
        if stderr:
            result["errors"].append(stderr)

        # Consider success if we got analysis or code
        if result["analysis"] or result["code_changes"]:
            result["success"] = True

        return result

    async def _apply_changes(
        self,
        parsed: Dict[str, Any],
        worktree_path: Path
    ) -> None:
        """
        Apply code changes to worktree.

        Args:
            parsed: Parsed Gemini output
            worktree_path: Worktree path
        """
        import asyncio

        for change in parsed.get("code_changes", []):
            file_path = worktree_path / change["file"]

            # Create parent directories
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write code
            with open(file_path, "w") as f:
                f.write(change["code"])

        # Commit if changes made
        if parsed.get("code_changes"):
            message = f"Gemini: {parsed.get('analysis', 'Code changes')[:100]}"

            # Add all
            proc = await asyncio.create_subprocess_exec(
                "git", "add", ".",
                cwd=worktree_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

            # Commit
            proc = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", message,
                cwd=worktree_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """
        Estimate Gemini execution cost.

        Gemini 2.0 Flash pricing:
        - Input: $0.075/MTok (≤128K context)
        - Output: $0.30/MTok

        Typical task: 5K input + 1K output = ~$0.0007
        With overhead: ~$0.10-0.30 per task

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

            cost = (input_tokens / 1_000_000 * 0.075) + \
                   (output_tokens / 1_000_000 * 0.30)
            return round(cost, 3)

        # Fallback estimate
        if parsed_output.get("code_changes"):
            return 0.20  # More complex with code generation
        else:
            return 0.10  # Simple analysis/documentation

    def _get_env_vars(self) -> Dict[str, str]:
        """
        Get environment variables for Gemini.

        Returns:
            Environment variables including API key
        """
        import os
        env = os.environ.copy()

        # Gemini specific env vars
        if "GEMINI_API_KEY" not in env and "GOOGLE_API_KEY" not in env:
            print("Warning: GEMINI_API_KEY or GOOGLE_API_KEY not set")

        return env
