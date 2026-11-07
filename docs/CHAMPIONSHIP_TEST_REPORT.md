# Championship test report

Saturday, November 7, 2026, America/Chicago.

## Automated suite

`python3 -m pytest -q --tb=line` from `TamuDatathonF26`: 41 passed in 4.02 seconds.

New cases in that run:

- Tied values from `_pct` share one rank.
- Forty random hands: `_omaha_scores` equals `omaha_score`.
- `public_write_route("/api/observations")` is false.

## Poker matches after the tie-rank change

PitBoss was agent 1. Opponent was the cloned ShortStackSage tree at `/tmp/poker-field/ssd-heads-up-poker`. Three hundred duplicated deals.

| Seed | bb/deal | Result | Errors | Think |
|---|---|---|---|---|
| 11 | −0.270 (stderr 0.335) | chop | 0 | 0.64s and 0.76s of 8s |
| 29 | −0.518 (stderr 0.460) | chop | 0 | 0.71s and 0.76s of 8s |

The prior build on the same seeds was −0.167 and −0.408, also chops. The point estimates moved by less than one standard error. The change stays because equal hands no longer get different ranks.

The 1,000-deal seed-47 loss to ShortStackSage (−0.458 bb/deal) and the Aura chop (−0.414) were measured before this tie change. They were not rerun.

## Gemini

`explain_case("Why was M-1158 flagged for inspection?")` returned `ok: true` from `gemini-2.5-flash`. Cited ids: `ace-recommendation-1`, `ace-holm-1`. The number guard did not reject the reply. The key was not printed. Record: `docs/gemini_release_check.json`.

## Not run

- `poker/tools/check_build.sh`. The Docker socket was absent.
- A fresh 2,000-hand round robin.
- A block bootstrap of the M-1158 residual.
- Sponsor API calls other than the one Gemini request.
