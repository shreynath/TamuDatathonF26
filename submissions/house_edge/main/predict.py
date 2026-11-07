"""Reproduce the House Edge CSV offline.

python predict.py --data /data --out /output/submission.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from model import load_model, load_split, write_submission


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default=str(Path(__file__).with_name("artifacts") / "model.json"))
    args = parser.parse_args()
    model = load_model(Path(args.model))
    folder = Path(args.data)
    test_folder = folder / "test"
    if (test_folder / "queries.csv").exists():
        folder = test_folder
    queries, history, _labels = load_split(folder)
    write_submission(Path(args.out), model.predict(queries, history))


if __name__ == "__main__":
    main()
