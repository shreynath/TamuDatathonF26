"""GoDaddy Registry domain qualification. This module never registers a name."""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import IntegrationError

# TLDs named in GoDaddy Registry Acceptable Use Policy GDR-POL-002.
# The MLH campaign link for this event is https://www.tech.study/ , a .study name.
# .tech is not in that policy list and is not treated as eligible here.
GODADDY_REGISTRY_TLDS = frozenset(
    {
        "abogado",
        "adult",
        "bayern",
        "beer",
        "biz",
        "blackfriday",
        "boston",
        "casa",
        "club",
        "compare",
        "cooking",
        "courses",
        "dds",
        "design",
        "fashion",
        "fishing",
        "fit",
        "garden",
        "horse",
        "law",
        "luxe",
        "miami",
        "nrw",
        "photo",
        "porn",
        "rodeo",
        "select",
        "sex",
        "study",
        "surf",
        "vip",
        "vodka",
        "wedding",
        "work",
        "xxx",
        "yoga",
    }
)
CAMPAIGN_TLD = "study"
_BLOCKED_SUFFIXES = frozenset({"local", "internal", "localhost", "onion", "invalid", "test", "example", "alt"})
_SUGGESTIONS = (
    {
        "domain": "gildedace.study",
        "why": "Names the floor-review project on the .study TLD used by the MLH GoDaddy Registry campaign page.",
    },
    {
        "domain": "pitboss.study",
        "why": "Names the tournament agent and the evidence assistant. A .study name fits a learning write-up of the method.",
    },
    {
        "domain": "evidencefirst.study",
        "why": "States the design rule: code computes the figures, and a model may only explain them.",
    },
)


def registry_tlds() -> frozenset[str]:
    return GODADDY_REGISTRY_TLDS


def suggest_names() -> list[dict]:
    """Candidates only. Availability and ownership are unknown."""
    return [dict(item, available=None, registered_by_user=None) for item in _SUGGESTIONS]


def _label_ok(label: str) -> bool:
    if not 1 <= len(label) <= 63:
        return False
    if label.startswith("-") or label.endswith("-"):
        return False
    if not re.fullmatch(r"[a-z0-9-]+", label):
        return False
    if "--" in label and not label.startswith("xn--"):
        return False
    return True


def parse_domain(hostname: str) -> dict:
    if not isinstance(hostname, str):
        raise IntegrationError("Invalid domain")
    host = hostname.strip().rstrip(".").lower()
    if not host or not host.isascii() or any(ch.isspace() for ch in host):
        raise IntegrationError("Invalid domain")
    if "://" in host or "@" in host or "/" in host or "\\" in host or ":" in host:
        raise IntegrationError("Invalid domain")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise IntegrationError("Invalid domain")
    labels = host.split(".")
    if len(labels) < 2 or not all(_label_ok(label) for label in labels):
        raise IntegrationError("Invalid domain")
    if len(host) > 253 or labels[-1] in _BLOCKED_SUFFIXES:
        raise IntegrationError("Invalid domain")
    return {"host": host, "labels": labels, "tld": labels[-1]}


def _routable(ip: str) -> bool:
    try:
        return bool(ipaddress.ip_address(ip).is_global)
    except ValueError:
        return False


def _default_tls(hostname: str, ip: str) -> dict:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((ip, 443), timeout=4) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError):
        return {"ok": False, "reason": "TLS handshake failed"}
    not_after = cert.get("notAfter") if isinstance(cert, dict) else None
    if not isinstance(not_after, str):
        return {"ok": False, "reason": "Certificate has no expiry"}
    try:
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return {"ok": False, "reason": "Certificate expiry is unreadable"}
    if expires <= datetime.now(timezone.utc):
        return {"ok": False, "reason": "Certificate is expired"}
    return {"ok": True, "expires": expires.date().isoformat()}


