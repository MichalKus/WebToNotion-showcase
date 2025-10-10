"""Unit tests for the RateLimiter class."""

import asyncio
import time
import pytest

from webtonotion.services.notion_service import RateLimiter


class TestRateLimiter:
    """Test cases for the RateLimiter class."""

    def test_rate_limiter_initialization(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(max_requests=3, time_window=1.0)
        assert limiter.max_requests == 3
        assert limiter.time_window == 1.0
        assert limiter.tokens == 3

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_requests_under_limit(self):
        """Test rate limiter allows requests under the limit."""
        limiter = RateLimiter(max_requests=3, time_window=1.0)

        # Should not block for the first 3 requests
        for _ in range(3):
            await limiter.wait_if_needed()

        assert limiter.tokens == 0

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excess_requests(self):
        """Test rate limiter blocks excess requests."""
        limiter = RateLimiter(max_requests=2, time_window=0.1)

        # Use up all tokens
        await limiter.wait_if_needed()
        await limiter.wait_if_needed()

        assert limiter.tokens == 0

        # Next request should require waiting
        start_time = time.time()
        await limiter.wait_if_needed()
        elapsed = time.time() - start_time

        # Should have waited at least a small amount of time
        assert elapsed > 0.01