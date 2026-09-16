"""
Standalone profit calculator — analyze profitability without scraping.

Usage:
    from profit_calc import ProfitCalculator
    calc = ProfitCalculator()
    result = calc.calculate(ebay_price=15.99, supplier_price=8.50)
    print(result)
"""

from dataclasses import dataclass
from config import PROFIT_CONFIG, FILTERS


@dataclass
class ProfitResult:
    ebay_price: float
    supplier_price: float
    ebay_fee: float
    returns_buffer: float
    total_costs: float
    profit: float
    margin: float
    roi: float
    passes_price_filter: bool
    passes_profit_filter: bool
    recommendation: str


class ProfitCalculator:
    """Calculate profit and ROI for product reselling."""

    def __init__(
        self,
        ebay_fee_pct: float = None,
        returns_buffer_pct: float = None,
        min_profit: float = 2.0,
    ):
        self.ebay_fee_pct = ebay_fee_pct or PROFIT_CONFIG["ebay_fee_percent"]
        self.returns_buffer_pct = returns_buffer_pct or PROFIT_CONFIG["returns_buffer_percent"]
        self.min_profit = min_profit

    def calculate(
        self,
        ebay_price: float,
        supplier_price: float,
        shipping_cost: float = 0.0,
        packaging_cost: float = 0.0,
    ) -> ProfitResult:
        """Calculate full profit breakdown."""
        # Fees
        ebay_fee = ebay_price * (self.ebay_fee_pct / 100)
        returns_buffer = ebay_price * (self.returns_buffer_pct / 100)

        # Total costs
        total_costs = supplier_price + shipping_cost + packaging_cost + ebay_fee + returns_buffer

        # Profit
        profit = ebay_price - total_costs
        margin = (profit / ebay_price * 100) if ebay_price > 0 else 0
        roi = (profit / total_costs * 100) if total_costs > 0 else 0

        # Filters
        passes_price = FILTERS["price_min"] <= ebay_price <= FILTERS["price_max"]
        passes_profit = profit >= self.min_profit

        # Recommendation
        if profit <= 0:
            rec = "SKIP — Loss"
        elif margin < 15:
            rec = "SKIP — Low margin"
        elif not passes_price:
            rec = "SKIP — Outside price range"
        elif profit >= 5 and margin >= 30:
            rec = "STRONG BUY"
        elif profit >= 3 and margin >= 20:
            rec = "BUY"
        else:
            rec = "MARGINAL — Consider"

        return ProfitResult(
            ebay_price=ebay_price,
            supplier_price=supplier_price,
            ebay_fee=round(ebay_fee, 2),
            returns_buffer=round(returns_buffer, 2),
            total_costs=round(total_costs, 2),
            profit=round(profit, 2),
            margin=round(margin, 1),
            roi=round(roi, 1),
            passes_price_filter=passes_price,
            passes_profit_filter=passes_profit,
            recommendation=rec,
        )

    def batch_calculate(
        self,
        ebay_price: float,
        supplier_prices: list[dict],
    ) -> list[ProfitResult]:
        """Calculate profit for multiple supplier options."""
        results = []
        for sp in supplier_prices:
            result = self.calculate(
                ebay_price=ebay_price,
                supplier_price=sp["price"],
                shipping_cost=sp.get("shipping", 0),
                packaging_cost=sp.get("packaging", 0),
            )
            results.append(result)
        return sorted(results, key=lambda r: r.profit, reverse=True)

    def breakeven_supplier_price(self, ebay_price: float) -> float:
        """Calculate the maximum supplier price to break even."""
        total_fee_pct = self.ebay_fee_pct + self.returns_buffer_pct
        max_cost = ebay_price * (1 - total_fee_pct / 100)
        return round(max_cost, 2)

    def format_result(self, result: ProfitResult) -> str:
        """Format profit result as readable string."""
        lines = [
            f"\n{'='*40}",
            f"PROFIT CALCULATION",
            f"{'='*40}",
            f"  eBay Price:        £{result.ebay_price:.2f}",
            f"  Supplier Price:    £{result.supplier_price:.2f}",
            f"  eBay Fee (12.8%):  £{result.ebay_fee:.2f}",
            f"  Returns Buffer:    £{result.returns_buffer:.2f}",
            f"  ─────────────────────────",
            f"  PROFIT:            £{result.profit:.2f}",
            f"  MARGIN:            {result.margin:.1f}%",
            f"  ROI:               {result.roi:.1f}%",
            f"  ─────────────────────────",
            f"  Recommendation:    {result.recommendation}",
            f"{'='*40}\n",
        ]
        return "\n".join(lines)
