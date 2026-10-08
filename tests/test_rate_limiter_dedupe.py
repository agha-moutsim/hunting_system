r"""Two files, one name.

``backend/utils/rate_limiter.py`` and ``backend/utils/__init__.py`` each
define their own ``RateLimiter``. The implementations are identical, but
they are two distinct classes with two distinct ``_domain_limiters``
registries — so ``from utils import RateLimiter`` and
``from utils.rate_limiter import RateLimiter`` silently hand out
different objects, and a caller that mixes the two paths spends its rate
budget twice against the same site.

``utils/__init__.py``'s own docstring names
``from utils.rate_limiter import RateLimiter`` as the way in, so the
module is canonical and the package re-exports from it.

These three assertions are the whole point: one class, one registry, one
set of singletons. There is no behaviour test because nothing behavioural
changes — the surviving implementation is moved, not rewritten.
"""

import utils
import utils.rate_limiter as rl


def test_there_is_one_rate_limiter_class_not_two():
    """Identity, not equality. Two classes with identical methods still
    fail an `is` check, which is exactly the bug."""
    assert utils.RateLimiter is rl.RateLimiter


def test_the_registry_is_shared_across_both_import_paths():
    """The real hazard. Two registries means two independent budgets for
    one host, so a caller using the package path could double the rate
    the module path was carefully holding."""
    from_module = rl.get_rate_limiter("ebay.co.uk", calls_per_second=0.5)
    from_package = utils.get_rate_limiter("ebay.co.uk", calls_per_second=0.5)

    assert from_package is from_module

    # And a second domain is still a separate bucket.
    other = utils.get_rate_limiter("aliexpress.com", calls_per_second=0.5)
    assert other is not from_module


def test_the_pre_configured_limiters_are_re_exported_not_rebuilt():
    """`EBAY_LIMITER` must be THE instance, not a fresh one. A rebuilt
    singleton would start its clock over and quietly lose the throttling
    the first one had already accrued."""
    assert utils.EBAY_LIMITER is rl.EBAY_LIMITER
    assert utils.ALIEXPRESS_LIMITER is rl.ALIEXPRESS_LIMITER
    assert utils.AMAZON_LIMITER is rl.AMAZON_LIMITER
    assert utils.SUPPLIER_LIMITER is rl.SUPPLIER_LIMITER
