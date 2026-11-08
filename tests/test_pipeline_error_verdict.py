"""C1 — a verdict the decision engine failed to produce has no money.

`_evaluate_and_profit` used to write ``profit: 0`` with no ``profit_computed``
flag when the engine raised. The live Analyze page reads that flag: absent
means "not a placeholder", so the Decision card printed a measured £0.00 and
0.0% for a run whose engine never answered.
"""

from types import SimpleNamespace

import pipeline as pl


class _Boom:
    def evaluate(self, **kwargs):
        raise RuntimeError("decision engine exploded")


def _run():
    instance = pl.Pipeline.__new__(pl.Pipeline)
    instance._decision = _Boom()
    result = pl.PipelineResult()
    product = SimpleNamespace(
        title="Greenhouse 6ft",
        price=20.0,
        shipping_cost=0.0,
        brand=None,
    )

    instance._evaluate_and_profit(product, None, {}, None, result)

    return result


def test_the_error_verdict_says_profit_was_not_computed():
    result = _run()

    assert result.verdict["verdict"] == "error"
    assert result.verdict["profit_computed"] is False


def test_the_error_verdict_keeps_the_zero_as_a_placeholder():
    """The flag is what makes the zero safe; the wire shape is unchanged."""
    verdict = _run().verdict

    assert verdict["profit"] == 0
    assert verdict["margin"] == 0
    assert verdict["filters"] == []
