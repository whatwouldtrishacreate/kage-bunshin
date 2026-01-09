"""
Rate Limiting Utilities

Implements exponential backoff for API rate limit errors (429 Too Many Requests).
LLM Council Phase 1 Recommendation.
"""

import asyncio
import time
from typing import List, Optional

from orchestrator.config import (
    MAX_REQUESTS_PER_MINUTE,
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_MAX_RETRIES,
)


class RateLimiter:
    """
    Token bucket rate limiter for API requests.

    Tracks requests per minute and enforces limits with exponential backoff.
    """

    def __init__(self, rpm_limit: Optional[int] = None):
        """
        Initialize rate limiter.

        Args:
            rpm_limit: Requests per minute limit (defaults to MAX_REQUESTS_PER_MINUTE)
        """
        self.rpm_limit = rpm_limit or MAX_REQUESTS_PER_MINUTE
        self.request_times: List[float] = []

    async def acquire(self):
        """
        Acquire permission to make a request.

        Blocks until a request slot is available within the RPM limit.
        """
        now = time.time()

        # Remove requests older than 1 minute
        cutoff = now - 60
        self.request_times = [t for t in self.request_times if t > cutoff]

        # If at limit, wait until oldest request expires
        if len(self.request_times) >= self.rpm_limit:
            oldest = self.request_times[0]
            wait_time = 60 - (now - oldest)
            if wait_time > 0:
                print(
                    f"⏳ Rate limit: {len(self.request_times)}/{self.rpm_limit} RPM. "
                    f"Waiting {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)
                now = time.time()

        # Record this request
        self.request_times.append(now)

    async def backoff_on_429(self, attempt: int, error_msg: Optional[str] = None):
        """
        Exponential backoff for 429 rate limit errors.

        Formula: wait = min(base * (2 ^ attempt), max)

        Args:
            attempt: Retry attempt number (0-indexed)
            error_msg: Optional error message to display

        Example:
            attempt 0: 1.0s
            attempt 1: 2.0s
            attempt 2: 4.0s
            attempt 3: 8.0s
            attempt 4: 16.0s
            attempt 5: 32.0s (capped at RATE_LIMIT_BACKOFF_MAX)
        """
        delay = min(
            RATE_LIMIT_BACKOFF_BASE * (2**attempt),
            RATE_LIMIT_BACKOFF_MAX
        )

        msg = f"🔄 Rate limit hit (429). Retry #{attempt + 1}/{RATE_LIMIT_MAX_RETRIES}. "
        msg += f"Backing off for {delay:.1f}s"
        if error_msg:
            msg += f": {error_msg}"

        print(msg)
        await asyncio.sleep(delay)

    def get_stats(self) -> dict:
        """
        Get current rate limiter statistics.

        Returns:
            Dictionary with rate limit metrics
        """
        now = time.time()
        cutoff = now - 60
        recent_requests = [t for t in self.request_times if t > cutoff]

        return {
            "rpm_limit": self.rpm_limit,
            "requests_last_minute": len(recent_requests),
            "slots_available": self.rpm_limit - len(recent_requests),
            "percent_used": round(100.0 * len(recent_requests) / self.rpm_limit, 2),
        }


async def retry_with_exponential_backoff(
    func,
    *args,
    max_retries: Optional[int] = None,
    **kwargs
):
    """
    Retry function with exponential backoff on rate limit errors.

    Args:
        func: Async function to retry
        *args: Positional arguments for func
        max_retries: Maximum retry attempts (defaults to RATE_LIMIT_MAX_RETRIES)
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful func execution

    Raises:
        Exception: If all retries exhausted or non-retryable error occurs
    """
    max_retries = max_retries or RATE_LIMIT_MAX_RETRIES
    limiter = RateLimiter()

    for attempt in range(max_retries + 1):
        try:
            # Attempt execution
            return await func(*args, **kwargs)

        except Exception as e:
            error_str = str(e).lower()

            # Check if this is a rate limit error (429)
            is_rate_limit = (
                "429" in error_str
                or "rate limit" in error_str
                or "too many requests" in error_str
            )

            if not is_rate_limit:
                # Not a rate limit error - raise immediately
                raise

            if attempt >= max_retries:
                # Exhausted retries
                raise Exception(
                    f"Rate limit error persisted after {max_retries} retries: {e}"
                )

            # Exponential backoff
            await limiter.backoff_on_429(attempt, str(e))

    # Should never reach here
    raise Exception("retry_with_exponential_backoff: unexpected exit")
