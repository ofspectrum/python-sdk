"""
Retry utilities with exponential backoff
"""

import time
import random
from dataclasses import dataclass
from typing import Callable, TypeVar, Optional, Tuple, Type
from functools import wraps

from ..exceptions import OfSpectrumError, RateLimitError, ServiceUnavailableError, NetworkError

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""

    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: Tuple[Type[Exception], ...] = (
        RateLimitError,
        ServiceUnavailableError,
        NetworkError,
    )

    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given attempt using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )

        if self.jitter:
            # Add up to 25% jitter
            delay = delay * (0.75 + random.random() * 0.5)

        return delay


def with_retry(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for adding retry logic to functions.

    Args:
        config: Retry configuration (uses defaults if not provided)
        on_retry: Optional callback called before each retry with (exception, attempt)

    Example:
        @with_retry(RetryConfig(max_retries=5))
        def make_request():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retry_on as e:
                    last_exception = e

                    if attempt == config.max_retries:
                        raise

                    # For rate limit errors, respect retry_after if available
                    if isinstance(e, RateLimitError) and e.retry_after:
                        delay = float(e.retry_after)
                    else:
                        delay = config.calculate_delay(attempt)

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator


async def async_with_retry(
    func: Callable[..., T],
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    *args,
    **kwargs
) -> T:
    """
    Async version of retry logic.

    Args:
        func: Async function to retry
        config: Retry configuration
        on_retry: Optional callback called before each retry
        *args: Arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Result of successful function call
    """
    import asyncio

    if config is None:
        config = RetryConfig()

    last_exception: Optional[Exception] = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except config.retry_on as e:
            last_exception = e

            if attempt == config.max_retries:
                raise

            if isinstance(e, RateLimitError) and e.retry_after:
                delay = float(e.retry_after)
            else:
                delay = config.calculate_delay(attempt)

            if on_retry:
                on_retry(e, attempt)

            await asyncio.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry state")
