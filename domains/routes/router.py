"""Multi-mode routes. Crowd weights come only from observation rows."""

from __future__ import annotations

import csv
import json
from heapq import heappop, heappush
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = Path(__file__).with_name("graph.json")
OBS_PATH = ROOT / "data" / "routes" / "observations.csv"

MODES = ("walk", "bike", "scooter", "car", "ev", "bus")
SPEED_KMH = {"walk": 5, "bike": 16, "scooter": 15, "car": 35, "ev": 35, "bus": 22}


def load_graph() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def load_observations(path: Path = OBS_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    kept = []
    for row in rows:
        if row.get("consent") != "yes":
            continue
        if not row.get("respondent_id") or not row.get("observed_at"):
            continue
        kept.append(row)
    return kept


def crowd_index(observations: list[dict], edge_id: str) -> tuple[float | None, int]:
    levels = []
    for row in observations:
        if row.get("edge_id") != edge_id:
            continue
        if row.get("crowd_level", "") == "":
            continue
        levels.append(float(row["crowd_level"]))
    if not levels:
        return None, 0
    return sum(levels) / len(levels), len(levels)


def _neighbors(graph: dict, mode: str) -> dict[str, list[tuple[str, dict]]]:
    allowed = {"walk": {"walk", "shared"}, "bike": {"bike", "shared"}, "scooter": {"bike", "shared"},
               "car": {"drive"}, "ev": {"drive"}, "bus": {"bus"}}[mode]
    out: dict[str, list[tuple[str, dict]]] = {node["id"]: [] for node in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["kind"] not in allowed:
            continue
        out[edge["from"]].append((edge["to"], edge))
    return out


def route(origin: str, dest: str, mode: str, observations: list[dict] | None = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    graph = load_graph()
    observations = load_observations() if observations is None else observations
    nodes = {node["id"]: node for node in graph["nodes"]}
    if origin not in nodes or dest not in nodes:
        return {"ok": False, "error": "unknown place", "base": None, "adjusted": None}
    if mode == "bus" and not any(edge["kind"] == "bus" for edge in graph["edges"]):
        return {"ok": False, "error": "bus mode unavailable: no GTFS feed is loaded", "base": None, "adjusted": None}
    neighbors = _neighbors(graph, mode)

    def search(use_crowd: bool) -> dict | None:
        queue = [(0.0, origin, [])]
        seen = set()
        while queue:
            minutes, node, path = heappop(queue)
            if node in seen:
                continue
            seen.add(node)
            path = path + [node]
            if node == dest:
                return {"minutes": round(minutes, 2), "nodes": path}
            for nxt, edge in neighbors[node]:
                hours = edge["km"] / SPEED_KMH[mode]
                base = hours * 60
                level, count = crowd_index(observations, edge["id"])
                factor = 1 + 0.15 * level if use_crowd and level is not None else 1
                heappush(queue, (minutes + base * factor, nxt, path))
        return None

    base = search(False)
    adjusted = search(True) if observations else None
    cited = []
    if adjusted and base:
        for edge in graph["edges"]:
            level, count = crowd_index(observations, edge["id"])
            if count and edge["from"] in adjusted["nodes"] and edge["to"] in adjusted["nodes"]:
                cited.append({"edge_id": edge["id"], "crowd_level": level, "observations": count})
    return {
        "ok": True,
        "mode": mode,
        "origin": origin,
        "dest": dest,
        "sample_size": len(observations),
        "base": base,
        "adjusted": adjusted if observations else None,
        "crowd_layer": "available" if observations else "unavailable",
        "cited_observations": cited,
        "network": "supplementary local graph, not the primary dataset",
    }


def append_observation(row: dict, path: Path = OBS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["respondent_id", "protocol_version", "consent", "observed_at", "submitted_at",
              "mode", "origin", "dest", "edge_id", "crowd_level", "wait_minutes", "place_note"]
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new_file:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fields})
