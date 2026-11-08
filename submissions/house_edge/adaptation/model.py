"""Adaptation-round forecaster. Python standard library only.

Ticks at or after the cutoff are never inputs. A missing tick is unknown.
Lags are exact tick offsets. Condition labels are never read.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

PAYOUTS = (0, 1, 2, 5, 20)
INDEX = {value: index for index, value in enumerate(PAYOUTS)}
PATTERN_SPECS = {
    "c1235": ("cat", (1, 2, 3, 5)),
    "c123": ("cat", (1, 2, 3)),
    "c12": ("cat", (1, 2)),
    "e12": ("exact", (1, 2)),
    "e1": ("exact", (1,)),
    "z123": ("zero", (1, 2, 3)),
    "z12": ("zero", (1, 2)),
}


def load_split(folder: Path) -> tuple[list[dict], dict, dict[str, int]]:
    queries = _rows(folder / "queries.csv")
    history: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
    for row in _rows(folder / "history.csv"):
        history[(row["episode_id"], row["machine_id"])][int(row["tick"])] = int(row["payout"])
    labels: dict[str, int] = {}
    label_path = folder / "labels.csv"
    if label_path.exists():
        labels = {row["query_id"]: int(row["outcome"]) for row in _rows(label_path)}
    return queries, history, labels


def write_submission(path: Path, predictions: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["query_id", "p_0", "p_1", "p_2", "p_5", "p_20"])
        for query_id in sorted(predictions):
            probs = normalize(predictions[query_id])
            writer.writerow([query_id, *["%.10f" % value for value in probs]])


def normalize(counts: list[float]) -> list[float]:
    total = math.fsum(counts)
    if total <= 0:
        return [1.0 / len(PAYOUTS)] * len(PAYOUTS)
    return [value / total for value in counts]


def mix(parts: list[tuple[float, list[float]]]) -> list[float]:
    total = math.fsum(weight for weight, _ in parts if weight > 0)
    if total <= 0:
        return [1.0 / len(PAYOUTS)] * len(PAYOUTS)
    mixed = [0.0] * len(PAYOUTS)
    for weight, dist in parts:
        if weight <= 0:
            continue
        for index, value in enumerate(dist):
            mixed[index] += weight * value
    return normalize(mixed)


def kl(left: list[float], right: list[float]) -> float:
    return math.fsum(p * math.log((p + 1e-12) / (q + 1e-12)) for p, q in zip(left, right))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _code(kind: str, payout: int) -> int:
    if kind == "exact":
        return INDEX[int(payout)]
    if kind == "zero":
        return 0 if int(payout) == 0 else 1
    if int(payout) == 0:
        return 0
    if int(payout) == 1:
        return 1
    return 2


def _context_at(usable: dict[int, int], tick: int, kind: str, lags: tuple[int, ...]) -> tuple[int, ...] | None:
    values = []
    for lag in lags:
        previous = usable.get(tick - lag)
        if previous is None:
            return None
        values.append(_code(kind, previous))
    return tuple(values)


def event_counts(events: list[tuple[int, int]], half_life: float) -> list[float]:
    counts = [0.0] * len(PAYOUTS)
    if half_life > 0 and events:
        scale = math.log(0.5) / half_life
        for age, payout_index in events:
            counts[payout_index] += math.exp(age * scale)
    return counts


def window_counts(events: list[tuple[int, int]], start_age: int, end_age: int) -> list[float]:
    counts = [0.0] * len(PAYOUTS)
    for age, payout_index in events:
        if start_age <= age < end_age:
            counts[payout_index] += 1.0
    return counts


class Forecaster:
    def __init__(self, settings: dict | None = None):
        self.settings = default_settings()
        if settings:
            self.settings.update(settings)
        self.global_prior = [1.0 / len(PAYOUTS)] * len(PAYOUTS)
        self.context_prior: dict[str, list[float]] = {}
        self.transitions: dict[str, list] = {}

    def fit(self, queries: list[dict], history: dict, labels: dict[str, int]) -> "Forecaster":
        counts = [0.0] * len(PAYOUTS)
        contexts: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(PAYOUTS))
        by_machine: dict[tuple[str, str], dict] = {}
        for query in queries:
            by_machine[(query["episode_id"], query["machine_id"])] = query
            observed = dict(history.get((query["episode_id"], query["machine_id"]), {}))
            if query["query_id"] in labels:
                observed[int(query["cutoff"])] = labels[query["query_id"]]
            key = _key(query)
            for payout in observed.values():
                counts[INDEX[int(payout)]] += 1.0
                contexts[key][INDEX[int(payout)]] += 1.0
        self.global_prior = normalize([value + 0.5 for value in counts])
        shrink = float(self.settings.get("context_shrink", 12.0))
        self.context_prior = {
            key: normalize([value + shrink * prior for value, prior in zip(values, self.global_prior)])
            for key, values in contexts.items()
        }
        tables: dict[str, list] = defaultdict(
            lambda: [[[0.0] * len(PAYOUTS) for _ in PAYOUTS] for _ in range(8)]
        )
        for machine_key, query in by_machine.items():
            context = _key(query)
            cutoff = int(query["cutoff"])
            observed = {
                tick: payout
                for tick, payout in history.get(machine_key, {}).items()
                if tick < cutoff
            }
            if query["query_id"] in labels:
                observed[cutoff] = labels[query["query_id"]]
            for tick, payout in observed.items():
                for lag in range(1, 9):
                    previous = observed.get(tick - lag)
                    if previous is None:
                        continue
                    tables[context][lag - 1][INDEX[int(previous)]][INDEX[int(payout)]] += 1.0
        self.transitions = {key: value for key, value in tables.items()}
        return self

    def predict(self, queries: list[dict], history: dict) -> dict[str, list[float]]:
        prepared = [self._prepare(query, history) for query in queries]
        return {item["query_id"]: self._forecast(item) for item in prepared}

    def _prepare(self, query: dict, history: dict) -> dict:
        cutoff = int(query["cutoff"])
        usable = {
            tick: payout
            for tick, payout in history.get((query["episode_id"], query["machine_id"]), {}).items()
            if tick < cutoff
        }
        events = [(cutoff - 1 - tick, INDEX[int(payout)]) for tick, payout in usable.items()]
        lag_events: list[list[tuple[int, int]] | None] = []
        lag_prev: list[int | None] = []
        for lag in range(1, 9):
            previous = usable.get(cutoff - lag)
            if previous is None:
                lag_events.append(None)
                lag_prev.append(None)
                continue
            prev_index = INDEX[int(previous)]
            matched = [
                (cutoff - 1 - tick, INDEX[int(payout)])
                for tick, payout in usable.items()
                if usable.get(tick - lag) == previous
            ]
            lag_events.append(matched)
            lag_prev.append(prev_index)
        patterns = {}
        for name, (kind, lags) in PATTERN_SPECS.items():
            wanted = _context_at(usable, cutoff, kind, lags)
            if wanted is None:
                patterns[name] = None
                continue
            patterns[name] = [
                (cutoff - 1 - tick, INDEX[int(payout)])
                for tick, payout in usable.items()
                if _context_at(usable, tick, kind, lags) == wanted
            ]
        peers = []
        for (episode, machine), ticks in history.items():
            if episode != query["episode_id"] or machine == query["machine_id"]:
                continue
            peers.append([(cutoff - 1 - tick, INDEX[int(payout)]) for tick, payout in ticks.items() if tick < cutoff])
        return {
            "query_id": query["query_id"],
            "context": _key(query),
            "machine_type": query["machine_type"],
            "events": events,
            "lag_events": lag_events,
            "lag_prev": lag_prev,
            "patterns": patterns,
            "peers": peers,
        }

    def _prior(self, item: dict) -> list[float]:
        return self.context_prior.get(item["context"], self.global_prior)

    def _forecast(self, item: dict) -> list[float]:
        settings = self.settings
        prior = self._prior(item)
        strength = float(settings["prior_strength"])
        half_life = float(settings["half_life"])
        decay_counts = event_counts(item["events"], half_life)
        decay = normalize([strength * value + count for value, count in zip(prior, decay_counts)])

        window = int(settings["short_window"])
        short_counts = window_counts(item["events"], 0, window)
        long_counts = window_counts(item["events"], window, 10**9)
        short = normalize([0.5 * value + count for value, count in zip(prior, short_counts)])
        long = normalize([0.5 * value + count for value, count in zip(prior, long_counts)])
        short_mass = math.fsum(short_counts)
        long_mass = math.fsum(long_counts)
        disagreement = kl(short, long) if short_mass >= 4 and long_mass >= 4 else 0.0
        if disagreement >= float(settings["kl_switch"]):
            memory = short
        else:
            memory = mix([(0.35, short), (0.65, long)])

        lag_half_life = float(settings["lag_half_life"])
        lag_strength = float(settings["lag_strength"])
        lag_rows = []
        lag_weights = []
        table = self.transitions.get(item["context"])
        for lag in range(1, 9):
            events = item["lag_events"][lag - 1]
            prev_index = item["lag_prev"][lag - 1]
            if events is None or prev_index is None:
                continue
            own = event_counts(events, lag_half_life)
            evidence = math.fsum(own)
            if evidence <= 0:
                continue
            base = prior
            if table is not None and settings.get("use_type_lag", True):
                row = table[lag - 1][prev_index]
                if math.fsum(row) > 0:
                    base = normalize([count + 0.5 for count in row])
            lag_rows.append(normalize([lag_strength * value + count for value, count in zip(base, own)]))
            lag_weights.append(evidence / lag)
        own_lag = mix([(weight, row) for weight, row in zip(lag_weights, lag_rows)]) if lag_rows else decay
        lag_evidence = math.fsum(lag_weights)
        lag_trust = lag_evidence / (lag_evidence + float(settings["lag_gate"]))

        spec = str(settings["pattern"])
        pattern_events = item["patterns"].get(spec)
        pattern_counts = event_counts(pattern_events or [], float(settings["pattern_half_life"]))
        pattern_evidence = math.fsum(pattern_counts)
        pattern = normalize(
            [float(settings["pattern_strength"]) * value + count for value, count in zip(prior, pattern_counts)]
        )
        pattern_trust = pattern_evidence / (pattern_evidence + float(settings["pattern_gate"]))

        peer_scale = float(settings["peer_scale"])
        peer_window = int(settings["peer_window"])
        peer_dist = decay
        peer_trust = 0.0
        if peer_scale > 0 and item["peers"]:
            recent = [0.0] * len(PAYOUTS)
            older = [0.0] * len(PAYOUTS)
            for peer in item["peers"]:
                for index, value in enumerate(window_counts(peer, 0, peer_window)):
                    recent[index] += value
                for index, value in enumerate(window_counts(peer, peer_window, peer_window * 4)):
                    older[index] += value
            if math.fsum(recent) >= 8 and math.fsum(older) >= 8:
                recent_dist = normalize(recent)
                older_dist = normalize(older)
                shift = math.fsum(abs(a - b) for a, b in zip(recent_dist, older_dist))
                nudged = [max(0.0, value + peer_scale * (a - b)) for value, a, b in zip(decay, recent_dist, older_dist)]
                peer_dist = normalize(nudged)
                peer_trust = min(1.0, shift / float(settings["peer_shift"]))

        size_weight = float(settings["size_weight"])
        size_dist = decay
        if size_weight > 0:
            zero_counts = event_counts(item["events"], float(settings["zero_half_life"]))
            size_counts = event_counts(item["events"], float(settings["size_half_life"]))
            zero_total = strength + math.fsum(zero_counts)
            p0 = (strength * prior[0] + zero_counts[0]) / zero_total
            size_mass = [strength * prior[index] + size_counts[index] for index in range(1, 5)]
            size_total = math.fsum(size_mass)
            conditional = [value / size_total for value in size_mass]
            size_dist = [p0, *[(1.0 - p0) * value for value in conditional]]

        weights = settings["weights"]
        return mix(
            [
                (float(weights["decay"]), decay),
                (float(weights["memory"]), memory),
                (float(weights["lag"]) * lag_trust, own_lag),
                (float(weights["pattern"]) * pattern_trust, pattern),
                (float(weights["peer"]) * peer_trust, peer_dist),
                (float(weights["size"]), size_dist),
            ]
        )


def default_settings() -> dict:
    return {
        "half_life": 48.0,
        "prior_strength": 12.0,
        "context_shrink": 12.0,
        "short_window": 24,
        "kl_switch": 0.12,
        "lag_half_life": 48.0,
        "lag_strength": 8.0,
        "lag_gate": 6.0,
        "use_type_lag": True,
        "pattern": "c123",
        "pattern_half_life": 32.0,
        "pattern_strength": 2.0,
        "pattern_gate": 4.0,
        "peer_scale": 0.0,
        "peer_window": 24,
        "peer_shift": 0.25,
        "size_weight": 0.0,
        "zero_half_life": 16.0,
        "size_half_life": 96.0,
        "use_main": False,
        "weights": {
            "decay": 0.7,
            "memory": 0.15,
            "lag": 0.15,
            "pattern": 0.0,
            "peer": 0.0,
            "size": 0.0,
        },
    }


def _key(query: dict) -> str:
    return f"{query['machine_type']}|{query['signal']}"


def save_settings(path: Path, settings: dict) -> None:
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
