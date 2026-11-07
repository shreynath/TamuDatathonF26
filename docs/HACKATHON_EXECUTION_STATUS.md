# Hackathon execution status

Clock used for this file: Saturday, November 7, 2026, afternoon America/Chicago. House Edge main still closes at 9:00 PM. Adaptation opens at 9:00 PM and closes Sunday at 11:00 AM. Routes is out of the plan.

| Project | Status | Deadline | Baseline | Blocker | Next action | Acceptance | Submission |
|---|---|---|---|---|---|---|---|
| House Edge | Partial | Main 9:00 PM CT Sat; adaptation 11:00 AM CT Sun | Fresh Python 3.13 rebuild matches the saved CSV with max abs diff 0. SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1`. Validation 31.010/60 vs pooled-recent 30.826/60 | Google Form requires a Google sign-in this browser does not have. Registration email was not readable from here | You sign in and upload `/tmp/he-fresh-submission.csv` plus `/tmp/he-entry.zip` | Checker said VALID FORMAT, 1536 rows | Not uploaded |
| Poker | Partial | Latest successful build plays; form is open with the event | Public repo, 12 pytest passes, 0 errors, thinking time about 0.01–0.04s of 8s | Same Google sign-in wall. Docker is not installed, so `check_build.sh` did not run | Submit the URL and the 40-character SHA on the form | Local judge only | Repo is public. Form was not submitted |
| Dashboard Royale | Partial | Devpost, event page; not re-verified today | Weekday MAE $68,698.55 vs constant $218,258.10 | No Devpost submission and no video | Open the dashboard, record the 2-minute video, submit | Q1–Q6 are answered in `ace_case.json` and the write-up | Public repo https://github.com/shreynath/gilded-ace and Pages https://shreynath.github.io/gilded-ace/ . Local check at http://127.0.0.1:8765/ passed the zone filter |
| Highway | Partial | Event end | 918 calls replayed on a fresh server, 0 `ok: false` | Hidden expected actions are still hidden | Keep the log; do not let it displace Royale | Invariants in `tests/test_highway.py` | Not submitted |
| Databricks | Partial | Sponsor window | Token works. Table `workspace.pitboss.forecast_comparison`. MLflow run `e83cbda9e53040c1b24ed438dfa20441` | Genie on our table needs a serialized space the API did not return | Use the starter space only as a sample | Warehouse was stopped after the checks | Not a sponsor form submission |
| Gemini | Operational | MLH Best Use of Gemini. The partner page shows the API cookbook, not a separate form. | Live `gemini-2.5-flash` reply kept only after every number matched `ace_case.json`: 10% capture $9,031.34, technician $11,520, inspect $1,200. | The public page cannot call Gemini without exposing the key, so the checked reply is static. | Keep the key in `.env`. Do not print it. | `tests/test_gemini_guard.py` | Not a separate MLH receipt |
| Grok / SpaceXSI | Blocked | MLH raffle for building with Cursor and Grok Bot this weekend | This project is being built in Cursor with Grok | `@grok/agent-sdk` 0.6.0 is not signed in, and Node is v20.20.1 while the SDK requires Node >= 22.13 | Install Node 22 and run `npx @grok/agent-sdk@0.6.0 login`, then the bot can be scaffolded | `whoami` returned not signed in | Raffle entry was not submitted from here |
| Ollama | Blocked | Optional | Cloud host reachable | HTTP 401 on chat. The key in `.env` was rejected | Rotate or replace the key. Do not print it | A 200 from `/api/chat` | Not used for any scored number |
| Rev's Casino | Not attempted | Unknown from this tree | None | No starter was in the repo and the clock went to the scored tracks | Read the brief only if Royale and House Edge are banked | A real brief | Not started |

## Priority

1. You upload House Edge before 9:00 PM. The files are ready.
2. You submit the poker URL and SHA. The build check still needs Docker or the organizer builder.
3. Finish Royale video and Devpost.
4. At 9:00 PM, run `submissions/house_edge/adaptation/prepare.py` on the new kit before changing the model.
5. Leave Routes alone.
