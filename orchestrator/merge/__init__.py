"""Merge strategies for Kage Bunshin no Jutsu."""

from .detector import ConflictDetector
from .strategies import ConflictInfo, MergeExecutor, MergeResult

__all__ = ["MergeExecutor", "MergeResult", "ConflictInfo", "ConflictDetector"]
