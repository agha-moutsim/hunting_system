from dataclasses import dataclass, field
from typing import Optional

from config import EBAY_MARKETPLACE, FILTERS
from scrapers.base import ScrapedProduct, DemandData
from engine.profit import calculate_profit
from engine.price_gate import band_label, clamp_band, in_band


@dataclass
class FilterResult:
    name: str
    passed: bool
    actual: str
    expected: str
    verified: bool = True


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

    Verdict ladder:
      1. any verified rule broken, or profit <= 0  -> "fail"
         (a known miss can never be masked by unrelated unknowns)
      2. every rule passed                         -> "pass"
         (unverified-but-passing rows do not block; e.g. brand unknown)
      3. anything unverified and profit > 0        -> "pending"
      4. otherwise                                 -> "fail"
    """

    def __init__(self, filters: dict | None = None):
        # PR-5/PR-7: band always comes from config; missing keys backfilled.
        self.filters = clamp_band(filters)

    def evaluate(
        self,
        product: ScrapedProduct,
        demand: Optional[DemandData] = None,
        supplier_price: Optional[float] = None,
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

        # --- Condition filter ---
        condition_pass = product.condition.lower() == "new"
        filters.append(FilterResult(
            name="Condition",
            passed=condition_pass,
            actual=product.condition,
            expected="New",
            verified=product.verified,
        ))

        # --- Price filter (eBay listing price) ---
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

        # --- Supplier Price filter (supplier cost in band, PR-1 figure type 2) ---
        if supplier_price is not None:
            filters.append(FilterResult(
                name="Supplier Price",
                passed=in_band(supplier_price),
                actual=f"£{supplier_price:.2f}",
                expected=band_label(),
                verified=True,
            ))

        # --- Demand filter (30d) ---
        if demand and demand.sold_count_30d is not None:
            d30_pass = demand.sold_count_30d >= self.filters["demand_min_30d"]
            filters.append(FilterResult(
                name="Demand (30d)",
                passed=d30_pass,
                actual=f"{demand.sold_count_30d} sold",
                expected=f"\u2265{self.filters['demand_min_30d']} sold",
                verified=demand.verified,
            ))
        else:
            filters.append(FilterResult(
                name="Demand (30d)",
                passed=False,
                actual="N/A",
                expected=f"\u2265{self.filters['demand_min_30d']} sold",
                verified=False,
            ))

        # --- Demand filter (7d) ---
        if demand and demand.sold_count_7d is not None:
            d7_pass = demand.sold_count_7d >= self.filters["demand_min_7d"]
            filters.append(FilterResult(
                name="Demand (7d)",
                passed=d7_pass,
                actual=f"{demand.sold_count_7d} sold",
                expected=f"\u2265{self.filters['demand_min_7d']} sold",
                verified=demand.verified,
            ))
        else:
            filters.append(FilterResult(
                name="Demand (7d)",
                passed=False,
                actual="N/A",
                expected=f"\u2265{self.filters['demand_min_7d']} sold",
                verified=False,
            ))

        # --- Profit ---
        profit_info = {"profit": 0.0, "margin": 0.0}
        if supplier_price is not None:
            profit_info = calculate_profit(product.price, supplier_price)

        # --- Margin filter ---
        margin_min = self.filters.get("margin_min", 25.0)
        margin_pass = profit_info["margin"] >= margin_min
        filters.append(FilterResult(
            name="Margin",
            passed=margin_pass,
            actual=f"{profit_info['margin']:.1f}%",
            expected=f"\u2265{margin_min}%",
            verified=supplier_price is not None,
        ))

        # --- Delivery filter ---
        delivery_min = self.filters.get("delivery_min", 3)
        delivery_max = self.filters.get("delivery_target_max", 8)
        delivery_exception_max = self.filters.get("delivery_exception_max", 25)
        demand_strong = self.filters.get("demand_strong_30d", 30)

        # Check if product has delivery info
        delivery_days = getattr(product, "delivery_days_max", None)
        if delivery_days is not None:
            # Exception: high-demand products can have longer delivery
            demand_30d = demand.sold_count_30d if demand and demand.sold_count_30d else 0
            if demand_30d >= demand_strong and delivery_days <= delivery_exception_max:
                delivery_pass = True
                delivery_note = f" (exception: {demand_30d} sold/month)"
            else:
                delivery_pass = delivery_days <= delivery_max
                delivery_note = ""
            filters.append(FilterResult(
                name="Delivery",
                passed=delivery_pass,
                actual=f"{delivery_days} days{delivery_note}",
                expected=f"{delivery_min}-{delivery_max} days",
                verified=True,
            ))
        else:
            filters.append(FilterResult(
                name="Delivery",
                passed=False,
                actual="Unknown",
                expected=f"{delivery_min}-{delivery_max} days",
                verified=False,
            ))

        # --- Brand filter (generic only) ---
        brand_filter = self.filters.get("brand_filter", "generic_only")
        if brand_filter == "generic_only":
            # Check if product has brand info
            brand = getattr(product, "brand", None)
            if brand:
                brand_lower = brand.lower()
                # Known brand indicators
                brand_indicators = ["apple", "samsung", "sony", "nike", "adidas", "lg", "bose",
                                   "philips", "dyson", "amazon basics", "microsoft", "google"]
                is_branded = any(b in brand_lower for b in brand_indicators)
                filters.append(FilterResult(
                    name="Brand",
                    passed=not is_branded,
                    actual=f"Branded: {brand}" if is_branded else "Generic",
                    expected="Generic (no brand)",
                    verified=True,
                ))
            else:
                # No brand info - can't verify
                filters.append(FilterResult(
                    name="Brand",
                    passed=True,
                    actual="No brand detected",
                    expected="Generic (no brand)",
                    verified=False,
                ))

        # --- Verdict ---
        all_passed = all(f.passed for f in filters)
        any_unverified = any(not f.verified for f in filters)
        profit_positive = profit_info["profit"] > 0
        # A rule we KNOW is broken always wins: a verified failure can never
        # be downgraded to "pending" by some unrelated unverified row.
        verified_failure = any(not f.passed and f.verified for f in filters)

        if verified_failure or not profit_positive:
            verdict_str = "fail"
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
