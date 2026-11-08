# Pit Boss

One repository, separate entries. Open the row for the competition you want. Routes, H-E-B, Rev's Casino, and Build-a-Dataset are not entries.

| Competition | Open this | What a judge gets | Status |
|---|---|---|---|
| House Edge, main | `submissions/house_edge/main` | Forecast CSV and code ZIP in `artifacts/` | You uploaded this at 8 PM Saturday. Local validation is 31.010 / 60. |
| House Edge, round two | `submissions/house_edge/adaptation` | A new CSV and ZIP once the adaptation kit is on disk | The Drive file checked at 10:11 AM Central was still the main kit. |
| Poker | https://github.com/shreynath/PitBossEquity | Public repo plus commit `6b2921de93674e8600659540e307df5894b9e259` | Champion is unchanged. Form: https://forms.gle/Jx9RWE5VgR8dbbcj9 |
| Dashboard Royale | `apps/web/public/index.html` and `docs/royale/WRITEUP.md` | Floor page and the case file `apps/web/public/ace_case.json` | Pages: https://shreynath.github.io/gilded-ace/ |
| Highway | `domains/highway` and `domains/highway/design_card.md` | Fail-closed action log from `data/highway` | Local tests pass. Portal receipt is not in this repo. |
| Databricks | `infra/databricks` | Teammate-owned. This tree does not change it. | Not this entry. |
| Gemini | `integrations/gemini` and `docs/gemini_live_m1158.json` | One kept live reply. Numbers had to already be in the case. | Public page does not call Gemini. |
| Other MLH prizes | `sponsor_hub/` and `docs/COMPETITIONS.md` | Adapters and checklists | Not live accounts, not a registered domain, not a published DEV post. |

Ratings, deadlines, and the House Edge point scale are in `docs/COMPETITIONS.md`.

Run the local suite from this folder:

```sh
python3 -m pytest -q
```

Sponsor checks, which do not register a domain or publish the article:

```sh
python3 -m sponsor_hub.cli dev
python3 -m sponsor_hub.cli domain --value gildedace.study
python3 apps/api/server.py
```

The evidence page is http://127.0.0.1:8765/sponsors.html . Secrets stay in `.env`.
