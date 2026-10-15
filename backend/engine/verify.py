"""Store URL verification - REGRESSION-007, closing the loop.

Phase 2 stopped FABRICATING ``/str/{username}`` links. That removed the
fabrication, but it still could not answer the question the user actually
asked: *does this store exist?* eBay serves a CAPTCHA for ``/str/`` to a
plain request, so:

  - a naive HTTP check calls every store unverified, and
  - a naive "HTTP 200 means fine" check is worse than useless.

Measured 2026-10-10 through ScrapingBee, with a deliberate negative control:

    /str/zzqx-nonexistent-store-99887766 -> 410  "eBay Home"                 0 items
    /str/har_476199                      -> 410  "eBay Home"                 0 items
    /str/consciousgenerationstore         -> 410  "eBay Home"                 0 items
    /str/pravivity                       -> 200  "pravivity | eBay UK Stores" 48 items
    /str/juicebitz                       -> 200  "JuicEBitz | eBay UK Stores" 54 items

``har_476199`` is a seller USER ID being read as a store slug - the original
defect, reproduced live. eBay answers a dead slug with **410**, not 404, and
a real store with **200** plus ``| eBay UK Stores`` in the title.

Three outcomes, and only three:

    verified    it is a shop - 200, the store marker, and listings
    not_found   eBay answered, and there is no shop at that slug
    unavailable we could not find out - no key, transport error, 5xx, captcha

``unavailable`` is never collapsed into ``not_found``. C13 says a value we
could not confirm must not be shown as one we did, and a blocked request
says nothing at all about whether a shop exists.

Fail-closed everywhere: this module never raises into a caller, and it costs
at most ``MAX_CHECKS`` requests per process before reporting ``unavailable``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

SCRAPINGBEE_API = "https://app.scrapingbee.com/api/v1/"

# How many store checks one process may spend. Capped so a run cannot drain
# the account; past it every check reports `unavailable` rather than guessing.
MAX_CHECKS = 12
# Cached results, so repeated runs over the same competitor set are free.
CACHE_TTL_S = 900.0
# A check is a rendered page load, so the wait is generous.
CHECK_TIMEOUT_S = 60.0

_STORE_TITLE_RE = re.compile(r"\|\s*eBay\s+UK\s+Stores?\b", re.I)
_ITEM_RE = re.compile(r'href="[^"]*/itm/', re.I)
_CAPTCHA_RE = re.compile(r"security measure|unusual traffic|are you a robot", re.I)


class StoreCheck(str, Enum):
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class StoreCheckResult:
    status: StoreCheck
    http_status: Optional[int] = None
    reason: str = ""
    from_cache: bool = False


# --- process-level budget + cache -------------------------------------------

_lock = threading.Lock()
_cache: dict[str, tuple[float, StoreCheckResult]] = {}
_checks_spent = 0


def reset_budget() -> None:
    """Refill the per-process check budget (tests, and long-lived servers)."""
    global _checks_spent
    with _lock:
        _checks_spent = 0


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def budget_remaining() -> int:
    with _lock:
        return max(0, MAX_CHECKS - _checks_spent)


def is_store_url(url: str) -> bool:
    """True only for an https eBay storefront URL worth spending a check on."""
    text = str(url or "").strip()
    if not text.lower().startswith("https://"):
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    host = parsed.hostname or ""
    if not (host == "ebay.co.uk" or host.endswith(".ebay.co.uk")):
        return False
    return "/str/" in parsed.path


# --- classification ----------------------------------------------------------

def classify_store_response(status_code: int, body: str) -> StoreCheckResult:
    """Decide what an eBay response MEANS.

    Separated from fetching so the decision - the part that must never be
    wrong - is testable without a network call.
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return StoreCheckResult(StoreCheck.UNAVAILABLE, reason="unreadable status")

    # A captcha answers 200 and is NOT a store existing.
    if _CAPTCHA_RE.search(body or ""):
        return StoreCheckResult(
            StoreCheck.UNAVAILABLE, code,
            "eBay served a captcha / bot challenge, not the page")

    # eBay answers a dead storefront slug with 410 Gone, not 404.
    if code in (404, 410):
        return StoreCheckResult(StoreCheck.NOT_FOUND, code, "eBay reports no store at this URL")

    if code >= 500:
        return StoreCheckResult(StoreCheck.UNAVAILABLE, code, "eBay returned a server error")

    if code == 200:
        if _STORE_TITLE_RE.search(body or "") and _ITEM_RE.search(body or ""):
            return StoreCheckResult(StoreCheck.VERIFIED, code, "storefront confirmed by eBay")
        # 200 without the store marker and without listings is eBay's generic
        # shell, not a shop. Same meaning as a 410 for our purposes.
        return StoreCheckResult(
            StoreCheck.NOT_FOUND, code, "response is not an eBay storefront")

    return StoreCheckResult(StoreCheck.UNAVAILABLE, code, f"unexpected status {code}")


# --- fetching ----------------------------------------------------------------

def _fetch(url: str, *, api_key: str, timeout: int = CHECK_TIMEOUT_S):
    """One rendered fetch. Raises only transport errors, which the caller
    converts into `unavailable`."""
    import requests

    return requests.get(
        SCRAPINGBEE_API,
        params={"api_key": api_key, "url": url,
                "render_js": "true", "wait": "2500"},
        timeout=timeout,
    )


def verify_store_url(
    url: str,
    *,
    api_key: Optional[str] = None,
    timeout: int = CHECK_TIMEOUT_S,
    max_checks: int = MAX_CHECKS,
    use_cache: bool = True,
) -> StoreCheckResult:
    """Check one storefront URL. Never raises; always returns one of the three.

    An empty result set is the common case here, and it must be honest: with
    no key, no budget, a blocked transport or an unexpected page, the answer
    is `unavailable` and never `not_found`.
    """
    if not is_store_url(url):
        return StoreCheckResult(
            StoreCheck.UNAVAILABLE, reason="not an eBay storefront URL, not checked")

    key = (api_key if api_key is not None
           else os.getenv("SCRAPINGBEE_API_KEY", "")).strip()
    if not key:
        return StoreCheckResult(
            StoreCheck.UNAVAILABLE, reason="no SCRAPINGBEE_API_KEY configured")

    now = time.monotonic()
    if use_cache:
        with _lock:
            hit = _cache.get(url)
            if hit and (now - hit[0]) < CACHE_TTL_S:
                return StoreCheckResult(hit[1].status, hit[1].http_status,
                                        hit[1].reason, from_cache=True)

    global _checks_spent
    with _lock:
        if _checks_spent >= max_checks:
            return StoreCheckResult(
                StoreCheck.UNAVAILABLE,
                reason=f"verification budget spent ({max_checks} checks)")
        _checks_spent += 1

    try:
        resp = _fetch(url, api_key=key, timeout=timeout)
        result = classify_store_response(resp.status_code, resp.text)
    except Exception as e:  # noqa: BLE001 - a failed check is not a verdict
        result = StoreCheckResult(
            StoreCheck.UNAVAILABLE, reason=f"check could not complete: {type(e).__name__}")

    if use_cache:
        with _lock:
            _cache[url] = (time.monotonic(), result)
    return result