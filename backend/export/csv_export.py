"""CSV export for eBay Hunter results."""

import csv
import io
from typing import Any

from engine.profit import calculate_profit
from engine.provenance import Provenance
from engine.stores import MAX_STORES
from export.format import store_block_for


def _prov_of(result: Any, name: str) -> Provenance:
    """C13 — provenance of one field; a missing stamp reads as unverified."""
    fp = getattr(result, "field_provenance", None) or {}
    raw = (fp.get(name) or {}).get("provenance", "")
    try:
        return Provenance(raw)
    except ValueError:
        return Provenance.UNVERIFIED


def _store_count_cells(result: Any) -> list:
    """C11 — padded to MAX_STORES so header and row stay column-aligned.

    A short store list MUST still emit MAX_STORES cells (blanks), or every
    later column silently shifts left — the failure mode of a CSV header
    whose width depends on data the row may not have.
    """
    stores = (getattr(result, "ebay_stores", None) or [])[:MAX_STORES]
    cells = [str(s.get("sold_count", "")) for s in stores]
    return cells + [""] * (MAX_STORES - len(cells))


def _store_url_cells(result: Any) -> list:
    """C11 — the derived storefront URLs, same padding rule as the counts."""
    stores = (getattr(result, "ebay_stores", None) or [])[:MAX_STORES]
    cells = [str(s.get("url", "")) for s in stores]
    return cells + [""] * (MAX_STORES - len(cells))


def _store_prov_cell(result: Any) -> str:
    """C11/C13 — the store block's stamp as one CSV cell.

    Its own label when the block carries one, else the tier's label, else
    Unverified — a cell is never blank and never claims more than the block.
    """
    block = store_block_for(result)
    if block.get("label"):
        return str(block["label"])
    try:
        return Provenance(str(block.get("provenance") or "").strip().lower()).label
    except ValueError:
        return Provenance.UNVERIFIED.label


# --- Supplier block columns (P4 availability + C14 match) -------------------
#
# C11/C13/C14 — a supplier block is described ONCE, as a tuple of
# (header suffix, cell reader). The header cells and the data cells are
# both generated from that tuple, so the two widths cannot drift: a
# column added here lands on both sides or on neither. Readers receive
# the supplier dict, or None when the row has no such supplier, and
# return "" for anything absent or unknown — blank is honest, a guess
# is not (C1). Match cells only ever repeat what engine/match.py
# computed (C14): a score prints at 3 dp or not at all.

def _cell_name(supplier: Any):
    if supplier is None:
        return ""
    return supplier.get("name") or ""


def _cell_price(supplier: Any):
    if supplier is None:
        return ""
    try:
        return f"£{float(supplier.get('price') or 0):.2f}"
    except (TypeError, ValueError):
        # C1 — an unparseable price is blank, never a fabricated £0.00.
        return ""


def _cell_url(supplier: Any):
    if supplier is None:
        return ""
    return supplier.get("url") or ""


def _cell_type(supplier: Any):
    if supplier is None:
        return ""
    return supplier.get("supplier_type") or ""


def _cell_delivery(supplier: Any):
    if supplier is None:
        return ""
    value = supplier.get("delivery_days", "")
    # Keep 0 and other real values; only a missing key/null reads blank.
    return "" if value is None else value


def _cell_stock(supplier: Any):
    """C1 — the state as captured; unknown prints blank, never a guess."""
    if supplier is None:
        return ""
    return supplier.get("in_stock") or ""


def _cell_stock_raw(supplier: Any):
    """C13 — the exact source text the stock state was read from."""
    if supplier is None:
        return ""
    return supplier.get("stock_raw") or ""


def _cell_shipping_cost(supplier: Any):
    """C1 — 0.0 means unknown, so it prints blank, never £0.00; the
    source-text column beside it is what tells free from unread."""
    if supplier is None:
        return ""
    try:
        cost = float(supplier.get("shipping_cost") or 0)
    except (TypeError, ValueError):
        return ""
    return f"£{cost:.2f}" if cost else ""


def _cell_shipping_days(supplier: Any):
    """C1 — 0 days means unknown: blank, never a fabricated lead time."""
    if supplier is None:
        return ""
    try:
        days = int(supplier.get("shipping_days") or 0)
    except (TypeError, ValueError):
        return ""
    return str(days) if days else ""


def _cell_shipping_raw(supplier: Any):
    """C13 — the exact source text; free vs unread is told apart HERE."""
    if supplier is None:
        return ""
    return supplier.get("shipping_raw") or ""


def _cell_match_score(supplier: Any):
    """C14 — the computed score at 3 dp; blank only when the row carries
    none. A real 0.000 prints: it is a score, not an absence."""
    if supplier is None:
        return ""
    value = supplier.get("match_score")
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""


