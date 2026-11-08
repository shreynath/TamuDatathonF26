"""Strict provider boundaries, minimal JSON client, and safe configuration."""
from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from typing import Callable, Any

class IntegrationError(RuntimeError):
    """Safe failure. Never include tokens, URLs containing secrets, or raw response bodies."""

@dataclass(frozen=True)
class ProviderState:
    provider: str
    configured: bool
    checked_live: bool = False
    note: str = ""  # This is NOT a connectivity or prize-eligibility assertion.

_ALLOWED_SNOWFLAKE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,199}$")
_ALLOWED_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value: raise IntegrationError(f"{name} is not configured")
    return value

def snowflake_host() -> str:
    account = required_env("SNOWFLAKE_ACCOUNT")
    if not _ALLOWED_SNOWFLAKE.fullmatch(account) or account.startswith(".") or ".." in account or account.endswith("."):
        raise IntegrationError("SNOWFLAKE_ACCOUNT must be an account identifier, not a URL")
    return f"https://{account}.snowflakecomputing.com"

def clean_model(model: str) -> str:
    if not _ALLOWED_MODEL.fullmatch(model) or ".." in model: raise IntegrationError("Invalid model identifier")
    return model

def safe_post_json(url: str, body: dict, headers: dict, *, timeout: float = 12, transport: Callable | None = None) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise IntegrationError("Provider endpoint must be a permitted HTTPS URL")
    data = json.dumps(body, ensure_ascii=False).encode("utf8")
    if len(data) > 50000: raise IntegrationError("Provider payload exceeds limit")
    # The caller chooses a fixed provider-specific URL, never an arbitrary URL from user input.
    req = Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        if transport is not None:
            result = transport(req, timeout)
            if not isinstance(result, dict): raise IntegrationError("Invalid provider JSON response")
            return result
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(250_001)
            if len(raw) > 250_000: raise IntegrationError("Provider response too large")
        result = json.loads(raw)
        if not isinstance(result, dict): raise IntegrationError("Invalid provider JSON response")
        return result
    except HTTPError as ex:
        raise IntegrationError(f"Provider HTTP error {ex.code}") from None
    except (URLError, TimeoutError):
        raise IntegrationError("Provider connection failed") from None
    except (ValueError, UnicodeError):
        raise IntegrationError("Provider response was not valid JSON") from None

def public_status() -> dict[str, ProviderState]:
    # "configured" is NOT "connected"; no network calls and no secrets returned.
    keys = {
      "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
      "snowflake": ("SNOWFLAKE_PAT", "SNOWFLAKE_ACCOUNT"),
      "tigerdata": ("TIGER_DATABASE_URL",),
      "mongodb": ("MONGODB_ATLAS_URI",),
      "vultr": ("VULTR_API_KEY",),
      "solana_devnet": (),
      "godaddy_domain": ("SPONSOR_DOMAIN",),
      "spacexsi": (),
      "dev_writing": (),
    }
    return {k: ProviderState(k, (bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) if k == "gemini" else bool(names) and all(os.getenv(n) for n in names)), note="configuration only; live verification not run") for k,names in keys.items()}
