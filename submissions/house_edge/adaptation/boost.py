"""Frozen histogram-boosting forecast. Python standard library only.

The trees were fit on training spins. A tick is a label only for earlier ticks.
Missing lags are -1. Condition labels are never read.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PAYOUTS = (0, 1, 2, 5, 20)
INDEX = {value: index for index, value in enumerate(PAYOUTS)}
LAGS = (1, 2, 3, 4, 5, 8)
WINDOWS = (8, 16, 32)
TYPE_CODE = {"steady": 0, "balanced": 1, "jackpot": 2}


def features(usable: dict[int, int], tick: int, machine_type: str, signal: str) -> list[float]:
    row: list[float] = []
    for lag in LAGS:
        previous = usable.get(tick - lag)
        row.append(-1.0 if previous is None else float(INDEX[int(previous)]))
    for window in WINDOWS:
        values = [usable[older] for older in range(tick - window, tick) if older in usable]
        if not values:
            row.extend((0.6, 0.0, 0.0))
            continue
        row.append(sum(value == 0 for value in values) / len(values))
        row.append(sum(values) / len(values) / 5.0)
        row.append(len(values) / window)
    row.append(float(TYPE_CODE[machine_type]))
    row.append(float(int(signal)))
    return row


def load_trees(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(nodes: list[list[float]], row: list[float]) -> float:
    index = 0
    while True:
        feature, threshold, left, right, value, is_leaf, missing_left = nodes[index]
        if is_leaf:
            return value
        observed = row[int(feature)]
        if observed != observed:
            index = int(left if missing_left else right)
        elif observed <= threshold:
            index = int(left)
        else:
            index = int(right)


def predict_row(model: dict, row: list[float]) -> list[float]:
    raw = [float(value) for value in model["baseline"]]
    for iteration in model["trees"]:
        for klass, nodes in enumerate(iteration):
            raw[klass] += _walk(nodes, row)
    largest = max(raw)
    weights = [math.exp(value - largest) for value in raw]
    total = math.fsum(weights)
    return [value / total for value in weights]


def predict_queries(model: dict, queries: list[dict], history: dict) -> dict[str, list[float]]:
    predictions = {}
    for query in queries:
        cutoff = int(query["cutoff"])
        usable = {
            tick: payout
            for tick, payout in history.get((query["episode_id"], query["machine_id"]), {}).items()
            if tick < cutoff
        }
        row = features(usable, cutoff, query["machine_type"], query["signal"])
        predictions[query["query_id"]] = predict_row(model, row)
    return predictions
