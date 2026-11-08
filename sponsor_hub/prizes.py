"""Non-destructive external verification and digest tools for optional MLH prize tracks."""
from __future__ import annotations
import hashlib, json, re
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from .core import IntegrationError, required_env, safe_post_json

def vultr_instances(*, fetch=None) -> list[dict]:
    """Read-only health/inventory check; DOES NOT provision or bill cloud resources."""
    key=required_env("VULTR_API_KEY")
    url="https://api.vultr.com/v2/instances"
    req=Request(url,headers={"Authorization":f"Bearer {key}","Accept":"application/json"})
    if fetch is not None:
        result=fetch(req)
    else:
        try:
            with urlopen(req,timeout=8) as response: result=json.loads(response.read(200001))
        except Exception: raise IntegrationError("Vultr instance inventory unavailable") from None
    if not isinstance(result,dict) or not isinstance(result.get("instances"),list): raise IntegrationError("Unexpected Vultr inventory")
    return [{"id":str(x.get("id","")),"region":str(x.get("region","")),"status":str(x.get("status",""))} for x in result["instances"] if isinstance(x,dict)]

def report_sha256(raw:bytes)->str:
    if not isinstance(raw,bytes): raise IntegrationError("Report content must be bytes")
    return hashlib.sha256(raw).hexdigest()

def verify_report(raw:bytes,digest:str)->bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}",digest)) and report_sha256(raw)==digest

_MEMO_PROGRAMS = {
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
}

def _memo_texts(tx: dict) -> list[str]:
    groups = []
    message = tx.get("transaction", {}).get("message", {}) if isinstance(tx.get("transaction"), dict) else {}
    groups.append(message.get("instructions") or [])
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        if isinstance(inner, dict):
            groups.append(inner.get("instructions") or [])
    found: list[str] = []
    for group in groups:
        for instruction in group:
            if not isinstance(instruction, dict):
                continue
            program = str(instruction.get("programId") or "")
            name = str(instruction.get("program") or "")
            if program not in _MEMO_PROGRAMS and name not in {"spl-memo", "memo"}:
                continue
            parsed = instruction.get("parsed")
            if isinstance(parsed, str):
                found.append(parsed.strip())
            elif isinstance(parsed, dict) and isinstance(parsed.get("memo"), str):
                found.append(parsed["memo"].strip())
    return found

def solana_devnet_transaction(signature:str, *, expected_digest:str|None=None, transport=None)->dict:
    """Read-only check. digest_verified is true only when a memo holds the exact digest."""
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{64,88}",signature):
        raise IntegrationError("Invalid Solana signature")
    if expected_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise IntegrationError("Invalid report digest")
    url="https://api.devnet.solana.com"
    body={"jsonrpc":"2.0","id":1,"method":"getTransaction","params":[signature,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0,"commitment":"confirmed"}]}
    result=safe_post_json(url,body,{},transport=transport)
    tx=result.get("result")
    if tx is None or not isinstance(tx,dict): raise IntegrationError("Transaction was not found or not confirmed")
    status=tx.get("meta",{}).get("err")
    if status is not None: raise IntegrationError("Transaction failed")
    memos=_memo_texts(tx)
    verified=bool(expected_digest) and expected_digest in memos
    return {"signature":signature,"found":True,"slot":tx.get("slot"),"digest_verified":verified,
            "memo_present":bool(memos),
            "note":"digest_verified requires a memo whose text is the exact report SHA-256"}

def verify_domain_dns(hostname:str, resolver=None)->dict:
    """Read-only qualification. Does not register a domain or claim ownership."""
    from .godaddy import qualify_domain
    return qualify_domain(hostname, resolver=resolver, live_dns=True)

def vultr_deploy_plan(plan: dict) -> dict:
    """Reject an unsafe instance plan. This does not call Vultr or create a bill."""
    if not isinstance(plan, dict):
        raise IntegrationError("Invalid deploy plan")
    region = str(plan.get("region") or "")
    size = str(plan.get("plan") or "")
    if not re.fullmatch(r"[a-z0-9]{2,12}", region) or not re.fullmatch(r"[a-z0-9-]{2,32}", size):
        raise IntegrationError("Invalid region or plan")
    ports = plan.get("firewall_ports")
    if not isinstance(ports, list) or 443 not in ports:
        raise IntegrationError("Deploy plan must allow HTTPS")
    if 22 in ports and plan.get("ssh_cidr") in {None, "0.0.0.0/0", "::/0"}:
        raise IntegrationError("Refusing SSH open to the internet")
    startup = str(plan.get("user_data") or "")
    if re.search(r"(api[_-]?key|secret|password|token)\s*[:=]", startup, re.I):
        raise IntegrationError("Refusing startup script that embeds a secret")
    return {"ok": True, "region": region, "plan": size, "provisioned": False}
