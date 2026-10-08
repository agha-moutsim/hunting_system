r"""B4. The model costs 21.2 seconds to load, once per unload.

Measured on this box: ``llama3.1:8b`` is 4.9 GB and takes ~21s to get into
RAM, then generates at ~8.6 tok/s. Ollama unloads it five minutes after
its last use, so any analysis more than five minutes after the previous
one paid that 21s again on top of the generation time it already cannot
afford.

``keep_alive: -1`` tells Ollama to never unload. The model is loaded once
per process lifetime instead of once per idle gap.

Two things are tested, because there are two places that talk to Ollama
and they do not share a client:

  * ``OllamaClient`` (the async path Analyze uses)
  * ``deep_search._ollama_generate`` (its own synchronous payload — it
    never goes through OllamaClient)

plus the startup prewarm, which must never stop the app booting when
Ollama is not running.
"""

import asyncio

import pytest

from llm.ollama_client import OllamaClient

pytestmark = pytest.mark.usefixtures("_no_ollama")


@pytest.fixture()
def _no_ollama(monkeypatch):
    """Nothing here should ever reach a real Ollama."""
    import llm.prewarm as pw

    def _blocked(*args, **kwargs):
        raise AssertionError("reached Ollama — this file runs offline")

    monkeypatch.setattr(pw, "_post", _blocked, raising=False)


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"response": "ok"}


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so we can read the body we sent."""

    is_closed = False

    def __init__(self):
        self.sent = []

    async def post(self, path, json=None, **kwargs):
        self.sent.append(json)
        return _FakeResponse()

    async def aclose(self):
        return None


class TestThePayloadKeepsTheModelResident:
    def test_ollama_client_sends_keep_alive(self):
        client = OllamaClient()
        fake = _FakeAsyncClient()
        client._client = fake

        asyncio.run(client.generate("hello"))

        assert len(fake.sent) == 1
        assert fake.sent[0]["keep_alive"] == -1

    def test_deep_search_sends_keep_alive_too(self, monkeypatch):
        """deep_search builds its own payload. That call site drifting is
        how we end up paying 21s on one path and not the other."""
        import deep_search as ds

        captured = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": "ok"}

        def _post(url, json=None, timeout=None):
            captured.update(json)
            return _Resp()

        monkeypatch.setattr(ds.requests, "post", _post)
        ds._ollama_generate("a prompt")

        assert captured["keep_alive"] == -1

    def test_both_call_sites_agree_on_the_value(self, monkeypatch):
        """A single knob. If the two sites ever read different settings
        the whole point of the fix is lost."""
        import deep_search as ds

        from config import OLLAMA_KEEP_ALIVE

        captured = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": "ok"}

        monkeypatch.setattr(
            ds.requests, "post", lambda u, json=None, timeout=None: (
                captured.update(json) or _Resp()
            )
        )
        ds._ollama_generate("x")

        client = OllamaClient()
        fake = _FakeAsyncClient()
        client._client = fake
        asyncio.run(client.generate("x"))

        assert captured["keep_alive"] == OLLAMA_KEEP_ALIVE
        assert fake.sent[0]["keep_alive"] == OLLAMA_KEEP_ALIVE


class TestThePrewarmNeverBreaksBoot:
    def test_prewarm_swallows_a_connection_error(self, monkeypatch):
        import llm.prewarm as pw

        def _down(*args, **kwargs):
            raise ConnectionError("Ollama is not running")

        monkeypatch.setattr(pw, "_post", _down)
        # Must not raise — a missing LLM is a degraded app, not a dead one.
        asyncio.run(pw.prewarm_model())

    def test_prewarm_swallows_a_timeout(self, monkeypatch):
        import llm.prewarm as pw

        def _slow(*args, **kwargs):
            raise TimeoutError("too slow")

        monkeypatch.setattr(pw, "_post", _slow)
        asyncio.run(pw.prewarm_model())

    def test_startup_still_succeeds_with_ollama_down(self, monkeypatch):
        """The boot seam. Importing and starting the app must not depend
        on Ollama being up — the whole design is that Analyze degrades."""
        import llm.prewarm as pw

        def _down(*args, **kwargs):
            raise ConnectionError("Ollama is not running")

        monkeypatch.setattr(pw, "_post", _down)

        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as client:
            assert client.get("/api/health").status_code == 200

    def test_prewarm_returns_none_rather_than_a_result(self, monkeypatch):
        """It is a side effect, not an API. Returning a value would invite
        callers to depend on a body we do not parse."""
        import llm.prewarm as pw

        monkeypatch.setattr(
            pw, "_post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError())
        )
        assert asyncio.run(pw.prewarm_model()) is None
