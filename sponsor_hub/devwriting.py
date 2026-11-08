"""Score the local DEV Writing Challenge draft. Publishing is a separate, explicit step."""
from __future__ import annotations

import re
from pathlib import Path

from .core import IntegrationError

ARTICLE_PATH = Path(__file__).resolve().parents[1] / "docs" / "DEV_ARTICLE.md"
_HEADINGS = ("What I Built", "How It Works", "What I Learned")
_ANCHORS = ("M-1158", "15,796.25", "$1,200", "68,698.55", "31.010", "#mlhacks")
_FALSE_CLAIMS = (
    "the domain is registered",
    "we registered a domain",
    "this post is live on dev.to",
    "snowflake cortex is connected",
    "the vultr instance is running",
    "the solana transaction is confirmed",
    "mongodb atlas is connected",
    "tiger data is connected",
)


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'+-]*", text))


def score_article(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise IntegrationError("DEV article is empty")
    folded = text.lower()
    missing: list[str] = []
    score = 0
    if "this is a submission for the mlh x dev writing challenge" in folded:
        score += 1
    else:
        missing.append("Opening line must say this is a submission for the MLH x DEV Writing Challenge")
    if "#mlhacks" in folded and re.search(r"(?m)^tags:.*\bmlhacks\b", folded):
        score += 1
    else:
        missing.append("Include the #mlhacks tag in the body and in the DEV front-matter tags")
    for heading in _HEADINGS:
        if re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", text):
            score += 1
        else:
            missing.append(f"Missing section: {heading}")
    count = _words(text)
    if count >= 900:
        score += 2
    else:
        missing.append(f"Article has {count} words; the rubric wants at least 900")
    if all(anchor in text or anchor.lower() in folded for anchor in _ANCHORS):
        score += 2
    else:
        missing.append("Cite the verified project figures: M-1158, house win, inspection cost, weekday MAE, House Edge local score, and #mlhacks")
    honest = (
        "not published" in folded
        and "has not been registered" in folded
        and "not live connections" in folded
    )
    if honest:
        score += 1
    else:
        missing.append("State that the draft is not published, no domain has been registered, and the cloud adapters are not live connections")
    false_hits = [phrase for phrase in _FALSE_CLAIMS if phrase in folded]
    if false_hits:
        score = min(score, 4)
        missing.append("Remove claims this repository cannot verify: " + "; ".join(false_hits))
    title = ""
    match = re.search(r"(?m)^title:\s*(.+)$", text)
    if match:
        title = match.group(1).strip().strip("\"'")
    return {
        "score": score,
        "max_score": 10,
        "word_count": count,
        "missing": missing,
        "false_claims": false_hits,
        "title": title,
        "ready_to_paste": score == 10 and not false_hits,
        "published": False,
    }


def load_scored_article(path: Path | None = None) -> dict:
    article = path or ARTICLE_PATH
    if not article.is_file():
        raise IntegrationError("DEV article file is missing")
    text = article.read_text(encoding="utf-8")
    scored = score_article(text)
    scored["path"] = "docs/DEV_ARTICLE.md"
    scored["markdown"] = text
    return scored
