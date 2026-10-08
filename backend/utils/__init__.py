"""
Shared helpers for the backend package.

The rate limiter lives in :mod:`utils.rate_limiter`. It is re-exported
from here so ``from utils import RateLimiter`` keeps working, without the
package defining a second, competing implementation of the same class.

Two copies of this module existed and their ``RateLimiter`` classes were
distinct objects with separate ``_domain_limiters`` registries, so the two
import paths spent the rate budget twice against one host. One class, one
registry, one set of singletons now. See tests/test_rate_limiter_dedupe.py.
"""

from utils.rate_limiter import (
    ALIEXPRESS_LIMITER,
    AMAZON_LIMITER,
    EBAY_LIMITER,
    SUPPLIER_LIMITER,
    RateLimiter,
    get_rate_limiter,
)

__all__ = [
    "RateLimiter",
    "get_rate_limiter",
    "EBAY_LIMITER",
    "ALIEXPRESS_LIMITER",
    "AMAZON_LIMITER",
    "SUPPLIER_LIMITER",
]
