"""C1 — the CLI profit command refuses placeholder prices.

`cli.py profit 20 0` used to price the item as if the supplier charged
nothing and print "PROFITABLE". A zero supplier price is this app's "not
read" placeholder, and a negative one would invent profit above the sale.
"""

from click.testing import CliRunner

from cli import cli


def _run(*args):
    return CliRunner().invoke(cli, ["profit", *args])


class TestProfitCommandRefusesPlaceholderPrices:
    def test_a_zero_supplier_price_is_not_a_free_item(self):
        result = _run("20", "0")

        assert result.exit_code == 0
        assert "No calculation" in result.output
        assert "not a free item" in result.output
        assert "£0.00" not in result.output
        assert "PROFITABLE" not in result.output

    def test_a_negative_supplier_price_is_refused(self):
        result = CliRunner().invoke(cli, ["profit", "20", "--", "-5"])

        assert "No calculation" in result.output
        assert "PROFITABLE" not in result.output

    def test_a_zero_ebay_price_is_refused(self):
        result = _run("0", "5")

        assert "No calculation" in result.output

    def test_a_negative_shipping_cost_is_refused(self):
        result = _run("20", "5", "--shipping-cost", "-1")

        assert "No calculation" in result.output

    def test_real_prices_still_produce_a_calculation(self):
        result = _run("20", "5")

        assert result.exit_code == 0
        assert "Supplier Price:   £5.00" in result.output
        assert "Profit:" in result.output
