"""
B4. Load the local model once, and keep it there.

Measured on this machine (2026-10-08): ``llama3.1:8b`` is 4.9 GB. Ollama
spends ~21.2s putting it into RAM, then generates at ~8.6 tok/s. Ollama's
own default is to unload a model five minutes after its last use, so the
first analysis after any quiet period paid 21.2s before generating a
single token — on a box whose LLM already cannot finish inside the route
budget.

Two mechanisms, both from the same measurement:

  * every request carries ``keep_alive: -1`` (see config.OLLAMA_KEEP_ALIVE)
    so Ollama never unloads it, and
  * this module warms it at application startup so even the first
    analysis of a fresh process skips the load.

The prewarm is a courtesy, not a dependency. If Ollama is not running,
or is slow, or the request fails for any reason at all, the app still
boots — every caller already degrades to an unverified result when the
LLM is unavailable, which is the whole reason Analyze cannot be blocked
on this.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import OLLAMA_BASE_URL, OLLAMA_KEEP_ALIVE, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# A warm-up is not worth its own long wait. Ten seconds is generous for a
# local socket; if it is not up by then, the first real call will load it.
PREWARM_TIMEOUT_S = 10.0


async def _post(url: str, *, json: dict, timeout: float) -> None:
    """POST and check the status. Kept as a module-level seam so tests can
    stand in for Ollama without a live one."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=json, timeout=timeout)
        resp.raise_for_status()


async def prewarm_model() -> None:
    """Ask Ollama to load the model now. Never raises, returns nothing."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    try:
        await _post(
            url,
            json={
                "model": OLLAMA_MODEL,
                "prompt": "",
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
            },
            timeout=PREWARM_TIMEOUT_S,
        )
        logger.info("Ollama model %s is warm", OLLAMA_MODEL)
    except Exception as exc:
        # Degraded, never dead. The first analysis will pay the load.
        logger.info(
            "Ollama prewarm skipped (%s); the model will load on first use",
            exc,
        )


def schedule_prewarm() -> Optional[asyncio.Task]:
    """Queue the prewarm on the running loop, if there is one.

    Returns the task so a caller can await it, or None when there is no
    running loop (importing this module must stay side-effect free).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(prewarm_model())
