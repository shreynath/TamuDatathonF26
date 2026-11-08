"""Offline House Edge forecaster. Python standard library only.

Ticks strictly below the cutoff are inputs. A missing tick is unknown.
Lags are exact tick offsets, not previous-row positions.
Condition labels are never read here.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

PAYOUTS = (0, 1, 2, 5, 20)
INDEX = {value: i for i, value in enumerate(PAYOUTS)}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def _normalize(counts: list[float]) -> list[float]:
    total = math.fsum(counts)
    if total <= 0:
        return [1.0 / len(PAYOUTS)] * len(PAYOUTS)
    return [value / total for value in counts]


def _mix(parts: list[tuple[float, list[float]]]) -> list[float]:
    weight = math.fsum(weight for weight, _ in parts)
    if weight <= 0:
        return [1.0 / len(PAYOUTS)] * len(PAYOUTS)
    mixed = [0.0] * len(PAYOUTS)
    for share, dist in parts:
        for i, value in enumerate(dist):
            mixed[i] += share * value
    return _normalize(mixed)


def _kl(left: list[float], right: list[float]) -> float:
    return math.fsum(p * math.log((p + 1e-12) / (q + 1e-12)) for p, q in zip(left, right))


def _category(payout: int) -> int:
    if payout == 0:
        return 0
    if payout == 1:
        return 1
    return 2


class Forecaster:
    def __init__(self, settings: dict | None = None):
        self.settings = {
            "half_life": 24.0,
            "prior_strength": 20.0,
            "short_window": 24,
            "kl_switch": 0.15,
            "weights": {"decay": 0.55, "short": 0.2, "lag": 0.15, "shared": 0.1},
            "shared_by_type": {"steady": 0.1, "balanced": 0.1, "jackpot": 0.1},
            "pattern_lags": [1, 2, 3, 5],
            "pattern_half_life": 32.0,
            "pattern_strength": 2.0,
            "pattern_weight": 0.75,
        }
        if settings:
            self.settings.update(settings)
        self.global_prior = [1.0 / len(PAYOUTS)] * len(PAYOUTS)
        self.context_prior: dict[str, list[float]] = {}
        self.transitions: dict[str, list[list[list[float]]]] = {}
        self.peer_transitions: dict[str, list[list[list[float]]]] = {}

    def _key(self, query: dict) -> str:
        return f"{query['machine_type']}|{query['signal']}"

    def fit(self, queries: list[dict], history: dict, labels: dict[str, int]) -> "Forecaster":
        counts = [0.0] * len(PAYOUTS)
        contexts: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(PAYOUTS))
        by_machine: dict[tuple[str, str], dict] = {}
        for query in queries:
            by_machine[(query["episode_id"], query["machine_id"])] = query
            outcomes = list(history.get((query["episode_id"], query["machine_id"]), {}).values())
            if query["query_id"] in labels:
                outcomes.append(labels[query["query_id"]])
            key = self._key(query)
            for outcome in outcomes:
                counts[INDEX[int(outcome)]] += 1
                contexts[key][INDEX[int(outcome)]] += 1
        total = math.fsum(counts) or 1.0
        self.global_prior = _normalize([value + 0.5 for value in counts])
        self.context_prior = {
            key: _normalize([value + 12.0 * prior for value, prior in zip(values, self.global_prior)])
            for key, values in contexts.items()
        }
        blank = [[[0.0] * len(PAYOUTS) for _ in PAYOUTS] for _ in range(8)]
        tables: dict[str, list] = defaultdict(lambda: [[[0.0] * len(PAYOUTS) for _ in PAYOUTS] for _ in range(8)])
        for key, ticks in history.items():
            query = by_machine.get(key)
            if query is None:
                continue
            context = self._key(query)
            cutoff = int(query["cutoff"])
            observed = {tick: payout for tick, payout in ticks.items() if tick < cutoff}
            if query["query_id"] in labels:
                observed[cutoff] = labels[query["query_id"]]
            for tick, payout in observed.items():
                for lag in range(1, 9):
                    previous = observed.get(tick - lag)
                    if previous is None:
                        continue
                    tables[context][lag - 1][INDEX[int(previous)]][INDEX[int(payout)]] += 1
        self.transitions = {key: value for key, value in tables.items()}
        peer: dict[str, list] = defaultdict(lambda: [[[0.0] * len(PAYOUTS) for _ in PAYOUTS] for _ in range(8)])
        by_episode: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key, query in by_machine.items():
            by_episode[query["episode_id"]].append(key)
        for keys in by_episode.values():
            series = {}
            for key in keys:
                query = by_machine[key]
                cutoff = int(query["cutoff"])
                observed = {
                    tick: payout
                    for tick, payout in history.get(key, {}).items()
                    if tick < cutoff
                }
                if query["query_id"] in labels:
                    observed[cutoff] = labels[query["query_id"]]
                series[key] = (self._key(query), observed)
            for key, (context, observed) in series.items():
                for tick, payout in observed.items():
                    for other, (_, other_observed) in series.items():
                        if other == key:
                            continue
                        for lag in range(1, 9):
                            previous = other_observed.get(tick - lag)
                            if previous is None:
                                continue
                            peer[context][lag - 1][INDEX[int(previous)]][INDEX[int(payout)]] += 1
        self.peer_transitions = {key: value for key, value in peer.items()}
        return self

    def _decay(self, ticks: dict[int, int], cutoff: int, half_life: float) -> list[float]:
        counts = [0.0] * len(PAYOUTS)
        for tick, payout in ticks.items():
            if tick >= cutoff:
                continue
            age = cutoff - 1 - tick
            counts[INDEX[int(payout)]] += 0.5 ** (age / half_life)
        return counts

    def _window(self, ticks: dict[int, int], cutoff: int, start: int) -> list[float]:
        counts = [0.0] * len(PAYOUTS)
        for tick, payout in ticks.items():
            if start <= tick < cutoff:
                counts[INDEX[int(payout)]] += 1
        return counts

    def _pattern(self, usable: dict[int, int], cutoff: int, context: list[float]) -> list[float]:
        """Own-history match on the recent payout categories.

        Machines of one type can move in opposite directions, so a pooled
        transition table cancels the signal. Matching this machine's own
        ticks, at lags 1, 2, 3, and 5, keeps that direction.
        """
        lags = tuple(int(lag) for lag in self.settings.get("pattern_lags", (1, 2, 3, 5)))
        half_life = float(self.settings.get("pattern_half_life", 32.0))
        strength = float(self.settings.get("pattern_strength", 2.0))

        def context_at(tick: int) -> tuple[int, ...] | None:
            values = []
            for lag in lags:
                previous = usable.get(tick - lag)
                if previous is None:
                    return None
                values.append(_category(int(previous)))
            return tuple(values)

        wanted = context_at(cutoff)
        counts = [strength * prior for prior in context]
        if wanted is not None and half_life > 0:
            for tick, payout in usable.items():
                if context_at(tick) != wanted:
                    continue
                age = cutoff - 1 - tick
                counts[INDEX[int(payout)]] += 0.5 ** (age / half_life)
        return _normalize(counts)

    def predict_one(self, query: dict, history: dict) -> list[float]:
        cutoff = int(query["cutoff"])
        ticks = history.get((query["episode_id"], query["machine_id"]), {})
        usable = {tick: payout for tick, payout in ticks.items() if tick < cutoff}
        context = self.context_prior.get(self._key(query), self.global_prior)
        strength = float(self.settings["prior_strength"])
        half_life = float(self.settings["half_life"])
        decay_counts = self._decay(usable, cutoff, half_life)
        decay = _normalize([strength * prior + count for prior, count in zip(context, decay_counts)])

        window = int(self.settings["short_window"])
        short_counts = self._window(usable, cutoff, cutoff - window)
        long_counts = self._window(usable, cutoff - window, -10**9)
        short = _normalize([0.5 * prior + count for prior, count in zip(context, short_counts)])
        long = _normalize([0.5 * prior + count for prior, count in zip(context, long_counts)])
        short_mass = math.fsum(short_counts)
        long_mass = math.fsum(long_counts)
        disagreement = _kl(short, long) if short_mass >= 4 and long_mass >= 4 else 0.0
        memory = short if disagreement >= float(self.settings["kl_switch"]) else _mix([(0.35, short), (0.65, long)])

        lag_rows = []
        present = 0
        table = self.transitions.get(self._key(query))
        for lag in range(1, 9):
            previous = usable.get(cutoff - lag)
            if previous is None or table is None:
                continue
            present += 1
            row = table[lag - 1][INDEX[int(previous)]]
            if math.fsum(row) <= 0:
                continue
            lag_rows.append(_normalize([0.2 * prior + count for prior, count in zip(context, row)]))
        lag = _mix([(1.0, row) for row in lag_rows]) if lag_rows else decay
        lag_weight_scale = present / 8.0

        shared_counts = [0.0] * len(PAYOUTS)
        for (episode, machine), other in history.items():
            if episode != query["episode_id"] or machine == query["machine_id"]:
                continue
            for tick, payout in other.items():
                if cutoff - window <= tick < cutoff:
                    shared_counts[INDEX[int(payout)]] += 1
        shared = _normalize(shared_counts) if math.fsum(shared_counts) else decay
        shared_weight = float(self.settings["shared_by_type"].get(query["machine_type"], 0.0))

        weights = dict(self.settings["weights"])
        weights["lag"] = float(weights["lag"]) * lag_weight_scale
        weights["shared"] = shared_weight
        parts = [
            (float(weights["decay"]), decay),
            (float(weights["short"]), memory),
            (float(weights["lag"]), lag),
            (float(weights["shared"]), shared),
        ]
        peer_weight = float(weights.get("peer", 0.0))
        peer_table = self.peer_transitions.get(self._key(query))
        if peer_weight > 0 and peer_table:
            peer_rows = []
            present_peer = 0
            for lag in range(1, 9):
                votes = [0.0] * len(PAYOUTS)
                found = False
                for (episode, machine), other in history.items():
                    if episode != query["episode_id"] or machine == query["machine_id"]:
                        continue
                    previous = other.get(cutoff - lag)
                    if previous is None:
                        continue
                    row = peer_table[lag - 1][INDEX[int(previous)]]
                    if math.fsum(row) <= 0:
                        continue
                    found = True
                    for index, count in enumerate(row):
                        votes[index] += count
                if found:
                    present_peer += 1
                    peer_rows.append(_normalize(votes))
            if peer_rows:
                parts.append((peer_weight * present_peer / 8.0, _mix([(1.0, row) for row in peer_rows])))
        pooled = _mix(parts)
        pattern_weight = float(self.settings.get("pattern_weight", 0.75))
        if pattern_weight <= 0:
            return pooled
        pattern = self._pattern(usable, cutoff, context)
        return _mix([(pattern_weight, pattern), (1.0 - pattern_weight, pooled)])

    def predict(self, queries: list[dict], history: dict) -> dict[str, list[float]]:
        return {query["query_id"]: self.predict_one(query, history) for query in queries}

    def to_json(self) -> dict:
        return {
            "settings": self.settings,
            "global_prior": self.global_prior,
            "context_prior": self.context_prior,
            "transitions": self.transitions,
            "peer_transitions": self.peer_transitions,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Forecaster":
        model = cls(payload["settings"])
        model.global_prior = payload["global_prior"]
        model.context_prior = payload["context_prior"]
        model.transitions = payload["transitions"]
        model.peer_transitions = payload.get("peer_transitions") or {}
        return model


def write_submission(path: Path, predictions: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["query_id", "p_0", "p_1", "p_2", "p_5", "p_20"])
        for query_id in sorted(predictions):
            probs = _normalize(predictions[query_id])
            writer.writerow([query_id, *["%.10f" % value for value in probs]])


def save_model(path: Path, model: Forecaster) -> None:
    path.write_text(json.dumps(model.to_json()), encoding="utf-8")


def load_model(path: Path) -> Forecaster:
    return Forecaster.from_json(json.loads(path.read_text(encoding="utf-8")))
