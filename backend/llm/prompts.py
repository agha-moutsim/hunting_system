"""
Prompt templates for the eBay product sourcing LLM analyzer.
"""

SYSTEM_PROMPT = (
    "You are an e-commerce product analysis engine. "
    "You evaluate eBay products for dropshipping viability. "
    "Always respond with valid JSON only — no markdown, no explanation outside the JSON."
)

ANALYSIS_PROMPT = """\
Analyze this eBay product listing and supplier matches for dropshipping viability.

## eBay Product
Title: {title}
Price: £{price}
Condition: {condition}
Seller: {seller}

## Demand Data
Sold in last 30 days: {sold_30d}
Sold in last 7 days: {sold_7d}
Average sold price: £{avg_price}
Price range: £{low_price} – £{high_price}

## Supplier Matches (ranked by relevance)
{supplier_block}

Respond with ONLY this JSON structure:
{{
  "brand_verdict": "generic" | "branded" | "ambiguous",
  "brand_name": "<specific brand name mentioned in the title or specs, else empty string>",
  "brand_reasoning": "<one sentence>",
  "demand_assessment": "strong" | "moderate" | "weak" | "spike",
  "demand_reasoning": "<one sentence>",
  "best_supplier_match": {{
    "name": "<supplier name>",
    "confidence": <0.0 to 1.0>,
    "reasoning": "<one sentence>"
  }},
  "supplier_type": "wholesaler" | "dropship" | "retailer" | "unknown",
  "supplier_type_reasoning": "<one sentence>",
  "recommended_action": "source" | "skip" | "investigate",
  "risk_flags": ["<any concerns>"]
}}
"""


def format_supplier_block(suppliers: list[dict]) -> str:
    """Format supplier match dicts into the prompt block."""
    if not suppliers:
        return "No supplier matches found."

    lines: list[str] = []
    for i, s in enumerate(suppliers, 1):
        lines.append(
            f"{i}. {s.get('name', 'Unknown')} — "
            f"£{s.get('price', '?')} | "
            f"Delivery: {s.get('delivery_days', '?')} days | "
            f"Source: {s.get('source', '?')}"
        )
    return "\n".join(lines)


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
        condition=product.get("condition", "New"),
        seller=product.get("seller", "Unknown"),
        sold_30d=demand.get("sold_count_30d", "unknown"),
        sold_7d=demand.get("sold_count_7d", "unknown"),
        avg_price=demand.get("avg_sold_price", "unknown"),
        low_price=demand.get("lowest_sold_price", "unknown"),
        high_price=demand.get("highest_sold_price", "unknown"),
        supplier_block=supplier_block,
    )
