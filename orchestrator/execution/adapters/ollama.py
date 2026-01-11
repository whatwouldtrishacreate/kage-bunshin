#!/usr/bin/env python3
"""
Ollama HTTP API Adapter
=======================

Adapter for Ollama local LLM execution using HTTP API.

Migrated from CLI subprocess to HTTP API for:
- No spinner/ANSI display bugs
- Better error handling
- Streaming support
- More reliable output parsing

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

import asyncio
import json
import logging
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Any

from .base import (
    CLIAdapter,
    TaskAssignment,
    ExecutionResult,
    ExecutionStatus,
)

# Configure logging
logger = logging.getLogger(__name__)


class OllamaAdapter(CLIAdapter):
    """
    Adapter for Ollama local LLM execution via HTTP API.

    Uses Ollama's REST API instead of CLI for more reliable operation.
    """

    def __init__(
        self,
        model: str = "qwen2.5-coder:32b",
        host: str = None,
        timeout: int = 300,
        stream: bool = False
    ):
        """
        Initialize Ollama adapter.

        Args:
            model: Ollama model to use (default: qwen2.5-coder:32b)
            host: Ollama API host (default: from OLLAMA_HOST env or http://localhost:11434)
            timeout: Request timeout in seconds (default: 300)
            stream: Enable streaming responses (default: False)
        """
        super().__init__("ollama")
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.timeout = timeout
        self.stream = stream

        # Ensure host doesn't end with slash
        self.host = self.host.rstrip("/")

    def _check_availability(self) -> bool:
        """
        Check if Ollama API is available.

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            req = urllib.request.Request(
                f"{self.host}/api/tags",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    def _list_models(self) -> List[str]:
        """
        List available models on Ollama server.

        Returns:
            List of model names
        """
        try:
            req = urllib.request.Request(
                f"{self.host}/api/tags",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _generate(
        self,
        prompt: str,
        system: str = None,
        timeout: int = None
    ) -> Dict[str, Any]:
        """
        Generate completion using Ollama HTTP API.

        Args:
            prompt: The prompt to send
            system: Optional system prompt
            timeout: Request timeout (uses self.timeout if not specified)

        Returns:
            API response as dictionary
        """
        url = f"{self.host}/api/generate"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        request_timeout = timeout or self.timeout

        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            raise RuntimeError(f"Ollama HTTP Error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama API unreachable at {self.host}: {e.reason}")
        except TimeoutError:
            raise TimeoutError(f"Ollama request timed out after {request_timeout}s")

    async def execute(
        self,
        task: TaskAssignment,
        worktree_path: Path
    ) -> ExecutionResult:
        """
        Execute task using Ollama HTTP API.

        Args:
            task: Task to execute
            worktree_path: Isolated worktree path

        Returns:
            ExecutionResult with status and output
        """
        from datetime import datetime

        start_time = datetime.now()

        try:
            # Check API availability
            if not self._check_availability():
                return ExecutionResult(
                    task_id=task.task_id,
                    cli_name=self.cli_name,
                    status=ExecutionStatus.FAILURE,
                    output="",
                    error=f"Ollama API not available at {self.host}",
                    cost=0.0,
                    duration=0.0
                )

            # Build prompt
            prompt = self._build_prompt(task, worktree_path)
            system = self._build_system_prompt()

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._generate(prompt, system, task.timeout)
            )

            # Extract response text
            output = response.get("response", "")

            # Parse output
            parsed = self._parse_output(output, "")

            # Apply code changes (if model provided them)
            await self._apply_changes(parsed, worktree_path)

            # Determine status
            if parsed.get("success", False):
                status = ExecutionStatus.SUCCESS
            else:
                status = ExecutionStatus.FAILURE

            duration = (datetime.now() - start_time).total_seconds()
            self._execution_count += 1

            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=status,
                output=output,
                error=None if status == ExecutionStatus.SUCCESS else (parsed.get("errors", ["Unknown error"])[0] if parsed.get("errors") else None),
                files_modified=await self._get_modified_files(worktree_path),
                commits=await self._get_commits(worktree_path),
                cost=0.0,
                duration=duration,
                retries=0
            )

        except TimeoutError as e:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.TIMEOUT,
                output="",
                error=str(e),
                cost=0.0,
                duration=duration
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.exception(f"Ollama execution failed: {e}")
            return ExecutionResult(
                task_id=task.task_id,
                cli_name=self.cli_name,
                status=ExecutionStatus.FAILURE,
                output="",
                error=str(e),
                cost=0.0,
                duration=duration
            )

    def _build_system_prompt(self) -> str:
        """Build system prompt for code generation."""
        return """You are a skilled software developer. When given a coding task:
1. Analyze the requirements carefully
2. Provide clean, well-documented code
3. Format code changes with file paths

For each file you modify or create, use this exact format:
FILE: <file_path>
```<language>
<code>
```

After all code changes, provide:
Explanation: <brief explanation of changes>

Be concise and focus on working code."""

    def _build_prompt(self, task: TaskAssignment, worktree_path: Path) -> str:
        """Build prompt for Ollama model."""
        context_str = ""
        if task.context:
            context_str = f"\nContext:\n{json.dumps(task.context, indent=2)}"

        return f"""Task: {task.description}
{context_str}

Working directory: {worktree_path}

Please provide the code changes needed to complete this task."""

    def _construct_command(self, task: TaskAssignment, worktree_path: Path) -> List[str]:
        """Construct CLI command (not used - HTTP API adapter)."""
        return []

    def _parse_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """Parse Ollama output to extract code changes."""
        output = stdout
        result = {
            "success": False,
            "code_changes": [],
            "explanation": "",
            "errors": []
        }

        if not output:
            result["errors"].append("Empty response from model")
            return result

        # Pattern 1: FILE: <path>\n```<lang>\n<code>\n```
        file_pattern = r"FILE:\s*(.+?)\n```(?:\w+)?\n(.+?)\n```"
        matches = re.findall(file_pattern, output, re.DOTALL)

        # Pattern 2: file `filename.py` followed by code block
        if not matches:
            file_pattern2 = r"(?:file[:\s]+`?|Here is[^`]*`?)([a-zA-Z0-9_\-./]+\.(?:py|js|ts|go|rs|java|c|cpp|h|hpp|rb|php|sh|yaml|yml|json|toml|md))`?[^`]*```(?:\w+)?\n(.+?)```"
            matches = re.findall(file_pattern2, output, re.DOTALL | re.IGNORECASE)

        # Pattern 3: Any code block with nearby filename
        if not matches:
            code_blocks = re.findall(r"```(?:\w+)?\n(.+?)```", output, re.DOTALL)
            file_mentions = re.findall(r"`([a-zA-Z0-9_\-./]+\.(?:py|js|ts|go|rs|java|c|cpp|h|hpp|rb|php|sh))`", output)
            if code_blocks and file_mentions:
                matches = [(file_mentions[0], code_blocks[0])]

        for file_path, code in matches:
            result["code_changes"].append({
                "file": file_path.strip(),
                "code": code.strip()
            })

        # Extract explanation
        explanation_match = re.search(r"Explanation:\s*(.+?)(?:\n\n|\Z)", output, re.DOTALL)
        if explanation_match:
            result["explanation"] = explanation_match.group(1).strip()

        if result["code_changes"] or result["explanation"]:
            result["success"] = True

        return result

    async def _apply_changes(self, parsed: Dict[str, Any], worktree_path: Path) -> None:
        """Apply code changes to worktree files."""
        for change in parsed.get("code_changes", []):
            file_path = worktree_path / change["file"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w") as f:
                f.write(change["code"])

        if parsed.get("code_changes"):
            await self._commit_changes(
                worktree_path,
                f"Ollama: {parsed.get('explanation', 'Code changes')[:50]}"
            )

    async def _commit_changes(self, worktree_path: Path, message: str) -> None:
        """Commit changes in worktree."""
        await asyncio.create_subprocess_exec(
            "git", "add", ".",
            cwd=worktree_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            cwd=worktree_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )

    async def _get_modified_files(self, worktree_path: Path) -> List[str]:
        """Get list of modified files in worktree."""
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD~1",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        if stdout:
            return stdout.decode().strip().split("\n")
        return []

    async def _get_commits(self, worktree_path: Path, base_branch: str = "main") -> List[str]:
        """Get list of commits made in this session."""
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--oneline", "-5",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        if stdout:
            return [line.split()[0] for line in stdout.decode().strip().split("\n") if line]
        return []

    def _estimate_cost(self, parsed_output: Dict[str, Any]) -> float:
        """Local execution = $0.00 always."""
        return 0.0
