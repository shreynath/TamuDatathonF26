"""Gemini and Ollama clients. Numbers stay in the calling code."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from packages.evidence.env import load_env


def _timeout() -> float:
    load_env()
    try:
        return float(os.environ.get("AI_REQUEST_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def _retries() -> int:
    load_env()
    try:
        return max(0, int(os.environ.get("AI_MAX_RETRIES", "2")))
    except ValueError:
        return 2


def gemini_key() -> str:
    load_env()
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def gemini_model() -> str:
    load_env()
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def ollama_host() -> str:
    load_env()
    return (os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


def ollama_headers() -> dict[str, str]:
    load_env()
    key = os.environ.get("OLLAMA_API_KEY", "").strip()
    host = ollama_host().lower()
    local = "127.0.0.1" in host or "localhost" in host
    if not key or local:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _request(url: str, payload: dict | None, headers: dict[str, str]) -> tuple[int, dict | str, float]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    started = time.perf_counter()
    attempts = _retries() + 1
    last_error = "unreachable"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=_timeout()) as response:
                body = response.read().decode("utf-8")
                elapsed = time.perf_counter() - started
                try:
                    return response.status, json.loads(body), elapsed
                except json.JSONDecodeError:
                    return response.status, body[:500], elapsed
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            if exc.code in (401, 403):
                return exc.code, detail, time.perf_counter() - started
            last_error = f"http {exc.code}"
            if attempt + 1 == attempts or exc.code not in (429, 500, 502, 503):
                return exc.code, detail, time.perf_counter() - started
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            if attempt + 1 == attempts:
                return 0, last_error, time.perf_counter() - started
        time.sleep(min(2 ** attempt, 4))
    return 0, last_error, time.perf_counter() - started


def gemini_generate(prompt: str) -> dict:
    key = gemini_key()
    model = gemini_model()
    if not key:
        return {"ok": False, "provider": "gemini", "error": "GEMINI_API_KEY is not set", "model": model}
    status, body, elapsed = _request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        },
        {"x-goog-api-key": key},
    )
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "provider": "gemini", "model": model, "status": status, "latency_s": round(elapsed, 3)}
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        return {"ok": False, "provider": "gemini", "model": model, "error": "unreadable", "latency_s": round(elapsed, 3)}
    return {"ok": True, "provider": "gemini", "model": model, "latency_s": round(elapsed, 3), "parsed": parsed}


def ollama_models() -> dict:
    status, body, elapsed = _request(ollama_host() + "/api/tags", None, ollama_headers())
    names = []
    if isinstance(body, dict):
        names = [item.get("name") for item in body.get("models", []) if item.get("name")]
    return {
        "ok": status == 200 and bool(names),
        "provider": "ollama",
        "host": ollama_host(),
        "status": status,
        "models": names[:12],
        "latency_s": round(elapsed, 3),
        "authenticated": bool(ollama_headers()),
    }


def ollama_generate(prompt: str, model: str | None = None) -> dict:
    listing = ollama_models()
    chosen = model or os.environ.get("OLLAMA_MODEL") or (listing["models"][0] if listing["models"] else "")
    if not chosen:
        return {"ok": False, "provider": "ollama", "error": "no model", "listing_status": listing["status"]}
    status, body, elapsed = _request(
        ollama_host() + "/api/chat",
        {"model": chosen, "messages": [{"role": "user", "content": prompt}], "stream": False},
        ollama_headers(),
    )
    text = body.get("message", {}).get("content") if isinstance(body, dict) else None
    return {
        "ok": status == 200 and bool(text),
        "provider": "ollama",
        "model": chosen,
        "status": status,
        "latency_s": round(elapsed, 3),
        "text": text,
    }


def smoke() -> dict:
    gemini = gemini_generate('Return a JSON object containing status equal to ok and result equal to 4.')
    ollama = ollama_generate('Reply with exactly: {"status":"ok","result":4}')
    return {
        "gemini": {key: value for key, value in gemini.items() if key != "parsed"} | {
            "parsed_status": (gemini.get("parsed") or {}).get("status") if gemini.get("ok") else None,
            "parsed_result": (gemini.get("parsed") or {}).get("result") if gemini.get("ok") else None,
        },
        "ollama": {key: value for key, value in ollama.items() if key != "text"} | {
            "text_preview": (ollama.get("text") or "")[:80],
        },
    }
