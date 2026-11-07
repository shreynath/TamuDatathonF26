"""Hack the Highway planner.

The language-model hook may propose incidents. Write tools run only after
this module derives the affected set. Rules come from policy_handbook.md.
Scenario today is 2027-03-08, not the laptop clock.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "highway"
sys.path.insert(0, str(DATA))

from enterprise import (  # noqa: E402
    LAST_IDX,
    LOANER_TIERS,
    START,
    TIER_RANK,
    Enterprise,
    ToolError,
    date_to_idx,
    idx_to_date,
)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _read(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class World:
    def __init__(self, data: Path = DATA):
        self.aliases = sorted(_read("aliases.csv"), key=lambda row: len(row["alias"]), reverse=True)
        self.shipments = _read("inbound_shipments.csv")
        self.lots = _read("part_lots.csv")
        self.orders = _read("production_orders.csv")
        self.bom = defaultdict(set)
        for row in _read("bom.csv"):
            self.bom[row["model"]].add(row["part_id"])
        self.vehicles = _read("finished_vehicles.csv")
        self.customers = {row["customer_id"]: row for row in _read("customers.csv")}
        self.customer_orders = _read("customer_orders.csv")
        self.plants = {row["alias"].lower(): row["entity_id"] for row in self.aliases if row["entity_type"] == "plant"}


def _as_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _weekday_date(today: date, name: str, which: str) -> date:
    target = WEEKDAYS.index(name)
    if which == "last":
        delta = (today.weekday() - target) % 7
        delta = 7 if delta == 0 else delta
        return today - timedelta(days=delta)
    delta = (target - today.weekday()) % 7
    delta = 7 if delta == 0 else delta
    return today + timedelta(days=delta)


def parse_dates(text: str, today: date = START) -> list[date]:
    found: list[tuple[int, date]] = []
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        value = _as_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            found.append((match.start(), value))
    for match in re.finditer(r"\b(next|last|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.I):
        which = "last" if match.group(1).lower() == "last" else "next"
        found.append((match.start(), _weekday_date(today, match.group(2).lower(), which)))
    month = "|".join(MONTHS)
    for match in re.finditer(rf"\b(?:(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+)?({month})\.?\s+(\d{{1,2}})\b", text, re.I):
        value = _as_date(today.year, MONTHS[match.group(2).lower()], int(match.group(3)))
        if value:
            found.append((match.start(), value))
    found.sort(key=lambda item: item[0])
    ordered: list[date] = []
    for _pos, value in found:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _entities(text: str, world: World) -> dict[str, list[str]]:
    lowered = text.lower()
    found: dict[str, list[str]] = defaultdict(list)
    for row in world.aliases:
        if row["alias"].lower() in lowered and row["entity_id"] not in found[row["entity_type"]]:
            found[row["entity_type"]].append(row["entity_id"])
    return found


def _kind(text: str) -> str:
    low = text.lower()
    if re.search(r"brochure|price list|price-list", low):
        return "noise"
    explicit = bool(re.search(r"\bSH-\d+\b|\bLOT-\d+\b|\d{4}-\d{2}-\d{2}", text))
    if re.search(r"rumor|not confirmed|nothing confirmed|no dates|possible shortage|may be off|someone on the floor", low) and not explicit:
        return "unconfirmed"
    if re.search(r"quality|faulty|suspect|contamination|moisture|on hold", low):
        return "quality_hold"
    if re.search(r"outage|power failure|dark from|production is stopped|lost production", low):
        return "plant_outage"
    if re.search(r"delay|can't make it|cannot make|will now arrive|original drop|carrier says|new eta", low):
        return "supplier_delay"
    return "noise" if "pdf" in low else "unconfirmed"


def parse_incidents(text: str, world: World, today: date = START) -> list[dict]:
    parts = re.split(r"\(\d+\)\s*", text)
    clauses = [part.strip(" .;") for part in parts if part.strip(" .;")]
    if len(clauses) <= 1:
        clauses = [text.strip()]
    incidents = []
    for clause in clauses:
        kind = _kind(clause)
        entities = _entities(clause, world)
        dates = parse_dates(clause, today)
        shipment = re.search(r"\b(SH-\d+)\b", clause)
        lot = re.search(r"\b(LOT-\d+)\b", clause)
        incidents.append({
            "kind": kind,
            "text": clause,
            "plants": entities.get("plant", []),
            "parts": entities.get("part", []),
            "suppliers": entities.get("supplier", []),
            "dates": [value.isoformat() for value in dates],
            "shipment_id": shipment.group(1) if shipment else None,
            "lot_id": lot.group(1) if lot else None,
        })
    return incidents


def _working(value: date) -> int | None:
    try:
        idx = date_to_idx(value)
    except ValueError:
        return None
    if 0 <= idx <= LAST_IDX:
        return idx
    return None


def _resolve_shipment(world: World, incident: dict) -> dict | None:
    if incident["shipment_id"]:
        for row in world.shipments:
            if row["shipment_id"] == incident["shipment_id"]:
                return row
    dates = [date.fromisoformat(value) for value in incident["dates"]]
    old = dates[0] if dates else None
    candidates = []
    for row in world.shipments:
        if incident["suppliers"] and row["supplier_id"] not in incident["suppliers"]:
            continue
        if incident["parts"] and row["part_id"] not in incident["parts"]:
            continue
        if incident["plants"] and row["plant_id"] not in incident["plants"]:
            continue
        eta = date.fromisoformat(row["eta_date"])
        distance = abs((eta - old).days) if old else 0
        candidates.append((distance, row["shipment_id"], row))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _resolve_lot(world: World, incident: dict) -> dict | None:
    if incident["lot_id"]:
        for row in world.lots:
            if row["lot_id"] == incident["lot_id"]:
                return row
    dates = [date.fromisoformat(value) for value in incident["dates"]]
    best = None
    for row in world.lots:
        if incident["parts"] and row["part_id"] not in incident["parts"]:
            continue
        if incident["suppliers"] and row["supplier_id"] not in incident["suppliers"]:
            continue
        if incident["plants"] and row["plant_id"] not in incident["plants"]:
            continue
        start = date.fromisoformat(row["first_build_date"])
        end = date.fromisoformat(row["last_build_date"])
        if dates and not any(start <= value <= end for value in dates):
            continue
        best = row
        break
    return best


def _earliest(enterprise: Enterprise, state: dict, model: str, plant: str, start_idx: int) -> tuple[str, int] | None:
    for idx in range(start_idx, LAST_IDX + 1):
        if len(state["slots"][(plant, idx)]) < enterprise.plants[plant]["slots"]:
            return plant, idx
    for other, info in sorted(enterprise.plants.items()):
        if other == plant or model not in info["models"]:
            continue
        for idx in range(start_idx, LAST_IDX + 1):
            if len(state["slots"][(other, idx)]) < info["slots"]:
                return other, idx
    return None


def _affected_orders(enterprise: Enterprise, state: dict, plant: str, blocked: set[int], part: str | None) -> list[str]:
    chosen = []
    for po, (current_plant, idx) in state["loc"].items():
        if current_plant != plant or idx not in blocked:
            continue
        model = enterprise.orders[po]["model"]
        if part is not None and part not in enterprise.bom[model]:
            continue
        chosen.append(po)
    return sorted(chosen)


def _act(enterprise: Enterprise, event_id: str, calls: list[dict], tool: str, args: dict, reason: str) -> dict:
    try:
        result = enterprise.call(event_id, tool, args)
        calls.append({"tool": tool, "args": args, "ok": True, "result": result, "reason": reason})
        return result
    except ToolError as exc:
        calls.append({"tool": tool, "args": args, "ok": False, "error": str(exc), "reason": reason})
        return {"error": str(exc)}


def _move_orders(enterprise: Enterprise, event_id: str, calls: list[dict], orders: list[str], start_idx: int, reason: str) -> None:
    state = enterprise.state(event_id)
    for po in orders:
        plant, _idx = state["loc"][po]
        model = enterprise.orders[po]["model"]
        slot = _earliest(enterprise, state, model, plant, start_idx)
        if slot is None:
            calls.append({"tool": None, "ok": False, "reason": f"no slot for {po}", "args": {}})
            continue
        dest_plant, dest_idx = slot
        dest_date = idx_to_date(dest_idx).isoformat()
        if dest_plant == plant:
            _act(enterprise, event_id, calls, "mes.reschedule",
                 {"production_order_id": po, "new_date": dest_date}, reason)
        else:
            _act(enterprise, event_id, calls, "mes.transfer",
                 {"production_order_id": po, "to_plant_id": dest_plant, "new_date": dest_date}, reason)


def _notify_and_loaners(enterprise: Enterprise, event_id: str, calls: list[dict], orders: list[str], reason: str) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    entitled = []
    for row in enterprise.cos.values():
        if row["production_order_id"] not in orders:
            continue
        grouped[row["dealer_id"]].append(row["customer_order_id"])
        tier = enterprise.customers[row["customer_id"]]["tier"]
        if tier in LOANER_TIERS:
            entitled.append((TIER_RANK[tier], row["promised_date"], row["customer_order_id"], row))
    for dealer, ids in sorted(grouped.items()):
        _act(enterprise, event_id, calls, "dealer.notify", {
            "dealer_id": dealer,
            "customer_order_ids": sorted(ids),
            "message": reason,
        }, reason)
    for _tier, _date, _co, row in sorted(entitled):
        dealer = row["dealer_id"]
        available = _act(enterprise, event_id, calls, "crm.loaner_availability",
                         {"dealer_id": dealer}, "Check the loaner pool before assigning one.")
        if not available.get("available"):
            continue
        _act(enterprise, event_id, calls, "crm.assign_loaner",
             {"customer_order_id": row["customer_order_id"]}, reason)


def plan_event(event: dict, world: World, enterprise: Enterprise, parsed: list[dict] | None = None) -> dict:
    incidents = parsed if parsed is not None else parse_incidents(event["text"], world)
    calls: list[dict] = []
    traces = []
    actionable = [item for item in incidents if item["kind"] not in {"noise", "unconfirmed"}]
    vague = [item for item in incidents if item["kind"] == "unconfirmed"]
    if not actionable and vague:
        _act(enterprise, event["event_id"], calls, "escalate",
             {"reason": "The report is not specific or confirmed."}, "unconfirmed")
        traces.append({"kind": "unconfirmed", "path": ["event", "escalate"], "reason": "No confirmed entity and date."})
    if not actionable and not vague:
        traces.append({"kind": "noise", "path": ["event"], "reason": "The message does not name an operational incident."})
    for incident in actionable:
        if incident["kind"] == "supplier_delay":
            shipment = _resolve_shipment(world, incident)
            dates = [date.fromisoformat(value) for value in incident["dates"]]
            if shipment is None or len(dates) < 1:
                _act(enterprise, event["event_id"], calls, "escalate",
                     {"reason": "Delay could not be tied to one shipment and a new ETA."}, incident["text"])
                continue
            old = date.fromisoformat(shipment["eta_date"])
            new = dates[-1]
            if new <= old:
                new = dates[-1]
            blocked = set()
            cursor = old
            while cursor < new:
                idx = _working(cursor)
                if idx is not None:
                    blocked.add(idx)
                cursor += timedelta(days=1)
            start = _working(new)
            if start is None:
                start = LAST_IDX
            orders = _affected_orders(enterprise, enterprise.state(event["event_id"]), shipment["plant_id"], blocked, shipment["part_id"])
            reason = f"Shipment {shipment['shipment_id']} part {shipment['part_id']} arrives {new.isoformat()}."
            _move_orders(enterprise, event["event_id"], calls, orders, start, reason)
            _notify_and_loaners(enterprise, event["event_id"], calls, orders, reason)
            traces.append({
                "kind": "supplier_delay",
                "path": ["shipment", shipment["shipment_id"], "part", shipment["part_id"], "plant", shipment["plant_id"], "orders", orders],
                "reason": reason,
            })
        elif incident["kind"] == "plant_outage":
            if not incident["plants"] or len(incident["dates"]) < 2:
                _act(enterprise, event["event_id"], calls, "escalate",
                     {"reason": "Outage is missing a plant or a date range."}, incident["text"])
                continue
            plant = incident["plants"][0]
            start_d, end_d = incident["dates"][0], incident["dates"][-1]
            start_day, end_day = date.fromisoformat(start_d), date.fromisoformat(end_d)
            if end_day < start_day:
                start_day, end_day = end_day, start_day
            blocked = set()
            cursor = start_day
            while cursor <= end_day:
                idx = _working(cursor)
                if idx is not None:
                    blocked.add(idx)
                cursor += timedelta(days=1)
            start = (max(blocked) + 1) if blocked else 0
            orders = _affected_orders(enterprise, enterprise.state(event["event_id"]), plant, blocked, None)
            reason = f"Plant {plant} is down {start_day.isoformat()} through {end_day.isoformat()}."
            _move_orders(enterprise, event["event_id"], calls, orders, start, reason)
            _notify_and_loaners(enterprise, event["event_id"], calls, orders, reason)
            traces.append({"kind": "plant_outage", "path": ["plant", plant, "orders", orders], "reason": reason})
        elif incident["kind"] == "quality_hold":
            lot = _resolve_lot(world, incident)
            if lot is None:
                _act(enterprise, event["event_id"], calls, "escalate",
                     {"reason": "Quality report did not match one lot."}, incident["text"])
                continue
            _act(enterprise, event["event_id"], calls, "quality.hold_lot", {"lot_id": lot["lot_id"]}, "Hold the named lot.")
            part = lot["part_id"]
            plant = lot["plant_id"]
            first, last = lot["first_build_date"], lot["last_build_date"]
            vins_by_dealer: dict[str, list[str]] = defaultdict(list)
            owners = []
            for vehicle in world.vehicles:
                if vehicle["plant_id"] != plant or not (first <= vehicle["build_date"] <= last):
                    continue
                order = enterprise.orders.get(vehicle["production_order_id"])
                if order is None or part not in enterprise.bom[order["model"]]:
                    continue
                if vehicle["status"] == "in_stock":
                    vins_by_dealer[vehicle["dealer_id"]].append(vehicle["vin"])
                elif vehicle["status"] == "sold" and vehicle["customer_id"]:
                    owners.append(vehicle["customer_id"])
            for dealer, vins in sorted(vins_by_dealer.items()):
                _act(enterprise, event["event_id"], calls, "dealer.stop_sale",
                     {"dealer_id": dealer, "vins": sorted(vins)}, "Stop sale of unsold vehicles from the lot window.")
            for customer_id in sorted(set(owners)):
                _act(enterprise, event["event_id"], calls, "crm.notify_customer",
                     {"customer_id": customer_id, "message": f"Lot {lot['lot_id']} is on hold."},
                     "Contact the owner of a sold vehicle.")
            traces.append({
                "kind": "quality_hold",
                "path": ["lot", lot["lot_id"], "part", part, "plant", plant, "vehicles"],
                "reason": f"Lot {lot['lot_id']} covers builds {first} to {last}.",
            })
    return {"event_id": event["event_id"], "incidents": incidents, "calls": calls, "traces": traces}


class EventAnalyst:
    """Classifies a message. It does not call tools."""

    def assess(self, text: str, world: World) -> list[dict]:
        return parse_incidents(text, world)


class PolicyPlanner:
    """Turns a classified incident into tool calls that obey the handbook."""

    def plan(self, event: dict, world: World, enterprise: Enterprise, incidents: list[dict]) -> dict:
        return plan_event(event, world, enterprise, incidents)


class ExecutionVerifier:
    """Rejects a trace that contains a failed write."""

    def failures(self, result: dict) -> list[dict]:
        return [call for call in result["calls"] if not call.get("ok", False)]


class Coordinator:
    def __init__(self) -> None:
        self.world = World()
        self.enterprise = Enterprise(str(DATA))
        self.analyst = EventAnalyst()
        self.planner = PolicyPlanner()
        self.verifier = ExecutionVerifier()

    def handle(self, event: dict, parsed: list[dict] | None = None) -> dict:
        incidents = self.analyst.assess(event["text"], self.world) if parsed is None else parsed
        result = self.planner.plan(event, self.world, self.enterprise, incidents)
        result["verifier_failures"] = self.verifier.failures(result)
        return result


def run_events(events: list[dict], parsed_by_id: dict[str, list[dict]] | None = None) -> list[dict]:
    coordinator = Coordinator()
    results = []
    for event in events:
        parsed = None if parsed_by_id is None else parsed_by_id.get(event["event_id"])
        results.append(coordinator.handle(event, parsed))
    return results


def write_log(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            for call in result["calls"]:
                if not call.get("tool"):
                    continue
                handle.write(json.dumps({
                    "event_id": result["event_id"],
                    "tool": call["tool"],
                    "args": call["args"],
                    "ok": call["ok"],
                }) + "\n")
