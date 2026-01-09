"""
Budget Management Utilities

Implements token budget tracking and enforcement to prevent runaway costs.
LLM Council Phase 1 Recommendation.
"""

from typing import Optional

from orchestrator.config import MAX_TOKENS_PER_TASK, TOKEN_WARNING_THRESHOLD
from orchestrator.execution.adapters.base import BudgetExceededError


class TokenBudgetTracker:
    """
    Tracks token usage for a single task execution.

    Uses character-based estimation (chars / 4) for simplicity.
    Phase 2 can integrate proper tokenizer (tiktoken, etc.)
    """

    def __init__(
        self, task_id: str, cli_name: str, max_tokens: Optional[int] = None
    ):
        """
        Initialize budget tracker.

        Args:
            task_id: Unique task identifier
            cli_name: Name of CLI being executed
            max_tokens: Token limit (defaults to MAX_TOKENS_PER_TASK)
        """
        self.task_id = task_id
        self.cli_name = cli_name
        self.max_tokens = max_tokens or MAX_TOKENS_PER_TASK
        self.tokens_used = 0
        self.warning_threshold = int(self.max_tokens * TOKEN_WARNING_THRESHOLD)
        self.warning_issued = False

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count from text.

        Uses simple character-based approximation: tokens ≈ chars / 4
        This is conservative (overestimates slightly) which is safer for budgets.

        Args:
            text: Input text to estimate

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Character-based estimation (conservative)
        # GPT models average ~4 chars per token
        # Claude models similar (~3.5-4 chars per token)
        return len(text) // 4

    def add_usage(self, text: str) -> int:
        """
        Add text to usage tracking and return estimated tokens.

        Args:
            text: Text to add to budget

        Returns:
            Estimated tokens for this text

        Raises:
            BudgetExceededError: If adding this text would exceed budget
        """
        tokens = self.estimate_tokens(text)
        new_total = self.tokens_used + tokens

        # Check if adding this would exceed budget
        if new_total > self.max_tokens:
            raise BudgetExceededError(
                message=f"Task would exceed token budget: {new_total} > {self.max_tokens}",
                cli_name=self.cli_name,
                task_id=self.task_id,
                tokens_used=new_total,
                token_limit=self.max_tokens,
            )

        # Update tracking
        self.tokens_used = new_total

        # Issue warning if threshold crossed (only once)
        if (
            not self.warning_issued
            and self.tokens_used >= self.warning_threshold
        ):
            self.warning_issued = True
            print(
                f"⚠️  Token usage warning: {self.tokens_used}/{self.max_tokens} "
                f"({int(100 * self.tokens_used / self.max_tokens)}% of budget)"
            )

        return tokens

    def get_usage(self) -> dict:
        """
        Get current usage statistics.

        Returns:
            Dictionary with usage metrics
        """
        return {
            "tokens_used": self.tokens_used,
            "token_limit": self.max_tokens,
            "tokens_remaining": self.max_tokens - self.tokens_used,
            "percent_used": round(100.0 * self.tokens_used / self.max_tokens, 2),
            "warning_issued": self.warning_issued,
        }

    def has_capacity(self, estimated_tokens: int) -> bool:
        """
        Check if there's capacity for additional tokens.

        Args:
            estimated_tokens: Number of tokens to check

        Returns:
            True if tokens would fit within budget
        """
        return (self.tokens_used + estimated_tokens) <= self.max_tokens
