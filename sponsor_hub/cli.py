"""Local integration diagnostics. No network unless explicitly using --live."""
from __future__ import annotations
import argparse,json,sys,os
from .core import IntegrationError, public_status
from .llm import gemini_complete,snowflake_complete
from .prizes import vultr_instances,report_sha256
from .godaddy import qualify_domain, suggest_names
from .devwriting import load_scored_article

def main():
    p=argparse.ArgumentParser(description="Pit Boss sponsor adapter diagnostics")
    p.add_argument('action',choices=['status','gemini','snowflake','vultr','domain','sha256','dev'])
    p.add_argument('--live',action='store_true',help='Explicitly authorize a real external provider request')
    p.add_argument('--value',default='',help='Domain or local report file path (never a token)')
    a=p.parse_args()
    try:
        if a.action=='status':
            out={k:{'configured':v.configured,'live_checked':False} for k,v in public_status().items()}
        elif a.action=='sha256':
            from pathlib import Path
            path=Path(a.value)
            if not path.is_file() or path.stat().st_size>5_000_000: raise IntegrationError('Missing/oversized report')
            out={'sha256':report_sha256(path.read_bytes()),'published_to_solana':False}
        elif a.action=='dev':
            scored=load_scored_article()
            scored.pop('markdown', None)
            out=scored
        elif a.action=='domain' and not a.live:
            out={'suggestions':suggest_names(), **qualify_domain(a.value)} if a.value else {'suggestions':suggest_names(),'prize_ready':False,'registered_by_user':None}
        else:
            if not a.live: raise IntegrationError('Use --live to permit the external call')
            if a.action=='gemini': out={'provider':'gemini','reply':gemini_complete('Reply with exactly PONG.'),'live':True}
            elif a.action=='snowflake': out={'provider':'snowflake','reply':snowflake_complete('Reply with exactly PONG.'),'live':True}
            elif a.action=='vultr': out={'provider':'vultr','instances':vultr_instances(),'live':True}
            elif a.action=='domain': out=qualify_domain(a.value, live_dns=True, live_rdap=True)
        print(json.dumps(out,indent=2,default=str))
    except IntegrationError as e:
        print(json.dumps({'ok':False,'error':str(e)}),file=sys.stderr)
        sys.exit(2)

if __name__=='__main__':main()
