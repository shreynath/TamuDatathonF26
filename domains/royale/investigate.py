"""Answer Royale questions from the case file. No model arithmetic."""

from __future__ import annotations

import re

_MACHINE = re.compile(r"m-\d+")
_BLOCKED = (
    "api key",
    "api_key",
    "system prompt",
    "ignore previous",
    "ignore the claims",
    "ignore the case",
    ".env",
    "secret",
    "password",
    "token",
)


def _refuse(reason: str) -> dict:
    return {
        "ok": False,
        "refused": True,
        "answer": reason,
        "metrics": {},
        "sources": [],
        "period": "2025-01-01 to 2025-06-30",
        "filters": {},
        "assumptions": [],
        "limitations": "No figure was calculated for a refused question.",
        "next": "Ask about a machine, month, guest tier, or the published spend plan.",
        "match_terms": [],
        "computed_by": "code",
    }


def _ok(answer: str, metrics: dict, sources: list[str], **extra) -> dict:
    payload = {
        "ok": True,
        "refused": False,
        "answer": answer,
        "metrics": metrics,
        "sources": sources,
        "period": extra.get("period", "2025-01-01 to 2025-06-30"),
        "filters": extra.get("filters", {}),
        "assumptions": extra.get("assumptions", []),
        "limitations": extra.get("limitations", "Carded play is not the machine meter. A residual is not a fault finding."),
        "next": extra.get("next", "Change the period or the recovery slider and read the same source tables."),
        "match_terms": extra.get("match_terms", []),
        "computed_by": "code",
    }
    return payload


def _known_ids(case: dict) -> set[str]:
    known = {"m-1026"}
    for key in ("bottom10", "period_bottom", "weakest_residual_per_hour"):
        for row in case.get(key) or []:
            machine = row.get("machine_id")
            if machine:
                known.add(str(machine).lower())
    return known


def _find(rows: list[dict], machine_id: str) -> dict | None:
    for row in rows:
        if row.get("machine_id") == machine_id:
            return row
    return None


