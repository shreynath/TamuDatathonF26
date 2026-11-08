"""Fit the adaptation trees once and write trees.json. Not part of the upload."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[3]
ADAPT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "data" / "incoming" / "adaptation_kit"))
sys.path.insert(0, str(ADAPT))

from slot_forecasting.contest import contest_score  # noqa: E402
from slot_forecasting.io import read_rows, read_submission, read_targets  # noqa: E402

from boost import features, load_trees, predict_queries, predict_row  # noqa: E402
from model import Forecaster, load_settings, load_split  # noqa: E402

PUBLIC = ROOT / "data" / "incoming" / "adaptation_kit" / "public"
PAYOUTS = (0, 1, 2, 5, 20)
INDEX = {value: index for index, value in enumerate(PAYOUTS)}


def pack_tree(predictor) -> list[list[float]]:
    nodes = []
    for node in predictor.nodes:
        if int(node["is_categorical"]):
            raise SystemExit("Categorical splits are not exported.")
        nodes.append(
            [
                int(node["feature_idx"]),
                float(node["num_threshold"]),
                int(node["left"]),
                int(node["right"]),
                float(node["value"]),
                int(node["is_leaf"]),
                int(node["missing_go_to_left"]),
            ]
        )
    return nodes


def main() -> None:
    train_queries, train_history, train_labels = load_split(PUBLIC / "train")
    rows = []
    targets = []
    for query in train_queries:
        cutoff = int(query["cutoff"])
        usable = dict(train_history.get((query["episode_id"], query["machine_id"]), {}))
        if query["query_id"] in train_labels:
            usable[cutoff] = train_labels[query["query_id"]]
        for tick, payout in usable.items():
            if tick < 8:
                continue
            rows.append(features(usable, tick, query["machine_type"], query["signal"]))
            targets.append(INDEX[int(payout)])
    model = HistGradientBoostingClassifier(
        max_depth=3,
        max_iter=80,
        learning_rate=0.08,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=0,
    )
    model.fit(np.array(rows, dtype=float), np.array(targets))
    if list(model.classes_) != [0, 1, 2, 3, 4]:
        raise SystemExit(f"Unexpected classes: {model.classes_}")
    payload = {
        "baseline": [float(value) for value in model._baseline_prediction.ravel()],
        "learning_rate": float(model.learning_rate),
        "max_depth": 3,
        "max_iter": int(model.n_iter_),
        "trees": [[pack_tree(tree) for tree in iteration] for iteration in model._predictors],
    }
    path = ADAPT / "trees.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    frozen = load_trees(path)
    valid_queries, valid_history, _labels = load_split(PUBLIC / "validation")
    mismatch = 0.0
    checked = 0
    for query in valid_queries[:40]:
        cutoff = int(query["cutoff"])
        usable = {
            tick: payout
            for tick, payout in valid_history[(query["episode_id"], query["machine_id"])].items()
            if tick < cutoff
        }
        row = features(usable, cutoff, query["machine_type"], query["signal"])
        local = predict_row(frozen, row)
        remote = model.predict_proba(np.array(row, dtype=float).reshape(1, -1))[0]
        mismatch = max(mismatch, max(abs(a - float(b)) for a, b in zip(local, remote)))
        checked += 1
    print(f"max abs diff on {checked} queries: {mismatch:.3e}")
    if mismatch > 1e-8:
        raise SystemExit("Exported trees do not match scikit-learn.")
    predictions = predict_queries(frozen, valid_queries, valid_history)
    targets_file = read_targets(PUBLIC / "validation" / "targets.csv")
    groups = {
        row["query_id"]: row["condition"]
        for row in read_rows(PUBLIC / "validation" / "conditions.csv", ("query_id", "condition"))
    }
    reference = read_submission(PUBLIC / "validation" / "reference.csv")
    by_condition = defaultdict(list)
    for query in valid_queries:
        episode = query["episode_id"]
        condition = groups[query["query_id"]]
        if episode not in by_condition[condition]:
            by_condition[condition].append(episode)
    select, report = set(), set()
    for episodes in by_condition.values():
        ordered = sorted(set(episodes))
        cut = len(ordered) // 2
        select.update(ordered[:cut])
        report.update(ordered[cut:])
    select_ids = {query["query_id"] for query in valid_queries if query["episode_id"] in select}
    report_ids = {query["query_id"] for query in valid_queries if query["episode_id"] in report}

    def points(preds, ids):
        subset = [target for target in targets_file if target.query_id in ids]
        scored = contest_score(
            {target.query_id: preds[target.query_id] for target in subset},
            subset,
            {target.query_id: groups[target.query_id] for target in subset},
            {target.query_id: reference[target.query_id] for target in subset},
            max_points=20,
        )
        return scored["technical_points"]

    print("trees", points(predictions, select_ids), points(predictions, report_ids), points(predictions, set(predictions)))
    settings = load_settings(ADAPT / "settings.json")
    frequency = Forecaster(settings).fit(train_queries, train_history, train_labels)
    base = frequency.predict(valid_queries, valid_history)
    best = None
    for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
        mixed = {}
        for query in valid_queries:
            key = query["query_id"]
            mixed[key] = [
                weight * predictions[key][index] + (1.0 - weight) * base[key][index] for index in range(5)
            ]
        select_points = points(mixed, select_ids)
        print(f"blend {weight:.2f} select {select_points:.4f}")
        if best is None or select_points > best[0]:
            best = (select_points, weight, mixed)
    assert best is not None
    print("chosen weight", best[1], "report", points(best[2], report_ids), "full", points(best[2], set(predictions)))
    (ADAPT / "blend_weight.json").write_text(json.dumps({"tree_weight": best[1]}) + "\n", encoding="utf-8")
    print("wrote", path, "bytes", path.stat().st_size)


if __name__ == "__main__":
    main()
