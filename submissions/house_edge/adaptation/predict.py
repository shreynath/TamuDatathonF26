"""Reproduce the adaptation-round forecast offline.

python predict.py --data /data --out /output/submission.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from boost import load_trees, predict_queries

PAYOUTS = (0, 1, 2, 5, 20)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_split(folder: Path) -> tuple[list[dict], dict]:
    queries = _rows(folder / "queries.csv")
    history: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
    for row in _rows(folder / "history.csv"):
        history[(row["episode_id"], row["machine_id"])][int(row["tick"])] = int(row["payout"])
    return queries, history


def write_submission(path: Path, predictions: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["query_id", "p_0", "p_1", "p_2", "p_5", "p_20"])
        for query_id in sorted(predictions):
            values = predictions[query_id]
            total = sum(values)
            writer.writerow([query_id, *["%.10f" % (value / total) for value in values]])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--trees", default=str(Path(__file__).with_name("trees.json")))
    args = parser.parse_args()
    model = load_trees(Path(args.trees))
    queries, history = load_split(Path(args.data) / "test")
    write_submission(Path(args.out), predict_queries(model, queries, history))


if __name__ == "__main__":
    main()
