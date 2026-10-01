"""Classify WHERE a supplier row came from — a real property of the source.

Deliberately a leaf module (no project imports) so `deep_search`,
`analysis_pipeline` and the exporters can all share one definition
without risking a circular import.

A row's type is derived from its URL/name only. We never ask the LLM
to declare it and never default it to something that sounds plausible.
"""

from urllib.parse import urlparse

# Domain fragments that identify a dropshipping marketplace.
_DROPSHIP_HOSTS = (
    "aliexpress", "cjdropshipping", "godropship", "joybuy",
    "temu", "shein", "banggood", "wish.com", "dx.com",
)

# Domain fragments that identify a high-street / national retailer.
_RETAILER_HOSTS = (
    "amazon.", "toolstation", "diy.com", "bandq", "screwfix",
    "argos", "wicks", "wickes", "b-and-q", "homebase",
    "currys", "johnlewis", "ao.com", "very.co.uk",
)

# Domain fragments that identify a wholesale trade supplier.
_WHOLESALER_HOSTS = (
    "wholesale", "tradecounter", "clearance-warehouse", "bulk",
)

# Display-name tokens — same sources, minus the trailing dots that make
# the host fragments precise (a host "amazon." must not match "amazonxyz").
_DROPSHIP_NAMES = (
    "aliexpress", "cj dropshipping", "cjdropshipping", "godropship",
    "joybuy", "temu", "shein", "banggood", "wish", "dx.com",
)
_RETAILER_NAMES = (
    "amazon", "toolstation", "b&q", "bandq", "b and q", "screwfix",
    "argos", "wicks", "wickes", "homebase", "currys", "john lewis",
    "johnlewis", "ao.com", "very",
)
_WHOLESALER_NAMES = (
    "wholesale", "trade counter", "tradecounter", "bulk",
)

UNKNOWN = "unknown"


def supplier_type_from_url(url: str) -> str:
    """Map a source URL onto wholesaler | dropshipper | retailer | unknown."""
    if not url:
        return UNKNOWN
    host = (urlparse(str(url)).hostname or "").lower().replace("www.", "")
    if not host:
        return UNKNOWN
    if any(d in host for d in _DROPSHIP_HOSTS):
        return "dropshipper"
    if any(w in host for w in _WHOLESALER_HOSTS):
        return "wholesaler"
    if any(r in host for r in _RETAILER_HOSTS):
        return "retailer"
    return UNKNOWN


def supplier_type_from_name(name: str) -> str:
    """Best-effort classification from a display name (no URL available).

    Uses a separate token list from the host matcher: host fragments carry
    a trailing dot ("amazon.") to avoid matching look-alike domains, which
    would never match the plain display name "Amazon UK".
    """
    if not name:
        return UNKNOWN
    needle = str(name).lower()
    if any(d in needle for d in _DROPSHIP_NAMES):
        return "dropshipper"
    if any(w in needle for w in _WHOLESALER_NAMES):
        return "wholesaler"
    if any(r in needle for r in _RETAILER_NAMES):
        return "retailer"
    return UNKNOWN


def supplier_type(name: str = "", url: str = "") -> str:
    """Classify by URL when we have one, else by name, else unknown.

    Never guesses: an unrecognised source reports `unknown` rather than
    being labelled `dropshipper` because that is the usual case.

    NOTE: both helpers return the string "unknown", which is truthy — so
    the fallback must test against UNKNOWN explicitly, not with `or`, or
    a missing URL silently suppresses name-based matching.
    """
    by_url = supplier_type_from_url(url)
    if by_url != UNKNOWN:
        return by_url
    return supplier_type_from_name(name)
