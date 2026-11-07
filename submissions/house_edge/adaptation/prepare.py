"""Adaptation stays in its own folder. It does not overwrite the main kit."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT / "submissions" / "house_edge" / "main"
ADAPT = ROOT / "data" / "incoming" / "adaptation_kit"
OUT = Path(__file__).resolve().parent / "artifacts"


def main() -> None:
    metadata = ADAPT / "public" / "metadata.json"
    if not metadata.exists():
        report = {
            "task_status": "blocked",
            "reason": "The adaptation kit is not on disk. It is released at 9 PM Central. This script will not copy over the main kit.",
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return
    meta = json.loads(metadata.read_text(encoding="utf-8"))
    if meta.get("round") != "adaptation" and meta.get("mode") != "adaptation" and "adaptation" not in json.dumps(meta):
        raise SystemExit("metadata.json does not describe the adaptation round")
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(MAIN / "artifacts" / "model.json", OUT / "model.json")
    sys.path.insert(0, str(MAIN))
    from predict import main as predict_main
    sys.argv = ["predict.py", "--data", str(ADAPT / "public"), "--out", str(OUT / "submission.csv"), "--model", str(OUT / "model.json")]
    predict_main()
    print(json.dumps({"task_status": "baseline_copied", "note": "Unchanged main model ran on the adaptation public data."}))


if __name__ == "__main__":
    main()