def _cell_match_tier(supplier: Any):
    """C14 — the tier the matcher assigned; no match row means blank."""
    if supplier is None:
        return ""
    return supplier.get("match_tier") or ""


def _cell_match_label(supplier: Any):
    """C14 — the fixed display label ("verified match" / …); blank if absent."""
    if supplier is None:
        return ""
    return supplier.get("match_label") or ""


# The single export's full supplier block: base columns, then the new
# availability/match tail. Prefixing with "Supplier 1"/"Supplier 2"
# produces every header for that block.
_SINGLE_SUPPLIER_COLS = (
    ("", _cell_name),
    (" Cost", _cell_price),
    (" URL", _cell_url),
    (" Type", _cell_type),
    (" Delivery", _cell_delivery),
    (" Stock", _cell_stock),
    (" Stock (source text)", _cell_stock_raw),
    (" Shipping Cost", _cell_shipping_cost),
    (" Shipping Days", _cell_shipping_days),
    (" Shipping (source text)", _cell_shipping_raw),
    (" Match Score", _cell_match_score),
    (" Match Tier", _cell_match_tier),
    (" Match Label", _cell_match_label),
)

# The bulk row reports ONE supplier — "Best Supplier"/"Supplier Cost",
# whose cost is read from best_supplier_price rather than the row — so
# only the new tail is shared with the single export, from the SAME
# tuple: the two exports cannot disagree on its width.
_BULK_SUPPLIER_TAIL = _SINGLE_SUPPLIER_COLS[5:]


def _block_headers(cols, prefix: str) -> list:
    """Header cells for one supplier block, from the block's own spec."""
    return [f"{prefix}{suffix}" for suffix, _ in cols]


def _block_cells(cols, supplier: Any) -> list:
    """Data cells for one supplier block, from the block's own spec."""
    return [read(supplier) for _, read in cols]


def _supplier_at(suppliers: list, index: int) -> Any:
    """The i-th supplier, or None — a short list yields blanks, not a shift."""
    return suppliers[index] if len(suppliers) > index else None


