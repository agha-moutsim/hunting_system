"""Format results to the user's exact JSON schema."""

from typing import Any

from engine.price_gate import band_label, in_band
from engine.profit import calculate_profit
from engine.provenance import Provenance


def _result_provenance(result: Any) -> dict:
    """C13 — the per-field origin map, defaulting honestly when absent.

    A result built before this change (or by a path that did not stamp)
    reports `unverified`, never a default of `verified` — a missing stamp
    must not be read as a confirmation.
    """
    return dict(getattr(result, "field_provenance", None) or {})


# C13 — an estimate must state its method. ONE wording for this module,
# the CSV cells and the live API block, so all three always agree.
PROFIT_METHOD = (
    "calculate_profit() from engine.profit using PROFIT_CONFIG "
    "(ebay fees + cost) in config.py"
)
NOT_RUN_REASON = "profit analysis did not run"
NOT_RUN_DATA_REASON = "profit analysis did not run — required data missing"
NO_STAMP_REASON = "no origin stamp was recorded for this block"


def unverified_stamp(reason: str) -> dict:
    """C13 — an unverified entry that says WHY it is unverified."""
    return {
        "provenance": Provenance.UNVERIFIED.value,
        "label": Provenance.UNVERIFIED.label,
        "reason": reason,
    }


def normalize_stamp(entry: Any, fallback_reason: str) -> dict:
    """C13 — one stamp into the pinned {provenance, label, …} shape.

    A missing or unknown tier reads `unverified` with `fallback_reason`;
    an unverified stamp with no reason gains one; `ai_insight` is demoted
    (analysis of a fact is not the fact's origin). Extra keys a producer
    attached (method, source_url, reason, …) pass through untouched.
    """
    if not isinstance(entry, dict):
        entry = {}
    try:
        prov = Provenance(str(entry.get("provenance") or "").strip().lower())
    except ValueError:
        return unverified_stamp(fallback_reason)
    if prov is Provenance.AI_INSIGHT:
        return unverified_stamp("AI analysis is not a source of fact")
    out = dict(entry)
    out["provenance"] = prov.value
    out["label"] = prov.label
    if prov is Provenance.UNVERIFIED and not str(out.get("reason") or "").strip():
        out["reason"] = fallback_reason
    return out


def profit_block_for(result: Any) -> dict:
    """C13 — the profit block's stamp, for a result object or payload dict.

    A failed "Data" row (deep search's marker that the eBay price or the
    supplier cost never arrived) or a run whose verdict never landed reads
    unverified WITH why: no profit was computed, so there is no estimate
    to claim. Otherwise the money comes from PROFIT_CONFIG and is an
    estimate carrying its method.
    """
    if isinstance(result, dict):
        verdict = result.get("verdict")
        rows = list(result.get("filters_passed") or [])
    else:
        verdict = getattr(result, "verdict", "")
        rows = list(getattr(result, "filters_passed", None) or [])
    if isinstance(verdict, dict):
        # Analyze serialises VerdictData — its own filter rows ride along.
        rows += list(verdict.get("filters") or [])
    for row in rows:
        if (isinstance(row, dict) and row.get("name") == "Data"
                and not row.get("passed")):
            return unverified_stamp(NOT_RUN_DATA_REASON)
    if not verdict:
        return unverified_stamp(NOT_RUN_REASON)
    return {
        "provenance": Provenance.ESTIMATED.value,
        "label": Provenance.ESTIMATED.label,
        "method": PROFIT_METHOD,
    }


def store_block_for(result: Any) -> dict:
    """C11/C13 — the store block's stamp for `result`.

    Accepts a result object or a plain payload dict (the API layer passes
    its response dict, so a live response and an export of the same run
    carry the same stamp). The producer's stamp passes through untouched;
    a result that never got one derives honestly: real rows read verified,
    no rows read unverified WITH a reason (an empty block may never read
    verified — C13).
    """
    if isinstance(result, dict):
        stores = list(result.get("ebay_stores") or [])
        block = dict(result.get("ebay_stores_provenance") or {})
    else:
        stores = list(getattr(result, "ebay_stores", None) or [])
        block = dict(getattr(result, "ebay_stores_provenance", None) or {})
    if not block:
        block = {
            "provenance": Provenance.VERIFIED.value if stores
            else Provenance.UNVERIFIED.value,
            "label": Provenance.VERIFIED.label if stores
            else Provenance.UNVERIFIED.label,
        }
        if not stores:
            block["reason"] = "no seller usernames returned by the eBay search"
    return block


