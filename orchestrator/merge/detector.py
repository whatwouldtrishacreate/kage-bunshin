#!/usr/bin/env python3
"""
Conflict Detector for Kage Bunshin no Jutsu
============================================

Detects merge conflicts between parallel CLI execution results.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class ConflictInfo:
    """Information about a merge conflict."""

    file_path: str
    conflict_type: str  # "content", "delete", "rename"
    details: str


class ConflictDetector:
    """
    Detects conflicts between git branches/worktrees.

    Uses git diff to identify:
    - Content conflicts (same file modified differently)
    - Delete conflicts (one modifies, one deletes)
    - Rename conflicts
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def detect_conflicts(
        self, source_branch: str, target_branch: str = "main"
    ) -> List[ConflictInfo]:
        """
        Detect conflicts between two branches.

        Args:
            source_branch: Branch to merge from
            target_branch: Branch to merge into

        Returns:
            List of ConflictInfo objects
        """
        conflicts = []

        # Get list of changed files in source
        source_files = self._get_changed_files(source_branch, target_branch)

        # Check each file for conflicts
        for file_path in source_files:
            conflict = self._check_file_conflict(
                file_path, source_branch, target_branch
            )
            if conflict:
                conflicts.append(conflict)

        return conflicts

    def _get_changed_files(self, source_branch: str, target_branch: str) -> Set[str]:
        """Get files changed in source branch vs target."""
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{target_branch}...{source_branch}"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return (
            set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
        )

    def _check_file_conflict(
        self, file_path: str, source_branch: str, target_branch: str
    ) -> Optional[ConflictInfo]:
        """
        Check if a file has conflicts.

        Returns ConflictInfo if conflict detected, None otherwise.
        """
        # Check if file was modified in both branches
        try:
            # Get file status in both branches
            merge_base_result = subprocess.run(
                ["git", "merge-base", target_branch, source_branch],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            merge_base = merge_base_result.stdout.strip()

            # Check if file changed in both branches since merge base
            target_changed = self._file_changed_since(
                file_path, merge_base, target_branch
            )
            source_changed = self._file_changed_since(
                file_path, merge_base, source_branch
            )

            if target_changed and source_changed:
                # Both branches modified the file - potential conflict
                return ConflictInfo(
                    file_path=file_path,
                    conflict_type="content",
                    details=f"File modified in both {target_branch} and {source_branch}",
                )

        except subprocess.CalledProcessError:
            # Error checking file - assume no conflict
            pass

        return None

    def _file_changed_since(
        self, file_path: str, base_commit: str, branch: str
    ) -> bool:
        """Check if file changed between base commit and branch."""
        try:
            result = subprocess.run(
                ["git", "diff", "--quiet", base_commit, branch, "--", file_path],
                cwd=self.project_dir,
                check=False,
            )
            # Return code 0 = no changes, 1 = has changes
            return result.returncode != 0
        except subprocess.CalledProcessError:
            return False

    def try_merge_check(
        self, source_branch: str, target_branch: str = "main"
    ) -> tuple[bool, List[str]]:
        """
        Perform a dry-run merge to check for conflicts.

        Args:
            source_branch: Branch to merge from
            target_branch: Branch to merge into

        Returns:
            Tuple of (can_merge_cleanly, conflicting_files)
        """
        try:
            # Create temporary merge (--no-commit --no-ff)
            result = subprocess.run(
                ["git", "merge", "--no-commit", "--no-ff", source_branch],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                # Clean merge possible
                subprocess.run(
                    ["git", "merge", "--abort"], cwd=self.project_dir, check=False
                )
                return True, []
            else:
                # Get conflicting files
                conflicts_result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                conflicting_files = [
                    f.strip() for f in conflicts_result.stdout.split("\n") if f.strip()
                ]

                # Abort merge
                subprocess.run(
                    ["git", "merge", "--abort"], cwd=self.project_dir, check=False
                )

                return False, conflicting_files

        except subprocess.CalledProcessError as e:
            # Error during merge check
            subprocess.run(
                ["git", "merge", "--abort"], cwd=self.project_dir, check=False
            )
            return False, []
