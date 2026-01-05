"""API routes for Kage Bunshin no Jutsu."""

from .tasks import router as tasks_router
from .progress import router as progress_router
from .merge import router as merge_router

__all__ = ["tasks_router", "progress_router", "merge_router"]
