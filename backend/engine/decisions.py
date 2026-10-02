from dataclasses import dataclass, field
from typing import Optional

from config import EBAY_MARKETPLACE
from scrapers.base import ScrapedProduct, DemandData
from engine.profit import calculate_profit
from engine.price_gate import clamp_band
from engine.condition_gate import active_condition, condition_passes


@dataclass
class FilterResult:
    name: str
    passed: bool
    actual: str
    expected: str
    verified: bool = True
    advisory: bool = False


@dataclass
class Verdict:
    verdict: str  # "pass", "fail", "pending"
    filters: list[FilterResult] = field(default_factory=list)
    profit: float = 0.0
    margin: float = 0.0
    scorecard: str = ""


class DecisionEngine:
    """Evaluate a product against all sourcing filters and produce a verdict.

    This is the ONE decision rule (CONSTRAINTS.md + CONSTRAINTS_PRICING.md)
    every feature adapts its evidence to — deep search and hunter must not
    re-derive their own rules.

    Verdict ladder (computed over GATING rows only; advisory rows such as
    Delivery are shown but never decide):
      1. any verified rule broken, or profit <= 0  -> "fail"
         (a known miss can never be masked by unrelated unknowns)
      2. the 7-day demand figure is unverified     -> "pending"
         (C4: without purchase-history data we never assume — estimates hold)
      3. every rule passed                         -> "pass"
         (other unverified-but-passing rows do not block; e.g. no brand name)
      4. anything unverified and profit > 0        -> "pending"
      5. otherwise                                 -> "fail"

    Rules: price gate = active range (PR-5/PR-7); supplier price is NEVER
    gated (display + margin decide); brand = VeRO check on the extracted
    brand name (C5); delivery = advisory comparison (C-new).
    """

    def __init__(self, filters: dict | None = None):
        # Valid user range kept, invalid falls back to defaults (PR-5/PR-7).
        self.filters = clamp_band(filters)

    def evaluate(
        self,
        product: ScrapedProduct,
        demand: Optional[DemandData] = None,
        supplier_price: Optional[float] = None,
        supplier_delivery_days: Optional[int] = None,
        competitor_store_count: Optional[int] = None,
        competitor_stores_verified: bool = True,
    ) -> Verdict:
        filters: list[FilterResult] = []

        # --- Marketplace filter ---
        marketplace_pass = "ebay" in product.source.lower() and "uk" in (
            product.source.lower() + EBAY_MARKETPLACE.lower()
        )
        filters.append(FilterResult(
            name="Marketplace",
            passed=marketplace_pass,
            actual=product.source,
            expected="eBay UK",
            verified=product.verified,
        ))

        # --- Condition filter (C10) ---
        # Reads the ACTIVE condition rather than a hardcoded "new"; a blank
        # condition fails because normalize_condition('') never equals it.
        required_condition = active_condition(self.filters)
        condition_ok = condition_passes(product.condition, required_condition)
        filters.append(FilterResult(
            name="Condition",
            passed=condition_ok,
            actual=product.condition or "(none)",
            expected=required_condition,
            # A condition we could not read is UNVERIFIED, not a known miss —
            # C1: never claim knowledge we don't have.
            verified=product.verified and bool(product.condition),
        ))

        # --- Price filter (eBay listing price vs active range) ---
        price_in_range = (
            self.filters["price_min"] <= product.price <= self.filters["price_max"]
        )
        filters.append(FilterResult(
            name="Price",
            passed=price_in_range,
            actual=f"£{product.price:.2f}",
            expected=f"£{self.filters['price_min']:.2f}–£{self.filters['price_max']:.2f}",
            verified=product.verified,
        ))

        # --- Demand filter (30d) ---
        if demand and demand.sold_count_30d is not None:
            d30_pass = demand.sold_count_30d >= self.filters["demand_min_30d"]
            filters.append(FilterResult(
                name="Demand (30d)",
                passed=d30_pass,
                actual=f"{demand.sold_count_30d} sold",
                expected=f"≥{self.filters['demand_min_30d']} sold",
                verified=demand.verified,
            ))
        else:
            filters.append(FilterResult(
                name="Demand (30d)",
                passed=False,
                actual="N/A",
                expected=f"≥{self.filters['demand_min_30d']} sold",
                verified=False,
            ))

        # --- Demand filter (7d) ---
        # P5: a browser purchase-history capture verifies the 7-day figure on
        # its own (demand.verified_7d); without one we keep the demand row's
        # own verified status. The 30-day row above is untouched.
        d7_verified = getattr(demand, "verified_7d", None) if demand else None
        if d7_verified is None:
            d7_verified = demand.verified if demand else False
        if demand and demand.sold_count_7d is not None:
            d7_pass = demand.sold_count_7d >= self.filters["demand_min_7d"]
            filters.append(FilterResult(
                name="Demand (7d)",
                passed=d7_pass,
                actual=f"{demand.sold_count_7d} sold",
                expected=f"≥{self.filters['demand_min_7d']} sold",
                verified=d7_verified,
            ))
        else:
            filters.append(FilterResult(
                name="Demand (7d)",
                passed=False,
                actual="N/A",
                expected=f"≥{self.filters['demand_min_7d']} sold",
                verified=False,
            ))

        # --- Profit ---
        # The supplier's postage is part of the cost of doing this deal, and
        # every caller goes to the trouble of reading it off the source and
        # passing it in. It used to be dropped here, so the headline profit
        # and the margin were overstated by exactly the postage on every
        # product that charges it. 0.0 means UNREAD, not free - calculate_profit
        # reports the figure as incomplete in that case (C1/C13).
        profit_info = {"profit": 0.0, "margin": 0.0}
        if supplier_price is not None:
            profit_info = calculate_profit(
                product.price,
                supplier_price,
                shipping_cost=getattr(product, "shipping_cost", 0.0) or 0.0,
            )

        # --- Margin filter ---
        margin_min = self.filters.get("margin_min", 25.0)
        margin_pass = profit_info["margin"] >= margin_min
        filters.append(FilterResult(
            name="Margin",
            passed=margin_pass,
            actual=f"{profit_info['margin']:.1f}%",
            expected=f"≥{margin_min}%",
            verified=supplier_price is not None,
        ))

        # --- Delivery (ADVISORY, C-new: never decides the verdict) ---
        delivery_min = self.filters.get("delivery_min", 3)
        delivery_max = self.filters.get("delivery_target_max", 8)
        product_days = getattr(product, "delivery_days_max", None)
        if product_days is not None and supplier_delivery_days is not None:
            delivery_actual = f"eBay {product_days}d · Supplier {supplier_delivery_days}d"
        elif product_days is not None:
            delivery_actual = f"eBay {product_days}d · Supplier unknown"
        elif supplier_delivery_days is not None:
            delivery_actual = f"eBay unknown · Supplier {supplier_delivery_days}d"
        else:
            delivery_actual = "Unknown"
        delivery_days_known = product_days if product_days is not None else supplier_delivery_days
        delivery_pass = (
            delivery_days_known is not None and delivery_days_known <= delivery_max
        )
        filters.append(FilterResult(
            name="Delivery (advisory)",
            passed=delivery_pass,
            actual=delivery_actual,
            expected=f"{delivery_min}-{delivery_max} days (for info only)",
            verified=product_days is not None,
            advisory=True,
        ))

        # --- Competition (ADVISORY: C11 count, never a rule) ---
        # There is no user-set "maximum competitors" threshold anywhere in
        # config, and inventing one to fail products on would be a fabricated
        # business rule. So the count is reported, never gated - and zero is
        # reported as a DEMAND WARNING, because "nobody else is selling this"
        # is what no demand looks like, not an open field.
        if competitor_store_count is not None:
            n = int(competitor_store_count)
            if n <= 0:
                competition_actual = "No competitor stores found"
                competition_note = (
                    "treat as a demand warning, not an opportunity"
                )
            else:
                competition_actual = f"{n} competitor store{'s' if n != 1 else ''} found"
                competition_note = (
                    "broadened search, so this is a floor not a total"
                    if not competitor_stores_verified
                    else "counted from the sold-listing search"
                )
            filters.append(FilterResult(
                name="Competition",
                # Advisory rows are excluded from the verdict below; `passed`
                # is reported only so a renderer has something to colour by,
                # and it never reaches gating.
                passed=n > 0,
                actual=competition_actual,
                expected=f"informational only - {competition_note}",
                verified=bool(competitor_stores_verified),
                advisory=True,
            ))

        # --- Brand filter (VeRO-based, C5) ---
        brand_name = getattr(product, "brand", None)
        if brand_name:
            from utils.vero import check_vero
            vero_status = check_vero(brand_name)
            if vero_status == "registered":
                filters.append(FilterResult(
                    name="Brand",
                    passed=False,
                    actual=f"{brand_name} — registered on VeRO",
                    expected="Not registered on VeRO",
                    verified=True,
                ))
            elif vero_status == "not_registered":
                filters.append(FilterResult(
                    name="Brand",
                    passed=True,
                    actual=f"{brand_name} — not on VeRO",
                    expected="Not registered on VeRO",
                    verified=True,
                ))
            else:
                filters.append(FilterResult(
                    name="Brand",
                    passed=False,
                    actual=f"{brand_name} — VeRO check unavailable",
                    expected="Not registered on VeRO",
                    verified=False,
                ))
        else:
            filters.append(FilterResult(
                name="Brand",
                passed=True,
                actual="No brand name detected",
                expected="Not registered on VeRO",
                verified=False,
            ))

        # --- Verdict (over gating rows only) ---
        gating = [f for f in filters if not f.advisory]
        all_passed = all(f.passed for f in gating)
        any_unverified = any(not f.verified for f in gating)
        profit_positive = profit_info["profit"] > 0
        # A rule we KNOW is broken always wins: a verified failure can never
        # be downgraded to "pending" by some unrelated unverified row.
        verified_failure = any(not f.passed and f.verified for f in gating)
        # C4: a 7-day figure with no purchase-history capture behind it holds
        # the verdict at "pending" — never PASS on an assumed count.
        d7_row = next((f for f in gating if f.name == "Demand (7d)"), None)
        d7_unverified = d7_row is not None and not d7_row.verified

        if verified_failure or not profit_positive:
            verdict_str = "fail"
        elif d7_unverified:
            verdict_str = "pending"
        elif all_passed:
            verdict_str = "pass"
        elif any_unverified:
            verdict_str = "pending"
        else:
            verdict_str = "fail"

        return Verdict(
            verdict=verdict_str,
            filters=filters,
            profit=profit_info["profit"],
            margin=profit_info["margin"],
        )
