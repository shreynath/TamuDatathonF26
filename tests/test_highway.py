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

    def test_invariants_on_the_full_feed(self):
        from enterprise import Enterprise, LOANER_TIERS

        results = run_events(EVENTS)
        enterprise = Enterprise(str(ROOT / "data" / "highway"))
        self.assertTrue(all(result["verifier_failures"] == [] for result in results))
        for result in results:
            notifies = {}
            for call in result["calls"]:
                self.assertTrue(call["ok"])
                if call["tool"] == "dealer.notify":
                    dealer = call["args"]["dealer_id"]
                    self.assertNotIn(dealer, notifies)
                    notifies[dealer] = call["args"]["customer_order_ids"]
                if call["tool"] == "crm.assign_loaner":
                    order = enterprise.cos[call["args"]["customer_order_id"]]
                    tier = enterprise.customers[order["customer_id"]]["tier"]
                    self.assertIn(tier, LOANER_TIERS)
            if result["event_id"] == "E-05":
                self.assertEqual(result["calls"], [])
            if result["event_id"] == "E-02":
                self.assertEqual([call["tool"] for call in result["calls"]], ["escalate"])

    def test_log_has_no_hardcoded_event_table(self):
        results = run_events(EVENTS)
        tools = {call["tool"] for result in results for call in result["calls"]}
        self.assertIn("mes.reschedule", tools)
        self.assertIn("quality.hold_lot", tools)
        path = ROOT / "data" / "highway" / "runs" / "action_log.jsonl"
        write_log(results, path)
        self.assertTrue(path.exists())

    def test_unknown_explicit_id_does_not_guess(self):
        from domains.highway.engine import _resolve_lot, _resolve_shipment

        world = World()
        missing = {
            "shipment_id": "SH-9999",
            "lot_id": None,
            "dates": ["2027-03-15"],
            "suppliers": [world.shipments[0]["supplier_id"]],
            "parts": [world.shipments[0]["part_id"]],
            "plants": [world.shipments[0]["plant_id"]],
        }
        self.assertIsNone(_resolve_shipment(world, missing))
        missing["shipment_id"] = None
        missing["lot_id"] = "LOT-9999"
        self.assertIsNone(_resolve_lot(world, missing))

    def test_world_uses_the_directory_it_is_given(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                World(Path(tmp))


if __name__ == "__main__":
    unittest.main()
