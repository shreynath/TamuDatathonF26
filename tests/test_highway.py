import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "highway"))

from domains.highway.engine import parse_dates, parse_incidents, run_events, write_log
from domains.highway.engine import World


EVENTS = json.loads((ROOT / "data" / "highway" / "events.json").read_text(encoding="utf-8"))


class HighwayTests(unittest.TestCase):
    def test_relative_dates_use_scenario_monday(self):
        dates = [value.isoformat() for value in parse_dates("dark from next Friday through Monday Mar 22")]
        self.assertEqual(dates[0], "2027-03-12")
        self.assertIn("2027-03-22", dates)

    def test_noise_and_rumor(self):
        results = {item["event_id"]: item for item in run_events(EVENTS)}
        self.assertEqual(results["E-05"]["calls"], [])
        self.assertEqual([call["tool"] for call in results["E-02"]["calls"]], ["escalate"])

    def test_paraphrase_still_finds_shipment(self):
        world = World()
        text = "Update: shipment SH-0182 of the surround-view cameras for Princeton was due 2027-03-15 and will now arrive 2027-03-18 because the port is congested."
        incidents = parse_incidents(text, world)
        self.assertEqual(incidents[0]["shipment_id"], "SH-0182")
        self.assertEqual(incidents[0]["kind"], "supplier_delay")

    def test_changed_date_changes_window(self):
        world = World()
        early = parse_incidents("SH-0182 delayed, will now arrive 2027-03-18.", world)[0]["dates"]
        later = parse_incidents("SH-0182 delayed, will now arrive 2027-03-20.", world)[0]["dates"]
        self.assertNotEqual(early, later)

    def test_log_has_no_hardcoded_event_table(self):
        results = run_events(EVENTS)
        tools = {call["tool"] for result in results for call in result["calls"]}
        self.assertIn("mes.reschedule", tools)
        self.assertIn("quality.hold_lot", tools)
        path = ROOT / "data" / "highway" / "runs" / "action_log.jsonl"
        write_log(results, path)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
