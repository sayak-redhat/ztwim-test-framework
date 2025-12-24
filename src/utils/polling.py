"""
Dynamic Polling Utilities for ZTWIM Test Framework.

Provides smart waiting mechanisms with:
- Exponential backoff
- Early return on success
- Adaptive polling intervals
- Progress logging
- Configurable timeouts
"""

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar, Optional, Any, List
from functools import wraps

from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class PollConfig:
    """Configuration for polling behavior."""
    
    # Initial delay before first check (seconds)
    initial_delay: float = 1.0
    
    # Minimum polling interval (seconds)
    min_interval: float = 2.0
    
    # Maximum polling interval (seconds)
    max_interval: float = 30.0
    
    # Backoff multiplier (1.0 = constant, 2.0 = double each time)
    backoff_factor: float = 1.5
    
    # Maximum total wait time (seconds)
    timeout: float = 300.0
    
    # Log progress every N polls
    log_every: int = 3
    
    # Custom message for logging
    message: str = "Waiting for condition"


@dataclass
class PollResult:
    """Result of a polling operation."""
    
    success: bool
    value: Any = None
    elapsed_time: float = 0.0
    attempts: int = 0
    error: Optional[Exception] = None
    
    def __bool__(self):
        return self.success


class DynamicPoller:
    """
    Dynamic polling with exponential backoff and early return.
    
    Usage:
        poller = DynamicPoller()
        
        # Simple usage
        result = poller.wait_until(
            condition=lambda: check_resource_ready(),
            message="Waiting for resource"
        )
        
        # With custom config
        result = poller.wait_until(
            condition=lambda: check_pod_status(),
            config=PollConfig(timeout=60, min_interval=1)
        )
    """
    
    def __init__(self, default_config: Optional[PollConfig] = None):
        """Initialize with optional default configuration."""
        self.default_config = default_config or PollConfig()
    
    def wait_until(
        self,
        condition: Callable[[], Any],
        message: str = None,
        config: PollConfig = None,
        on_progress: Callable[[int, float], None] = None
    ) -> PollResult:
        """
        Wait until condition returns truthy value.
        
        Args:
            condition: Callable that returns truthy value when ready
            message: Progress message for logging
            config: Polling configuration (uses default if not provided)
            on_progress: Optional callback(attempt, elapsed) for progress updates
            
        Returns:
            PollResult with success status, value, and timing info
        """
        cfg = config or self.default_config
        msg = message or cfg.message
        
        start_time = time.time()
        attempt = 0
        current_interval = cfg.min_interval
        last_error = None
        
        # Initial delay
        if cfg.initial_delay > 0:
            time.sleep(cfg.initial_delay)
        
        while True:
            attempt += 1
            elapsed = time.time() - start_time
            
            # Check timeout
            if elapsed >= cfg.timeout:
                logger.warning(
                    f"⏱️ {msg}: Timeout after {elapsed:.1f}s ({attempt} attempts)"
                )
                return PollResult(
                    success=False,
                    elapsed_time=elapsed,
                    attempts=attempt,
                    error=last_error or TimeoutError(f"{msg} - timeout after {elapsed:.1f}s")
                )
            
            # Try condition
            try:
                result = condition()
                
                if result:
                    logger.info(
                        f"✅ {msg}: Ready after {elapsed:.1f}s ({attempt} attempts)"
                    )
                    return PollResult(
                        success=True,
                        value=result,
                        elapsed_time=elapsed,
                        attempts=attempt
                    )
                    
            except Exception as e:
                last_error = e
                logger.debug(f"{msg}: Attempt {attempt} failed: {e}")
            
            # Progress logging
            if attempt % cfg.log_every == 0:
                remaining = cfg.timeout - elapsed
                logger.info(
                    f"⏳ {msg}: Attempt {attempt}, elapsed {elapsed:.1f}s, "
                    f"remaining {remaining:.1f}s"
                )
            
            # Progress callback
            if on_progress:
                on_progress(attempt, elapsed)
            
            # Wait with backoff
            time.sleep(current_interval)
            
            # Increase interval with backoff (cap at max)
            current_interval = min(
                current_interval * cfg.backoff_factor,
                cfg.max_interval
            )
    
    def wait_for_all(
        self,
        conditions: List[tuple],
        config: PollConfig = None
    ) -> PollResult:
        """
        Wait for multiple conditions to be met.
        
        Args:
            conditions: List of (name, callable) tuples
            config: Polling configuration
            
        Returns:
            PollResult with all conditions' results
        """
        cfg = config or self.default_config
        results = {}
        
        start_time = time.time()
        
        for name, condition in conditions:
            remaining_time = cfg.timeout - (time.time() - start_time)
            
            if remaining_time <= 0:
                return PollResult(
                    success=False,
                    value=results,
                    elapsed_time=time.time() - start_time,
                    error=TimeoutError(f"Timeout before checking: {name}")
                )
            
            condition_config = PollConfig(
                initial_delay=0,
                min_interval=cfg.min_interval,
                max_interval=cfg.max_interval,
                backoff_factor=cfg.backoff_factor,
                timeout=remaining_time,
                message=name
            )
            
            result = self.wait_until(condition, name, condition_config)
            results[name] = result
            
            if not result.success:
                return PollResult(
                    success=False,
                    value=results,
                    elapsed_time=time.time() - start_time,
                    error=result.error
                )
        
        return PollResult(
            success=True,
            value=results,
            elapsed_time=time.time() - start_time,
            attempts=sum(r.attempts for r in results.values())
        )


