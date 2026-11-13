"""C1 — the batch summary reads the pipeline's verdict dict.

The pipeline returns `verdict` as a dict. `get_summary` used `getattr(...)`
on it, so every row answered with the default: profit 0 and verdict "N/A",
and `format_summary` printed a fabricated £0.00 for each product.
"""

from batch import BatchAnalyzer, BatchResult


def _analyzer():
    # get_summary/format_summary use no pipeline state; avoid constructing one.
    return BatchAnalyzer.__new__(BatchAnalyzer)


def _ok(query, verdict):
    return BatchResult(query=query, status="success", result={"verdict": verdict})


class TestBatchSummaryReadsTheVerdictDict:
    def test_a_computed_profit_is_reported(self):
        summary = _analyzer().get_summary(
            [_ok("drill", {"verdict": "pass", "profit": 4.5, "profit_computed": True})]
        )

        assert summary["products"][0]["profit"] == 4.5
        assert summary["profitable"] == 1
        assert "£4.50" in _analyzer().format_summary(
            [_ok("drill", {"verdict": "pass", "profit": 4.5, "profit_computed": True})]
        )

    def test_the_verdict_word_is_read_not_defaulted(self):
        summary = _analyzer().get_summary(
            [_ok("drill", {"verdict": "pending", "profit": None, "profit_computed": False})]
        )

        assert summary["products"][0]["verdict"] == "pending"

    def test_an_uncomputed_profit_is_not_printed_as_zero(self):
        results = [
            _ok("drill", {"verdict": "pending", "profit": 0, "profit_computed": False})
        ]

        summary = _analyzer().get_summary(results)
        text = _analyzer().format_summary(results)

        assert summary["products"][0]["profit"] is None
        assert summary["profitable"] == 0
        assert "£0.00" not in text
        assert "not computed" in text

    def test_explicitly_false_wins_over_a_stale_number(self):
        summary = _analyzer().get_summary(
            [_ok("drill", {"verdict": "pending", "profit": 3.0, "profit_computed": False})]
        )

        assert summary["products"][0]["profit"] is None

    def test_a_legacy_result_without_the_flag_keeps_a_nonzero_profit(self):
        summary = _analyzer().get_summary(
            [_ok("drill", {"verdict": "pass", "profit": 2.0})]
        )

        assert summary["products"][0]["profit"] == 2.0

    def test_an_absent_verdict_reads_not_recorded(self):
        # C1 — the batch asked a real question and stored no answer; "N/A"
        # would claim the question did not apply.
        results = [
            _ok("drill", {"verdict": "", "profit": None, "profit_computed": False}),
            _ok("saw", {}),
        ]

        summary = _analyzer().get_summary(results)
        text = _analyzer().format_summary(results)

        assert summary["products"][0]["verdict"] == "NOT RECORDED"
        assert summary["products"][1]["verdict"] == "NOT RECORDED"
        assert "NOT RECORDED" in text

    def test_an_error_row_is_not_summarised_as_a_product(self):
        results = [
            BatchResult(query="drill", status="error", error="boom"),
            _ok("saw", {"verdict": "pass", "profit": 1.0, "profit_computed": True}),
        ]

        summary = _analyzer().get_summary(results)

        assert summary["failed"] == 1
        assert [p["query"] for p in summary["products"]] == ["saw"]
