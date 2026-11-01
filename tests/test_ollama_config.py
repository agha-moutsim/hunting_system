"""Ollama configuration and request defaults."""


from __future__ import annotations

import os


def test_default_model_and_num_predict_are_defined():
    import backend.config as config

    assert config.OLLAMA_MODEL
    assert config.OLLAMA_NUM_PREDICT >= 300


def test_deep_search_ollama_payload_disables_thinking(monkeypatch):
    import backend.deep_search as ds

    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    def fake_post(url, json, timeout):
        captured["payload"] = json
        return _Response()

    monkeypatch.setattr(ds.requests, "post", fake_post)
    ds._ollama_generate("prompt", system="system")

    assert captured["payload"]["think"] is False
    assert "num_predict" in captured["payload"]["options"]