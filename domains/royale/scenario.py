"""Catalog arithmetic for the Royale spend desk.

The recovery rate is an assumption the user sets. These functions do not
estimate that rate from the floor, and a positive draw is not evidence that
a repair causes the recovery.
"""

from __future__ import annotations

import random


def break_even_rate(cost: float, lost_theo: float) -> float | None:
    if lost_theo <= 0:
        return None
    return cost / lost_theo


def price_recovery(rate: float, lost_theo: float, cost: float) -> dict:
    if rate < 0 or rate > 1:
        raise ValueError("recovery rate must be between 0 and 1")
    captured = round(rate * lost_theo, 2)
    net = round(captured - cost, 2)
    return {
        "recovery_rate": rate,
        "captured_usd": captured,
        "cost_usd": round(cost, 2),
        "net_usd": net,
        "worth_funding": net > 0,
    }


def stress_recovery(
    *,
    lost_theo: float,
    cost: float,
    seed: int,
    draws: int = 4000,
    rate_high: float = 0.30,
    scale_low: float = 0.8,
    scale_high: float = 1.2,
) -> dict:
    """Hypothetical band around the point estimate. Not a confidence interval."""
    if draws < 1:
        raise ValueError("draws must be positive")
    if not 0 < rate_high <= 1:
        raise ValueError("rate_high must be in (0, 1]")
    if not 0 < scale_low <= scale_high:
        raise ValueError("scale band is invalid")
    rng = random.Random(seed)
    nets = []
    for _ in range(draws):
        rate = rng.uniform(0.0, rate_high)
        scale = rng.uniform(scale_low, scale_high)
        nets.append(rate * scale * lost_theo - cost)
    nets.sort()

    def percentile(fraction: float) -> float:
        index = int(round(fraction * (len(nets) - 1)))
        return round(nets[index], 2)

    positive = sum(1 for value in nets if value > 0) / len(nets)
    return {
        "draws": draws,
        "seed": seed,
        "rate_high": rate_high,
        "scale_low": scale_low,
        "scale_high": scale_high,
        "mean_net_usd": round(sum(nets) / len(nets), 2),
        "p05_net_usd": percentile(0.05),
        "p50_net_usd": percentile(0.50),
        "p95_net_usd": percentile(0.95),
        "probability_positive_net": round(positive, 4),
        "worst_budget_exposure_usd": round(cost, 2),
        "causal": False,
        "label": (
            "Hypothetical. Recovery is uniform from 0 to rate_high. "
            "Lost theo is scaled inside the stated band. "
            "This is not a measured effect of the technician shift."
        ),
    }