class _PublicHttpsRedirect(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
            raise IntegrationError("RDAP redirect refused")
        try:
            info = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as ex:
            raise IntegrationError("RDAP redirect refused") from ex
        ips = {row[4][0] for row in info if len(row) > 4 and row[4]}
        if not ips or any(not _routable(ip) for ip in ips):
            raise IntegrationError("RDAP redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _apply_rdap(result: dict, host: str, rdap, live_rdap: bool) -> None:
    if not live_rdap and rdap is None:
        result["blockers"].append("Registration was not checked against RDAP")
        return
    try:
        looked = (rdap or _default_rdap)(host)
        status = looked.get("rdap_status", "unknown") if isinstance(looked, dict) else "unknown"
    except IntegrationError:
        status = "lookup_failed"
    if status not in {"registered", "not_registered", "unknown", "lookup_failed"}:
        status = "unknown"
    result["rdap_status"] = status
    if status == "not_registered":
        result["blockers"].append("RDAP does not show a registration")
    elif status != "registered":
        result["blockers"].append("RDAP did not confirm a registration")


def _default_rdap(hostname: str) -> dict:
    url = f"https://rdap.org/domain/{hostname}"
    request = Request(url, headers={"Accept": "application/rdap+json, application/json"})
    opener = build_opener(_PublicHttpsRedirect)
    try:
        with opener.open(request, timeout=6) as response:
            status = response.status
    except HTTPError as ex:
        if ex.code == 404:
            return {"rdap_status": "not_registered"}
        raise IntegrationError("RDAP lookup failed") from None
    except (URLError, TimeoutError, IntegrationError):
        raise IntegrationError("RDAP lookup failed") from None
    if status == 200:
        return {"rdap_status": "registered"}
    return {"rdap_status": "unknown"}


def qualify_domain(
    hostname: str,
    *,
    resolver=None,
    tls_probe=None,
    rdap=None,
    live_dns: bool = False,
    live_rdap: bool = False,
) -> dict:
    """Read-only qualification. prize_ready stays false. This does not register anything."""
    parsed = parse_domain(hostname)
    host = parsed["host"]
    tld = parsed["tld"]
    registry = tld in GODADDY_REGISTRY_TLDS
    blockers: list[str] = []
    if not registry:
        blockers.append("TLD is not in the GoDaddy Registry list this checker uses")
    elif tld != CAMPAIGN_TLD:
        blockers.append("TLD is on the Registry list, but the MLH campaign page for this event is a .study name")
    result = {
        "domain": host,
        "tld": tld,
        "syntax_ok": True,
        "godaddy_registry_tld": registry,
        "campaign_tld": tld == CAMPAIGN_TLD,
        "study_mission": (
            "Use of a .study name has to stay consistent with learning and self-development."
            if tld == CAMPAIGN_TLD
            else ""
        ),
        "resolves": False,
        "addresses": [],
        "public_addresses_only": False,
        "https_verified": False,
        "https_expires": None,
        "rdap_status": "not_checked",
        "registered_by_user": None,
        "prize_ready": False,
        "blockers": blockers,
    }
    if not live_dns and resolver is None:
        result["blockers"].append("DNS and HTTPS were not checked")
        _apply_rdap(result, host, rdap, live_rdap)
        result["prize_ready"] = False
        return result
    lookup = resolver or socket.getaddrinfo
    try:
        info = lookup(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        info = []
    addresses = sorted({str(row[4][0]) for row in info if len(row) > 4 and row[4]})
    public = [ip for ip in addresses if _routable(ip)]
    result["addresses"] = addresses
    result["resolves"] = bool(addresses)
    result["public_addresses_only"] = bool(addresses) and len(public) == len(addresses)
    if not addresses:
        result["blockers"].append("Domain does not resolve")
    elif not public:
        result["blockers"].append("Domain resolves only to a non-public address")
    else:
        probe = tls_probe or (_default_tls if live_dns else None)
        if probe is None:
            result["blockers"].append("HTTPS was not checked")
        else:
            https_ok = False
            expires = None
            for ip in public:
                checked = probe(host, ip)
                if isinstance(checked, dict) and checked.get("ok"):
                    https_ok = True
                    expires = checked.get("expires")
                    break
            result["https_verified"] = https_ok
            result["https_expires"] = expires
            if not https_ok:
                result["blockers"].append("HTTPS certificate did not verify")
    _apply_rdap(result, host, rdap, live_rdap)
    result["blockers"].append("This process does not register a domain and cannot prove ownership")
    result["prize_ready"] = False
    return result


def submission_steps(qualification: dict | None = None) -> list[dict]:
    ready = qualification or {}
    return [
        {
            "step": "Choose a GoDaddy Registry TLD. This event's campaign page is a .study name.",
            "done": bool(ready.get("campaign_tld")),
        },
        {
            "step": "Register the name yourself at a GoDaddy Registry registrar. Pay the registration. This repository cannot do that.",
            "done": False,
        },
        {
            "step": "Point DNS at a host you control and serve the project over HTTPS.",
            "done": bool(ready.get("resolves") and ready.get("https_verified") and ready.get("public_addresses_only")),
        },
        {
            "step": "Re-run python -m sponsor_hub.cli domain --live --value <name> and keep the output with the registrar receipt.",
            "done": False,
        },
    ]
