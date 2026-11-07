# Championship audit

Clock: Saturday, November 7, 2026, about 3:15 PM America/Chicago. House Edge main still closes at 9:00 PM Central. Adaptation opens at 9:00 PM and closes Sunday at 11:00 AM. Databricks was not modified. Routes was not extended.

## Submission protection

| Entry | Artifact | Check | Receipt |
|---|---|---|---|
| House Edge | `/tmp/he-fresh-submission.csv` and `submissions/house_edge/main/artifacts/submission.csv` | SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1`. 1,536 data rows. Header `query_id,p_0,p_1,p_2,p_5,p_20`. | None. The form redirects to Google sign-in. |
| House Edge code | `/tmp/he-entry.zip` and `submissions/house_edge/main/artifacts/entry.zip` | Both SHA-256 `bbb18384cb9766fe27d5a3facea298e9f591510653a0a1246765200ab463d986`. | None. |
| Poker | https://github.com/shreynath/PitBossEquity `316bcf1acb5e6cf254ba1acb6e15906ca913f80d` | Local `poker/agent.py` is 485 lines and SHA-256 `6046f169f4961f3bbf319c53aa5f4c05d66293a9ea37bcb8303bcd90f82d0d05`, same size as the public blob. `pytest` 12 passed. | None. Same Google sign-in wall. Docker daemon is not running, so `tools/check_build.sh` did not run. |

The House Edge model was not replaced. The banked local score remains 31.010/60 against pooled-recent 30.826/60.

## What changed in this pass

- `safe_static` refuses parent traversal, repeated percent-encoding, backslashes, null bytes, non-html/json types, and a symlink that leaves the approved root. `/api/databricks` is no longer a public route. Request bodies over 16,384 bytes get HTTP 413. Responses send `nosniff`, `no-store`, and `no-referrer`.
- The Royale page recomputes a recovery slider from modeled lost theo and the catalog costs. At 10% the technician net is negative ($9,031 captured versus $11,520). Break-even is 12.76%. A 4,000-draw hypothetical stress, seed 1158, has mean technician net $2,049.25 and a 56.75% positive-net share. The label says this is not a causal effect. The funded action is still one $1,200 inspection of M-1158, with $98,800 unspent.
- M-1288 has the lowest residual per available hour, $-13.6571, and Holm p 1.000. M-1158 is rank 2 on that list and is the Holm leak. The spend was not moved.
- Questions on the page are answered from the case file. The browser does not call Gemini and does not hold a key. One live `gemini-2.5-flash` rephrase of the M-1158 answer was kept only after every number was already in the packet (`docs/gemini_live_m1158.json`).

## Tests

`python3 -m pytest -q` in `TamuDatathonF26`: 38 passed. Poker `pytest`: 12 passed. Python 3.13.5.

Browser on http://127.0.0.1:8765/ : June selects M-1296 at bank B-14 and leaves Holm cells blank. June plus High-Limit Room plus B-14 says no machines match. June Gold is 1,670 players. The 20% slider shows captured theo $18,063 and technician net $6,543. The M-1158 question returns the case figures. At 390px width the page does not scroll sideways. The hardened server on 127.0.0.1:8766 returned 404 for `.env`, `../`, encoded `..`, `.git/config`, and `/api/databricks`, 413 for a 20KB body, and the grounded inspect cost 1200.0.

## Scores, from this evidence

| Component | Score | Why it is not higher |
|---|---|---|
| Poker correctness | 8 | Evaluator and legal-action tests pass. Official container was not built. |
| Poker submission | 4 | Public SHA matches. Form has no receipt. |
| House Edge model | 8 | Protected file still matches the scored CSV. No new model beat it. |
| House Edge submission | 3 | Files are ready. Form has no receipt. |
| Dashboard Royale | 7 | Filters, forecast, priced plan, and scenario desk work on https://shreynath.github.io/gilded-ace/ at `9cf601b`. No video and no Devpost receipt. |
| Highway | 7 | Fail-closed ids and the feed invariants pass. No portal receipt. |
| API security | 7 | The tested local routes refuse the cases above. This is not a proof about every route or a deployed host. |
| Gemini | 6 | One guarded live call succeeded. The public page does not call the model, because the key would otherwise ship in the browser. |

## Still blocked

- Sign in at the House Edge form and upload both files before 9:00 PM Central. CSV: `/tmp/he-fresh-submission.csv`. ZIP: `/tmp/he-entry.zip`.
- Sign in at https://forms.gle/Jx9RWE5VgR8dbbcj9 and submit https://github.com/shreynath/PitBossEquity with SHA `316bcf1acb5e6cf254ba1acb6e15906ca913f80d`.
- Start Docker Desktop, then from `poker/` run `./tools/check_build.sh`.
- Record the Royale walkthrough and submit Devpost. No sponsor account was configured for Vultr, Tiger Data, Snowflake, MongoDB Atlas, Solana, or GoDaddy, so those prizes were not claimed.
