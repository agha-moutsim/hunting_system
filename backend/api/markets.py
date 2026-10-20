"""The marketplace list the header selector reads.

The response is deliberately small and honest: only markets whose deals URL
was observed reachable are offered, and every non-UK row carries the sentence
explaining that no fee table exists for it. No eBay credentials, headers or
site internals are exposed.
"""

from fastapi import APIRouter

from marketplaces import DEFAULT_MARKETPLACE, offered_marketplaces

router = APIRouter()


@router.get("/markets")
def list_markets():
    return {
        "default": DEFAULT_MARKETPLACE,
        "marketplaces": offered_marketplaces(),
    }
