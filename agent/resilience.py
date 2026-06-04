import time
import asyncio
import logging
from functools import wraps
from typing import Callable, Any, TypeVar, Coroutine

logger = logging.getLogger("agent.resilience")

T = TypeVar("T")

def retry_sync(attempts: int = 3, backoff: float = 0.5):
    """Decorator to retry a synchronous function in case of transient failures (rate limits, timeouts)."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_err = None
            current_backoff = backoff
            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    err_msg = str(e).lower()
                    is_transient = any(
                        phrase in err_msg 
                        for phrase in [
                            "429", "500", "502", "503", "504", 
                            "rate limit", "too many requests", "overloaded", 
                            "timeout", "connection", "rate_limit_exceeded"
                        ]
                    )
                    
                    if not is_transient and attempt == attempts - 1:
                        raise e
                        
                    logger.warning(f"⚠️ Sync call to '{func.__name__}' failed (attempt {attempt+1}/{attempts}): {e}. Retrying in {current_backoff:.2f}s...")
                    time.sleep(current_backoff)
                    current_backoff *= 2
            raise last_err
        return wrapper
    return decorator

def retry_async(attempts: int = 3, backoff: float = 0.5):
    """Decorator to retry an asynchronous function in case of transient failures."""
    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_err = None
            current_backoff = backoff
            for attempt in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    err_msg = str(e).lower()
                    is_transient = any(
                        phrase in err_msg 
                        for phrase in [
                            "429", "500", "502", "503", "504", 
                            "rate limit", "too many requests", "overloaded", 
                            "timeout", "connection", "rate_limit_exceeded"
                        ]
                    )
                    
                    if not is_transient and attempt == attempts - 1:
                        raise e
                        
                    logger.warning(f"⚠️ Async call to '{func.__name__}' failed (attempt {attempt+1}/{attempts}): {e}. Retrying in {current_backoff:.2f}s...")
                    await asyncio.sleep(current_backoff)
                    current_backoff *= 2
            raise last_err
        return wrapper
    return decorator

def run_with_retry_sync(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a synchronous callable with retry logic."""
    wrapped = retry_sync()(func)
    return wrapped(*args, **kwargs)

async def run_with_retry_async(func: Callable[..., Coroutine[Any, Any, T]], *args, **kwargs) -> T:
    """Run an asynchronous callable with retry logic."""
    wrapped = retry_async()(func)
    return await wrapped(*args, **kwargs)
