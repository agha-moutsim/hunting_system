"""
Async Ollama client — thin wrapper around the /api/generate endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_S,
)

logger = logging.getLogger(__name__)


class OllamaClient:
    """Low-level async client for a local Ollama instance."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        temperature: float = OLLAMA_TEMPERATURE,
        timeout: float = OLLAMA_TIMEOUT_S,
        keep_alive: int = OLLAMA_KEEP_ALIVE,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._timeout = timeout
        self.keep_alive = keep_alive
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        format_json: bool = False,
    ) -> str:
        """Send a prompt and return the raw text response."""
        client = await self._ensure_client()

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # -1 = keep the model in RAM. On this box loading it costs
            # ~21s, which a call that then has ~55s of budget cannot spare.
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature, "num_predict": 500},
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"

        try:
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP %s: %s", exc.response.status_code, exc.response.text[:500])
            raise
        except httpx.ConnectError:
            logger.error("Cannot reach Ollama at %s — is it running?", self.base_url)
            raise
        except Exception:
            logger.exception("Unexpected Ollama error")
            raise

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