def _score_of(supplier: dict) -> float | None:
    """C14 — the computed score, or null when the row was never scored.

    A real 0.0 is a score and survives; a string/absent value reads null,
    because a fabricated confidence is worse than none.
    """
    value = supplier.get("match_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


_AVAILABILITY_FIELDS = (
    "in_stock", "stock_raw", "availability_url",
    "shipping_cost", "shipping_days", "shipping_raw",
)


def _supplier_field_stamps(suppliers: list) -> dict:
    """C1/C13/C14 — origin entries for the new supplier fields.

    Availability: the tier of the FIRST row that actually carries the
    value — nobody read it anywhere, so it reads unverified WITH why
    (C1: 0/"" is "not read", never a value to stamp). Match: verified
    only when every scored row reached the verified tier, because one
    unconfirmed score in the block makes the block unconfirmed (C14).
    ai_insight can never appear: normalize_stamp demotes it (C13).
    """
    rows = [s for s in suppliers if isinstance(s, dict)]
    stamps: dict[str, dict] = {}

    for name in _AVAILABILITY_FIELDS:
        carrier = next((r for r in rows if r.get(name) not in (None, "", 0)), None)
        if carrier is None:
            stamps[name] = unverified_stamp(
                f"{name} was not read on any supplier row"
            )
        else:
            stamps[name] = normalize_stamp(
                {"provenance": carrier.get("provenance") or ""},
                f"{name} carried no origin stamp",
            )

    scored = [r for r in rows if r.get("match_score") is not None]
    if not scored:
        match_stamp = unverified_stamp("no supplier row was scored")
    elif all(r.get("match_tier") == "verified" for r in scored):
        match_stamp = normalize_stamp({"provenance": "verified"}, "")
    else:
        match_stamp = unverified_stamp(
            "not every supplier row reached the verified match tier"
        )
    for name in ("match_score", "match_tier", "match_label"):
        stamps[name] = dict(match_stamp)
    return stamps


def format_to_schema(result: Any) -> dict:
    """Format a single DeepSearchResult to the user's exact JSON schema.

    Schema:
    {
      "product_name": "string",
      "category": "string",
      "most_items_sold_on_eBay": "string",
      "top_eBay_sellers": [{"name": str, "url": str}],
      "monthly_sales": "string",
      "eBay_price_range": {"min": float, "max": float, "avg": float, "median": float},
      "suppliers": [{"name": str, "item_cost": float, "link": str, "type": str, "delivery_days": str}],
      "profit_analysis": {"ebay_fees": float, "total_cost": float, "profit": float, "margin_percent": float, "verdict": str}
    }

    PR-1/PR-6: no exported eBay-side figure may sit outside the active
    range — price-range statistics are nulled when out of range and
    `band_notes` reports what was removed (PR-4). Supplier prices are
    NEVER gated (PR-1) and export in full.
    """
    # Preserve any exclusion notes an earlier gate layer already recorded.
    prior = getattr(result, "band_notes", None)
    band_notes: list[str] = [prior] if prior else []

    # Calculate eBay fees
    ebay_price = result.ebay_avg_price if in_band(result.ebay_avg_price) else 0.0
    if result.ebay_avg_price and not in_band(result.ebay_avg_price):
        band_notes.append(
            f"eBay avg price £{result.ebay_avg_price:.2f} removed (not in {band_label()} range)"
        )
    supplier_cost = result.best_supplier_price or 0.0

    # Money from the single engine source (PROFIT_CONFIG) — C1/C3.
    # With no usable in-band eBay price there is nothing to compute fees
    # or profit FROM: export nulls, never arithmetic on a gated 0.
    has_price = bool(ebay_price)
    calc = calculate_profit(ebay_price, supplier_cost)
    ebay_fees = calc["total_fees"] if has_price else None
    total_cost = (supplier_cost + calc["total_fees"]) if has_price else None
    profit = calc["profit"] if has_price else None
    margin = calc["margin"] if has_price else None

    # Format top sellers
    field_prov = _result_provenance(result)
    # C13 — the section's own stamp, reason included (a badge that does not
    # say WHY it is unverified is indistinguishable from a real check).
    sellers_section = normalize_stamp(field_prov.get("ebay_top_sellers"),
                                      NO_STAMP_REASON)
    top_sellers = []
    for seller in (result.ebay_top_sellers or [])[:5]:
        top_sellers.append({
            "name": seller.get("name", ""),
            "url": seller.get("url", ""),
            # C13 — carries its own origin; a row with no URL is unverified.
            "provenance": Provenance.VERIFIED.value
            if seller.get("url") else Provenance.UNVERIFIED.value,
            "provenance_label": Provenance.VERIFIED.label
            if seller.get("url") else Provenance.UNVERIFIED.label,
        })

    # Format suppliers — never range-gated (PR-1)
    suppliers = result.suppliers or []

    export_suppliers = []
    for supplier in suppliers:
        sup_prov = supplier.get("provenance") or Provenance.UNVERIFIED.value
        try:
            sup_prov_enum = Provenance(sup_prov)
        except ValueError:
            sup_prov_enum = Provenance.UNVERIFIED
        export_suppliers.append({
            "name": supplier.get("name", ""),
            "full_name": supplier.get("full_name", ""),
            "item_cost": supplier.get("price", 0),
            "link": supplier.get("url", ""),
            "type": supplier.get("supplier_type", "unknown"),
            "delivery_days": supplier.get("delivery_days", "unknown"),
            "seller_rating": supplier.get("seller_rating", ""),
            "seller_orders": supplier.get("seller_orders", ""),
            "product_title": supplier.get("product_title", ""),
            "image_url": supplier.get("image_url", ""),
            # C13 — provenance and its receipt travel with every row.
            "provenance": sup_prov_enum.value,
            "provenance_label": sup_prov_enum.label,
            "source_url": supplier.get("source_url") or supplier.get("url", ""),
            "source_name": supplier.get("source_name", ""),
            "match_basis": supplier.get("match_basis", ""),
            # P4 — availability as captured (C1): blank/0 is unknown, never
            # a guess; availability_url only when a stock figure was read.
            "in_stock": supplier.get("in_stock") or "",
            "stock_raw": supplier.get("stock_raw") or "",
            "availability_url": supplier.get("availability_url") or "",
            "shipping_cost": supplier.get("shipping_cost") or 0.0,
            "shipping_days": supplier.get("shipping_days") or 0,
            "shipping_raw": supplier.get("shipping_raw") or "",
            # C14 — the computed match, absent (null/blank) when unscored.
            "match_score": _score_of(supplier),
            "match_tier": supplier.get("match_tier") or "",
            "match_label": supplier.get("match_label") or "",
        })

    # Sold-history statistics (PR-1 figure type 3) — out of band becomes null,
    # never a stale/guessed number (C1: don't fabricate).
    def _stat(v: float) -> float | None:
        if not v:
            return None
        if in_band(v):
            return v
        band_notes.append(f"eBay sold statistic £{v:.2f} removed (not in band)")
        return None

    # Build output — C13: every section carries its own stamp with the
    # receipt (reason/method/source) the producer attached to it.
    demand_section = normalize_stamp(field_prov.get("ebay_total_sold_30d"),
                                     NO_STAMP_REASON)
    suppliers_section = normalize_stamp(field_prov.get("suppliers"),
                                        NO_STAMP_REASON)
    profit_section = profit_block_for(result)

    # C11 — the competitor-store block. Rows arrive already built and
    # stamped by engine.stores; here we only guarantee the key exists so a
    # consumer never has to distinguish "no stores" from "not applicable".
    stores = list(getattr(result, "ebay_stores", None) or [])
    store_block = store_block_for(result)
    # C11/C13 — the store stamp rides in the fields map too, so a consumer
    # reading provenance.fields sees the SAME stamp as the top-level block.
    field_prov["ebay_stores"] = dict(store_block)
    # P4/C14 — the new supplier fields get their own entries in the same
    # map, so a consumer reading provenance.fields sees stock/shipping
    # and match origin beside the block stamps above.
    for name, stamp in _supplier_field_stamps(suppliers).items():
        field_prov.setdefault(name, stamp)

    output = {
        "product_name": result.product_name,
        "category": result.product_category or "Unknown",
        "most_items_sold_on_eBay": result.ebay_items_sold_month or "Unknown",
        "top_eBay_sellers": top_sellers,
        "monthly_sales": result.ebay_items_sold_month or "Unknown",
        "eBay_price_range": {
            "min": _stat(result.ebay_price_min),
            "max": _stat(result.ebay_price_max),
            "avg": _stat(result.ebay_avg_price),
            "median": _stat(result.ebay_price_median),
        },
        "suppliers": export_suppliers,
        # C11 — up to 4 real eBay stores; each row carries its own
        # provenance, url_derived flag and the required count label.
        "ebay_stores": stores,
        "profit_analysis": {
            "ebay_fees": round(ebay_fees, 2) if ebay_fees is not None else None,
            "total_cost": round(total_cost, 2) if total_cost is not None else None,
            "profit": round(profit, 2) if profit is not None else None,
            "margin_percent": round(margin, 1) if margin is not None else None,
            "verdict": result.verdict or "PENDING",
        },
        # C13 — where each block came from, plus the full per-field map.
        # Every entry is the same shape: {provenance, label, ...} — the
        # same block api/provenance_block builds for a live response.
        "provenance": {
            "demand": demand_section,
            "top_eBay_sellers": sellers_section,
            "suppliers": suppliers_section,
            "ebay_stores": store_block,
            "profit_analysis": profit_section,
            "fields": field_prov,
        },
    }
    if band_notes:
        output["band_notes"] = "; ".join(band_notes)

    return output


def format_bulk_to_schema(results: list) -> list[dict]:
    """Format multiple results to the user's exact JSON schema."""
    return [format_to_schema(r) for r in results]