def export_to_csv(result: Any) -> str:
    """Export a single result to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Product Name",
        "Category",
        "eBay Sold (30d)",
        "eBay Sold (7d)",
        "Price Min",
        "Price Max",
        "Price Avg",
        "Price Median",
        "Top Seller 1",
        "Top Seller 1 URL",
        "Top Seller 2",
        "Top Seller 2 URL",
        # C11/C14 — supplier blocks from the shared spec: header and row
        # are built from the same tuple, so the widths cannot drift.
        *_block_headers(_SINGLE_SUPPLIER_COLS, "Supplier 1"),
        *_block_headers(_SINGLE_SUPPLIER_COLS, "Supplier 2"),
        "eBay Fees",
        "Total Cost",
        "Profit",
        "Margin %",
        "Verdict",
        # C13 — every row says where it came from.
        "Demand Provenance",
        "Top Sellers Provenance",
        "Suppliers Provenance",
        "Profit Provenance",
        # C11 — the store block's own stamp (an empty block reads Unverified).
        "Stores Provenance",
        # C11 — up to 4 competitor stores. The column header IS the required
        # count label, so the number can never be read as eBay's sold count.
        *[
            f"Store {i} · observed listings (search window, cap 50)"
            for i in range(1, MAX_STORES + 1)
        ],
        *[f"Store {i} URL" for i in range(1, MAX_STORES + 1)],
    ])

    # Data row
    top_sellers = result.ebay_top_sellers or []
    suppliers = result.suppliers or []

    # Money from the single engine source (PROFIT_CONFIG) — C1/C3.
    # No usable eBay price = nothing to compute from (post-gate None or 0):
    # money cells stay blank rather than arithmetic on a fabricated 0.
    avg_ok = bool(result.ebay_avg_price)
    calc = calculate_profit(
        result.ebay_avg_price or 0, result.best_supplier_price or 0
    )
    ebay_fees = calc["total_fees"]
    total_cost = (result.best_supplier_price or 0) + calc["total_fees"]
    profit = calc["profit"]
    margin = calc["margin"]

    writer.writerow([
        result.product_name,
        result.product_category or "Unknown",
        result.ebay_total_sold_30d or result.ebay_items_sold_month or "",
        result.ebay_total_sold_7d or "",
        f"£{result.ebay_price_min:.2f}" if result.ebay_price_min else "",
        f"£{result.ebay_price_max:.2f}" if result.ebay_price_max else "",
        f"£{result.ebay_avg_price:.2f}" if result.ebay_avg_price else "",
        f"£{result.ebay_price_median:.2f}" if result.ebay_price_median else "",
        top_sellers[0].get("name", "") if len(top_sellers) > 0 else "",
        top_sellers[0].get("url", "") if len(top_sellers) > 0 else "",
        top_sellers[1].get("name", "") if len(top_sellers) > 1 else "",
        top_sellers[1].get("url", "") if len(top_sellers) > 1 else "",
        # C11 — one block per supplier; a short list yields blank cells
        # (never a shifted row) because the width is the spec's, not the data's.
        *_block_cells(_SINGLE_SUPPLIER_COLS, _supplier_at(suppliers, 0)),
        *_block_cells(_SINGLE_SUPPLIER_COLS, _supplier_at(suppliers, 1)),
        f"£{ebay_fees:.2f}" if avg_ok else "",
        f"£{total_cost:.2f}" if avg_ok else "",
        f"£{profit:.2f}" if avg_ok else "",
        f"{margin:.1f}%" if avg_ok else "",
        result.verdict or "PENDING",
        # C13 — provenance for each block.
        _prov_of(result, "ebay_total_sold_30d").label,
        _prov_of(result, "ebay_top_sellers").label,
        _prov_of(result, "suppliers").label,
        # Profit is always computed from PROFIT_CONFIG — an estimate (C13).
        Provenance.ESTIMATED.label,
        # C11 — the store stamp travels with the store columns beside it.
        _store_prov_cell(result),
        # C11 — stores come pre-built and stamped by engine.stores.
        *_store_count_cells(result),
        *_store_url_cells(result),
    ])

    # PR-4: exclusions must be reported even in CSV form.
    prior_notes = getattr(result, "band_notes", None)
    if prior_notes:
        writer.writerow([])
        writer.writerow([f"NOTE: {prior_notes}"])

    return output.getvalue()


def export_bulk_to_csv(results: list) -> str:
    """Export multiple results to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Product Name",
        "Category",
        "eBay Sold (30d)",
        "Price Avg",
        "Best Supplier",
        "Supplier Cost",
        # C11/C14 — the shared tail (stock/shipping/match), from the SAME
        # spec tuple the single export uses: one width, two exports.
        *_block_headers(_BULK_SUPPLIER_TAIL, "Supplier"),
        "eBay Fees",
        "Profit",
        "Margin %",
        "Verdict",
        # C13 — every factual block this row carries declares its origin
        # (the bulk row has no seller columns, so no seller stamp either).
        "Demand Provenance",
        "Suppliers Provenance",
        "Profit Provenance",
        # C11 — the store block's own stamp (an empty block reads Unverified).
        "Stores Provenance",
        # C11 — Bulk returns stores too (spec names Bulk explicitly).
        *[
            f"Store {i} · observed listings (search window, cap 50)"
            for i in range(1, MAX_STORES + 1)
        ],
        *[f"Store {i} URL" for i in range(1, MAX_STORES + 1)],
    ])

    # Data rows
    for result in results:
        # Money from the single engine source (PROFIT_CONFIG) — C1/C3
        avg_ok = bool(result.ebay_avg_price)
        supplier_cost = result.best_supplier_price or 0
        calc = calculate_profit(result.ebay_avg_price or 0, supplier_cost)
        ebay_fees = calc["total_fees"]
        total_cost = supplier_cost + calc["total_fees"]
        profit = calc["profit"]
        margin = calc["margin"]

        # Find best supplier — its dict rides along for the tail columns,
        # so the block describes the SAME row the name/cost cells name.
        best_supplier = ""
        best_row = None
        if result.suppliers:
            valid = [s for s in result.suppliers if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
            if valid:
                best = min(valid, key=lambda s: s["price"])
                best_supplier = best.get("name", "")
                best_row = best

        writer.writerow([
            result.product_name,
            result.product_category or "Unknown",
            result.ebay_total_sold_30d or result.ebay_items_sold_month or "",
            f"£{result.ebay_avg_price:.2f}" if result.ebay_avg_price else "",
            best_supplier,
            f"£{supplier_cost:.2f}" if supplier_cost else "",
            # C11 — the supplier tail: blanks (never a shift) when nothing won.
            *_block_cells(_BULK_SUPPLIER_TAIL, best_row),
            f"£{ebay_fees:.2f}" if avg_ok else "",
            f"£{profit:.2f}" if avg_ok else "",
            f"{margin:.1f}%" if avg_ok else "",
            result.verdict or "PENDING",
            _prov_of(result, "ebay_total_sold_30d").label,
            _prov_of(result, "suppliers").label,
            # Profit is always computed from PROFIT_CONFIG — an estimate (C13),
            # same wording as the single export.
            Provenance.ESTIMATED.label,
            # C11 — the store stamp travels with the store columns beside it.
            _store_prov_cell(result),
            *_store_count_cells(result),
            *_store_url_cells(result),
        ])

    return output.getvalue()
