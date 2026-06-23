"""
utils/retry.py — Retry decorator with exponential backoff.
Retries up to max_attempts, continues execution on final failure.
"""

import time
import functools
from typing import Callable, Type, Tuple

from utils.logger import log


def retry(
    max_attempts: int = 3,
    delay: float = 5.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_failure=None,
):
    """
    Decorator that retries a function up to max_attempts times.

    Args:
        max_attempts: Maximum number of attempts (default 3).
        delay:        Initial wait between retries in seconds (default 5s).
        backoff:      Multiplier applied to delay after each failure (default 2x).
        exceptions:   Tuple of exception types to catch.
        on_failure:   Optional callable(attempt, max, error) called on each failure.

    On final failure, logs the error and returns None (does NOT raise).
    This ensures the pipeline continues even if a district completely fails.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 1:
                        log.info(f"    ✓ Succeeded on attempt {attempt}/{max_attempts}")
                    return result

                except exceptions as exc:
                    last_exception = exc
                    log.warning(
                        f"    Attempt {attempt}/{max_attempts} failed: {exc}"
                    )

                    if on_failure:
                        try:
                            on_failure(attempt, max_attempts, exc)
                        except Exception:
                            pass

                    if attempt < max_attempts:
                        log.debug(f"    Retrying in {current_delay:.1f}s...")
                        time.sleep(current_delay)
                        current_delay *= backoff

            # All attempts exhausted — log and continue
            log.error(
                f"    ✗ All {max_attempts} attempts failed for {func.__name__}. "
                f"Last error: {last_exception}. Continuing..."
            )
            return None

        return wrapper
    return decorator


def retry_async(
    max_attempts: int = 3,
    delay: float = 5.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Async version of the retry decorator."""
    import asyncio

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 1:
                        log.info(f"    ✓ Succeeded on attempt {attempt}/{max_attempts}")
                    return result

                except exceptions as exc:
                    last_exception = exc
                    log.warning(
                        f"    Attempt {attempt}/{max_attempts} failed: {exc}"
                    )

                    if attempt < max_attempts:
                        log.debug(f"    Retrying in {current_delay:.1f}s...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff

            log.error(
                f"    ✗ All {max_attempts} attempts failed for {func.__name__}. "
                f"Last error: {last_exception}. Continuing..."
            )
            return None

        return wrapper
    return decorator
