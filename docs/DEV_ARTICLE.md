---
title: Evidence Before the Bet: Building Gilded Ace at TAMU Datathon
published: false
tags: mlhacks, python, data, hackathon
---

This is a submission for the MLH x DEV Writing Challenge.

#mlhacks

## What I Built

I built Pit Boss, a set of auditable tools for a casino-floor simulation at TAMU Datathon. The piece I want other developers to copy is Gilded Ace, a floor review that refuses to treat the lowest-revenue slot machine as the worst machine.

The manager in the case wants to replace the ten machines with the lowest house win from January through June 2025. Raw win is a bad sort. A quiet machine, a short schedule, and a run of bad luck can all land on that list. Gilded Ace recomputes the floor from the case file. Rank 1 means the lowest value, not the best machine. M-1026 looks weak at raw rank 42 of 310 and is rank 265 on residual per available hour. It is not a replacement candidate.

Of the actual bottom ten, one machine fails a luck screen. M-1158 won $15,796.25 against theoretical win of $51,961.00. The residual is $-36,164.75. Its residual-per-hour rank is 2, and its Holm-adjusted p-value is 0.0026. The other nine raw-bottom machines are not significant after Holm correction across the floor. That test is a normal approximation to daily residuals. It is not proof of a hardware fault.

The funded action is one inspection at $1,200. The budget is $100,000, so $98,800 stays unspent. A technician shift costs $11,520. Ten percent of modeled lost theoretical win is $9,031.34, which is below that shift, so the shift is not bought. Thirty and fifty percent captures would clear it. Those cases are reported and not spent. The page says the 4,000-draw stress, seed 1158, is hypothetical. Mean technician net in that stress is $2,049.25, and it is not a measured effect.

The same repository holds the other datathon tracks, each in its own folder. House Edge is a probability ladder over a fixed query file. Its local validation score is 32.782 out of 60, against a pooled-recent baseline of 30.826. The poker entry is a short-deck five-card Omaha agent, PitBossEquity, published at commit 6b2921de93674e8600659540e307df5894b9e259. A later commit records a league against public opponents and keeps that measured champion instead of promoting an untested challenger. Highway answers shipment questions from a local handbook and refuses an id that is not in the file.

### Key features

- A static case file, `apps/web/public/ace_case.json`, is the source of every number on the floor page.
- Filters for month, zone, and bank recompute from that file. June can select a different machine than the six-month table.
- A recovery slider shows the technician decision at 10, 30, and 50 percent capture, including the zero-lift downside.
- An investigation API answers a question only when the machine id is in the case. Unknown ids and prompt-injection phrases get a refusal, not a guess.
- Optional sponsor adapters can explain a verified answer. They cannot replace it.

## Demo

The floor page is the demo. Locally it is `python apps/api/server.py`, then http://127.0.0.1:8765/ . The public static copy is https://shreynath.github.io/gilded-ace/ . The sponsor evidence page is http://127.0.0.1:8765/sponsors.html and only works on that private API. GitHub Pages does not hold an API key.

1. Open the floor page and read M-1158 beside the raw bottom ten.
2. Move the recovery slider. At 10 percent the technician net is negative.
3. Ask why M-1158 was flagged. The answer quotes the inspection cost of $1,200 and the case residual.
4. Ask for a machine that is not in the tables. The API refuses.

## How It Works

The browser loads one JSON document. It does not call a model and it does not hold a key. Rank, forecast error, and the spend plan were computed ahead of time by `domains/royale/analyze.py` and checked into the case file.

Demand uses a chronological holdout. January through April train a weekday mean and a constant mean. May and June are the holdout. Weekday MAE is $68,698.55. Constant MAE is $218,258.10. Staff from the weekday pattern. The forecast does not pick a machine.

Carded play is a different total from the meters. 4,382 of 113,890 carded players produce half of carded coin-in. Comp cost per carded coin-in moves from about 0.105 percent in January to about 0.124 percent in June. That drift is too small to buy a floor-wide comp change. Player comp cost and property comp cost are different grains and are not added together.

The investigation route is fail-closed. `domains/royale/investigate.py` matches a short question to a known machine, month, or the published spend plan. If the question names M-9999, or asks for an API key, the response has `ok: false` and no newly calculated figure. The metrics that do go out were already in the case file.

When a model is allowed to speak, it speaks second. `integrations/gemini/grounded.py` sends the scored claims, then drops the reply if any number in it is absent from those claims. One live `gemini-2.5-flash` reply was kept on that rule. It restates the M-1158 residual and the $1,200 inspection. The saved reply is `docs/gemini_live_m1158.json`. The public page still does not call Gemini, because a key in the browser would be a leaked key.