# Convenience functions
def wait_until(
    condition: Callable[[], Any],
    message: str = "Waiting",
    timeout: float = 300,
    interval: float = 5,
    backoff: float = 1.5
) -> PollResult:
    """
    Convenience function for simple polling.
    
    Args:
        condition: Callable returning truthy when ready
        message: Log message
        timeout: Max wait time in seconds
        interval: Initial polling interval
        backoff: Backoff multiplier
        
    Returns:
        PollResult
        
    Example:
        result = wait_until(
            lambda: pod.status.phase == "Running",
            message="Pod to be running",
            timeout=60
        )
        if result:
            print(f"Ready in {result.elapsed_time}s")
    """
    config = PollConfig(
        initial_delay=0,
        min_interval=interval,
        max_interval=min(interval * 10, 60),
        backoff_factor=backoff,
        timeout=timeout,
        message=message
    )
    
    return DynamicPoller().wait_until(condition, message, config)


def wait_for_resource(
    get_func: Callable[[], Any],
    ready_func: Callable[[Any], bool],
    message: str = "Resource ready",
    timeout: float = 300
) -> PollResult:
    """
    Wait for a resource to become ready.
    
    Args:
        get_func: Function to get the resource
        ready_func: Function to check if resource is ready
        message: Log message
        timeout: Max wait time
        
    Returns:
        PollResult with resource as value
        
    Example:
        result = wait_for_resource(
            get_func=lambda: client.get_pod("my-pod"),
            ready_func=lambda pod: pod.status.phase == "Running",
            message="Pod my-pod",
            timeout=120
        )
    """
    def check():
        resource = get_func()
        if resource and ready_func(resource):
            return resource
        return None
    
    return wait_until(check, message, timeout)


def retry_on_error(
    func: Callable[[], T],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> T:
    """
    Retry a function on error with exponential backoff.
    
    Args:
        func: Function to call
        max_attempts: Maximum retry attempts
        delay: Initial delay between retries
        backoff: Backoff multiplier
        exceptions: Tuple of exceptions to catch
        
    Returns:
        Function result
        
    Raises:
        Last exception if all retries fail
        
    Example:
        result = retry_on_error(
            lambda: api.create_resource(body),
            max_attempts=3,
            exceptions=(ApiException,)
        )
    """
    last_error = None
    current_delay = delay
    
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed: {e}. "
                    f"Retrying in {current_delay:.1f}s..."
                )
                time.sleep(current_delay)
                current_delay *= backoff
            else:
                logger.error(f"All {max_attempts} attempts failed")
    
    raise last_error


def poll_decorator(
    timeout: float = 300,
    interval: float = 5,
    message: str = None
):
    """
    Decorator to add polling to a check function.
    
    Example:
        @poll_decorator(timeout=60, message="Pod ready")
        def is_pod_ready(pod_name):
            pod = client.get_pod(pod_name)
            return pod.status.phase == "Running"
        
        # This will poll until True or timeout
        result = is_pod_ready("my-pod")
    """
    def decorator(func: Callable[..., bool]):
        @wraps(func)
        def wrapper(*args, **kwargs) -> PollResult:
            msg = message or f"Waiting for {func.__name__}"
            return wait_until(
                lambda: func(*args, **kwargs),
                message=msg,
                timeout=timeout,
                interval=interval
            )
        return wrapper
    return decorator

