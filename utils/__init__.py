"""
Rate limiter — prevents overwhelming target websites.

Usage:
    from utils.rate_limiter import RateLimiter
    limiter = RateLimiter(calls_per_second=1)
    await limiter.acquire()
"""

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, calls_per_second: float = 1.0, burst: int = 3):
        """
        Args:
            calls_per_second: Maximum calls per second
            burst: Maximum burst size (quick successive calls)
        """
        self._min_interval = 1.0 / calls_per_second
        self._burst = burst
        self._last_call: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str = "default"):
        """Wait until we can make a request."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call[key]

            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                await asyncio.sleep(wait_time)

            self._last_call[key] = time.monotonic()

    def reset(self, key: str = "default"):
        """Reset the limiter for a key."""
        self._last_call[key] = 0.0


# Global rate limiters per domain
_domain_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(domain: str, calls_per_second: float = 0.5) -> RateLimiter:
    """Get or create a rate limiter for a domain."""
    if domain not in _domain_limiters:
        _domain_limiters[domain] = RateLimiter(calls_per_second=calls_per_second)
    return _domain_limiters[domain]


# Pre-configured limiters for known sites
EBAY_LIMITER = RateLimiter(calls_per_second=2.0)       # 2 req/s
ALIEXPRESS_LIMITER = RateLimiter(calls_per_second=0.5)  # 1 req/2s
AMAZON_LIMITER = RateLimiter(calls_per_second=0.3)      # ~1 req/3s
SUPPLIER_LIMITER = RateLimiter(calls_per_second=1.0)    # 1 req/s
