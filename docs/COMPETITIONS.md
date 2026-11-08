# Competition map

Sunday, November 8, 2026, morning America/Chicago. A fit score is how complete the artifact is for that challenge. A win score is the chance this entry finishes first, from the evidence in this repo. Neither number is a prize receipt.

## House Edge

The checker in the participant kit is the scale that accepts a file. `slot_forecasting/rounds.py` scores **main out of 60** and **adaptation out of 40**. It rejects metadata that still says 80/20 and calls that the old kit. The pasted guide's "80 points" is that older scale. Copying the validation answer key scores 60.000 on a held-out half of the public validation file. That key is not the test file, and the test probabilities are not in the kit.

The uploaded main forecast remains `submissions/house_edge/main/artifacts/submission.csv`, SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1`. The code ZIP is `artifacts/entry.zip`, SHA-256 `bbb18384cb9766fe27d5a3facea298e9f591510653a0a1246765200ab463d986`. Local validation is **31.010 / 60**. The frozen pooled reference is the 30-point line. A 36-setting refit of the same forecaster moved the selection half from 30.987 to 30.994. That is not a new model. A separate model trained on the public probability targets scored 27.9 on the half it did not train on.

| | Score |
|---|---|
| Fit, file contract | 8. The CSV has the six required columns and 1,536 queries. The ZIP opens on `README.md` and `reproduce.json`. |
| Forecast quality | 4. It is a small step past the starter, not exact odds. |
| Chance of winning the track | 3. Exact odds are 60 on this kit. This entry is near 31. |

Round two, from the guide pasted Sunday morning: data at 10:30 AM Central, uploads close at 12:00 PM Central. The same Drive link still served the main kit at 10:11 AM. `submissions/house_edge/adaptation/prepare.py` refuses to invent a round-two file until `data/incoming/adaptation_kit/public/metadata.json` says adaptation.

Main form: https://docs.google.com/forms/d/e/1FAIpQLSfv2WV_Fz7NHstRPN2TGi3pvMAFrcQuvs2SkQL1DqpdLebhFg/viewform

Data: https://drive.google.com/file/d/1WXrMzPXHv_ZuwpKvdRrcKYoJaMR5J6VV/view

## Datathon tracks

| Track | Fit | Win chance | Why it is not higher |
|---|---|---|---|
| Poker | 8 | 6 | PitBossEquity `6b2921de93674e8600659540e307df5894b9e259` scores continuing ranges and kept that champion after the public-opponent league. The official container was not built here. The form is a separate step. |
| Dashboard Royale | 8 | 6 | Case file, filters, forecast, and the $1,200 inspection are on https://shreynath.github.io/gilded-ace/ . The guide also asks for a video of at most 2 minutes and a Devpost. Those receipts are not in this repo. |
| Highway | 7 | 5 | The engine fails closed on unknown ids. Tests pass. The portal file set has no receipt here. |
| Databricks | n/a | n/a | Teammate-owned. Not modified. |
| Build-a-Dataset | 1 | 1 | No consented observations collected for a submission. |
| H-E-B | 0 | 0 | No brief in this repo. |
| Rev's Casino | 0 | 0 | Not attempted. |

## MLH prizes

| Prize | Fit | Win chance | Why it is not higher |
|---|---|---|---|
| Gemini API | 7 | 5 | One live `gemini-2.5-flash` reply was kept only after every number was already in the case. The public page does not hold the key. |
| Snowflake, Tiger Data, MongoDB Atlas, Vultr | 4 | 2 | The clients match the documented calls and pass mocked tests. No account was connected, so a judge cannot see a live resource. |
| Solana | 3 | 1 | The code hashes a report and checks a Devnet memo. No transaction was published. |
| GoDaddy Registry | 4 | 2 | `.study` is the campaign TLD. `gildedace.study`, `pitboss.study`, and `evidencefirst.study` were unregistered at RDAP on November 7. Nothing was purchased. |
| DEV Writing | 8 | 4 | `docs/DEV_ARTICLE.md` scores 10/10 on the local template rubric and is not on DEV. |
| SpaceXSI | 3 | 2 | The repo was edited in Cursor. A Grok Bot run is not recorded, and the raffle opt-in is a form the code cannot send. |

## What would move a score

House Edge moves only if round-two data arrives and a refit beats the starter on that round's own validation file. Poker moves when the form has the champion SHA. Royale moves when the video and Devpost exist. The MLH rows move when the named account, domain, post, or chain receipt exists. A local test does not add those.
