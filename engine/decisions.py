from dataclasses import dataclass, field
from typing import Optional

from config import EBAY_MARKETPLACE, FILTERS
from scrapers.base import ScrapedProduct, DemandData
from engine.profit import calculate_profit


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
    """Evaluate a product against all sourcing filters and produce a verdict."""

    def __init__(self, filters: dict | None = None):
        self.filters = filters or FILTERS

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

        # --- Price filter ---
        price_in_range = (
            self.filters["price_min"] <= product.price <= self.filters["price_max"]
        )
        filters.append(FilterResult(
            name="Price",
            passed=price_in_range,
            actual=f"\u00a3{product.price:.2f}",
            expected=f"\u00a3{self.filters['price_min']:.2f}\u2013\u00a3{self.filters['price_max']:.2f}",
            verified=product.verified,
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

        # --- Verdict ---
        all_passed = all(f.passed for f in filters)
        any_unverified = any(not f.verified for f in filters)
        verdict_str = "pass" if all_passed and profit_info["profit"] > 0 else (
            "pending" if any_unverified else "fail"
        )

        return Verdict(
            verdict=verdict_str,
            filters=filters,
            profit=profit_info["profit"],
            margin=profit_info["margin"],
        )
