"""Ask Gemini about the Royale case, then reject any number that is not in the file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from integrations.gemini.client import explain

CASE_PATH = Path(__file__).resolve().parents[2] / "apps" / "web" / "public" / "ace_case.json"
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def number_tokens(text: str) -> set[str]:
    return {token.replace(",", "") for token in _NUMBER.findall(text)}


def stray_numbers(answer_text: str, source_text: str) -> list[str]:
    allowed = number_tokens(source_text)
    return sorted(token for token in number_tokens(answer_text) if token not in allowed)


def case_claims(case: dict) -> list[dict]:
    """The scored claims, without the 61-row forecast series."""
    forecast = {key: value for key, value in case["forecast"].items() if key != "holdout_series"}
    recommendation = dict(case["recommendation"])
    recommendation["claim_id"] = "ace-recommendation-1"
    testing = dict(case["multiple_testing"])
    testing["claim_id"] = "ace-holm-1"
    return [
        case["claim"],
        case["downtime"],
        forecast,
        case["players"],
        case["comps"],
        recommendation,
        testing,
    ]


def explain_case(question: str, case: dict | None = None) -> dict:
    loaded = case if case is not None else json.loads(CASE_PATH.read_text())
    claims = case_claims(loaded)
    source = json.dumps(claims)
    result = explain(claims, question)
    if not result.get("ok"):
        return result
    answer = result["answer"]
    text = json.dumps(answer)
    stray = stray_numbers(text, source)
    if stray:
        return {"ok": False, "rejected": True, "error": "answer contained a number that is not in the case", "stray": stray}
    return {"ok": True, "answer": answer, "evidence_ids": answer.get("evidence_ids") or []}
