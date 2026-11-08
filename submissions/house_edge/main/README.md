# House Edge entry

`predict.py` loads `artifacts/model.json` and the public test split. It uses the Python standard library.

The forecast is the previous pooled model mixed with this machine's own history. A tick counts only when its payout categories at lags 1, 2, 3, and 5 match the categories just before the cutoff. Recent matches count more (half-life 32). That piece has weight 0.75. The pooled model keeps weight 0.25. Ticks at or after the cutoff are ignored, including other machines in the episode.

Local validation score from the kit checker: 32.782 / 60.

| Condition | Loss ratio |
| --- | --- |
| stable | 0.759 |
| short_history | 0.877 |
| drift | 0.899 |
| shared_change | 0.787 |

The kit scores main out of 60. The hidden test file is not in the kit. The Saturday 8 PM upload scored 31.010 / 60 on this same validation split (CSV SHA-256 `4c8712cdb0c99a5ddc377fc7ab10b6dc51c44908a81d5d8c0b08239f38b60aa1`). Replace that upload with `artifacts/submission.csv` if the form still accepts it.
