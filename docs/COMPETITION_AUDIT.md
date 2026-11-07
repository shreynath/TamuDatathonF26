# Competition audit

Checked Saturday, November 7, 2026, 2:38 PM America/Chicago. House Edge main is due 9:00 PM CT the same day. Nothing below was treated as submitted unless a confirmation page was actually returned.

## House Edge

| Item | Result |
|---|---|
| CSV | `/tmp/he-fresh-submission.csv`, 142,879 bytes, SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1` |
| ZIP | `/tmp/he-entry.zip` and `submissions/house_edge/main/artifacts/entry.zip`, both 17,199 bytes, SHA-256 `bbb18384cb9766fe27d5a3facea298e9f591510653a0a1246765200ab463d986` |
| Banked score | 31.010/60 on the kit validation set. Not replaced. |
| Form | https://docs.google.com/forms/d/e/1FAIpQLSfv2WV_Fz7NHstRPN2TGi3pvMAFrcQuvs2SkQL1DqpdLebhFg/viewform still redirects to Google sign-in. No receipt. |

## Poker

The public competition repo was behind the tested agent. `game.py` and `evaluator.py` already matched. `agent.py` did not.

| Repo | SHA | What it is |
|---|---|---|
| Public, previous | `a2ae357d5e4977aeae1f4572ec8a3f38db6be6da` | Fixed equity thresholds. Rollback if the organizer image rejects the new build. |
| Private main | `78a6e3f963d890232dcceea8a3576784735c2779` | Value policy plus `poker/stress_sim.py`. |
| Public, now | `316bcf1acb5e6cf254ba1acb6e15906ca913f80d` | Same `agent.py` bytes as private main. GitHub raw SHA-256 `6046f169f4961f3bbf319c53aa5f4c05d66293a9ea37bcb8303bcd90f82d0d05`. |

Local checks on that file: `pytest` 12 passed. All-in price audit, 0 mistakes on the sampled shoves. Duplicate 1,000-deal matches after the preflop shape fix: calling station, always-half, random, and always-pot had intervals above 0 on the reported seeds. Thinking stayed under about 2 seconds of the 8-second bank on those runs.

Docker is installed at `/usr/local/bin/docker` and the daemon was not running, so `tools/check_build.sh` did not run. The form at https://forms.gle/Jx9RWE5VgR8dbbcj9 was not submitted from this session.

## Dashboard Royale

https://shreynath.github.io/gilded-ace/ returned HTTP 200. Public SHA `81cda0aae81ec3971ca1dbfa5b6d50f7d79308e8`. The page has a zone filter, the forecast holdout note, and the priced recommendation. It does not yet change the analysis period, drill a guest group, or play a video. No Devpost receipt.

## Not done, on purpose

Routes stays out. Build-a-Dataset was not invented. HEB's in-person brief was not guessed. Rev's was not started. The House Edge model was not replaced. Ollama cloud still is not a successful authenticated integration. A Databricks dashboard URL was supplied for workspace `dbc-e0b5a6a8-b975`; it was not used as proof of a casino analysis.
