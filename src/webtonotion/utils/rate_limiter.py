"""Rate limiting utility for API requests.

This module provides a RateLimiter class to manage API request rates
and prevent exceeding rate limits for external services.
"""

import asyncio
import time
from typing import Dict, Optional


class RateLimiter:
    """Rate limiter for API requests.
    
    Implements a token bucket algorithm to limit the rate of API requests.
    This helps prevent rate limit errors from external services.
    """
    
    def __init__(self, max_requests: int, time_window: float):
        """Initialize the rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed in the time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.tokens = max_requests
        self.last_refill_time = time.time()
        self.lock = asyncio.Lock()
    
    async def wait_if_needed(self) -> None:
        """Wait if necessary to comply with rate limits.
        
        This method will block until a token is available for a new request.
        """
        async with self.lock:
            await self._refill_tokens()
            
            if self.tokens <= 0:
                # Calculate wait time needed for at least one token
                wait_time = self.time_window / self.max_requests
                await asyncio.sleep(wait_time)
                await self._refill_tokens()
            
            # Consume a token
            self.tokens -= 1
    
    async def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        current_time = time.time()
        elapsed = current_time - self.last_refill_time
        
        # Calculate how many tokens to add based on elapsed time
        new_tokens = int((elapsed / self.time_window) * self.max_requests)
        
        if new_tokens > 0:
            self.tokens = min(self.tokens + new_tokens, self.max_requests)
            self.last_refill_time = current_time