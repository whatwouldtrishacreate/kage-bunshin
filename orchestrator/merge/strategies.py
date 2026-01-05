#!/usr/bin/env python3
"""
Merge Strategies for Kage Bunshin no Jutsu
===========================================

Implements three merge strategies:
1. THEIRS - Accept best result automatically (no conflict check)
2. AUTO - Auto-merge if no conflicts, fail otherwise
3. MANUAL - Require manual conflict resolution
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from .detector import ConflictDetector, ConflictInfo


@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    strategy: str
    merged_files: List[str]
    conflicts: List[str]
    commit_hash: Optional[str] = None
    message: str = ""


class MergeExecutor:
    """
    Executes merge operations using different strategies.

    Integrates with Week 1 WorktreeManager to merge session worktrees
    back into the main branch.
    """

    def __init__(self, project_dir: Path, base_branch: str = "main"):
        self.project_dir = project_dir
        self.base_branch = base_branch
        self.detector = ConflictDetector(project_dir)

    def merge_theirs(
        self,
        source_branch: str,
        commit_message: Optional[str] = None
    ) -> MergeResult:
        """
        THEIRS strategy: Accept source branch unconditionally.

        Uses git merge with -X theirs strategy.

        Args:
            source_branch: Branch to merge from
            commit_message: Optional custom commit message

        Returns:
            MergeResult
        """
        try:
            # Get list of files that will be merged
            merged_files = self._get_changed_files(source_branch)

            # Perform merge with theirs strategy
            merge_cmd = [
                "git", "merge",
                "-X", "theirs",
                "--no-edit",
                source_branch
            ]

            if commit_message:
                merge_cmd.extend(["-m", commit_message])

            result = subprocess.run(
                merge_cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )

            # Get commit hash
            commit_hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = commit_hash_result.stdout.strip()

            return MergeResult(
                success=True,
                strategy="theirs",
                merged_files=list(merged_files),
                conflicts=[],
                commit_hash=commit_hash,
                message=f"Successfully merged {len(merged_files)} files using THEIRS strategy"
            )

        except subprocess.CalledProcessError as e:
            return MergeResult(
                success=False,
                strategy="theirs",
                merged_files=[],
                conflicts=[],
                message=f"Merge failed: {e.stderr}"
            )

    def merge_auto(
        self,
        source_branch: str,
        commit_message: Optional[str] = None
    ) -> MergeResult:
        """
        AUTO strategy: Merge if no conflicts, fail otherwise.

        Checks for conflicts first, then merges if clean.

        Args:
            source_branch: Branch to merge from
            commit_message: Optional custom commit message

        Returns:
            MergeResult
        """
        # Check for conflicts first
        can_merge, conflicting_files = self.detector.try_merge_check(
            source_branch,
            self.base_branch
        )

        if not can_merge:
            return MergeResult(
                success=False,
                strategy="auto",
                merged_files=[],
                conflicts=conflicting_files,
                message=f"Auto-merge blocked: {len(conflicting_files)} conflicts detected"
            )

        # No conflicts - perform merge
        try:
            merged_files = self._get_changed_files(source_branch)

            merge_cmd = ["git", "merge", "--no-edit", source_branch]
            if commit_message:
                merge_cmd.extend(["-m", commit_message])

            subprocess.run(
                merge_cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )

            # Get commit hash
            commit_hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = commit_hash_result.stdout.strip()

            return MergeResult(
                success=True,
                strategy="auto",
                merged_files=list(merged_files),
                conflicts=[],
                commit_hash=commit_hash,
                message=f"Successfully auto-merged {len(merged_files)} files (no conflicts)"
            )

        except subprocess.CalledProcessError as e:
            return MergeResult(
                success=False,
                strategy="auto",
                merged_files=[],
                conflicts=[],
                message=f"Merge failed: {e.stderr}"
            )

    def merge_manual(
        self,
        source_branch: str
    ) -> MergeResult:
        """
        MANUAL strategy: Detect conflicts and prepare for manual resolution.

        Does NOT perform the merge, just returns conflict information.

        Args:
            source_branch: Branch to merge from

        Returns:
            MergeResult with conflict information
        """
        # Check for conflicts
        can_merge, conflicting_files = self.detector.try_merge_check(
            source_branch,
            self.base_branch
        )

        merged_files = self._get_changed_files(source_branch)

        if can_merge:
            return MergeResult(
                success=False,
                strategy="manual",
                merged_files=list(merged_files),
                conflicts=[],
                message="Manual merge requested but no conflicts detected. Use AUTO or THEIRS strategy instead."
            )
        else:
            return MergeResult(
                success=False,
                strategy="manual",
                merged_files=list(merged_files),
                conflicts=conflicting_files,
                message=f"Manual resolution required for {len(conflicting_files)} conflicts"
            )

    def _get_changed_files(self, source_branch: str) -> List[str]:
        """Get list of files changed in source branch."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{self.base_branch}...{source_branch}"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
            return files
        except subprocess.CalledProcessError:
            return []