The sponsor bridge uses the same idea for an optional second provider. The deterministic answer is built first. The model must return JSON with a narrative and citations drawn from the evidence ids. A citation that is not in that list is rejected. After machine ids such as M-1158 are removed, every remaining number in the narrative has to appear in the verified payload. A story that says the inspection returns some other dollar amount is discarded. The code answer is what the caller still sees. Paid inference on `/api/investigate` now requires an `X-Sponsor-Token` of at least 24 characters. The token is an environment variable. It is not in the static page.

Tiger Data, Snowflake Cortex, MongoDB Atlas, Vultr, and Solana each have an adapter with the same posture. Writes require an explicit confirmation flag. The Solana helper hashes a report and, given a signature, checks a Devnet memo for that exact digest. It does not sign a transaction. The Vultr helper lists instances and can reject a deploy plan that opens SSH to the world. It does not create a server. The GoDaddy helper checks syntax, whether the TLD is on the GoDaddy Registry list used by this project, public DNS, and HTTPS. `.study` is the campaign TLD, because the MLH link is `https://www.tech.study/`. The checker never registers a name. `prize_ready` stays false.

## Technologies Used

- Frontend: one HTML page and the case JSON. No framework.
- Backend: the Python standard library, `http.server`, bound to loopback unless a public bind is explicitly allowed.
- Analytics: DuckDB for the Royale preparation, then a checked-in case file so the page does not need a warehouse at view time.
- Tests: pytest for the sponsor adapters, unittest for the static-path guards.
- Tools: Cursor for the editing session, git for the commits, and a public GitHub Pages copy of the static floor review.

## Partner Technologies

I used the Gemini API as a narrator for a verified case, not as a calculator. The working call is the grounded M-1158 reply described above. The model is useful when it is willing to rephrase and useless when it invents a figure. The guard is the product.

Snowflake, Tiger Data, MongoDB Atlas, Vultr, Solana, and GoDaddy Registry are implemented as opt-in adapters and exercised with fake responses in `tests/test_sponsors.py` and `tests/test_sponsors_stress.py`. They are not live connections. A green test is not a sponsor account. I am not claiming those prizes from mocked HTTP.

A GoDaddy Registry domain has not been registered from this repository. This article is not published until it is posted on DEV. The cloud adapters above are not live connections.

## Hackathon Experience

The hard part was not picking a model. The hard part was keeping a number from moving after I had already explained it.

Raw rank and residual rank tell different stories, and both have to stay on the page. M-1288 has the worst residual per available hour on the published list and a Holm p-value of 1. Spending the replacement budget there would have been a story about a sort key, not about a leak. I left the funded action on M-1158.

The poker track had a similar trap. A newer agent can look smarter in a handful of hands and still lose to the measured champion over the league. The later commit records the public opponents and keeps the champion. I would rather submit the bot that was scored than the bot I most recently edited.

House Edge had the same discipline. The CSV and the entry ZIP have fixed SHA-256 hashes in the release notes. I did not replace the model to chase a story.

The largest limit is submission, not code. Google Form sign-in, a Devpost video, a registrar checkout, and a DEV account are human steps. This draft does not pretend they are done.

## What I Learned

- A leaderboard of raw totals is an exposure metric until you divide by hours and test the residual.
- Multiple comparisons are part of the result. Looking at 310 machines and celebrating one small p-value is how a floor gets a false alarm.
- Holdout the forecast in time. A weekday mean that only beats a constant mean on the months it trained on is not a staffing plan.
- Put the model behind the evidence. If the narrative cannot cite an id from the payload, or it introduces a number the payload does not contain, drop the narrative and keep the code.
- Do not let a sponsor adapter become a second source of truth. Configuration is not connectivity, and a mock is not a receipt.
- Keep the measured champion. A public league is there to stop me from promoting an untested poker change.
- Say what is not done. A draft, a DNS check, and a local score are useful. They are not a prize submission.

## What's Next

Paste this file into DEV during the current monthly window, with the `mlhacks` tag, after a last read for anything the case file does not support. Register a `.study` name only with an explicit purchase, then point it at a host that serves the floor page over HTTPS. Run the live provider smoke tests only with private credentials and only for accounts we are willing to be billed for. Submit the House Edge files, the poker URL and SHA, and the Royale Devpost with a two-minute walkthrough of the slider and the M-1158 refusal.

Until those receipts exist, the project is a tested local system with one kept Gemini call and a public static floor page. That is the claim I can defend.
