import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from domains.routes.router import append_observation, load_observations, route


class RouteTests(unittest.TestCase):
    def test_crowd_layer_disappears_without_rows(self):
        result = route("msc", "northgate", "walk", observations=[])
        self.assertTrue(result["ok"])
        self.assertIsNone(result["adjusted"])
        self.assertEqual(result["crowd_layer"], "unavailable")

    def test_observation_changes_walk(self):
        quiet = [{"consent": "yes", "respondent_id": "r1", "observed_at": "2026-11-07T18:00:00-06:00",
                  "edge_id": "library-northgate-walk", "crowd_level": "1"}]
        crowded = [{"consent": "yes", "respondent_id": "r1", "observed_at": "2026-11-07T18:00:00-06:00",
                    "edge_id": "library-northgate-walk", "crowd_level": "5"}]
        base = route("msc", "northgate", "walk", observations=[])
        busy = route("msc", "northgate", "walk", observations=crowded)
        calm = route("msc", "northgate", "walk", observations=quiet)
        self.assertGreater(busy["adjusted"]["minutes"], calm["adjusted"]["minutes"])
        self.assertEqual(base["base"]["minutes"], busy["base"]["minutes"])

    def test_append_roundtrip_requires_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.csv"
            append_observation({
                "respondent_id": "anon-1",
                "protocol_version": "1",
                "consent": "yes",
                "observed_at": "2026-11-07T18:00:00-06:00",
                "submitted_at": "2026-11-07T18:05:00-06:00",
                "mode": "walk",
                "origin": "msc",
                "dest": "library",
                "edge_id": "msc-library-walk",
                "crowd_level": "2",
                "wait_minutes": "",
                "place_note": "public block",
            }, path)
            rows = load_observations(path)
            self.assertEqual(len(rows), 1)
            with path.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
            written[0]["consent"] = "no"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=written[0].keys())
                writer.writeheader()
                writer.writerows(written)
            self.assertEqual(load_observations(path), [])


if __name__ == "__main__":
    unittest.main()
