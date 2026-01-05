#!/usr/bin/env python3
"""
Layer 1 Context Manager for CLI Council
========================================

Lightweight file-based context sharing between parallel CLI sessions.

Context Layers (from Architecture Summary):
- Layer 1 (File-based): Minimal status updates (this module)
- Layer 2 (API): On-demand detailed context (future)
- Layer 3 (Checkpoints): Cross-session memory (future)

Layer 1 provides minimal "awareness" for parallel CLIs:
- What file is each CLI working on?
- What's their current status?
- When did they last update?

This prevents unnecessary conflicts and enables smart merge decisions.

File Structure:
    .cli-council/context/{session_id}.json:
    {
        "session_id": "session-abc123",
        "cli_name": "auto-claude",
        "task_id": "002-implement-memory",
        "current_file": "src/api.py",
        "status": "working",
        "last_update": "2026-01-04T12:30:00Z",
        "progress": "50%",
        "message": "Implementing authentication endpoint"
    }

Usage:
    ctx_mgr = ContextManager(project_dir)

    # Update context when starting work on a file
    await ctx_mgr.update_context(
        session=session,
        current_file="src/api.py",
        status="working",
        message="Implementing auth endpoint"
    )

    # Check what other CLIs are working on
    contexts = await ctx_mgr.get_all_contexts()
    for ctx in contexts:
        print(f"{ctx.cli_name} working on {ctx.current_file}")
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .worktree import SessionWorktree


class ContextError(Exception):
    """Error during context operations."""
    pass


@dataclass
class ContextFile:
    """
    Minimal context shared between CLI sessions.

    Represents the current state of a single CLI session.
    """
    session_id: str
    cli_name: str
    task_id: str
    current_file: Optional[str] = None  # File currently being modified
    status: str = "working"  # "working", "blocked", "done", "waiting"
    last_update: Optional[str] = None  # ISO timestamp
    progress: Optional[str] = None  # Optional progress indicator (e.g., "50%")
    message: Optional[str] = None  # Optional human-readable status message
    files_locked: List[str] = None  # Files this session has locked

    def __post_init__(self):
        if self.files_locked is None:
            self.files_locked = []
        if self.last_update is None:
            self.last_update = datetime.now().isoformat()


class ContextManager:
    """
    Layer 1: File-based context manager for minimal session awareness.

    Enables parallel CLIs to see what others are working on without
    expensive API calls or complex coordination.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.context_dir = project_dir / ".cli-council" / "context"
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def _get_context_file_path(self, session_id: str) -> Path:
        """Get the path to a session's context file."""
        return self.context_dir / f"{session_id}.json"

    # ==================== Context Update Operations ====================

    async def update_context(
        self,
        session: SessionWorktree,
        current_file: Optional[str] = None,
        status: str = "working",
        progress: Optional[str] = None,
        message: Optional[str] = None,
        files_locked: Optional[List[str]] = None,
    ) -> None:
        """
        Update a session's context file.

        Args:
            session: The session to update context for
            current_file: File currently being worked on
            status: Status ("working", "blocked", "done", "waiting")
            progress: Optional progress indicator
            message: Optional human-readable message
            files_locked: List of files currently locked by session
        """
        context = ContextFile(
            session_id=session.session_id,
            cli_name=session.cli_name,
            task_id=session.task_id,
            current_file=current_file,
            status=status,
            last_update=datetime.now().isoformat(),
            progress=progress,
            message=message,
            files_locked=files_locked or [],
        )

        context_path = self._get_context_file_path(session.session_id)
        with open(context_path, "w") as f:
            json.dump(asdict(context), f, indent=2)

    async def mark_done(self, session: SessionWorktree, message: Optional[str] = None) -> None:
        """
        Mark a session as done.

        Args:
            session: The session that completed
            message: Optional completion message
        """
        await self.update_context(
            session=session,
            status="done",
            message=message or "Session completed successfully",
        )

    async def mark_blocked(
        self, session: SessionWorktree, reason: str, blocked_on: Optional[str] = None
    ) -> None:
        """
        Mark a session as blocked.

        Args:
            session: The session that is blocked
            reason: Why the session is blocked
            blocked_on: Optional file or resource blocking progress
        """
        message = f"Blocked: {reason}"
        if blocked_on:
            message += f" (waiting for {blocked_on})"

        await self.update_context(
            session=session,
            status="blocked",
            message=message,
        )

    async def remove_context(self, session_id: str) -> None:
        """
        Remove a session's context file (e.g., on cleanup).

        Args:
            session_id: Session identifier
        """
        context_path = self._get_context_file_path(session_id)
        if context_path.exists():
            context_path.unlink()

    # ==================== Context Query Operations ====================

    async def get_context(self, session_id: str) -> Optional[ContextFile]:
        """
        Get the context for a specific session.

        Args:
            session_id: Session identifier

        Returns:
            ContextFile if exists, None otherwise
        """
        context_path = self._get_context_file_path(session_id)
        if not context_path.exists():
            return None

        try:
            with open(context_path, "r") as f:
                data = json.load(f)
            return ContextFile(**data)
        except (json.JSONDecodeError, IOError, TypeError) as e:
            print(f"Warning: Failed to read context for {session_id}: {e}")
            return None

    async def get_all_contexts(self) -> List[ContextFile]:
        """
        Get contexts for all active sessions.

        Returns:
            List of ContextFile objects
        """
        contexts = []
        for context_file in self.context_dir.glob("*.json"):
            session_id = context_file.stem
            context = await self.get_context(session_id)
            if context:
                contexts.append(context)
        return contexts

    async def get_contexts_by_status(self, status: str) -> List[ContextFile]:
        """
        Get all sessions with a specific status.

        Args:
            status: Status to filter by ("working", "blocked", "done", "waiting")

        Returns:
            List of matching ContextFile objects
        """
        all_contexts = await self.get_all_contexts()
        return [ctx for ctx in all_contexts if ctx.status == status]

    async def get_contexts_by_task(self, task_id: str) -> List[ContextFile]:
        """
        Get all sessions working on a specific task.

        Args:
            task_id: Task identifier

        Returns:
            List of ContextFile objects for this task
        """
        all_contexts = await self.get_all_contexts()
        return [ctx for ctx in all_contexts if ctx.task_id == task_id]

    # ==================== Conflict Detection ====================

    async def find_file_conflicts(self, file_path: str) -> List[ContextFile]:
        """
        Find sessions currently working on a file.

        Args:
            file_path: Path to check

        Returns:
            List of sessions working on this file
        """
        all_contexts = await self.get_all_contexts()
        return [
            ctx
            for ctx in all_contexts
            if ctx.current_file == file_path and ctx.status == "working"
        ]

    async def find_lock_conflicts(self, file_path: str) -> List[ContextFile]:
        """
        Find sessions that have locked a file.

        Args:
            file_path: Path to check

        Returns:
            List of sessions with locks on this file
        """
        all_contexts = await self.get_all_contexts()
        return [
            ctx
            for ctx in all_contexts
            if file_path in (ctx.files_locked or [])
        ]

    async def get_stale_contexts(self, timeout_minutes: int = 30) -> List[ContextFile]:
        """
        Find contexts that haven't updated recently (possible dead sessions).

        Args:
            timeout_minutes: Minutes of inactivity to consider stale

        Returns:
            List of stale contexts
        """
        stale = []
        now = datetime.now()

        for context in await self.get_all_contexts():
            if context.last_update:
                last_update = datetime.fromisoformat(context.last_update)
                age_minutes = (now - last_update).total_seconds() / 60
                if age_minutes > timeout_minutes:
                    stale.append(context)

        return stale

    # ==================== Summary & Statistics ====================

    async def get_task_summary(self, task_id: str) -> Dict[str, Any]:
        """
        Get a summary of all sessions working on a task.

        Args:
            task_id: Task identifier

        Returns:
            Summary dictionary with counts and session info
        """
        contexts = await self.get_contexts_by_task(task_id)

        return {
            "task_id": task_id,
            "total_sessions": len(contexts),
            "by_status": {
                "working": len([c for c in contexts if c.status == "working"]),
                "blocked": len([c for c in contexts if c.status == "blocked"]),
                "done": len([c for c in contexts if c.status == "done"]),
                "waiting": len([c for c in contexts if c.status == "waiting"]),
            },
            "by_cli": {
                cli: len([c for c in contexts if c.cli_name == cli])
                for cli in set(c.cli_name for c in contexts)
            },
            "sessions": [
                {
                    "session_id": ctx.session_id,
                    "cli_name": ctx.cli_name,
                    "status": ctx.status,
                    "current_file": ctx.current_file,
                    "message": ctx.message,
                }
                for ctx in contexts
            ],
        }

    async def get_global_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all active sessions across all tasks.

        Returns:
            Global summary with statistics
        """
        all_contexts = await self.get_all_contexts()

        return {
            "total_sessions": len(all_contexts),
            "by_status": {
                "working": len([c for c in all_contexts if c.status == "working"]),
                "blocked": len([c for c in all_contexts if c.status == "blocked"]),
                "done": len([c for c in all_contexts if c.status == "done"]),
                "waiting": len([c for c in all_contexts if c.status == "waiting"]),
            },
            "by_cli": {
                cli: len([c for c in all_contexts if c.cli_name == cli])
                for cli in set(c.cli_name for c in all_contexts)
            },
            "by_task": {
                task: len([c for c in all_contexts if c.task_id == task])
                for task in set(c.task_id for c in all_contexts)
            },
        }

    # ==================== Cleanup ====================

    async def cleanup_stale_contexts(self, timeout_minutes: int = 30) -> int:
        """
        Remove stale context files from dead sessions.

        Args:
            timeout_minutes: Minutes of inactivity to consider stale

        Returns:
            Number of contexts removed
        """
        stale = await self.get_stale_contexts(timeout_minutes)
        count = 0

        for context in stale:
            await self.remove_context(context.session_id)
            count += 1

        return count

    async def cleanup_done_contexts(self) -> int:
        """
        Remove contexts for completed sessions.

        Returns:
            Number of contexts removed
        """
        done = await self.get_contexts_by_status("done")
        count = 0

        for context in done:
            await self.remove_context(context.session_id)
            count += 1

        return count
