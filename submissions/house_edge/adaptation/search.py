"""Choose adaptation settings on one half of the validation episodes.

The report half is scored after the choice is frozen.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPT = ROOT / "data" / "incoming" / "adaptation_kit"
MAIN_KIT = ROOT / "data" / "incoming" / "house_edge_kit"
MAIN_MODEL = ROOT / "submissions" / "house_edge" / "main"
sys.path.insert(0, str(ADAPT))

from slot_forecasting.contest import contest_score  # noqa: E402
from slot_forecasting.io import read_rows, read_submission, read_targets  # noqa: E402

from model import Forecaster, default_settings, load_split  # noqa: E402

PUBLIC = ADAPT / "public"
OUT = Path(__file__).resolve().parent / "artifacts"


def conditions_of(folder: Path) -> dict[str, str]:
    return {row["query_id"]: row["condition"] for row in read_rows(folder / "conditions.csv", ("query_id", "condition"))}


def halves(queries: list[dict], conditions: dict[str, str]) -> tuple[set[str], set[str]]:
    by_condition: dict[str, list[str]] = defaultdict(list)
    for query in queries:
        episode = query["episode_id"]
        condition = conditions[query["query_id"]]
        if episode not in by_condition[condition]:
            by_condition[condition].append(episode)
    select, report = set(), set()
    for episodes in by_condition.values():
        ordered = sorted(set(episodes))
        cut = max(1, len(ordered) // 2)
        select.update(ordered[:cut])
        report.update(ordered[cut:])
    return select, report


def load_score_parts(folder: Path):
    targets = read_targets(folder / "targets.csv")
    groups = conditions_of(folder)
    reference = read_submission(folder / "reference.csv")
    return targets, groups, reference


def score_ids(predictions, targets, groups, reference, ids: set[str]) -> dict:
    subset = [target for target in targets if target.query_id in ids]
    return contest_score(
        {target.query_id: predictions[target.query_id] for target in subset},
        subset,
        {target.query_id: groups[target.query_id] for target in subset},
        {target.query_id: reference[target.query_id] for target in subset},
        max_points=20,
    )


def merge_splits(first, second):
    queries = list(first[0]) + list(second[0])
    history = dict(first[1])
    history.update(second[1])
    labels = dict(first[2])
    labels.update(second[2])
    return queries, history, labels


def apply_forecasts(model: Forecaster, prepared: list[dict], settings: dict) -> dict[str, list[float]]:
    model.settings = settings
    return {item["query_id"]: model._forecast(item) for item in prepared}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    train = load_split(PUBLIC / "train")
    valid_q, valid_h, _labels = load_split(PUBLIC / "validation")
    main_train = load_split(MAIN_KIT / "public" / "train")
    targets, groups, reference = load_score_parts(PUBLIC / "validation")
    select_eps, report_eps = halves(valid_q, groups)
    select_ids = {query["query_id"] for query in valid_q if query["episode_id"] in select_eps}
    report_ids = {query["query_id"] for query in valid_q if query["episode_id"] in report_eps}
    all_ids = {query["query_id"] for query in valid_q}

    def evaluate(predictions, ids):
        report = score_ids(predictions, targets, groups, reference, ids)
        return {
            "technical_points": report["technical_points"],
            "mean_loss_ratio": report["mean_loss_ratio"],
            "by_condition": {
                name: {"loss_ratio": values["loss_ratio"], "error": values["error"]}
                for name, values in report["by_condition"].items()
            },
        }

    base = Forecaster(default_settings())
    base.fit(*train)
    prepared = [base._prepare(query, valid_h) for query in valid_q]
    both = Forecaster(default_settings())
    both.fit(*merge_splits(train, main_train))

    results = []

    def remember(name, model, settings, predictions=None):
        if predictions is None:
            predictions = apply_forecasts(model, prepared, settings)
        record = {
            "name": name,
            "select": evaluate(predictions, select_ids),
            "settings": settings,
        }
        results.append((record["select"]["technical_points"], name, record, predictions))
        brief = {key: round(record["select"]["by_condition"][key]["loss_ratio"], 4) for key in record["select"]["by_condition"]}
        print(f"{record['select']['technical_points']:.4f}  {name}  {brief}", flush=True)
        return predictions

    print("baselines", flush=True)
    remember("default-adapt", base, default_settings())
    sharp = default_settings()
    sharp["prior_strength"] = 2.0
    sharp["half_life"] = 2000.0
    sharp["weights"] = {"decay": 1.0, "memory": 0.0, "lag": 0.0, "pattern": 0.0, "peer": 0.0, "size": 0.0}
    remember("mle-adapt", base, sharp)
    remember("default-both", both, default_settings())

    import importlib.util

    spec = importlib.util.spec_from_file_location("main_model", MAIN_MODEL / "model.py")
    main_model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_model)
    legacy_model = main_model.Forecaster().fit(*train)
    legacy_pred = legacy_model.predict(valid_q, valid_h)
    remember("legacy-refit", base, legacy_model.settings, legacy_pred)
    frozen = main_model.load_model(MAIN_MODEL / "artifacts" / "model.json")
    remember("legacy-frozen", base, frozen.settings, frozen.predict(valid_q, valid_h))

    print("coordinate search", flush=True)
    current = default_settings()
    starts = [default_settings(), sharp, legacy_model.settings | {"use_main": False}]
    # The legacy settings dict is not the same schema. Search only our schema.
    starts = [default_settings(), sharp]

    axes = [
        ("half_life", [8, 16, 24, 48, 96, 256, 2000]),
        ("prior_strength", [1, 2, 4, 8, 16, 32]),
        ("lag_half_life", [8, 24, 64, 256]),
        ("lag_strength", [1, 4, 12, 30]),
        ("lag_gate", [1, 4, 12, 30]),
        ("pattern", ["c1235", "c123", "c12", "e12", "e1", "z123", "z12"]),
        ("pattern_half_life", [16, 32, 96]),
        ("pattern_strength", [0.5, 2, 8]),
        ("pattern_gate", [1, 4, 12]),
        ("short_window", [12, 24, 40, 80]),
        ("kl_switch", [0.05, 0.12, 0.3, 1.0]),
        ("peer_scale", [0.0, 0.5, 1.0]),
        ("peer_window", [12, 24, 48]),
        ("zero_half_life", [8, 16, 48]),
        ("size_half_life", [48, 96, 256]),
        ("use_type_lag", [True, False]),
    ]

    def vary_weights(base_settings):
        found = []
        options = {
            "decay": [0.15, 0.4, 0.7, 1.0],
            "memory": [0.0, 0.2, 0.45],
            "lag": [0.0, 0.2, 0.45, 0.7],
            "pattern": [0.0, 0.25, 0.55],
            "peer": [0.0, 0.2],
            "size": [0.0, 0.25, 0.5],
        }
        # One-at-a-time from the current weights, then a few sharp corners.
        for key, values in options.items():
            for value in values:
                trial = json.loads(json.dumps(base_settings))
                trial["weights"][key] = value
                found.append(trial)
        for decay, lag, pattern, memory in (
            (1.0, 0.0, 0.0, 0.0),
            (0.6, 0.4, 0.0, 0.0),
            (0.5, 0.0, 0.5, 0.0),
            (0.4, 0.2, 0.2, 0.2),
            (0.3, 0.1, 0.0, 0.1),
            (0.2, 0.6, 0.2, 0.0),
        ):
            trial = json.loads(json.dumps(base_settings))
            trial["weights"] = {
                "decay": decay,
                "memory": memory,
                "lag": lag,
                "pattern": pattern,
                "peer": 0.0,
                "size": 0.0,
            }
            found.append(trial)
        return found

    best_select = -1.0
    best_settings = default_settings()
    best_predictions = None

    def consider(trial, predictions, label):
        nonlocal best_select, best_settings, best_predictions
        report = evaluate(predictions, select_ids)
        points = report["technical_points"]
        if points > best_select + 1e-6:
            best_select = points
            best_settings = trial
            best_predictions = predictions
            print(f"{best_select:.4f}  {label}", flush=True)
        return points

    for start_index, start in enumerate(starts):
        current = json.loads(json.dumps(start))
        current_score = consider(current, apply_forecasts(base, prepared, current), f"start{start_index}")
        for _round in range(2):
            improved = False
            for trial in vary_weights(current):
                predictions = apply_forecasts(base, prepared, trial)
                points = evaluate(predictions, select_ids)["technical_points"]
                if points > current_score + 1e-6:
                    current_score = points
                    current = trial
                    improved = True
                    consider(trial, predictions, f"start{start_index} weights")
            for key, values in axes:
                for value in values:
                    trial = json.loads(json.dumps(current))
                    trial[key] = value
                    predictions = apply_forecasts(base, prepared, trial)
                    points = evaluate(predictions, select_ids)["technical_points"]
                    if points > current_score + 1e-6:
                        current_score = points
                        current = trial
                        improved = True
                        consider(trial, predictions, f"start{start_index} {key}={value}")
            if not improved:
                break
        print(f"start {start_index} local {current_score:.4f}", flush=True)

    assert best_predictions is not None
    report_score = evaluate(best_predictions, report_ids)
    full_score = evaluate(best_predictions, all_ids)
    both_predictions = apply_forecasts(both, prepared, best_settings)
    both_select = evaluate(both_predictions, select_ids)
    chosen_model = "adapt"
    chosen_predictions = best_predictions
    chosen_settings = json.loads(json.dumps(best_settings))
    if both_select["technical_points"] > best_select + 0.02:
        chosen_model = "both"
        chosen_predictions = both_predictions
        chosen_settings["use_main"] = True
        report_score = evaluate(chosen_predictions, report_ids)
        full_score = evaluate(chosen_predictions, all_ids)
        best_select = both_select["technical_points"]
    summary = {
        "chosen_model": chosen_model,
        "selection_points": best_select,
        "report_points": report_score,
        "full_points": full_score,
        "both_select_points": both_select["technical_points"],
        "settings": chosen_settings,
    }
    (OUT / "search.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selection": best_select, "report": report_score["technical_points"], "full": full_score["technical_points"], "model": chosen_model}, indent=2))


if __name__ == "__main__":
    main()
