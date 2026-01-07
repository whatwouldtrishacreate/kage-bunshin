#!/usr/bin/env python3
"""
3-Layer Lock Manager for CLI Council
=====================================

Prevents race conditions during parallel CLI execution with three defense layers:

Layer 1: OS-Level File Locks (fcntl)
- Per-file locking using OS primitives
- Atomic lock acquisition
- Automatically released on process death

Layer 2: Ownership Registry
- In-memory tracking of file ownership
- Maps files → sessions for conflict detection
- Enables deadlock detection

Layer 3: Merge Coordination
- Prevents conflicting simultaneous merges
- Serializes merge operations across sessions
- Ensures atomic merge-to-base operations

Usage:
    lock_mgr = LockManager()

    # Acquire lock on file for session
    if await lock_mgr.acquire_file_lock(session, Path("src/api.py")):
        # Safe to modify file
        ...
        await lock_mgr.release_file_lock(session, Path("src/api.py"))
"""

import asyncio
import fcntl
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .worktree import SessionWorktree


class LockError(Exception):
    """Error during lock operations."""

    pass


@dataclass
class LockInfo:
    """Information about a file lock."""

    session_id: str
    cli_name: str
    file_path: Path
    lock_fd: int  # File descriptor
    acquired_at: datetime
    lock_type: str = "file"  # "file" or "merge"


