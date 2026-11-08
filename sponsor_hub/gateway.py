"""Opt-in bridge for existing apps/api/server.py; authenticated, bounded, fail-closed."""
from __future__ import annotations
import hmac,json,os,threading,time
from collections import defaultdict,deque
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse,parse_qs
from .core import IntegrationError, public_status
from .llm import evidence_reply

MAX_BODY=4096
_REQUESTS=defaultdict(deque)
_LOCK=threading.Lock()
_MAX_CLIENTS=10000

def _send(handler, code:int, body:dict):
    payload=json.dumps(body,default=str).encode("utf8")
    handler._send(code,payload,"application/json")

def _authenticated(handler)->bool:
    configured=os.getenv("SPONSOR_API_TOKEN","")
    presented=handler.headers.get("X-Sponsor-Token","")
    if len(configured)<24 or len(presented)!=len(configured):
        return False
    return hmac.compare_digest(configured,presented)

def _throttle(client:str, *, now:float|None=None, limit:int=12, window:int=60)->bool:
    now=time.monotonic() if now is None else now
    with _LOCK:
        if client not in _REQUESTS and len(_REQUESTS) >= _MAX_CLIENTS:
            return False
        q=_REQUESTS[client]
        while q and now-q[0]>=window: q.popleft()
        if not q:
            _REQUESTS.pop(client, None)
            if len(_REQUESTS) >= _MAX_CLIENTS:
                return False
            q=_REQUESTS[client]
        if len(q)>=limit:return False
        q.append(now)
        return True

def handle_get_sponsor(handler,path:str)->bool:
    if path=="/api/sponsors/status":
        # Status intentionally says 'configured' and never 'connected'. No secrets.
        status={k:{"configured":v.configured,"checked_live":v.checked_live} for k,v in public_status().items()}
        _send(handler,200,{"ok":True,"providers":status,"warning":"Configuration does not prove connectivity or prize eligibility"})
        return True
    if path=="/api/sponsors/dev-rubric":
        if not _throttle(handler.client_address[0]):
            _send(handler,429,{"ok":False,"error":"Rate limit"}); return True
        try:
            from .devwriting import load_scored_article
            scored=load_scored_article()
            scored.pop("markdown", None)
            _send(handler,200,{"ok":True,**scored,"published":False})
        except IntegrationError as ex:
            _send(handler,400,{"ok":False,"error":str(ex)[:150]})
        return True
    if path=="/api/sponsors/domain":
        if not _authenticated(handler):
            _send(handler,401,{"ok":False,"error":"Not authorized"}); return True
        if not _throttle(handler.client_address[0]):
            _send(handler,429,{"ok":False,"error":"Rate limit"}); return True
        try:
            from .godaddy import qualify_domain, suggest_names
            q=parse_qs(urlparse(handler.path).query)
            host=q.get("host",[""])[0]
            if not host:
                _send(handler,200,{"ok":True,"suggestions":suggest_names(),"prize_ready":False,"registered_by_user":None})
                return True
            live=q.get("check",[""])[0]=="dns"
            result=qualify_domain(host, live_dns=live, live_rdap=False)
            _send(handler,200,{"ok":True,**result})
        except IntegrationError as ex:
            _send(handler,400,{"ok":False,"error":str(ex)[:150]})
        return True
    if path not in {"/api/sponsors/timeseries","/api/sponsors/history"}:return False
    if not _authenticated(handler):
        _send(handler,401,{"ok":False,"error":"Not authorized"});return True
    if not _throttle(handler.client_address[0]):
        _send(handler,429,{"ok":False,"error":"Rate limit"});return True
    try:
        if path=="/api/sponsors/timeseries":
            from .storage import TigerData
            q=parse_qs(urlparse(handler.path).query)
            start=datetime.fromisoformat(q.get('start',[''])[0])
            end=datetime.fromisoformat(q.get('end',[''])[0])
            values=TigerData().daily(start,end)
            _send(handler,200,{"ok":True,"series":values,"source":"tigerdata"})
        else:
            from .storage import AtlasEvidence
            rows=AtlasEvidence().latest(10)
            _send(handler,200,{"ok":True,"investigations":rows,"source":"mongodb_atlas"})
    except (IntegrationError,ValueError) as ex:
        _send(handler,400,{"ok":False,"error":str(ex)[:120]})
    except Exception:
        _send(handler,503,{"ok":False,"error":"Provider is not available"})
    return True

def handle_post_sponsor(handler)->bool:
    if handler.path.split('?',1)[0] not in {"/api/sponsors/ask","/api/sponsors/save"}: return False
    if not _authenticated(handler):
        _send(handler,401,{"ok":False,"error":"Not authorized"}); return True
    if not _throttle(handler.client_address[0]):
        _send(handler,429,{"ok":False,"error":"Rate limit"}); return True
    try:
        length=int(handler.headers.get("Content-Length","0"))
        if not 1<=length<=MAX_BODY: raise IntegrationError("Invalid request size")
        if handler.headers.get("Content-Type","").split(";",1)[0].strip()!="application/json":
            raise IntegrationError("Content-Type must be application/json")
        raw=handler.rfile.read(length)
        payload=json.loads(raw)
        if not isinstance(payload,dict): raise IntegrationError("Invalid body")
        question=payload.get("question")
        provider=payload.get("provider","gemini")
        if not isinstance(question,str) or not (1<=len(question.strip())<=400): raise IntegrationError("Invalid question")
        if provider not in {"gemini","snowflake"}: raise IntegrationError("Unsupported provider")
        from domains.royale.investigate import investigate
        case_path=Path(__file__).resolve().parents[1]/"apps"/"web"/"public"/"ace_case.json"
        if not case_path.is_file(): raise IntegrationError("Verified case file unavailable")
        case=json.loads(case_path.read_text(encoding="utf8"))
        deterministic=investigate(question,case)
        if not deterministic.get("ok"):
            _send(handler,422,{"ok":False,"error":"No verified deterministic answer available"}); return True
        public={"ok":True,"answer":deterministic["answer"],"metrics":deterministic.get("metrics",{}),
                "sources":deterministic.get("sources",[]),"period":deterministic.get("period",""),
                "limitations":deterministic.get("limitations",""),"computed_by":"code"}
        if handler.path.split('?',1)[0]=="/api/sponsors/save":
            if os.getenv("SPONSOR_ENABLE_WRITES")!="1":
                _send(handler,403,{"ok":False,"error":"Storage writes are disabled"});return True
            from .storage import AtlasEvidence
            record={"answer":deterministic["answer"],"sources":deterministic["sources"],"period":deterministic.get("period","")}
            inserted=AtlasEvidence().save(record,confirm_write=True)
            _send(handler,200,{"ok":True,"saved_id":inserted,"source":"mongodb_atlas"});return True
        try:
            answer=evidence_reply(question,deterministic,provider)
        except IntegrationError as ex:
            public["narrative"]=None
            public["narrative_error"]=str(ex)[:150]
            public["provider"]=provider
            _send(handler,200,public)
            return True
        _send(handler,200,answer)
    except (IntegrationError,ValueError,UnicodeError) as ex:
        _send(handler,400,{"ok":False,"error":str(ex)[:150]})
    except Exception:
        # Do not disclose provider tokens, URLs, tracebacks, or underlying case data.
        _send(handler,503,{"ok":False,"error":"Integration unavailable"})
    return True
