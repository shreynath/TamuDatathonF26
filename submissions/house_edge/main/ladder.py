"""Select House Edge settings on one half of the validation episodes.

The other half is scored once, after the choice is frozen.
Official contest_score from the kit is used for the comparison.
The kit is an evaluation tool only. predict.py does not import it.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "data" / "incoming" / "house_edge_kit"
sys.path.insert(0, str(KIT))

from slot_forecasting.contest import score_contest_files  # noqa: E402

from model import Forecaster, load_split, write_submission  # noqa: E402

PUBLIC = KIT / "public"
OUT = ROOT / "submissions" / "house_edge" / "main" / "artifacts"


def _conditions(folder: Path) -> dict[str, str]:
    import csv
    with (folder / "conditions.csv").open(newline="", encoding="utf-8") as handle:
        return {row["query_id"]: row["condition"] for row in csv.DictReader(handle)}


def _halves(queries: list[dict], conditions: dict[str, str]) -> tuple[set[str], set[str]]:
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
        report.update(ordered[cut:] or ordered[:1])
    return select, report


def _subset(queries: list[dict], episodes: set[str]) -> list[dict]:
    return [query for query in queries if query["episode_id"] in episodes]


def _score(folder: Path, predictions: dict, name: str) -> dict:
    path = OUT / f"{name}.csv"
    write_submission(path, predictions)
    report = score_contest_files(
        path,
        folder / "targets.csv",
        folder / "queries.csv",
        folder / "conditions.csv",
        folder / "reference.csv",
        max_points=60,
    )
    return {"technical_points": report["technical_points"], "mean_loss_ratio": report["mean_loss_ratio"],
            "by_condition": report["by_condition"]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    train_q, train_h, train_y = load_split(PUBLIC / "train")
    valid_q, valid_h, _ = load_split(PUBLIC / "validation")
    model = Forecaster().fit(train_q, train_h, train_y)
    conditions = _conditions(PUBLIC / "validation")
    select, report = _halves(valid_q, conditions)
    candidates = []
    for half_life in (16, 24, 48):
        for window in (16, 24, 40):
            for shared in (0.0, 0.15, 0.3):
                for lag in (0.0, 0.2, 0.35):
                    decay = max(0.05, 1.0 - 0.25 - lag)
                    settings = {
                        "half_life": half_life,
                        "prior_strength": 20.0,
                        "short_window": window,
                        "kl_switch": 0.15,
                        "weights": {"decay": decay, "short": 0.25, "lag": lag, "shared": shared},
                        "shared_by_type": {"steady": shared * 0.5, "balanced": shared, "jackpot": shared * 1.5},
                    }
                    model.settings = settings
                    chosen = model.predict(_subset(valid_q, select), valid_h)
                    # Score only the selection queries by writing a file that still must
                    # contain every validation id. Fill the report half with the decay-only
                    # candidate so the file is complete, then read by_condition is not
                    # a pure selection score. Score selection ids through a temporary
                    # targets copy instead.
                    candidates.append((settings, chosen))

    best_points = -1.0
    best_settings = None
    best_select_pred = None
    selection_queries = {query["query_id"] for query in _subset(valid_q, select)}
    for settings, chosen in candidates:
        filled = {}
        for query in valid_q:
            if query["query_id"] in selection_queries:
                filled[query["query_id"]] = chosen[query["query_id"]]
            else:
                filled[query["query_id"]] = [0.6, 0.2, 0.12, 0.06, 0.02]
        # The filler would distort a full-file score. Score with a filtered
        # target file written beside the candidate.
        points = _selection_points(valid_q, valid_h, conditions, select, chosen)
        if points > best_points:
            best_points = points
            best_settings = settings
            best_select_pred = chosen

    assert best_settings is not None and best_select_pred is not None
    model.settings = best_settings
    report_pred = model.predict(_subset(valid_q, report), valid_h)
    report_points = _selection_points(valid_q, valid_h, conditions, report, report_pred)
    full_pred = model.predict(valid_q, valid_h)
    full = _score(PUBLIC / "validation", full_pred, "validation_selected")
    test_q, test_h, _ = load_split(PUBLIC / "test")
    test_pred = model.predict(test_q, test_h)
    write_submission(OUT / "submission.csv", test_pred)
    write_submission(ROOT / "submissions" / "house_edge" / "main" / "validation_predictions.csv", full_pred)
    payload = model.to_json()
    (OUT / "model.json").write_text(json.dumps(payload), encoding="utf-8")
    summary = {
        "selection_points_half": best_points,
        "report_points_half": report_points,
        "full_validation_technical_points": full["technical_points"],
        "full_validation_mean_loss_ratio": full["mean_loss_ratio"],
        "by_condition": full["by_condition"],
        "settings": best_settings,
        "max_points_in_kit_metadata": 60,
        "note": "Kit metadata max_points is 60 for this main file. The planning paste said 80. The kit file is the source used here.",
        "upload": "not submitted; portal and team token are not in this repo",
    }
    (OUT / "ladder_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("selection_points_half", "report_points_half", "full_validation_technical_points", "settings")}, indent=2))


def _selection_points(queries, history, conditions, episodes, predictions) -> float:
    import csv
    import tempfile
    folder = PUBLIC / "validation"
    ids = {query["query_id"] for query in queries if query["episode_id"] in episodes}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for name in ("queries.csv", "targets.csv", "conditions.csv", "reference.csv"):
            with (folder / name).open(newline="", encoding="utf-8") as source:
                rows = [row for row in csv.DictReader(source) if row["query_id"] in ids]
                with (tmp_path / name).open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
        write_submission(tmp_path / "pred.csv", {key: predictions[key] for key in ids})
        report = score_contest_files(
            tmp_path / "pred.csv",
            tmp_path / "targets.csv",
            tmp_path / "queries.csv",
            tmp_path / "conditions.csv",
            tmp_path / "reference.csv",
            max_points=60,
        )
    return float(report["technical_points"])


if __name__ == "__main__":
    main()
