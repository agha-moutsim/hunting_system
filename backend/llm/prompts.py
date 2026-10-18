"""
Prompt templates for the eBay product sourcing LLM analyzer.

Length is not cosmetic here. Measured on this machine (2026-10-08) with
the payload this module builds: 97.5s end to end, of which 39.2s was
prompt evaluation of 514 tokens and 57.5s was generating 203. Roughly
half the prompt was our own boilerplate explaining the JSON shape, and
the box this runs on generates at ~3.5 tok/s - so every sentence of that
boilerplate costs real seconds.

What was cut: the markdown headers, the repeated "one sentence" prose
around each field, and the per-supplier verbosity.
What was NOT cut, and must never be: the enums (they are the schema),
the data (the model may not reason about what it cannot see), or the
no-fabrication rule, which lives in SYSTEM_PROMPT.
"""

SYSTEM_PROMPT = (
    "You are an e-commerce product analysis engine evaluating eBay products "
    "for dropshipping viability. "
    "Respond with valid JSON only - no markdown, no explanation outside the JSON. "
    "You produce ANALYSIS and reasoning only: never invent a supplier name, a "
    "seller name, a price, a URL or a stock figure. Anything factual must come "
    "from the supplied data. When a value is absent from that data, report it "
    "as unknown rather than estimating it."
)

ANALYSIS_PROMPT = """\
Analyze this eBay listing and its supplier matches for dropshipping viability.

eBay listing
  {title}
  Price: GBP {price} | Condition: {condition} | Seller: {seller}

Demand, last 30 days
  sold {sold_30d} (7d {sold_7d}) | avg sold price GBP {avg_price} | sold range GBP {low_price}-{high_price}

Live listings competing right now — SUPPLY, not sales. Nothing in this block sold.
  {active_listings} in-band New listings | avg asking GBP {avg_active_price} | asking range GBP {low_active_price}-{high_active_price}

Supplier matches{supplier_block}

Reply with ONLY this JSON, no markdown:
{{
  "brand_verdict": "generic"|"branded"|"ambiguous",
  "brand_name": "<brand named in the title, else empty string>",
  "brand_reasoning": "<one sentence>",
  "demand_assessment": "strong"|"moderate"|"weak"|"spike",
  "demand_reasoning": "<one sentence>",
  "best_supplier_match": {{
    "name": "<ONE name copied EXACTLY from the list above, or omit this object entirely if none fits>",
    "confidence": 0.0,
    "reasoning": "<one sentence>"
  }},
  "supplier_type": "wholesaler"|"dropship"|"retailer"|"unknown",
  "supplier_type_reasoning": "<one sentence>",
  "recommended_action": "source"|"skip"|"investigate",
  "risk_flags": ["<concern>"]
}}
"""


def format_supplier_block(suppliers: list[dict]) -> str:
    """Format supplier match dicts into the prompt block."""
    if not suppliers:
        return "\nNo supplier matches found."

    lines: list[str] = []
    for i, s in enumerate(suppliers, 1):
        lines.append(
            f"\n{i}. {s.get('name', 'Unknown')} | GBP {s.get('price', '?')} | "
            f"{s.get('delivery_days', '?')}d | {s.get('source', '?')}"
        )
    return "".join(lines)


def build_analysis_prompt(
    product: dict,
    demand: dict,
    suppliers: list[dict],
) -> str:
    """Assemble the full analysis prompt from product/demand/supplier dicts."""
    supplier_block = format_supplier_block(suppliers)

    return ANALYSIS_PROMPT.format(
        title=product.get("title", "N/A"),
        price=product.get("price", "N/A"),
        # C10/C13 - never default the condition. The scraped value is passed
        # through verbatim; a missing one reads as "unknown", because a
        # silent "New" here would tell the model the gate already passed.
        condition=product.get("condition") or "unknown",
        seller=product.get("seller", "Unknown"),
        sold_30d=demand.get("sold_count_30d", "unknown"),
        sold_7d=demand.get("sold_count_7d", "unknown"),
        avg_price=demand.get("avg_sold_price", "unknown"),
        low_price=demand.get("lowest_sold_price", "unknown"),
        high_price=demand.get("highest_sold_price", "unknown"),
        # The supply-side block, named apart from the sold figures above so the
        # model cannot read a live asking price as evidence that something sold
        # — which is what the previous single "avg ... range" line invited.
        active_listings=demand.get("active_listings_in_band", "unknown"),
        avg_active_price=demand.get("avg_active_price", "unknown"),
        low_active_price=demand.get("lowest_active_price", "unknown"),
        high_active_price=demand.get("highest_active_price", "unknown"),
        supplier_block=supplier_block,
    )
