"""Install opt-in handler hooks into an existing TamuDatathonF26 checkout.

Does not touch Databricks, Poker, or the existing contest submissions.
Refuses unknown source layouts; creates a timestamped backup.
Run from repository root: python bridge_install.py --confirm
"""
from pathlib import Path
import argparse,shutil,datetime


def patch(source:str)->str:
    if "from sponsor_hub.gateway import handle_get_sponsor, handle_post_sponsor" in source:
        return source
    importer="from domains.routes.router import route"
    get_anchor='        parsed = urlparse(self.path)'
    post_anchor='    def do_POST(self) -> None:'
    if source.count(importer)!=1 or source.count(get_anchor)!=1 or source.count(post_anchor)!=1:
        raise RuntimeError("Existing server layout changed; manual review required")
    source=source.replace(importer, importer+"\nfrom sponsor_hub.gateway import handle_get_sponsor, handle_post_sponsor, _authenticated",1)
    source=source.replace(get_anchor,get_anchor+"\n        if handle_get_sponsor(self, parsed.path):\n            return",1)
    source=source.replace(post_anchor,post_anchor+"\n        if handle_post_sponsor(self):\n            return",1)
    # Keep deterministic /api/investigate available, but never allow an anonymous
    # caller to trigger the incumbent Gemini call on a public cloud deployment.
    unsafe='if result["ok"] and isinstance(question, str):'
    if unsafe in source:
        source=source.replace(unsafe,'if result["ok"] and isinstance(question, str) and _authenticated(self):',1)
    # Default remains loopback. A container must opt in to non-loopback binding.
    binder='ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()'
    if binder in source:
        source=source.replace('from pathlib import Path','from pathlib import Path\nimport os',1)
        source=source.replace(binder,'ThreadingHTTPServer((os.getenv("PITBOSS_HOST", "127.0.0.1"), int(os.getenv("PITBOSS_PORT", "8765"))), Handler).serve_forever()',1)
    return source

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--confirm",action="store_true")
    args=parser.parse_args()
    path=Path('apps/api/server.py')
    if not path.exists(): raise SystemExit('Run from TamuDatathonF26 repository root')
    original=path.read_text()
    patched=patch(original)
    if not args.confirm:
        print('Dry-run only. To install handler hooks run: python bridge_install.py --confirm')
        return
    if patched==original:
        print('Already installed');return
    backup=path.with_suffix('.py.backup-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    shutil.copy2(path,backup)
    path.write_text(patched)
    import ast
    try: ast.parse(path.read_text())
    except SyntaxError:
        shutil.copy2(backup,path)
        raise
    print('Installed verified hooks; backup:',backup)

if __name__=='__main__': main()
