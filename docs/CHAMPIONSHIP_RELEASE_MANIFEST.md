# Championship release manifest

Saturday, November 7, 2026, America/Chicago.

## Repositories

| Repo | Role | SHA | Pushed |
|---|---|---|---|
| https://github.com/shreynath/TamuDatathonF26 | Monorepo | `4ad6fcc766de534a2e16cc872c2f1abce08f8071` | yes, `main` |
| https://github.com/shreynath/PitBossEquity | Tournament agent | `6b2921de93674e8600659540e307df5894b9e259` | yes, `main` |
| https://github.com/shreynath/gilded-ace | Public dashboard | `9cf601b15a283dbdce9bb29c06e5db4ac2e59db1` | not updated this pass |

PitBossEquity rollback: `316bcf1acb5e6cf254ba1acb6e15906ca913f80d`.

`evaluator.py` and `game.py` in PitBossEquity match the monorepo copies. `numpy` is declared without a version so the official base image can supply it.

## House Edge artifacts

| File | SHA-256 |
|---|---|
| `submissions/house_edge/main/artifacts/submission.csv` | `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1` |
| `submissions/house_edge/main/artifacts/entry.zip` | `bbb18384cb9766fe27d5a3facea298e9f591510653a0a1246765200ab463d986` |
| `/tmp/he-entry.zip` | same ZIP hash |

CSV: 1,536 data rows. Header: `query_id,p_0,p_1,p_2,p_5,p_20`. Validator status from the earlier clean rebuild remains `VALID FORMAT`. No new model was built.

## Submission receipts

| Entry | Status |
|---|---|
| House Edge Google Form | No receipt. Sign-in blocked the upload. |
| Poker Google Form | No receipt. The SHA to submit is `6b2921de93674e8600659540e307df5894b9e259`. |
| Royale Devpost | No receipt. |
| Highway portal | No receipt. |
| Docker poker image | Not built. Socket missing. |

## Public site

https://shreynath.github.io/gilded-ace/ is still the earlier Pages build. This pass did not publish a new dashboard.
