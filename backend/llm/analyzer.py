"""
Main LLM analyzer — orchestrates Ollama calls and parses structured output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from llm.ollama_client import OllamaClient
from llm.prompts import SYSTEM_PROMPT, build_analysis_prompt

logger = logging.getLogger(__name__)


@dataclass
class SupplierMatch:
    """A single supplier match result."""
    name: str
    confidence: float
    reasoning: str


@dataclass
class LLMAnalysis:
    """Structured output from the LLM analyzer."""
    brand_verdict: str = "ambiguous"
    brand_name: str = ""
    brand_reasoning: str = ""
    demand_assessment: str = "moderate"
    demand_reasoning: str = ""
    best_supplier_match: Optional[SupplierMatch] = None
    supplier_type: str = "unknown"
    supplier_type_reasoning: str = ""
    recommended_action: str = "investigate"
    risk_flags: list[str] = field(default_factory=list)
    raw_response: str = ""
    parse_success: bool = False


# Fallback returned when the LLM or parsing fails
UNVERIFIED_DEFAULT = LLMAnalysis()


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract a JSON object from the LLM response, tolerating markdown fences."""
    text = raw.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        start = 1
        end = len(lines) - 1
        if lines[0].startswith("```json"):
            start = 1
        if lines[-1].strip() == "```":
            end = -1
        text = "\n".join(lines[start:end]).strip()

    return json.loads(text)


def _build_supplier_match(data: dict) -> Optional[SupplierMatch]:
    """Parse the nested best_supplier_match dict."""
    raw = data.get("best_supplier_match")
    if not raw or not isinstance(raw, dict):
        return None
    return SupplierMatch(
        name=str(raw.get("name", "Unknown")),
        confidence=float(raw.get("confidence", 0.0)),
        reasoning=str(raw.get("reasoning", "")),
    )


def _safe_str(val: Any, allowed: list[str], default: str) -> str:
    """Return val if it's in the allowed set, else default."""
    s = str(val).lower().strip()
    return s if s in allowed else default


def _parse_analysis(raw: str) -> LLMAnalysis:
    """Parse the raw LLM text into a structured LLMAnalysis."""
    data = _parse_llm_json(raw)

    brand = _safe_str(
        data.get("brand_verdict"),
        ["generic", "branded", "ambiguous"],
        "ambiguous",
    )
    demand = _safe_str(
        data.get("demand_assessment"),
        ["strong", "moderate", "weak", "spike"],
        "moderate",
    )
    stype = _safe_str(
        data.get("supplier_type"),
        ["wholesaler", "dropship", "retailer", "unknown"],
        "unknown",
    )
    action = _safe_str(
        data.get("recommended_action"),
        ["source", "skip", "investigate"],
        "investigate",
    )

    flags = data.get("risk_flags", [])
    if not isinstance(flags, list):
        flags = [str(flags)]

    return LLMAnalysis(
        brand_verdict=brand,
        brand_name=str(data.get("brand_name", "")).strip(),
        brand_reasoning=str(data.get("brand_reasoning", "")),
        demand_assessment=demand,
        demand_reasoning=str(data.get("demand_reasoning", "")),
        best_supplier_match=_build_supplier_match(data),
        supplier_type=stype,
        supplier_type_reasoning=str(data.get("supplier_type_reasoning", "")),
        recommended_action=action,
        risk_flags=flags,
        raw_response=raw,
        parse_success=True,
    )


class ProductAnalyzer:
    """High-level analyzer that combines product data, demand, and suppliers."""

    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()

    async def analyze(
        self,
        product: dict[str, Any],
        demand: dict[str, Any],
        suppliers: list[dict[str, Any]],
    ) -> LLMAnalysis:
        """Run LLM analysis and return structured results.

        On any failure (network, Ollama down, bad JSON) returns
        UNVERIFIED_DEFAULT so the pipeline can continue.
        """
        prompt = build_analysis_prompt(product, demand, suppliers)

        try:
            raw = await self.client.generate(
                prompt,
                system=SYSTEM_PROMPT,
                format_json=True,
            )
        except Exception:
            logger.warning("Ollama call failed — returning unverified defaults")
            return UNVERIFIED_DEFAULT

        if not raw:
            logger.warning("Empty Ollama response — returning unverified defaults")
            return UNVERIFIED_DEFAULT

        try:
            result = _parse_analysis(raw)
            logger.info(
                "LLM analysis: brand=%s demand=%s supplier=%s action=%s",
                result.brand_verdict,
                result.demand_assessment,
                result.supplier_type,
                result.recommended_action,
            )
            return result
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("Failed to parse LLM JSON (%s) — returning unverified defaults", exc)
            return LLMAnalysis(raw_response=raw, parse_success=False)

    async def close(self) -> None:
        await self.client.close()
