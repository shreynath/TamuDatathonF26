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

## Rejected preflop table

A 96-sample equity for all 376,992 preflop hands, mean 0.4999 after shuffling the draw, replaced the four-runout rank. The poker tests passed. ShortStackSage, with PitBoss as agent 1:

| Deals | Seed | bb/deal | Result |
|---|---|---|---|
| 1000 | 47 | −0.279 (stderr 0.253) | chop |
| 1000 | 83 | −0.117 (stderr 0.261) | chop |
| 1000 | 11 | −0.670 (stderr 0.265) | loss |
| 300 | 29 | −0.665 (stderr 0.461) | chop |

Zero errors. Thinking stayed under 0.3 seconds. Seed 47 moved from a loss to a chop. Seed 11 became a loss, so the table was not published. The tournament SHA remains `6b2921de93674e8600659540e307df5894b9e259`.

## Gemini

`explain_case("Why was M-1158 flagged for inspection?")` returned `ok: true` from `gemini-2.5-flash`. Cited ids: `ace-recommendation-1`, `ace-holm-1`. The number guard did not reject the reply. The key was not printed. Record: `docs/gemini_release_check.json`.

## Not run

- `poker/tools/check_build.sh`. Docker client 28.3.2 is installed. The daemon at `~/.docker/run/docker.sock` was not running at 5:40 PM Central.
- A fresh 2,000-hand round robin.
- A block bootstrap of the M-1158 residual.
- Sponsor API calls other than the one Gemini request.
