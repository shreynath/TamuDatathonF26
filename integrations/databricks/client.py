"""Databricks adapter. The public demo does not require this call to succeed."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.evidence.env import load_env


def status() -> dict:
    load_env()
    token = os.environ.get("DATABRICKS_TOKEN", "").strip()
    host = os.environ.get("DATABRICKS_HOST", "").strip().rstrip("/")
    if not token:
        return {"ok": False, "error": "DATABRICKS_TOKEN is not set"}
    if not host:
        return {
            "ok": False,
            "error": "DATABRICKS_HOST is not set",
            "token_configured": True,
        }
    request = urllib.request.Request(
        host + "/api/2.0/preview/scim/v2/Me",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"ok": response.status == 200, "host": host}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"databricks http {exc.code}", "host": host}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": "databricks unreachable", "detail": str(exc.reason), "host": host}
