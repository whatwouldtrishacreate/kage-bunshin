#!/usr/bin/env python3
"""
Shared Context Store for CLI Council
====================================

Reduces context duplication across parallel CLI sessions by maintaining
a base context shared by all CLIs, with CLI-specific deltas.

Architecture:
- Base context: Shared foundation (~1200 tokens)
- Delta contexts: CLI-specific additions (~150-200 tokens each)
- Total reduction: 30-50% for 3+ CLIs

Example:
    Without SharedContextStore (3 CLIs):
    - CLI 1: 1200 tokens (full context)
    - CLI 2: 1200 tokens (full context)
    - CLI 3: 1200 tokens (full context)
    Total: 3600 tokens

    With SharedContextStore:
    - Base: 1200 tokens (shared)
    - CLI 1 delta: 150 tokens
    - CLI 2 delta: 200 tokens
    - CLI 3 delta: 100 tokens
    Total: 1650 tokens (54% reduction ✅)

File Structure:
    .cli-council/shared-context/{task_id}.json:
    {
        "task_id": "task-abc123",
        "base": {
            "description": "...",
            "files": [...],
            "patterns": {...}
        },
        "created_at": "2026-01-09T12:00:00Z",
        "estimated_tokens": 1200
    }

Usage:
    store = SharedContextStore(project_dir)

    # Create base context at task submission
    base = await store.create_base_context(task_id, full_context)

    # Get merged context for each CLI
    merged = await store.get_merged_context(task_id, cli_name, delta)
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SharedContextError(Exception):
    """Error during shared context operations."""
    pass


@dataclass
class SharedContext:
    """
    Shared base context for a task.

    Contains the foundation context shared across all CLIs,
    extracted from the full task context.
    """
    task_id: str
    base: Dict[str, Any]  # Shared foundation context
    created_at: str
    estimated_tokens: int

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class SharedContextStore:
    """
    Manages shared context storage and retrieval.

    Reduces context duplication by maintaining a base context
    shared across all CLIs, with CLI-specific deltas merged at runtime.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize shared context store.

        Args:
            project_dir: Project root directory
        """
        self.project_dir = project_dir
        self.shared_context_dir = project_dir / ".cli-council" / "shared-context"
        self.shared_context_dir.mkdir(parents=True, exist_ok=True)

    def _get_context_file_path(self, task_id: str) -> Path:
        """Get the path to a task's shared context file."""
        return self.shared_context_dir / f"{task_id}.json"

    def _estimate_tokens(self, data: Any) -> int:
        """
        Estimate tokens in data structure.

        Uses character-based approximation: tokens ≈ chars / 4

        Args:
            data: Data to estimate (dict, list, str, etc.)

        Returns:
            Estimated token count
        """
        if data is None:
            return 0

        # Convert to JSON string and count characters
        json_str = json.dumps(data, separators=(',', ':'))
        return len(json_str) // 4

    def _extract_base_context(self, full_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract shared base context from full context.

        Base context includes fields that are common across all CLIs:
        - Task description
        - File list (without CLI-specific filters)
        - Global patterns
        - Project structure

        CLI-specific fields (not in base):
        - CLI-specific instructions
        - CLI-specific file filters
        - CLI-specific constraints

        Args:
            full_context: Full context dictionary

        Returns:
            Base context dictionary
        """
        base = {}

        # Fields to include in base context (shared across CLIs)
        shared_fields = [
            "description",
            "files",
            "patterns",
            "project_structure",
            "task_id",
            "requirements",
            "constraints",
            "global_settings",
        ]

        for field in shared_fields:
            if field in full_context:
                base[field] = full_context[field]

        return base

    def _calculate_delta(
        self,
        full_context: Dict[str, Any],
        base_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate CLI-specific delta from full and base contexts.

        Delta = full_context - base_context (fields not in base)

        Args:
            full_context: Full context for a CLI
            base_context: Shared base context

        Returns:
            Delta context (CLI-specific fields only)
        """
        delta = {}

        for key, value in full_context.items():
            # Include if not in base, or if value differs from base
            if key not in base_context:
                delta[key] = value
            elif value != base_context.get(key):
                delta[key] = value

        return delta

    # ==================== Context Storage Operations ====================

    async def create_base_context(
        self,
        task_id: str,
        full_context: Dict[str, Any]
    ) -> SharedContext:
        """
        Create and store base context for a task.

        Extracts shared foundation from full context and saves it.

        Args:
            task_id: Task identifier
            full_context: Full context dictionary

        Returns:
            Created SharedContext object

        Raises:
            SharedContextError: If storage fails
        """
        # Extract base context
        base = self._extract_base_context(full_context)

        # Create shared context object
        shared_context = SharedContext(
            task_id=task_id,
            base=base,
            created_at=datetime.now().isoformat(),
            estimated_tokens=self._estimate_tokens(base)
        )

        # Save to file
        context_path = self._get_context_file_path(task_id)
        try:
            with open(context_path, 'w') as f:
                json.dump(asdict(shared_context), f, indent=2)
        except (IOError, OSError) as e:
            raise SharedContextError(
                f"Failed to save shared context for task {task_id}: {e}"
            )

        return shared_context

    async def get_base_context(self, task_id: str) -> Optional[SharedContext]:
        """
        Get the base context for a task.

        Args:
            task_id: Task identifier

        Returns:
            SharedContext if exists, None otherwise
        """
        context_path = self._get_context_file_path(task_id)
        if not context_path.exists():
            return None

        try:
            with open(context_path, 'r') as f:
                data = json.load(f)
            return SharedContext(**data)
        except (json.JSONDecodeError, IOError, TypeError) as e:
            print(f"Warning: Failed to read shared context for {task_id}: {e}")
            return None

    async def get_merged_context(
        self,
        task_id: str,
        cli_name: str,
        delta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge base context with CLI-specific delta.

        Loads base context and merges it with the delta to produce
        the full context for a specific CLI.

        Args:
            task_id: Task identifier
            cli_name: CLI name (for logging)
            delta: CLI-specific context delta

        Returns:
            Merged full context dictionary

        Raises:
            SharedContextError: If base context not found
        """
        # Load base context
        shared_context = await self.get_base_context(task_id)

        if not shared_context:
            raise SharedContextError(
                f"No base context found for task {task_id}"
            )

        # Merge base + delta
        merged = dict(shared_context.base)
        merged.update(delta)

        # Add metadata
        merged["_shared_context_metadata"] = {
            "cli_name": cli_name,
            "base_tokens": shared_context.estimated_tokens,
            "delta_tokens": self._estimate_tokens(delta),
            "merged_at": datetime.now().isoformat()
        }

        return merged

    async def get_delta_for_cli(
        self,
        task_id: str,
        full_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate delta by comparing full context to stored base.

        Useful when you have a full context and want to extract
        just the CLI-specific delta.

        Args:
            task_id: Task identifier
            full_context: Full context for a CLI

        Returns:
            Delta context (CLI-specific fields)

        Raises:
            SharedContextError: If base context not found
        """
        shared_context = await self.get_base_context(task_id)

        if not shared_context:
            raise SharedContextError(
                f"No base context found for task {task_id}"
            )

        return self._calculate_delta(full_context, shared_context.base)

    # ==================== Cleanup Operations ====================

    async def remove_context(self, task_id: str) -> None:
        """
        Remove shared context for a task.

        Args:
            task_id: Task identifier
        """
        context_path = self._get_context_file_path(task_id)
        if context_path.exists():
            context_path.unlink()

    async def cleanup_old_contexts(self, max_age_hours: int = 24) -> int:
        """
        Remove shared contexts older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of contexts removed
        """
        count = 0
        now = datetime.now()

        for context_file in self.shared_context_dir.glob("*.json"):
            try:
                task_id = context_file.stem
                shared_context = await self.get_base_context(task_id)

                if shared_context and shared_context.created_at:
                    created_at = datetime.fromisoformat(shared_context.created_at)
                    age_hours = (now - created_at).total_seconds() / 3600

                    if age_hours > max_age_hours:
                        await self.remove_context(task_id)
                        count += 1
            except Exception as e:
                # Skip files we can't process
                print(f"Warning: Failed to process {context_file}: {e}")
                continue

        return count

    # ==================== Statistics ====================

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about shared context usage.

        Returns:
            Statistics dictionary with counts and sizes
        """
        total_contexts = 0
        total_base_tokens = 0
        contexts = []

        for context_file in self.shared_context_dir.glob("*.json"):
            try:
                task_id = context_file.stem
                shared_context = await self.get_base_context(task_id)

                if shared_context:
                    total_contexts += 1
                    total_base_tokens += shared_context.estimated_tokens
                    contexts.append({
                        "task_id": task_id,
                        "base_tokens": shared_context.estimated_tokens,
                        "created_at": shared_context.created_at
                    })
            except Exception:
                continue

        return {
            "total_contexts": total_contexts,
            "total_base_tokens": total_base_tokens,
            "average_base_tokens": (
                total_base_tokens // total_contexts if total_contexts > 0 else 0
            ),
            "contexts": contexts
        }
