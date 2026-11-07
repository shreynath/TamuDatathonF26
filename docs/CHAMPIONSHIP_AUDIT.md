# Championship audit

Recorded Saturday, November 7, 2026, about 5:15 PM America/Chicago. Local and `origin/main` were `9b6b822` at the start of this pass. House Edge main-round files were checked before any code change. Hacking on the public schedule runs until 12:00 PM Sunday. The 9:00 PM House Edge handoff is still the time to stop experiments on that entry.

Databricks was not modified. Routes was not restarted.

## What changed

| Item | File | Result |
|---|---|---|
| Tied range ranks shared one percentile | `poker/agent.py` `_pct` | Sort order no longer splits equal strengths. Seeds 11 and 29 against ShortStackSage stayed chops: −0.270 and −0.518 bb/deal, 0 errors. |
| Vector evaluator checked against `omaha_score` | `poker/test_agent.py` | 40 random 10-card deals matched. |
| Observation writes closed | `apps/api/server.py` `public_write_route` | `/api/observations` is not a public write. Routes code remains for the historical tests. |
| Gemini narrative on the local investigate API | `apps/api/server.py` | A live `gemini-2.5-flash` reply was kept only after the number guard. Evidence ids were `ace-recommendation-1` and `ace-holm-1`. The deterministic answer is still the one the route returns as `answer`. |
| Tournament repo updated | PitBossEquity `6b2921de93674e8600659540e307df5894b9e259` | `agent.py` and `requirements.txt` only. `evaluator.py` and `game.py` were already identical to this repo. Rollback remains `316bcf1`. |

## Left unchanged on purpose

- House Edge model and CSV. SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1`, 1,536 data rows, header `query_id,p_0,p_1,p_2,p_5,p_20`. ZIP SHA-256 `bbb18384cb9766fe27d5a3facea298e9f591510653a0a1246765200ab463d986`. Score remains 31.010/60.
- The $1,200 inspection recommendation. The Databricks $39,900 plan is a teammate scenario with stated assumptions. It was not copied into the local recommendation.
- `numpy` stays unpinned. The official poker base image already provides it, and a pin can force a second install.
- No Vultr, Snowflake, MongoDB, Solana, Tiger Data, or GoDaddy resources were created. No credentials for those services are in this environment, and no paid resource was authorized.

## Scores after this pass

These are engineering judgments, not judge scores.

| Component | Engineering | Competition readiness | Missing gate |
|---|---|---|---|
| Poker | 8.6 | 6.2 | Form receipt, official container, and the 1,000-deal ShortStackSage holdout is still a loss on the prior build (−0.46 bb/deal, seed 47). |
| House Edge | 7.5 | 5.0 | Form receipt. The validation edge is 0.184 and was not from a fresh holdout. |
| Dashboard Royale | 8.5 | 6.0 | Public Pages was not rebuilt this pass. No video, no Devpost receipt. Two budget stories are not yet one page. |
| Highway | 8.5 | 6.5 | Tests pass. No new randomized suite and no portal receipt. |
| API | 8.6 | — | Local containment and the closed write route. No public host, so no rate-limit proof. |
| Gemini | 6.0 | 4.0 | One live grounded call works. GitHub Pages still cannot call Gemini without a backend key. |

## Manual submissions still required

House Edge form: https://docs.google.com/forms/d/e/1FAIpQLSfv2WV_Fz7NHstRPN2TGi3pvMAFrcQuvs2SkQL1DqpdLebhFg/viewform

Upload `submissions/house_edge/main/artifacts/entry.zip`. This environment reaches a Google sign-in wall and cannot complete it.

Poker form: https://forms.gle/Jx9RWE5VgR8dbbcj9

Submit SHA `6b2921de93674e8600659540e307df5894b9e259`. If that build fails the official container, submit rollback `316bcf1acb5e6cf254ba1acb6e15906ca913f80d` instead. Docker's socket was not present here, so `check_build.sh` did not run.
