# Claims and evidence

AI disclosure: Cursor and the model in this session wrote code and prose. DuckDB computed every dollar. Gemini was checked with a live JSON call and was not used to produce these figures. Ollama cloud returned HTTP 401, so it did not write any number.

| Claim | Query | Result | Alternative | Limit |
|---|---|---|---|---|
| Rank 1 is the lowest value | `tests/test_royale_rank.py` and `RANK() OVER (ORDER BY value)` | Controlled rows put the smallest win at rank 1 | A chart legend could reverse this | The test covers the SQL direction, not every chart in other tools |
| M-1026 is not a bottom-10 problem | `domains/royale/report.py` on `prepared_daily_view` | Raw rank 42, residual-per-hour rank 265 of 310, residual +$8,062 | Quiet zone or short hours | Carded play is excluded |
| Only M-1158 in the raw bottom 10 has a Holm-significant negative residual | Daily residual mean, normal approximation, Holm across machines with 20 or more positive-coin days | Residual −$36,165, rank 2 per hour, adjusted p 0.0026 | High volatility, not a broken paytable | Days are treated as independent |
| Weekday forecast beats a constant mean | `property_day.coin_in_usd`, train before 2025-05-01 | MAE $68,698.55 vs $218,258.10 | A holiday model could win on a few days | No tourism series was an input |
| Do not buy the technician shift | Modeled lost theo $90,313.38; 10% is $9,031.34 | Below the $11,520 catalog price | 30% capture would exceed it | Lost theo assumes the observed rate would have continued |
| Fund one inspection | `action_catalog` A-INSPECT, $1,200 | One unit, target M-1158, $98,800 unspent | A $22,000 purchase if July confirms the gap | Inspection does not recover money by itself |

Empty-location rows in `prepared_daily_view`: 1,018, counted in DuckDB.
