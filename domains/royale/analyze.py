"""Compute the Gilded Ace case from parquet. Numbers are written, not typed."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "royale-src" / "data"
OUT = ROOT / "apps" / "web" / "public"
DAILY = DATA / "1_prepared_views" / "prepared_daily_view.parquet"
PROPERTY = DATA / "1_prepared_views" / "property_day.parquet"
PLAYERS = DATA / "1_prepared_views" / "player_period.parquet"
ACTIONS = DATA / "2_machine_decision" / "action_catalog.parquet"


def main() -> None:
    from domains.royale.report import main as report_main
    report_main()
    return
    if not DAILY.exists():
        raise SystemExit(f"Royale parquet is missing: {DAILY}")
    con = duckdb.connect()
    exclusion = con.sql(f"""
        SELECT
          COUNT(*) AS rows_total,
          COUNT(*) FILTER (WHERE location_id IS NULL OR location_id = '') AS empty_location,
          COUNT(*) FILTER (WHERE NOT active) AS inactive_flag
        FROM '{DAILY}'
    """).fetchone()
    machines = con.sql(f"""
        WITH active AS (
          SELECT * FROM '{DAILY}'
          WHERE active AND location_id IS NOT NULL AND location_id <> ''
        ),
        agg AS (
          SELECT machine_id,
                 ANY_VALUE(zone_name) AS zone_name,
                 ANY_VALUE(theme) AS theme,
                 ANY_VALUE(volatility_class) AS volatility_class,
                 SUM(house_win_usd)::DOUBLE AS house_win,
                 SUM(theo_usd)::DOUBLE AS theo,
                 SUM(luck_residual_usd)::DOUBLE AS residual,
                 SUM(coin_in_usd)::DOUBLE AS coin_in,
                 SUM(available_hours)::DOUBLE AS hours,
                 SUM(payout_usd)::DOUBLE AS payout
          FROM active
          GROUP BY machine_id
        )
        SELECT *,
               house_win / NULLIF(hours, 0) AS win_per_hour,
               residual / NULLIF(hours, 0) AS residual_per_hour,
               RANK() OVER (ORDER BY house_win) AS raw_rank,
               RANK() OVER (ORDER BY residual / NULLIF(hours, 0)) AS residual_rank
        FROM agg
    """).df()
    bottom_raw = machines.nsmallest(10, "house_win")
    # A machine that looks bad on raw win and looks ordinary once residual per hour is used.
    gap = machines.assign(gap=machines["residual_rank"] - machines["raw_rank"])
    case_row = gap.sort_values("gap", ascending=False).iloc[0]
    forecast = con.sql(f"""
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
        SELECT
          AVG(ABS(d.coin_in - m.weekday_mean)) FILTER (WHERE d.split = 'holdout') AS weekday_mae,
          AVG(ABS(d.coin_in - c.constant_mean)) FILTER (WHERE d.split = 'holdout') AS constant_mae
        FROM days d
        JOIN means m USING (local_weekday)
        CROSS JOIN constant c
    """).fetchone()
    concentration = con.sql(f"""
        WITH totals AS (
          SELECT SUM(tracked_coin_in_usd)::DOUBLE AS coin_in,
                 SUM(tracked_payout_usd)::DOUBLE AS payout,
                 SUM(tracked_net_usd)::DOUBLE AS net,
                 SUM(comp_cost_usd)::DOUBLE AS comp_cost
          FROM '{PLAYERS}'
        ),
        ranked AS (
          SELECT player_id, tracked_coin_in_usd::DOUBLE AS coin_in,
                 SUM(tracked_coin_in_usd) OVER () AS all_coin,
                 SUM(tracked_coin_in_usd) OVER (ORDER BY tracked_coin_in_usd DESC) AS running
          FROM '{PLAYERS}'
        )
        SELECT (SELECT coin_in FROM totals) AS tracked_coin_in,
               (SELECT payout FROM totals) AS tracked_payout,
               (SELECT net FROM totals) AS tracked_net,
               (SELECT comp_cost FROM totals) AS comp_cost,
               MIN(running / all_coin) FILTER (WHERE running >= 0.5 * all_coin) AS share_at_half
        FROM ranked
    """).fetchone()
    catalog = con.sql(f"SELECT action_type_id, name, unit_cost_cents, recurring_cost_cents_per_day, lead_days, quantity_limit FROM '{ACTIONS}'").df()
    keep = catalog[catalog["name"].str.contains("eep", case=False)] if catalog["name"].str.contains("eep", case=False).any() else None
    case = {
        "data_version": "dashboard-royale cloned main depth 1",
        "exclusions": {
            "rows_total": int(exclusion[0]),
            "empty_location": int(exclusion[1]),
            "inactive_flag": int(exclusion[2]),
            "method": "Counted in DuckDB. The planning number 1018 is not used.",
        },
        "claim": {
            "claim_id": "ace-case-1",
            "domain": "royale",
            "entity_id": str(case_row["machine_id"]),
            "analysis_window": "2025-01-01 to 2025-06-30, active days with a location",
            "claim_type": "ranking_changes_after_exposure_and_luck",
            "metric": "raw house win versus residual per available hour",
            "units": "usd and rank",
            "estimate": {
                "house_win_usd": round(float(case_row["house_win"]), 2),
                "theo_usd": round(float(case_row["theo"]), 2),
                "residual_usd": round(float(case_row["residual"]), 2),
                "available_hours": round(float(case_row["hours"]), 2),
                "raw_rank": int(case_row["raw_rank"]),
                "residual_per_hour_rank": int(case_row["residual_rank"]),
                "zone": case_row["zone_name"],
                "theme": case_row["theme"],
                "volatility": case_row["volatility_class"],
            },
            "uncertainty_method": "Daily residual variance and sum of squared bet sizes are not both in prepared_daily_view. This rank is descriptive, not a confidence interval.",
            "supporting_query_or_rows": "domains/royale/analyze.py aggregation of prepared_daily_view",
            "model_run_id": "royale-analyze-1",
            "alternative_explanation": "Low raw win can be a quiet location, downtime, or a lucky streak for the player. Residual per available hour is the check.",
            "limitations": "Carded player tables are not in this machine total. Traffic counters are not treated as unique visitors.",
            "proposed_action": "Keep the budget unless a later claim shows a machine that stays bad after luck, hours, and placement.",
        },
        "forecast": {
            "claim_id": "ace-forecast-1",
            "train": "2025-01-01 through 2025-04-30",
            "holdout": "2025-05-01 through 2025-06-30",
            "weekday_mae_usd": round(float(forecast[0]), 2),
            "constant_mae_usd": round(float(forecast[1]), 2),
            "consequence": "Use the lower-MAE forecast only as a staffing context. It does not by itself justify replacing a machine.",
        },
        "players": {
            "claim_id": "ace-players-1",
            "tracked_coin_in_usd": round(float(concentration[0]), 2),
            "tracked_payout_usd": round(float(concentration[1]), 2),
            "tracked_net_usd": round(float(concentration[2]), 2),
            "comp_cost_usd": round(float(concentration[3]), 2),
            "coin_in_share_when_half_reached": round(float(concentration[4]), 4),
            "note": "Tracked-player totals are carded play. They are not the machine-meter total.",
        },
        "recommendation": {
            "action": "keep_the_budget",
            "reason": "The highlighted machine's raw rank is a poor reason to spend. The residual-per-hour rank moves it off the bottom.",
            "cost_usd": 0,
            "measurement": "Repeat the two rankings on the next 30 gaming days before buying a replacement.",
            "catalog_has_keep": bool(keep is not None and len(keep)),
        },
        "bottom_raw": [
            {"machine_id": row.machine_id, "house_win_usd": round(float(row.house_win), 2)}
            for row in bottom_raw.itertuples()
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ace_case.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
    export = ROOT / "infra" / "databricks" / "export_contract.json"
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text(json.dumps({
        "chain": ["source snapshot", "validated transform", "analytical table", "model evaluation", "recommendation", "published export"],
        "executed_offline_with": "duckdb",
        "live_warehouse": "not called; DATABRICKS_HOST was not required for this export",
        "case_claim_id": "ace-case-1",
    }, indent=2), encoding="utf-8")
    print(json.dumps({"machine": case["claim"]["entity_id"], "raw_rank": case["claim"]["estimate"]["raw_rank"], "residual_rank": case["claim"]["estimate"]["residual_per_hour_rank"], "empty_location": case["exclusions"]["empty_location"]}, indent=2))


if __name__ == "__main__":
    main()
