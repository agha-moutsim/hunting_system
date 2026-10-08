r"""B2. This box generates at 3.5 tok/s, so every token is 0.29 seconds.

Measured on real hardware (2026-10-08), with the exact payload
ProductAnalyzer sends: 97.5s end to end, of which 39.2s was prompt
evaluation of 514 tokens and 57.5s was generating 203 tokens. The model
stopped on its own (`done_reason: stop`) well inside num_predict=500, so
the budget was never the constraint - the prompt was, and the prompt is
mostly our own boilerplate.

These tests hold two things still while the prose is shortened:

  * the JSON contract the parser reads, key for key, and
  * the sentence that stops the model inventing a supplier.

plus one constant for num_predict, because 500 in one place and 800 in
the other is the same drift that put a literal 45.0 in four places.
"""

from config import OLLAMA_NUM_PREDICT
from llm.prompts import SYSTEM_PROMPT, build_analysis_prompt

# Every key `_parse_analysis` reads off the model. If the template stops
# naming one of these, the parser gets an empty field and the analysis
# looks thinner than it is - with no error to say why.
REQUIRED_KEYS = [
    "brand_verdict",
    "brand_name",
    "brand_reasoning",
    "demand_assessment",
    "demand_reasoning",
    "best_supplier_match",
    "supplier_type",
    "supplier_type_reasoning",
    "recommended_action",
    "risk_flags",
]


class TestTheJsonContractSurvivesTheTrim:
    def test_the_template_names_every_key_the_parser_reads(self):
        for key in REQUIRED_KEYS:
            assert f'"{key}"' in (build_analysis_prompt({}, {}, []) ), key

    def test_the_enums_are_still_spelled_out(self):
        """The allowed values are the schema. Dropping them turns a
        constrained classification into free text."""
        for pair in [
            ("brand_verdict", "generic"),
            ("brand_verdict", "branded"),
            ("brand_verdict", "ambiguous"),
            ("demand_assessment", "strong"),
            ("demand_assessment", "moderate"),
            ("demand_assessment", "weak"),
            ("demand_assessment", "spike"),
            ("supplier_type", "wholesaler"),
            ("supplier_type", "dropship"),
            ("supplier_type", "retailer"),
            ("recommended_action", "source"),
            ("recommended_action", "skip"),
            ("recommended_action", "investigate"),
        ]:
            key, value = pair
            section = build_analysis_prompt({}, {}, [])
            assert f'"{key}"' in section
            assert value in section, f"{key} lost its {value!r} option"

    def test_the_supplied_data_still_reaches_the_prompt(self):
        """Shortening the instructions must not start dropping facts."""
        prompt = build_analysis_prompt(
            {"title": "A DRILL", "price": 24.99, "condition": "New"},
            {"sold_count_30d": 42},
            [{"name": "Supplier One", "price": 10.0}],
        )
        assert "A DRILL" in prompt
        assert "42" in prompt
        assert "Supplier One" in prompt


class TestTheModelIsToldNotToInvent:
    def test_the_no_fabrication_rule_is_still_present(self):
        """C1 lives in this sentence. It is the difference between a
        verdict and a plausible story.

        Wording is pinned lowercase on purpose: test_provenance.py holds
        the same substring, and a trim that rephrases it is a trim that
        quietly removed the rule."""
        assert "never invent a supplier name" in SYSTEM_PROMPT

    def test_absent_values_are_reported_as_unknown(self):
        assert "unknown" in SYSTEM_PROMPT

    def test_the_rule_survives_a_prompt_built_with_no_data(self):
        """An empty analysis must not become an invitation to guess."""
        assert "never invent a supplier name" in SYSTEM_PROMPT
        assert build_analysis_prompt({}, {}, [])


class TestOneNumPredictForBothCallSites:
    def test_the_constant_exists_and_is_the_measured_amount(self):
        """Set by the LARGER consumer, not the smaller one.

        Both paths stopped on their own (`done_reason: stop`), so this is
        a ceiling, not a speed setting: Analyze used 203 tokens, Deep
        Search 411. 350 would have fit Analyze comfortably and truncated
        Deep Search mid-JSON - and a truncated JSON is not a slower
        answer, it is no answer."""
        assert OLLAMA_NUM_PREDICT == 500

    def test_the_async_client_uses_the_constant(self):
        import asyncio

        from llm.ollama_client import OllamaClient

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": "{}"}

        class _Fake:
            is_closed = False

            def __init__(self):
                self.sent = []

            async def post(self, path, json=None, **kwargs):
                self.sent.append(json)
                return _Resp()

        client = OllamaClient()
        fake = _Fake()
        client._client = fake
        asyncio.run(client.generate("x"))

        assert fake.sent[0]["options"]["num_predict"] == OLLAMA_NUM_PREDICT

    def test_deep_search_uses_the_constant_too(self, monkeypatch):
        """It builds its own payload, which is exactly how the two values
        ended up as 500 and 800 in the first place."""
        import deep_search as ds

        captured = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": "{}"}

        def _post(url, json=None, timeout=None):
            captured.update(json)
            return _Resp()

        monkeypatch.setattr(ds.requests, "post", _post)
        ds._ollama_generate("x")

        assert captured["options"]["num_predict"] == OLLAMA_NUM_PREDICT
