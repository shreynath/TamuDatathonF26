# Pit Boss

Evidence-to-decision project for TAMU Datathon. Each competition artifact stays in its own folder.

House Edge probabilities are in `submissions/house_edge/main`. They were checked locally and were not uploaded.

The Gilded Ace case is `apps/web/public/ace_case.json`, computed by `python3 domains/royale/analyze.py`.

Trip observations for `/routes` are collected through `python3 apps/api/server.py` and stored in `data/routes/observations.csv`. The street graph is supplementary.

Highway actions come from `domains/highway/engine.py` and the local handbook in `data/highway`.

API keys belong in `.env`, which is gitignored. `.env.example` has empty placeholders.
