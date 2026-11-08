# House Edge adaptation entry

- Round: adaptation
- Season ID: `5fffdc4d0c700bbf61c3f911`
- Forecast file: uploaded separately as `submission.csv`
- Forecast SHA-256: `27a06bf08cb0b2ea3859ecf30e698e91e83ccd4e4636889a00d66d2e21df8f30`
- Libraries: Python standard library only

## Setup

- Python 3.11+ (tested on Python 3.13)
- Dependencies: none at prediction time
- Hardware: CPU, well under 1 GiB RAM
- Public data path: `/data` on the runner, or the extracted kit `public/` folder locally

`predict.py` loads the frozen trees in `trees.json` and writes test probabilities. It does not read condition labels, validation targets, or the uploaded CSV. Ticks at or after the cutoff are ignored. Main-round data is not used.

The trees were fit once, offline, on this round's training spins. Each training row uses only earlier ticks. There is no random seed at prediction time.

## Recreate the forecast

From this folder:

```sh
python predict.py --data /data --out /output/submission.csv
```

Local check, from the adaptation kit folder:

```sh
python predict.py --data "/absolute/path/to/adaptation/public" --out "/absolute/path/to/submission.csv"
python check_submission.py /absolute/path/to/submission.csv
```

- Required files: `predict.py`, `boost.py`, `trees.json`, `reproduce.json`
- Runtime on this machine: about 1 second

## What the model does

Eighty depth-3 trees score the last payouts at lags 1, 2, 3, 4, 5, and 8, plus the zero rate and average size over the last 8, 16, and 32 ticks. Machine type and signal are included. A missing tick stays unknown. The five scores are turned into probabilities with a softmax.

Public validation score from the kit checker: 10.754 / 20.

| Condition | Loss ratio |
| --- | --- |
| stable | 0.905 |
| short_history | 0.877 |
| drift | 0.792 |
| shared_change | 0.866 |

The half of validation episodes that was not used to choose anything about this file scored 10.672 / 20. The other half scored 10.837 / 20.
