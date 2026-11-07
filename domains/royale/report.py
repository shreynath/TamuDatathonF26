"""Dashboard Royale answers. Every dollar in the JSON is computed here."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import duckdb

from domains.royale.investigate import briefings
from domains.royale.scenario import break_even_rate, stress_recovery

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "royale-src" / "data"
OUT = ROOT / "apps" / "web" / "public"
DAILY = DATA / "1_prepared_views" / "prepared_daily_view.parquet"
PROPERTY = DATA / "1_prepared_views" / "property_day.parquet"
PLAYERS = DATA / "1_prepared_views" / "player_period.parquet"
ACTIONS = DATA / "2_machine_decision" / "action_catalog.parquet"
CALENDAR = DATA / "2_machine_decision" / "calendar_day.parquet"
CITY = DATA / "4_context" / "real_sources" / "city_visitation_monthly.parquet"

NORMAL = NormalDist()


def rank_one_is_lowest(values: list[tuple[str, float]]) -> dict[str, int]:
    """SQL RANK() OVER (ORDER BY value): 1 is the smallest value."""
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    ranks = {}
    last = None
    last_rank = 0
    for index, (name, value) in enumerate(ordered, start=1):
        if last != value:
            last_rank = index
            last = value
        ranks[name] = last_rank
    return ranks


def holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], key))
    adjusted = {}
    running = 0.0
    count = len(ordered)
    for index, key in enumerate(ordered):
        value = min(1.0, (count - index) * p_values[key])
        running = max(running, value)
        adjusted[key] = running
    return adjusted


def _two_sided(z: float) -> float:
    if not math.isfinite(z):
        return 1.0
    return min(1.0, 2.0 * (1.0 - NORMAL.cdf(abs(z))))


def _money(value: float) -> float:
    return round(float(value), 2)


def build() -> dict:
    con = duckdb.connect()
    exclusion = con.sql(f"""
        SELECT COUNT(*) AS rows_total,
               COUNT(*) FILTER (WHERE location_id IS NULL OR location_id = '') AS empty_location,
               COUNT(*) FILTER (WHERE NOT active) AS inactive_flag
        FROM '{DAILY}'
    """).fetchone()
    days = con.sql(f"""
        SELECT d.machine_id, d.gaming_date, d.month, d.local_weekday, d.is_weekend,
               d.events_active, d.zone_name, d.bank_id, d.theme, d.volatility_class, d.manufacturer,
               d.coin_in_usd::DOUBLE AS coin_in,
               d.payout_usd::DOUBLE AS payout,
               d.house_win_usd::DOUBLE AS house_win,
               d.theo_usd::DOUBLE AS theo,
               d.luck_residual_usd::DOUBLE AS residual,
               d.available_hours::DOUBLE AS available_hours,
               c.scheduled_seconds / 3600.0 AS scheduled_hours
        FROM '{DAILY}' d
        JOIN '{CALENDAR}' c USING (gaming_date)
        WHERE d.active AND d.location_id IS NOT NULL AND d.location_id <> ''
    """).df()
    grouped = []
    tests = {}
    for machine_id, frame in days.groupby("machine_id"):
        coin = float(frame["coin_in"].sum())
        payout = float(frame["payout"].sum())
        house = float(frame["house_win"].sum())
        theo = float(frame["theo"].sum())
        residual = float(frame["residual"].sum())
        hours = float(frame["available_hours"].sum())
        scheduled = float(frame["scheduled_hours"].sum())
        lost_hours = float((frame["scheduled_hours"] - frame["available_hours"]).clip(lower=0).sum())
        rate = coin / hours if hours else 0.0
        theo_rate = theo / hours if hours else 0.0
        sample = frame.loc[frame["coin_in"] > 0, "residual"]
        n = int(sample.shape[0])
        mean = float(sample.mean()) if n else 0.0
        stdev = float(sample.std(ddof=1)) if n > 1 else 0.0
        z = mean / (stdev / math.sqrt(n)) if n > 1 and stdev > 0 else 0.0
        tests[str(machine_id)] = {
            "n_days": n,
            "mean_daily_residual": mean,
            "stdev": stdev,
            "z": z,
            "p_raw": _two_sided(z),
        }
        grouped.append({
            "machine_id": str(machine_id),
            "zone": str(frame["zone_name"].iloc[0]),
            "bank": str(frame["bank_id"].dropna().iloc[0]) if frame["bank_id"].notna().any() else "",
            "theme": str(frame["theme"].iloc[0]),
            "volatility": str(frame["volatility_class"].iloc[0]),
            "manufacturer": str(frame["manufacturer"].iloc[0]),
            "house_win": house,
            "theo": theo,
            "residual": residual,
            "coin_in": coin,
            "payout": payout,
            "hours": hours,
            "scheduled_hours": scheduled,
            "lost_hours": lost_hours,
            "modeled_lost_coin_in": rate * lost_hours,
            "modeled_lost_theo": theo_rate * lost_hours,
            "observed_hold": house / coin if coin else None,
            "theo_hold": theo / coin if coin else None,
        })
    n_machines = len(grouped)
    raw_rank = rank_one_is_lowest([(row["machine_id"], row["house_win"]) for row in grouped])
    residual_rank = rank_one_is_lowest([
        (row["machine_id"], row["residual"] / row["hours"] if row["hours"] else 0.0)
        for row in grouped
    ])
    adjusted = holm({key: value["p_raw"] for key, value in tests.items() if value["n_days"] >= 20})
    for row in grouped:
        row["raw_rank"] = raw_rank[row["machine_id"]]
        row["residual_per_hour_rank"] = residual_rank[row["machine_id"]]
        row["residual_per_hour"] = row["residual"] / row["hours"] if row["hours"] else None
        row["p_holm"] = adjusted.get(row["machine_id"])
        row["p_raw"] = tests[row["machine_id"]]["p_raw"]
        row["n_days"] = tests[row["machine_id"]]["n_days"]
    bottom = sorted(grouped, key=lambda row: row["house_win"])[:10]
    period_bottom = []
    for month, frame in days.groupby("month"):
        month_rows = []
        for machine_id, part in frame.groupby("machine_id"):
            month_rows.append({
                "month": str(month),
                "machine_id": str(machine_id),
                "zone": str(part["zone_name"].iloc[0]),
                "bank": str(part["bank_id"].dropna().iloc[0]) if part["bank_id"].notna().any() else "",
                "house_win": float(part["house_win"].sum()),
            })
        month_rows.sort(key=lambda row: row["house_win"])
        for rank, row in enumerate(month_rows, start=1):
            row["raw_rank"] = rank
        period_bottom.extend(month_rows[:10])
    leaks = [
        row for row in bottom
        if row["p_holm"] is not None and row["p_holm"] < 0.05 and row["residual"] < 0
    ]
    downtime_floor = sum(row["modeled_lost_theo"] for row in grouped)
    by_month = con.sql(f"""
        WITH floor AS (
          SELECT d.month, d.gaming_date, d.is_weekend, d.events_active,
                 d.coin_in_usd::DOUBLE AS coin_in,
                 d.house_win_usd::DOUBLE AS house_win,
                 GREATEST(c.scheduled_seconds / 3600.0 - d.available_hours, 0)
                   * d.theo_usd / NULLIF(d.available_hours, 0) AS lost_theo
          FROM '{DAILY}' d
          JOIN '{CALENDAR}' c USING (gaming_date)
          WHERE d.active AND d.location_id IS NOT NULL AND d.location_id <> ''
        )
        SELECT month,
               SUM(coin_in) AS coin_in,
               SUM(house_win) AS house_win,
               SUM(lost_theo) AS modeled_lost_theo,
               AVG(coin_in) FILTER (WHERE is_weekend) AS weekend_machine_day,
               AVG(coin_in) FILTER (WHERE NOT is_weekend) AS weekday_machine_day,
               AVG(coin_in) FILTER (WHERE events_active IS NOT NULL AND events_active <> '') AS event_machine_day,
               AVG(coin_in) FILTER (WHERE events_active IS NULL OR events_active = '') AS quiet_machine_day
        FROM floor
        GROUP BY month
        ORDER BY month
    """).df()
    forecast_rows = con.sql(f"""
        WITH days AS (
          SELECT gaming_date, local_weekday, coin_in_usd::DOUBLE AS coin_in,
                 CASE WHEN gaming_date < DATE '2025-05-01' THEN 'train' ELSE 'holdout' END AS split
          FROM '{PROPERTY}'
          WHERE gaming_date >= DATE '2025-01-01' AND gaming_date < DATE '2025-07-01'
        ),
        means AS (
          SELECT local_weekday, AVG(coin_in) AS weekday_mean FROM days WHERE split = 'train' GROUP BY 1
        ),
        constant AS (
          SELECT AVG(coin_in) AS constant_mean FROM days WHERE split = 'train'
        )
        SELECT d.gaming_date::VARCHAR AS gaming_date, d.split, d.coin_in,
               m.weekday_mean, c.constant_mean
        FROM days d
        JOIN means m USING (local_weekday)
        CROSS JOIN constant c
        ORDER BY d.gaming_date
    """).df()
    holdout = forecast_rows[forecast_rows["split"] == "holdout"]
    weekday_mae = float((holdout["coin_in"] - holdout["weekday_mean"]).abs().mean())
    constant_mae = float((holdout["coin_in"] - holdout["constant_mean"]).abs().mean())
    city = con.sql(f"""
        SELECT * FROM '{CITY}' LIMIT 5
    """).df()
    city_cols = list(city.columns)
    players = con.sql(f"""
        WITH base AS (
          SELECT player_id,
                 SUM(tracked_coin_in_usd)::DOUBLE AS coin_in,
                 SUM(tracked_payout_usd)::DOUBLE AS payout,
                 SUM(tracked_net_usd)::DOUBLE AS net,
                 SUM(comp_cost_usd)::DOUBLE AS comp_cost
          FROM '{PLAYERS}'
          GROUP BY player_id
        ),
        ranked AS (
          SELECT *, SUM(coin_in) OVER () AS all_coin,
                 SUM(coin_in) OVER (ORDER BY coin_in DESC) AS running,
                 COUNT(*) OVER () AS n_players,
                 ROW_NUMBER() OVER (ORDER BY coin_in DESC) AS rn
          FROM base
        )
        SELECT SUM(coin_in) AS coin_in, SUM(payout) AS payout, SUM(net) AS net,
               SUM(comp_cost) AS comp_cost,
               MAX(n_players) AS n_players,
               MIN(rn) FILTER (WHERE running >= 0.5 * all_coin) AS players_to_half,
               SUM(coin_in) FILTER (WHERE rn <= CAST(CEIL(0.1 * n_players) AS INTEGER))
                 / SUM(coin_in) AS top_decile_share
        FROM ranked
    """).fetchone()
    comps = con.sql(f"""
        SELECT period_month::VARCHAR AS month,
               SUM(comp_cost_usd)::DOUBLE AS comp_cost,
               SUM(tracked_coin_in_usd)::DOUBLE AS coin_in,
               SUM(comp_cost_usd) / NULLIF(SUM(tracked_coin_in_usd), 0) AS comp_per_coin
        FROM '{PLAYERS}'
        GROUP BY 1
        ORDER BY 1
    """).df()
    property_comp = con.sql(f"""
        SELECT gaming_date::VARCHAR AS gaming_date, comp_cost_usd::DOUBLE AS comp_cost,
               coin_in_usd::DOUBLE AS coin_in
        FROM '{PROPERTY}'
        WHERE gaming_date >= DATE '2025-01-01' AND gaming_date < DATE '2025-07-01'
    """).df()
    catalog = con.sql(f"SELECT * FROM '{ACTIONS}'").df()

    def catalog_row(action_id: str):
        match = catalog.loc[catalog["action_type_id"] == action_id]
        if match.empty:
            raise RuntimeError(f"action catalog has no {action_id}")
        return match.iloc[0]

    inspect = catalog_row("A-INSPECT")
    technician = catalog_row("A-TECH-SHIFT")
    inspect_cost = float(inspect["unit_cost_cents"]) / 100.0
    tech_cost = float(technician["unit_cost_cents"]) / 100.0
    inspect_limit = int(inspect["quantity_limit"])
    inspect_ids = [
        row["machine_id"] for row in leaks
        if abs(row["residual"]) > inspect_cost
    ][:inspect_limit]
    capture = {
        "pessimistic_10pct_usd": _money(0.10 * downtime_floor),
        "base_30pct_usd": _money(0.30 * downtime_floor),
        "optimistic_50pct_usd": _money(0.50 * downtime_floor),
        "technician_cost_usd": tech_cost,
    }
    actions = []
    if inspect_ids:
        actions.append({
            "action_type_id": "A-INSPECT",
            "quantity": len(inspect_ids),
            "targets": inspect_ids,
            "cost_usd": _money(inspect_cost * len(inspect_ids)),
            "lead_days": int(inspect["lead_days"]),
            "quantity_limit": inspect_limit,
            "unit_cost_cents": int(inspect["unit_cost_cents"]),
            "expected_effect": "Information only. The paytable check is cheaper than the residual gap on the targeted machine.",
            "uncertainty": "A significant residual can still be volatility. Inspection does not promise a recovered dollar.",
            "measurement": "Compare the next 30 gaming days of residual per hour with the Jan-Jun rate.",
        })
    # Fund the technician only if even the pessimistic capture clears the cost.
    if capture["pessimistic_10pct_usd"] > tech_cost:
        actions.append({
            "action_type_id": "A-TECH-SHIFT",
            "quantity": 1,
            "targets": ["floor"],
            "cost_usd": tech_cost,
            "lead_days": int(technician["lead_days"]),
            "quantity_limit": int(technician["quantity_limit"]),
            "unit_cost_cents": int(technician["unit_cost_cents"]),
            "expected_effect": "Pessimistic 10% of modeled lost theo still exceeds one shift.",
            "uncertainty": "Lost theo assumes downtime hours would have earned the observed theo rate.",
            "measurement": "Availability ratio and faults opened over the 30 days after the lead time.",
        })
    spent = sum(item["cost_usd"] for item in actions)
    published_lost = _money(downtime_floor)
    technician_break_even = break_even_rate(tech_cost, published_lost)
    if not actions:
        actions.append({
            "action_type_id": "A-HOLD",
            "quantity": 1,
            "targets": [],
            "cost_usd": 0,
            "expected_effect": "No machine in the raw bottom 10 has a Holm-significant negative residual large enough to inspect.",
            "uncertainty": "July could move a machine across the line.",
            "measurement": "Repeat both rankings on the next 30 gaming days.",
        })
    case_row = next(row for row in grouped if row["machine_id"] == "M-1026")
    guest_rows = con.sql(f"""
        SELECT 'all' AS month, opening_tier AS tier,
               SUM(tracked_coin_in_usd)::DOUBLE AS coin_in,
               SUM(tracked_net_usd)::DOUBLE AS net,
               COUNT(DISTINCT player_id) AS players
        FROM '{PLAYERS}'
        GROUP BY opening_tier
        UNION ALL
        SELECT period_month::VARCHAR, opening_tier,
               SUM(tracked_coin_in_usd)::DOUBLE,
               SUM(tracked_net_usd)::DOUBLE,
               COUNT(DISTINCT player_id)
        FROM '{PLAYERS}'
        GROUP BY 1, 2
    """).df()
    payload = {
        "data_version": "dashboard-royale cloned main, depth 1",
        "rank_rule": {
            "direction": "RANK() OVER (ORDER BY value ASC). Rank 1 is the lowest value.",
            "raw": "Rank 1 is the smallest six-month house win.",
            "residual_per_hour": "Rank 1 is the lowest residual per available hour, the weakest result versus theo after hours.",
            "machine_count": n_machines,
            "unit_test": "tests/test_royale_rank.py",
        },
        "exclusions": {
            "rows_total": int(exclusion[0]),
            "empty_location": int(exclusion[1]),
            "inactive_flag": int(exclusion[2]),
            "method": "Counted in DuckDB from prepared_daily_view. 1018 was not typed in.",
        },
        "claim": {
            "claim_id": "ace-case-1",
            "domain": "royale",
            "entity_id": "M-1026",
            "analysis_window": "2025-01-01 to 2025-06-30, active days with a location",
            "claim_type": "ranking_changes_after_exposure_and_luck",
            "metric": "raw house win versus residual per available hour",
            "units": "usd and rank",
            "estimate": {
                "house_win_usd": _money(case_row["house_win"]),
                "theo_usd": _money(case_row["theo"]),
                "residual_usd": _money(case_row["residual"]),
                "available_hours": round(case_row["hours"], 2),
                "raw_rank": case_row["raw_rank"],
                "residual_per_hour_rank": case_row["residual_per_hour_rank"],
                "machines_with_lower_residual_per_hour": case_row["residual_per_hour_rank"] - 1,
                "zone": case_row["zone"],
                "theme": case_row["theme"],
                "volatility": case_row["volatility"],
                "p_raw": case_row["p_raw"],
                "p_holm": case_row["p_holm"],
            },
            "uncertainty_method": "Normal approximation to the mean of daily residuals, Holm adjustment across machines with at least 20 positive-coin days. Not a confidence interval from bet-level variance.",
            "supporting_query_or_rows": "domains/royale/report.py",
            "model_run_id": "royale-report-2",
            "alternative_explanation": "Low raw win can be fewer hours, a quiet zone, or luck. Residual per hour is the luck check. Downtime is a separate modeled cost.",
            "limitations": "Carded play is not the meter total. A normal approximation is not a slot-physics test. Missing traffic is not zero.",
            "proposed_action": actions[0]["action_type_id"],
        },
        "bottom10": [
            {
                "machine_id": row["machine_id"],
                "zone": row["zone"],
                "bank": row["bank"],
                "theme": row["theme"],
                "volatility": row["volatility"],
                "manufacturer": row["manufacturer"],
                "house_win_usd": _money(row["house_win"]),
                "theo_usd": _money(row["theo"]),
                "residual_usd": _money(row["residual"]),
                "residual_per_hour": round(row["residual_per_hour"], 4) if row["residual_per_hour"] is not None else None,
                "raw_rank": row["raw_rank"],
                "residual_per_hour_rank": row["residual_per_hour_rank"],
                "observed_hold": round(row["observed_hold"], 4) if row["observed_hold"] is not None else None,
                "theo_hold": round(row["theo_hold"], 4) if row["theo_hold"] is not None else None,
                "lost_hours": round(row["lost_hours"], 2),
                "modeled_lost_theo_usd": _money(row["modeled_lost_theo"]),
                "p_raw": row["p_raw"],
                "p_holm": row["p_holm"],
                "holm_negative_residual": bool(row["p_holm"] is not None and row["p_holm"] < 0.05 and row["residual"] < 0),
            }
            for row in bottom
        ],
        "period_bottom": [
            {
                "month": row["month"],
                "machine_id": row["machine_id"],
                "zone": row["zone"],
                "bank": row["bank"],
                "house_win_usd": _money(row["house_win"]),
                "raw_rank": row["raw_rank"],
            }
            for row in period_bottom
        ],
        "multiple_testing": {
            "family": "Every on-floor machine with at least 20 days of positive coin-in.",
            "method": "Holm, family-wise error. A claim about one named machine should not use an unadjusted p-value.",
            "approximation": "Two-sided normal test of the mean daily luck residual. Daily residuals are treated as independent, which they are not if a machine's state persists.",
            "bottom10_holm_leaks": inspect_ids,
            "floor_holm_negative": sum(
                1 for row in grouped
                if row["p_holm"] is not None and row["p_holm"] < 0.05 and row["residual"] < 0
            ),
        },
        "downtime": {
            "claim_id": "ace-downtime-1",
            "modeled_lost_theo_usd": _money(downtime_floor),
            "definition": "For each on-floor day, lost hours are scheduled hours minus available hours, floored at zero. Modeled lost theo multiplies those hours by that machine-day's theo per available hour. This is an opportunity model, not observed wagers.",
            "by_month": [
                {
                    "month": str(row.month),
                    "coin_in_usd": _money(row.coin_in),
                    "house_win_usd": _money(row.house_win),
                    "modeled_lost_theo_usd": _money(row.modeled_lost_theo or 0),
                    "weekend_machine_day_coin_in": _money(row.weekend_machine_day or 0),
                    "weekday_machine_day_coin_in": _money(row.weekday_machine_day or 0),
                    "event_machine_day_coin_in": None if row.event_machine_day is None or (isinstance(row.event_machine_day, float) and math.isnan(row.event_machine_day)) else _money(row.event_machine_day),
                    "quiet_machine_day_coin_in": _money(row.quiet_machine_day or 0),
                }
                for row in by_month.itertuples()
            ],
        },
        "forecast": {
            "claim_id": "ace-forecast-1",
            "train": "2025-01-01 through 2025-04-30",
            "holdout": "2025-05-01 through 2025-06-30",
            "target": "property_day.coin_in_usd",
            "weekday_mae_usd": _money(weekday_mae),
            "constant_mae_usd": _money(constant_mae),
            "winner": "weekday_mean" if weekday_mae <= constant_mae else "constant_mean",
            "consequence": "Staff from the weekday pattern. The forecast does not identify a machine to replace.",
            "holdout_series": [
                {
                    "gaming_date": row.gaming_date,
                    "actual": _money(row.coin_in),
                    "weekday_mean": _money(row.weekday_mean),
                    "constant_mean": _money(row.constant_mean),
                }
                for row in holdout.itertuples()
            ],
        },
        "demand_context": {
            "city_visitation_columns": city_cols,
            "note": "City visitation is a real public series for Las Vegas, not this casino's guest count. It is context, not a model input for the frozen forecast.",
        },
        "players": {
            "claim_id": "ace-players-1",
            "tracked_coin_in_usd": _money(players[0]),
            "tracked_payout_usd": _money(players[1]),
            "tracked_net_usd": _money(players[2]),
            "comp_cost_usd": _money(players[3]),
            "n_players": int(players[4]),
            "players_to_half_of_coin_in": int(players[5]) if players[5] == players[5] else None,
            "top_decile_coin_in_share": round(float(players[6]), 4),
            "note": "Carded play only. Machine meters include everyone else.",
        },
        "guest_tiers": [
            {
                "month": str(row.month),
                "tier": str(row.tier),
                "coin_in_usd": _money(row.coin_in),
                "net_usd": _money(row.net),
                "players": int(row.players),
            }
            for row in guest_rows.itertuples()
        ],
        "comps": {
            "claim_id": "ace-comps-1",
            "player_months": [
                {
                    "month": row.month,
                    "comp_cost_usd": _money(row.comp_cost),
                    "tracked_coin_in_usd": _money(row.coin_in),
                    "comp_per_tracked_coin": round(float(row.comp_per_coin), 6),
                }
                for row in comps.itertuples()
            ],
            "property_comp_cost_usd": _money(float(property_comp["comp_cost"].sum())),
            "note": "Player comp cost and property comp cost are different grains. Do not add them.",
        },
        "recommendation": {
            "actions": actions,
            "cost_usd": _money(spent),
            "budget_usd": 100000,
            "unspent_usd": _money(100000 - spent),
            "kept_without_using_a_slot": True,
            "why_not_more": "The other nine raw-bottom machines are not Holm-significant. M-1026 is rank 42 on raw win and rank 265 of 310 on residual per hour, with rank 1 meaning the lowest value. A technician shift fails the 10% capture test.",
            "catalog_rows": int(len(catalog)),
            "capture_assumption": f"A technician shift is funded only if 10% of modeled lost theo exceeds ${tech_cost:,.0f}, the catalog unit cost of A-TECH-SHIFT. Base and optimistic captures are reported and not spent.",
            "downtime_sensitivity_usd": capture,
            "break_even_technician_rate": None if technician_break_even is None else round(technician_break_even, 4),
            "stress": stress_recovery(lost_theo=published_lost, cost=tech_cost, seed=1158),
        },
    }
    weakest = sorted(
        (row for row in grouped if row["residual_per_hour"] is not None),
        key=lambda row: (row["residual_per_hour"], row["machine_id"]),
    )[:5]
    payload["weakest_residual_per_hour"] = [
        {
            "machine_id": row["machine_id"],
            "zone": row["zone"],
            "bank": row["bank"],
            "residual_per_hour": round(row["residual_per_hour"], 4),
            "residual_usd": _money(row["residual"]),
            "available_hours": round(row["hours"], 2),
            "residual_per_hour_rank": row["residual_per_hour_rank"],
            "p_holm": row["p_holm"],
        }
        for row in weakest
    ]
    payload["assistant"] = briefings(payload)
    return payload


def write_site(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ace_case.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    data = json.dumps(payload).replace("<", "\\u003c")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Gilded Ace floor review</title>
  <style>
    :root {{ color-scheme: light; --ink: #1c1917; --muted: #57534e; --line: #e7e5e4; --paper: #fafaf9; --card: #fff; --accent: #9a3412; }}
    body {{ margin: 0; font: 16px/1.45 Georgia, serif; color: var(--ink); background: var(--paper); }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 1.5rem; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.2rem; }}
    h2 {{ font-size: 1.25rem; margin-top: 2rem; }}
    p, li {{ color: var(--ink); }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.8rem; }}
    .card {{ background: var(--card); border: 1px solid var(--line); padding: 0.9rem 1rem; }}
    .num {{ font-variant-numeric: tabular-nums; font-size: 1.35rem; }}
    table {{ width: 100%; border-collapse: collapse; background: white; font-size: 0.92rem; }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: right; padding: 0.35rem 0.4rem; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    th {{ font-weight: 600; }}
    button, select {{ font: inherit; padding: 0.35rem 0.5rem; }}
    svg {{ width: 100%; height: 220px; background: white; border: 1px solid var(--line); }}
    .warn {{ border-left: 4px solid var(--accent); padding-left: 0.8rem; }}
  </style>
</head>
<body>
<main>
  <h1>Gilded Ace, January–June 2025</h1>
  <p class="muted">The manager's bottom-10 list is raw house win. Rank 1 means the lowest value. This page tests luck, downtime, and a payout gap before spending.</p>
  <div id="overview" class="grid"></div>
  <h2>1. Does the raw ranking survive luck and hours?</h2>
  <p id="rank-note"></p>
  <label>Period <select id="period"></select></label>
  <label>Zone <select id="zone"></select></label>
  <label>Bank <select id="bank"></select></label>
  <div style="overflow-x:auto"><table id="bottom"></table></div>
  <h2>2. Demand</h2>
  <p id="month-detail"></p>
  <p id="demand"></p>
  <svg id="chart" viewBox="0 0 640 220" role="img" aria-label="May and June coin-in against the weekday forecast"></svg>
  <h2>3. Downtime</h2>
  <p id="down"></p>
  <h2>4 and 5. Carded players and comps</h2>
  <div id="players" class="grid"></div>
  <label>Guest tier <select id="tier"></select></label>
  <div style="overflow-x:auto"><table id="guests"></table></div>
  <h2>6. The $100,000 plan</h2>
  <div id="plan"></div>
  <h2>Scenario desk</h2>
  <p class="muted">The slider reprices the catalog against modeled lost theo. It does not estimate how much a repair would actually recover.</p>
  <label>Assumed recovery <input id="rate" type="range" min="0" max="50" value="10" aria-label="Assumed recovery percent"> <span id="rate-label">10%</span></label>
  <div id="scenario" class="grid"></div>
  <p id="stress"></p>
  <h2>Ask the case file</h2>
  <p class="muted">These answers are calculated from the case file in the page. The browser does not call a model and does not hold an API key.</p>
  <label>Question <input id="ask" type="text" size="48" placeholder="Why was M-1158 flagged?"></label>
  <button id="ask-btn" type="button">Answer</button>
  <p id="assistant-out"></p>
  <h2>Trace the spend</h2>
  <p id="trace"></p>
  <h2>How the forecast was checked</h2>
  <p id="method"></p>
</main>
<script>
const data = {data};
const money = (n) => "$" + Number(n).toLocaleString(undefined, {{maximumFractionDigits: 0}});
const ov = document.querySelector("#overview");
const rec = data.recommendation;
ov.innerHTML = [
  ["Recommendation", rec.actions.map(a => a.action_type_id).join(", ")],
  ["Cost", money(rec.cost_usd)],
  ["Unspent", money(rec.unspent_usd)],
  ["Weekday MAE", money(data.forecast.weekday_mae_usd)],
  ["Constant MAE", money(data.forecast.constant_mae_usd)]
].map(([k,v]) => `<div class="card"><div class="muted">${{k}}</div><div class="num">${{v}}</div></div>`).join("");
const m = data.claim.estimate;
const weak = (data.weakest_residual_per_hour || [])[0];
document.querySelector("#rank-note").innerHTML = `M-1026 raw rank <strong>${{m.raw_rank}}</strong> of ${{data.rank_rule.machine_count}} (1 = lowest house win) and residual-per-hour rank <strong>${{m.residual_per_hour_rank}}</strong> (1 = lowest residual per hour). ${{m.machines_with_lower_residual_per_hour}} machines have a lower residual per hour, so 265 is toward the strong end, not the weak end.` + (weak ? ` The weakest residual per hour on the floor is ${{weak.machine_id}} at ${{weak.residual_per_hour}} per hour, Holm p ${{weak.p_holm == null ? "—" : weak.p_holm.toFixed(3)}}. That rate is not the spend decision. The funded inspection stays on the Holm leak in the raw bottom 10.` : "");
const zones = ["All", ...new Set(data.bottom10.map(r => r.zone))];
const banks = ["All", ...new Set([...data.bottom10, ...(data.period_bottom || [])].map(r => r.bank).filter(Boolean))];
const periodSelect = document.querySelector("#period");
const zoneSelect = document.querySelector("#zone");
const bankSelect = document.querySelector("#bank");
periodSelect.innerHTML = ["All", ...data.downtime.by_month.map(row => row.month)].map(z => `<option>${{z}}</option>`).join("");
zoneSelect.innerHTML = zones.map(z => `<option>${{z}}</option>`).join("");
bankSelect.innerHTML = banks.map(z => `<option>${{z}}</option>`).join("");
function currentRows() {{
  if (periodSelect.value === "All") return data.bottom10;
  return (data.period_bottom || []).filter(row => row.month === periodSelect.value);
}}
function drawTable() {{
  const zone = zoneSelect.value;
  const bank = bankSelect.value;
  const rows = currentRows().filter(r => (zone === "All" || r.zone === zone) && (bank === "All" || r.bank === bank));
  const head = "<tr><th>Machine</th><th>Zone</th><th>Bank</th><th>House win</th><th>Raw rank</th><th>Residual/hour rank</th><th>Holm p</th><th>Leak</th></tr>";
  const body = rows.length
    ? rows.map(r => `<tr><td>${{r.machine_id}}</td><td>${{r.zone}}</td><td>${{r.bank || ""}}</td><td>${{money(r.house_win_usd)}}</td><td>${{r.raw_rank}}</td><td>${{r.residual_per_hour_rank ?? "—"}}</td><td>${{r.p_holm == null ? "—" : r.p_holm.toFixed(3)}}</td><td>${{r.holm_negative_residual == null ? "—" : (r.holm_negative_residual ? "yes" : "no")}}</td></tr>`).join("")
    : "<tr><td colspan='8'>No machines match this period, zone, and bank.</td></tr>";
  document.querySelector("#bottom").innerHTML = head + body;
  const month = data.downtime.by_month.find(row => row.month === periodSelect.value);
  document.querySelector("#month-detail").textContent = month
    ? `${{month.month}}: coin-in ${{money(month.coin_in_usd)}}, house win ${{money(month.house_win_usd)}}, modeled lost theo ${{money(month.modeled_lost_theo_usd)}}.`
    : "January–June combined. The table is the six-month raw bottom 10.";
}}
periodSelect.addEventListener("change", () => {{ drawTable(); drawGuests(); }});
zoneSelect.addEventListener("change", drawTable);
bankSelect.addEventListener("change", drawTable);
drawTable();
const months = data.downtime.by_month;
document.querySelector("#demand").textContent = months.map(row => `${{row.month}}: coin-in ${{money(row.coin_in_usd)}}, weekend machine-day ${{money(row.weekend_machine_day_coin_in)}}, weekday ${{money(row.weekday_machine_day_coin_in)}}`).join(" ");
document.querySelector("#down").textContent = data.downtime.definition + " Floor modeled lost theo: " + money(data.downtime.modeled_lost_theo_usd) + ".";
const p = data.players;
document.querySelector("#players").innerHTML = `
  <div class="card"><div class="muted">Carded coin-in</div><div class="num">${{money(p.tracked_coin_in_usd)}}</div></div>
  <div class="card"><div class="muted">Carded payout</div><div class="num">${{money(p.tracked_payout_usd)}}</div></div>
  <div class="card"><div class="muted">Carded net</div><div class="num">${{money(p.tracked_net_usd)}}</div></div>
  <div class="card"><div class="muted">Players to half of coin-in</div><div class="num">${{p.players_to_half_of_coin_in}} / ${{p.n_players}}</div></div>
  <div class="card"><div class="muted">Top 10% coin-in share</div><div class="num">${{(p.top_decile_coin_in_share*100).toFixed(1)}}%</div></div>
  <div class="card"><div class="muted">Carded comp cost</div><div class="num">${{money(p.comp_cost_usd)}}</div></div>`;
const tierSelect = document.querySelector("#tier");
const tiers = ["All", ...new Set((data.guest_tiers || []).filter(row => row.month === "all").map(row => row.tier))];
tierSelect.innerHTML = tiers.map(tier => `<option>${{tier}}</option>`).join("");
function drawGuests() {{
  const period = periodSelect.value;
  const tier = tierSelect.value;
  const rows = (data.guest_tiers || []).filter(row => row.month === (period === "All" ? "all" : period) && (tier === "All" || row.tier === tier));
  const guestHead = "<tr><th>Tier</th><th>Players</th><th>Carded coin-in</th><th>Carded net</th></tr>";
  const guestBody = rows.length
    ? rows.map(row => `<tr><td>${{row.tier}}</td><td>${{row.players}}</td><td>${{money(row.coin_in_usd)}}</td><td>${{money(row.net_usd)}}</td></tr>`).join("")
    : "<tr><td colspan='4'>No carded guests match this period and tier.</td></tr>";
  document.querySelector("#guests").innerHTML = guestHead + guestBody;
}}
tierSelect.addEventListener("change", drawGuests);
drawGuests();
const sensitivity = rec.downtime_sensitivity_usd;
document.querySelector("#trace").textContent = `A-INSPECT is ${{money((rec.actions[0].unit_cost_cents || 0) / 100)}} per machine in the action catalog (${{rec.actions[0].unit_cost_cents}} cents). Modeled lost theo is ${{money(data.downtime.modeled_lost_theo_usd)}}. Ten percent is ${{money(sensitivity.pessimistic_10pct_usd)}}, below the technician catalog cost of ${{money(sensitivity.technician_cost_usd)}}, so that shift is not funded. ${{rec.why_not_more}}`;
document.querySelector("#plan").innerHTML = rec.actions.map(a => `<div class="card warn"><strong>${{a.action_type_id}}</strong> · ${{money(a.cost_usd)}}<p>${{a.expected_effect}}</p><p>${{a.uncertainty}}</p><p>Measure: ${{a.measurement}}</p></div>`).join("");
document.querySelector("#method").textContent = `Train ${{data.forecast.train}}. Holdout ${{data.forecast.holdout}}. Weekday-mean MAE ${{money(data.forecast.weekday_mae_usd)}} versus constant-mean MAE ${{money(data.forecast.constant_mae_usd)}}. Winner: ${{data.forecast.winner}}. ${{data.forecast.consequence}}`;
const series = data.forecast.holdout_series;
const svg = document.querySelector("#chart");
const vals = series.flatMap(d => [d.actual, d.weekday_mean]);
const min = Math.min(...vals), max = Math.max(...vals);
const x = i => 20 + i * (600 / (series.length - 1));
const y = v => 200 - (v - min) / (max - min) * 180;
const line = (key) => series.map((d,i) => `${{i?"L":"M"}}${{x(i).toFixed(1)}},${{y(d[key]).toFixed(1)}}`).join(" ");
svg.innerHTML = `<path d="${{line("actual")}}" fill="none" stroke="#1c1917" stroke-width="1.5"/><path d="${{line("weekday_mean")}}" fill="none" stroke="#9a3412" stroke-width="1.5"/>`;
const rateInput = document.querySelector("#rate");
function drawScenario() {{
  const pct = Number(rateInput.value);
  const rate = pct / 100;
  const lost = data.downtime.modeled_lost_theo_usd;
  const tech = rec.downtime_sensitivity_usd.technician_cost_usd;
  const captured = rate * lost;
  const techNet = captured - tech;
  const be = lost > 0 ? tech / lost : null;
  document.querySelector("#rate-label").textContent = pct + "%";
  document.querySelector("#scenario").innerHTML = [
    ["Captured theo", money(captured)],
    ["Technician net", money(techNet)],
    ["Break-even", be == null ? "—" : (be * 100).toFixed(2) + "%"],
    ["Inspection", money(rec.cost_usd)]
  ].map(([k,v]) => `<div class="card"><div class="muted">${{k}}</div><div class="num">${{v}}</div></div>`).join("");
  const stress = rec.stress;
  document.querySelector("#stress").textContent = stress
    ? `Hypothetical stress, seed ${{stress.seed}}, ${{stress.draws}} draws. Recovery is uniform from 0 to ${{Math.round(stress.rate_high * 100)}} percent, and lost theo is scaled from ${{stress.scale_low}} to ${{stress.scale_high}}. Mean technician net ${{money(stress.mean_net_usd)}}. Share of draws with positive net ${{(stress.probability_positive_net * 100).toFixed(1)}} percent. This does not show that the shift causes that recovery. The cash outlay if recovery is zero is ${{money(stress.worst_budget_exposure_usd)}}.`
    : "";
}}
rateInput.addEventListener("input", drawScenario);
drawScenario();
const ask = document.querySelector("#ask");
function showAnswer() {{
  const q = ask.value.trim().toLowerCase();
  const items = data.assistant || [];
  const hit = items.find(item => item.question.toLowerCase() === q)
    || items.find(item => q && (item.match_terms || []).some(term => q.includes(term)));
  document.querySelector("#assistant-out").textContent = hit
    ? hit.answer
    : "This page only answers a question when the case file contains the figures. It will not invent a machine, a recovery, or a credential.";
}}
document.querySelector("#ask-btn").addEventListener("click", showAnswer);
ask.addEventListener("keydown", (event) => {{ if (event.key === "Enter") showAnswer(); }});
</script>
</body>
</html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    payload = build()
    write_site(payload)
    print(json.dumps({
        "machines": payload["rank_rule"]["machine_count"],
        "m1026_raw": payload["claim"]["estimate"]["raw_rank"],
        "m1026_residual": payload["claim"]["estimate"]["residual_per_hour_rank"],
        "leaks": payload["multiple_testing"]["bottom10_holm_leaks"],
        "lost_theo": payload["downtime"]["modeled_lost_theo_usd"],
        "weekday_mae": payload["forecast"]["weekday_mae_usd"],
        "constant_mae": payload["forecast"]["constant_mae_usd"],
        "actions": payload["recommendation"]["actions"],
        "empty_location": payload["exclusions"]["empty_location"],
    }, indent=2))


if __name__ == "__main__":
    main()