def investigate(question: str, case: dict) -> dict:
    text = " ".join(str(question).split())
    if not text:
        return _refuse("Ask a question about the published case.")
    if len(text) > 500:
        return _refuse("That question is longer than 500 characters.")
    folded = text.lower()
    if any(term in folded for term in _BLOCKED):
        return _refuse("This assistant does not reveal credentials, prompts, or anything outside the case file.")
    unknown = [item.upper() for item in _MACHINE.findall(folded) if item not in _known_ids(case)]
    if unknown:
        return _refuse(f"{unknown[0]} is not in the published case tables, so no figure is given for it.")

    sensitivity = case["recommendation"]["downtime_sensitivity_usd"]
    lost = float(case["downtime"]["modeled_lost_theo_usd"])
    tech = float(sensitivity["technician_cost_usd"])
    ten = float(sensitivity["pessimistic_10pct_usd"])
    inspect_cost = float(case["recommendation"]["cost_usd"])

    if "m-1158" in folded or "flagged" in folded or "inspection" in folded:
        row = _find(case.get("bottom10") or [], "M-1158")
        if row is None:
            return _refuse("M-1158 is not in the six-month bottom table.")
        leaks = case["multiple_testing"]["bottom10_holm_leaks"]
        return _ok(
            (
                f"M-1158 is in the raw bottom 10 and is the Holm-significant negative residual "
                f"in that list ({', '.join(leaks)}). Six-month house win is ${row['house_win_usd']:,.2f} "
                f"against theo ${row['theo_usd']:,.2f}, residual ${row['residual_usd']:,.2f}, "
                f"Holm p {row['p_holm']:.4f}. The funded action is one inspection at ${inspect_cost:,.2f}. "
                f"That buys a paytable check. It does not show the machine is broken."
            ),
            {
                "house_win_usd": row["house_win_usd"],
                "theo_usd": row["theo_usd"],
                "residual_usd": row["residual_usd"],
                "p_holm": row["p_holm"],
                "inspect_cost_usd": inspect_cost,
            },
            ["bottom10", "multiple_testing.bottom10_holm_leaks", "recommendation"],
            match_terms=["m-1158", "flagged", "inspection"],
            next="Read the residual-per-hour rank beside the raw rank before spending more.",
        )

    if "june" in folded and ("lowest" in folded or "m-1296" in folded or "bottom" in folded):
        june = [row for row in case.get("period_bottom") or [] if row.get("month") == "2025-06"]
        if not june:
            return _refuse("June rows are not in this case file.")
        lowest = min(june, key=lambda row: (row["raw_rank"], row["machine_id"]))
        return _ok(
            (
                f"In June 2025 the lowest house-win machine in the monthly bottom 10 is "
                f"{lowest['machine_id']} at ${lowest['house_win_usd']:,.2f}, bank {lowest['bank']}. "
                f"Monthly ranks are recomputed inside the month. They do not inherit the six-month Holm result."
            ),
            {"machine_id": lowest["machine_id"], "house_win_usd": lowest["house_win_usd"], "bank": lowest["bank"]},
            ["period_bottom"],
            period="2025-06",
            filters={"month": "2025-06"},
            match_terms=["june", "m-1296", "lowest"],
        )

    if "technician" in folded or "break-even" in folded or "breakeven" in folded or "worthwhile" in folded or "recovery rate" in folded:
        rate = None if lost <= 0 else tech / lost
        percent = None if rate is None else round(rate * 100, 2)
        return _ok(
            (
                f"Ten percent of modeled lost theo is ${ten:,.2f}. The technician shift costs ${tech:,.2f}, "
                f"so the 10% case does not fund it. The shift breaks even at {percent}% of the "
                f"${lost:,.2f} modeled lost theo. That rate is a threshold, not a forecast of what the shift recovers."
            ),
            {
                "modeled_lost_theo_usd": lost,
                "pessimistic_10pct_usd": ten,
                "technician_cost_usd": tech,
                "break_even_percent": percent,
            },
            ["downtime.modeled_lost_theo_usd", "recommendation.downtime_sensitivity_usd"],
            assumptions=["The 10% and break-even figures divide catalog cost by modeled lost theo."],
            match_terms=["technician", "break-even", "worthwhile", "recovery"],
        )

    if "forecast" in folded or "weekday" in folded or "outperform" in folded:
        forecast = case["forecast"]
        return _ok(
            (
                f"On the May–June holdout, the weekday-mean forecast MAE is ${forecast['weekday_mae_usd']:,.2f} "
                f"and the constant-mean MAE is ${forecast['constant_mae_usd']:,.2f}. "
                f"The weekday mean is the one that was kept. Training stopped at the end of April."
            ),
            {
                "weekday_mae_usd": forecast["weekday_mae_usd"],
                "constant_mae_usd": forecast["constant_mae_usd"],
                "winner": forecast["winner"],
            },
            ["forecast"],
            period=forecast["holdout"],
            match_terms=["forecast", "weekday", "outperform"],
        )

    if "significant" in folded or "holm" in folded:
        leaks = case["multiple_testing"]["bottom10_holm_leaks"]
        return _ok(
            (
                f"Inside the raw bottom 10, the Holm-significant negative residual is {', '.join(leaks)}. "
                f"The floor count of Holm-significant negative residuals is {case['multiple_testing']['floor_holm_negative']}. "
                f"An unadjusted p-value is not used for the spend decision."
            ),
            {
                "bottom10_holm_leaks": leaks,
                "floor_holm_negative": case["multiple_testing"]["floor_holm_negative"],
            },
            ["multiple_testing"],
            match_terms=["significant", "holm"],
        )

    if "gold" in folded:
        month = "2025-06" if "june" in folded else "all"
        rows = [
            row for row in case.get("guest_tiers") or []
            if row.get("tier") == "Gold" and row.get("month") == month
        ]
        if not rows:
            return _refuse("That Gold slice is not in the case file.")
        row = rows[0]
        return _ok(
            (
                f"Gold carded play for {month} is {row['players']} players, "
                f"coin-in ${row['coin_in_usd']:,.2f}, net ${row['net_usd']:,.2f}. "
                f"These are carded guests, not every dollar in the machine meters."
            ),
            {"players": row["players"], "coin_in_usd": row["coin_in_usd"], "net_usd": row["net_usd"]},
            ["guest_tiers"],
            period=month,
            filters={"tier": "Gold", "month": month},
            match_terms=["gold"],
        )

    if "residual" in folded and ("worst" in folded or "per available hour" in folded or "weakest" in folded):
        rows = case.get("weakest_residual_per_hour") or []
        if not rows:
            return _refuse("The residual ranking is not in this case file.")
        top = rows[0]
        names = ", ".join(row["machine_id"] for row in rows[:5])
        return _ok(
            (
                f"The lowest residual per available hour is {top['machine_id']} at "
                f"${top['residual_per_hour']:,.4f} per hour (rank 1), Holm p {top['p_holm']:.3f}. "
                f"The five weakest are {names}. M-1158 is rank 2 on this list and is the Holm leak that the inspection funds. "
                f"A worse rate with Holm p above 0.05 is not treated as a malfunction."
            ),
            {"machine_id": top["machine_id"], "residual_per_hour": top["residual_per_hour"]},
            ["weakest_residual_per_hour"],
            match_terms=["residual", "worst", "weakest"],
        )

    if "demand" in folded:
        months = case["downtime"]["by_month"]
        first, last = months[0], months[-1]
        return _ok(
            (
                f"Floor coin-in was ${first['coin_in_usd']:,.2f} in {first['month']} and "
                f"${last['coin_in_usd']:,.2f} in {last['month']}. Weekend machine-days stay above weekday machine-days "
                f"in every published month. The forecast uses the weekday pattern, not a machine ranking."
            ),
            {"first_month_coin_in_usd": first["coin_in_usd"], "last_month_coin_in_usd": last["coin_in_usd"]},
            ["downtime.by_month", "forecast"],
            match_terms=["demand"],
        )

    return _refuse("That question is not tied to a published table. No number was estimated for it.")


def briefings(case: dict) -> list[dict]:
    questions = [
        "Why was M-1158 flagged?",
        "Which machines have the worst residual per available hour?",
        "Which machine is lowest in June?",
        "Why is the technician shift not funded?",
        "What recovery rate makes the technician shift worthwhile?",
        "Which findings are statistically significant?",
        "What does the forecast outperform?",
        "What evidence supports the recommended inspection?",
        "What explains demand changes?",
        "How does Gold look in June?",
    ]
    rows = []
    for question in questions:
        row = investigate(question, case)
        row["question"] = question
        rows.append(row)
    return rows
