# House Edge

Authority: the unzipped kit in `data/incoming/house_edge_kit`, which is gitignored, plus the participant guide pasted during planning.

The kit metadata for this file says `max_points` 60 and `round` main. Confirm the portal before upload.

Predict with:

```
python3 submissions/house_edge/main/predict.py --data <public> --out <submission.csv>
```

The command reads `test/queries.csv` when `--data` is the public folder.
