"""Top-level provenance block for analysis responses — C13.

frontend/lib/types.ts pins `ProvenanceBlock` on DeepSearchResult and
AnalyzeResponse: its sections (demand, top_eBay_sellers, suppliers,
profit_analysis) plus `fields` — export/format.py adds `ebay_stores` to
the same block for an exported JSON, so both sides share its helpers here:
the store stamp, the profit stamp and the stamp normaliser are ONE
implementation, and a live response cannot drift from its export.

C13 rules enforced here (the section stamps come from format.normalize_stamp):
  * never absent — a block we did not fetch or did not compute reads
    `unverified` WITH a reason;
  * `ai_insight` is demoted to unverified (the LLM is not a source of fact);
  * an unverified stamp with no reason gains one, so a badge can never
    imply a check that was never made.
"""

from typing import Any

from engine.provenance import Provenance
from export.format import normalize_stamp, profit_block_for, store_block_for
from export.format import unverified_stamp  # noqa: F401 — re-exported seam

_NO_DEMAND_REASON = "no demand data retrieved"
_DEMAND_REASON = "demand data could not be verified"
_SELLERS_REASON = "no eBay top-seller data retrieved"
_SELLER_UNCONFIRMED_REASON = "a top-seller row could not be confirmed"
_SUPPLIERS_REASON = "no supplier rows retrieved"
_SUPPLIER_UNCONFIRMED_REASON = "a supplier row could not be confirmed"

__all__ = ["build_provenance_block", "unverified_stamp"]


def _verified_stamp() -> dict:
    return {
        "provenance": Provenance.VERIFIED.value,
        "label": Provenance.VERIFIED.label,
    }


def _field_stamp(fields: dict, name: str, fallback_reason: str) -> dict | None:
    """One entry of the per-field map, or None when the run stamped nothing.

    Deep search stamps its sold/seller/supplier fields as it fetches them,
    so those stamps (receipts included) are the first source of truth.
    """
    entry = fields.get(name)
    if isinstance(entry, dict) and str(entry.get("provenance") or "").strip():
        return normalize_stamp(entry, fallback_reason)
    return None


def _row_origin(row: dict) -> str:
    """One row's origin as a tier: a stamped row wins, else its own
    `verified` flag, else '' — no origin signal at all."""
    prov = str(row.get("provenance") or "").strip().lower()
    if prov:
        return prov
    if "verified" in row:
        return (Provenance.VERIFIED.value if row["verified"]
                else Provenance.UNVERIFIED.value)
    return ""


def _rows_stamp(rows: Any, empty_reason: str, unconfirmed_reason: str) -> dict:
    """C13 — block stamp for a list of rows: an empty list is unverified,
    and one unconfirmed row keeps the whole block from reading verified."""
    kept = [r for r in (rows or []) if isinstance(r, dict)]
    if not kept:
        return unverified_stamp(empty_reason)
    for row in kept:
        if _row_origin(row) != Provenance.VERIFIED.value:
            return unverified_stamp(unconfirmed_reason)
    return _verified_stamp()


def _demand_stamp(payload: dict, fields: dict) -> dict:
    """Deep search stamps the sold figures per field; Analyze carries a
    DemandData dict instead — both are read here, in that order."""
    stamp = (_field_stamp(fields, "ebay_total_sold_30d", _DEMAND_REASON)
             or _field_stamp(fields, "demand", _DEMAND_REASON))
    if stamp:
        return stamp
    demand = payload.get("demand")
    if isinstance(demand, dict):
        if demand.get("provenance"):
            return normalize_stamp(demand, _DEMAND_REASON)
        # scrapers/ebay.get_sold_data sets verified=False on every failure,
        # so the flag alone is the pipeline's own verdict on this block.
        if demand.get("verified"):
            return _verified_stamp()
        return unverified_stamp(_DEMAND_REASON)
    return unverified_stamp(_NO_DEMAND_REASON)


def _sellers_stamp(payload: dict, fields: dict) -> dict:
    stamp = _field_stamp(fields, "ebay_top_sellers", _SELLERS_REASON)
    if stamp:
        return stamp
    rows = payload.get("ebay_top_sellers")
    if rows is None:
        demand = payload.get("demand")
        rows = demand.get("top_sellers") if isinstance(demand, dict) else None
    return _rows_stamp(rows, _SELLERS_REASON, _SELLER_UNCONFIRMED_REASON)


def _suppliers_stamp(payload: dict, fields: dict) -> dict:
    stamp = _field_stamp(fields, "suppliers", _SUPPLIERS_REASON)
    if stamp:
        return stamp
    rows = payload.get("supplier_matches") or payload.get("suppliers")
    return _rows_stamp(rows, _SUPPLIERS_REASON, _SUPPLIER_UNCONFIRMED_REASON)


def build_provenance_block(payload: dict, *, reason: str = "") -> dict:
    """Assemble the pinned block for an analysis payload.

    `reason` is for a run that never completed (timeout): every section
    then reads unverified WITH that reason, because nothing was fetched
    and nothing was computed.
    """
    fields = dict(payload.get("field_provenance") or {})
    # C11/C13 — one store stamp per payload, derived exactly as the export
    # derives it, and mirrored into `fields` so provenance.fields can never
    # disagree with the top-level block (deep_search keeps the same mirror).
    store_block = store_block_for(payload)
    fields["ebay_stores"] = dict(store_block)

    if reason:
        blocked = unverified_stamp(reason)
        return {
            "demand": dict(blocked),
            "top_eBay_sellers": dict(blocked),
            "suppliers": dict(blocked),
            "ebay_stores": store_block,
            "profit_analysis": dict(blocked),
            "fields": fields,
        }

    return {
        "demand": _demand_stamp(payload, fields),
        "top_eBay_sellers": _sellers_stamp(payload, fields),
        "suppliers": _suppliers_stamp(payload, fields),
        "ebay_stores": store_block,
        # C13 — same stamp export/format gives the same run.
        "profit_analysis": profit_block_for(payload),
        "fields": fields,
    }
