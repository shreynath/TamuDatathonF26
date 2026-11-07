#!/usr/bin/env python3
"""Play PitBoss against public agents for this same short-deck game.

Third-party trees stay outside this repository. The script records the
commit it actually ran, then drives the official judge. It does not copy
opponent code into the submission package.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

POKER = Path(__file__).resolve().parents[1]
CHAMPION = "6b2921de93674e8600659540e307df5894b9e259"

# Paths are local checkouts. A missing GitHub repo is recorded, not invented.
OPPONENTS = [
    {
        "name": "ShortStackSage",
        "repo": "https://github.com/Dhanush006/ssd-heads-up-poker",
        "path": "/tmp/poker-field/ssd-heads-up-poker",
        "note": "A fresh GitHub lookup could not resolve this repo. The SHA is from the clone already on disk.",
    },
    {
        "name": "ShortStack",
        "repo": "https://github.com/Utsavdotcom/aura-farmer",
        "path": "/tmp/poker-field/aura-farmer",
    },
    {
        "name": "ShortDeckShark",
        "repo": "https://github.com/shaswat-singh23/datathon-poker",
        "path": "/tmp/poker-field/datathon-poker",
    },
    {
        "name": "EquityBot-v1",
        "repo": "https://github.com/jane-vo/tamu-datathon26",
        "path": "/tmp/poker-field/tamu-datathon26",
    },
    {
        "name": "SDPLO-RangeEV",
        "repo": "https://github.com/zeyad-commits/heads_up",
        "path": "/tmp/poker-field/heads_up",
        "note": "The published tree does not include the sdplo package. If that import fails, the process is not their intended strategy.",
    },
    {
        "name": "Timecasters",
        "repo": "https://github.com/andrewv426/timecasters-pokerbot",
        "path": "/tmp/poker-league/timecasters-pokerbot",
    },
    {
        "name": "MAKK",
        "repo": "https://github.com/karammasad/pokerMAKK",
        "path": "/tmp/poker-league/pokerMAKK",
    },
    {
        "name": "OPsAgent",
        "repo": "https://github.com/sapyao/heads-up",
        "path": "/tmp/poker-league/sapyao-heads-up",
    },
    {
        "name": "Prunuus",
        "repo": "https://github.com/Prunuus/heads-up",
        "path": "/tmp/poker-league/heads-up",
        "note": "Repository still uses the starter participant name.",
    },
    {
        "name": "Ruler10123",
        "repo": "https://github.com/Ruler10123/Datathon-2026-Poker-Bot-Challenge-Submission",
        "path": "/tmp/poker-league/Datathon-2026-Poker-Bot-Challenge-Submission",
        "note": "Repository still uses the starter participant name.",
    },
]


def git_sha(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    run = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else None


def license_status(path: Path) -> str:
    for name in ("LICENSE", "LICENSE.md", "COPYING", "license"):
        if (path / name).is_file():
            return name
    return "no-license-file"


def wait_ready(port: int, tries: int = 50) -> bool:
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5).read()
            return True
        except Exception:
            time.sleep(0.25)
    return False


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def parse_judge(stdout: str) -> dict:
    bb = stderr = None
    result = None
    thinks = []
    interval = None
    match = re.search(r"agent1:\s+([+-]?\d+\.\d+) bb/deal\s+\(std\s+[\d.]+,\s+stderr\s+([\d.]+)\)", stdout)
    if match:
        bb = float(match.group(1))
        stderr = float(match.group(2))
    found = re.search(r"Confidence interval \(z=1\.96\): \[([^\]]+)\]", stdout)
    if found:
        interval = found.group(1)
    verdict = re.search(r"RESULT:\s+(\S+)", stdout)
    if verdict:
        result = verdict.group(1)
    for line in stdout.splitlines():
        if "agent1 half" in line and "thinking" in line:
            thinks.append(line.strip())
    return {
        "bb_per_deal": bb,
        "stderr": stderr,
        "interval": interval,
        "result": result,
        "thinking": thinks,
        "errors": "errors 0" in stdout or all("errors 0" in line for line in thinks),
    }


def play(opponent: dict, deals: int, seed: str, our_port: int) -> dict:
    path = Path(opponent["path"])
    row = {
        "name": opponent["name"],
        "repo": opponent["repo"],
        "path": str(path),
        "sha": git_sha(path),
        "license": license_status(path) if path.is_dir() else "missing",
        "note": opponent.get("note"),
        "seed": seed,
        "deals": deals,
        "pitboss_sha": CHAMPION,
    }
    if not (path / "agent.py").is_file():
        row["status"] = "unavailable"
        row["reason"] = "agent.py is not in the checkout"
        return row
    log_path = POKER / "benchmarks" / f"{opponent['name']}-{seed}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "w")
    env = {**os.environ, "PORT": "5009"}
    proc = subprocess.Popen(
        ["python3", "agent.py"],
        cwd=path,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if not wait_ready(5009):
        stop(proc)
        log.close()
        text = log_path.read_text(errors="replace")[-500:]
        row["status"] = "not-ready"
        row["reason"] = text
        return row
    started = time.perf_counter()
    run = subprocess.run(
        ["python3", "judge_engine.py", "--agent1", str(our_port), "--agent2", "5009", "--deals", str(deals), "--seed", seed],
        cwd=POKER,
        capture_output=True,
        text=True,
        timeout=max(180, deals),
    )
    row["seconds"] = round(time.perf_counter() - started, 1)
    row["returncode"] = run.returncode
    row.update(parse_judge(run.stdout))
    row["status"] = "played"
    opponent_log = log_path.read_text(errors="replace")
    if "ModuleNotFoundError" in opponent_log or "Traceback" in opponent_log:
        row["opponent_log_tail"] = opponent_log[-400:]
    stop(proc)
    log.close()
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", type=int, default=300)
    parser.add_argument("--seeds", default="11,61")
    parser.add_argument("--out", default=str(POKER / "benchmarks" / "league.json"))
    args = parser.parse_args()
    seeds = [part.strip() for part in args.seeds.split(",") if part.strip()]
    our = subprocess.Popen(
        ["python3", "agent.py"],
        cwd=POKER,
        env={**os.environ, "PORT": "5008"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_ready(5008):
        stop(our)
        raise SystemExit("PitBoss did not start on port 5008")
    rows = []
    try:
        for opponent in OPPONENTS:
            for seed in seeds:
                print(f"playing {opponent['name']} seed {seed}", flush=True)
                row = play(opponent, args.deals, seed, 5008)
                rows.append(row)
                print(
                    row.get("status"),
                    row.get("result"),
                    row.get("bb_per_deal"),
                    row.get("sha"),
                    flush=True,
                )
    finally:
        stop(our)
    payload = {
        "champion": CHAMPION,
        "deals_per_half": args.deals,
        "seeds": seeds,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