class LockManager:
    """
    3-layer lock manager for safe parallel CLI execution.

    Coordinates file access across multiple CLI sessions to prevent:
    - Race conditions (concurrent file modifications)
    - Merge conflicts (simultaneous merge operations)
    - Deadlocks (circular wait conditions)
    """

    def __init__(self, project_dir: Optional[Path] = None):
        # Layer 2: Ownership Registry
        # Maps file path → LockInfo
        self.file_locks: Dict[str, LockInfo] = {}

        # Maps session_id → set of locked file paths
        self.session_locks: Dict[str, Set[str]] = defaultdict(set)

        # Layer 3: Merge Coordination
        self.merge_lock = asyncio.Lock()
        self.active_merge: Optional[str] = None  # session_id currently merging

        # File descriptor tracking for cleanup
        self._lock_fds: Dict[str, int] = {}  # file_path → fd

        # Centralized lock directory (shared across all sessions)
        self.project_dir = project_dir or Path.cwd()
        self.locks_dir = self.project_dir / ".cli-council" / "locks"
        self.locks_dir.mkdir(parents=True, exist_ok=True)

    # ==================== Layer 1: fcntl File Locks ====================

    async def acquire_file_lock(
        self, session: SessionWorktree, file_path: Path, timeout: float = 5.0
    ) -> bool:
        """
        Acquire OS-level fcntl lock on a file.

        Args:
            session: The session requesting the lock
            file_path: Path to file (relative to project root)
            timeout: Maximum seconds to wait for lock

        Returns:
            True if lock acquired, False if timeout

        Raises:
            LockError: If lock is held by same session (deadlock prevention)
        """
        file_key = str(file_path)

        # Check if we already own this lock
        if file_key in self.file_locks:
            existing_lock = self.file_locks[file_key]
            if existing_lock.session_id == session.session_id:
                raise LockError(
                    f"Session {session.session_id} already owns lock on {file_path}"
                )

        # Create lock file in centralized locks directory (shared across sessions)
        # Use sanitized file path to avoid directory traversal
        sanitized_name = str(file_path).replace("/", "_").replace("\\", "_")
        lock_file = self.locks_dir / f"{sanitized_name}.lock"

        # Try to acquire fcntl lock with timeout
        start_time = datetime.now()
        fd = None

        while (datetime.now() - start_time).total_seconds() < timeout:
            # Layer 2 check: If lock is already registered to another session, wait
            if file_key in self.file_locks:
                await asyncio.sleep(0.1)
                continue

            try:
                fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Success! Register in Layer 2
                lock_info = LockInfo(
                    session_id=session.session_id,
                    cli_name=session.cli_name,
                    file_path=file_path,
                    lock_fd=fd,
                    acquired_at=datetime.now(),
                    lock_type="file",
                )

                self.file_locks[file_key] = lock_info
                self.session_locks[session.session_id].add(file_key)
                self._lock_fds[file_key] = fd

                return True

            except BlockingIOError:
                # Lock held by another process, wait and retry
                if fd is not None:
                    os.close(fd)
                    fd = None
                await asyncio.sleep(0.1)

            except Exception as e:
                if fd is not None:
                    os.close(fd)
                raise LockError(f"Failed to acquire lock on {file_path}: {e}")

        # Timeout - clean up if needed
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass  # Already closed
        return False

    async def release_file_lock(
        self, session: SessionWorktree, file_path: Path
    ) -> bool:
        """
        Release fcntl lock on a file.

        Args:
            session: The session releasing the lock
            file_path: Path to file

        Returns:
            True if lock released, False if not owned
        """
        file_key = str(file_path)

        if file_key not in self.file_locks:
            return False

        lock_info = self.file_locks[file_key]

        # Verify ownership
        if lock_info.session_id != session.session_id:
            raise LockError(
                f"Session {session.session_id} does not own lock on {file_path} "
                f"(owned by {lock_info.session_id})"
            )

        # Release fcntl lock
        try:
            fcntl.flock(lock_info.lock_fd, fcntl.LOCK_UN)
            os.close(lock_info.lock_fd)
        except OSError:
            pass  # Already closed

        # Remove from registry
        del self.file_locks[file_key]
        self.session_locks[session.session_id].discard(file_key)
        if file_key in self._lock_fds:
            del self._lock_fds[file_key]

        return True

    async def release_all_session_locks(self, session: SessionWorktree) -> int:
        """
        Release all locks held by a session.

        Args:
            session: The session to release locks for

        Returns:
            Number of locks released
        """
        session_files = list(self.session_locks.get(session.session_id, set()))
        count = 0

        for file_key in session_files:
            if await self.release_file_lock(session, Path(file_key)):
                count += 1

        # Clean up session entry
        if session.session_id in self.session_locks:
            del self.session_locks[session.session_id]

        return count

    # ==================== Layer 2: Ownership Registry ====================

    def get_file_owner(self, file_path: Path) -> Optional[LockInfo]:
        """
        Get the current owner of a file lock.

        Args:
            file_path: Path to file

        Returns:
            LockInfo if file is locked, None otherwise
        """
        return self.file_locks.get(str(file_path))

    def get_session_locks(self, session_id: str) -> List[LockInfo]:
        """
        Get all locks held by a session.

        Args:
            session_id: Session identifier

        Returns:
            List of LockInfo for all locks held
        """
        locks = []
        for file_key in self.session_locks.get(session_id, set()):
            if file_key in self.file_locks:
                locks.append(self.file_locks[file_key])
        return locks

    def detect_deadlock_risk(
        self, session_id: str, requested_files: List[Path]
    ) -> Optional[str]:
        """
        Detect potential deadlock scenarios.

        Simple deadlock detection: Check if requesting files locked by
        sessions that are waiting for files we own.

        Args:
            session_id: Session requesting locks
            requested_files: Files being requested

        Returns:
            Warning message if deadlock risk detected, None otherwise
        """
        our_files = self.session_locks.get(session_id, set())

        for file_path in requested_files:
            file_key = str(file_path)
            if file_key in self.file_locks:
                owner = self.file_locks[file_key]
                owner_files = self.session_locks.get(owner.session_id, set())

                # Check if owner has any of our files
                if our_files & owner_files:
                    return (
                        f"Deadlock risk: {session_id} wants {file_path} "
                        f"from {owner.session_id}, but they both hold locks"
                    )

        return None

    # ==================== Layer 3: Merge Coordination ====================

    async def acquire_merge_lock(
        self, session: SessionWorktree, timeout: float = 30.0
    ) -> bool:
        """
        Acquire exclusive merge lock to prevent simultaneous merges.

        Only one session can merge at a time to prevent conflicts.

        Args:
            session: Session requesting merge
            timeout: Maximum seconds to wait

        Returns:
            True if lock acquired, False if timeout
        """
        try:
            await asyncio.wait_for(self.merge_lock.acquire(), timeout=timeout)
            self.active_merge = session.session_id
            return True
        except asyncio.TimeoutError:
            return False

    def release_merge_lock(self, session: SessionWorktree) -> None:
        """
        Release exclusive merge lock.

        Args:
            session: Session releasing merge lock

        Raises:
            LockError: If session doesn't own merge lock
        """
        if self.active_merge != session.session_id:
            raise LockError(
                f"Session {session.session_id} does not own merge lock "
                f"(owned by {self.active_merge})"
            )

        self.active_merge = None
        try:
            self.merge_lock.release()
        except RuntimeError:
            pass  # Lock already released

    def is_merge_in_progress(self) -> bool:
        """Check if any session is currently performing a merge."""
        return self.active_merge is not None

    # ==================== Utilities ====================

    def get_lock_stats(self) -> Dict[str, any]:
        """
        Get statistics about current locks.

        Returns:
            Dict with lock statistics
        """
        return {
            "total_file_locks": len(self.file_locks),
            "active_sessions": len([s for s in self.session_locks.values() if s]),
            "merge_in_progress": self.is_merge_in_progress(),
            "active_merge_session": self.active_merge,
        }

    def get_detailed_status(self) -> Dict[str, any]:
        """
        Get detailed status of all locks for debugging.

        Returns:
            Detailed lock status information
        """
        return {
            "file_locks": {
                file_key: {
                    "session_id": lock.session_id,
                    "cli_name": lock.cli_name,
                    "acquired_at": lock.acquired_at.isoformat(),
                }
                for file_key, lock in self.file_locks.items()
            },
            "session_locks": {
                session_id: list(files)
                for session_id, files in self.session_locks.items()
            },
            "merge_status": {
                "locked": self.is_merge_in_progress(),
                "active_session": self.active_merge,
            },
        }

    async def cleanup_stale_locks(self) -> int:
        """
        Clean up locks from dead processes.

        Attempts to acquire each lock non-blocking. If successful,
        the lock was stale (process died without cleanup).

        Returns:
            Number of stale locks cleaned
        """
        cleaned = 0
        stale_files = []

        for file_key, lock_info in list(self.file_locks.items()):
            try:
                # Try to acquire - if successful, lock was stale
                fcntl.flock(lock_info.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock_info.lock_fd, fcntl.LOCK_UN)
                os.close(lock_info.lock_fd)
                stale_files.append(file_key)
                cleaned += 1
            except BlockingIOError:
                # Lock still held - not stale
                pass
            except OSError:
                # File descriptor invalid - definitely stale
                stale_files.append(file_key)
                cleaned += 1

        # Remove stale locks from registry
        for file_key in stale_files:
            if file_key in self.file_locks:
                session_id = self.file_locks[file_key].session_id
                del self.file_locks[file_key]
                self.session_locks[session_id].discard(file_key)
                if file_key in self._lock_fds:
                    del self._lock_fds[file_key]

        return cleaned
