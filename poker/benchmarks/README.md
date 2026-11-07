# Public opponent league

Champion under test: `6b2921de93674e8600659540e307df5894b9e259`.

The harness is `tools/public_agent_league.py`. It starts this checkout on port 5008 and one public checkout on port 5009, then runs `judge_engine.py`. Every match is two halves with the seats swapped and the deals matched. No third-party source is copied into this package.

## Inventory

| Opponent | Source | SHA | License | Status |
| --- | --- | --- | --- | --- |
| ShortStackSage | existing clone of Dhanush006/ssd-heads-up-poker; a fresh GitHub lookup could not resolve the repo | `c94d9f42515bbab1af017adf19abe423126c80ca` | no license file | played |
| ShortStack | Utsavdotcom/aura-farmer | `b74f7d37cf04877a7c18886d14655473ef5d7650` | no license file | played |
| ShortDeckShark | shaswat-singh23/datathon-poker | `7700d89b1e7469ef791bc2c3d7b7c1375a539f35` | no license file | played |
| EquityBot-v1 | jane-vo/tamu-datathon26 | `1c30be631a88755a13eeb3daf387450b96331c9c` | no license file | played |
| SDPLO-RangeEV | zeyad-commits/heads_up | `33eb79e16af039227cc1d0c4c6a568aeccc93487` | no license file | process starts, but `sdplo` is missing; scores are a fallback |
| Timecasters | andrewv426/timecasters-pokerbot | `54118d0c191efe5328bb36c7ff246b771e6d0002` | no license file | played |
| MAKK | karammasad/pokerMAKK | `c5b6309dec900ddafb33afebe29708f04d1617bd` | no license file | played |
| OPsAgent | sapyao/heads-up | `0d540fa7518e8eb5a71878e2342af5aa9e3c8b0a` | no license file | starter-sized policy |
| Prunuus | Prunuus/heads-up | `e9ce98dc5749672c1d85fc9c12fcc3e901256969` | no license file | same agent file as Ruler10123 |
| Ruler10123 | Ruler10123/Datathon-2026-Poker-Bot-Challenge-Submission | `6ede29b0804435a6a69f0c54342af1d00b42222c` | no license file | same agent file as Prunuus |

Public code was used only as an opponent. None of it was copied into `agent.py`.

## Stage A, 300 duplicated deals

Seeds `11` and `61`. PitBoss is agent 1. Zero recorded errors.

| Opponent | Seed 11 | Seed 61 |
| --- | --- | --- |
| ShortStackSage | chop, −0.270 | chop, −0.245 |
| ShortStack | chop, +0.028 | chop, −0.417 |
| ShortDeckShark | win, +4.322 | win, +3.095 |
| EquityBot-v1 | chop, +0.643 | chop, −1.503 |
| SDPLO fallback | chop, +1.262 | win, +1.655 |
| Timecasters | chop, +0.770 | win, +1.500 |
| MAKK | chop, +0.737 | loss, −2.217 |
| OPsAgent, Prunuus, Ruler10123 | win, +1.100 | win, +1.040 |

The three starter-sized agents produced the same scores. The SDPLO rows are not a result against that team's intended bot.

## Stage B, 1,000 duplicated deals

Fresh seeds `201` and `307`. Zero errors. Thinking stayed under 2.4 seconds of the 8-second half bank.

| Opponent | Seed 201 | Seed 307 |
| --- | --- | --- |
| ShortStackSage | chop, +0.035 (−0.417 to +0.487) | chop, −0.342 (−0.791 to +0.107) |
| ShortStack | chop, +0.032 (−0.475 to +0.538) | chop, +0.139 (−0.380 to +0.658) |
| MAKK | chop, −0.255 (−1.036 to +0.527) | chop, +0.311 (−0.427 to +1.050) |

The 300-deal loss to MAKK did not repeat at full length. The champion remains level with the strongest public bots and ahead of ShortDeckShark and the starter policies. No challenger was promoted.

## Not claimed

No external Hold'em solver was imported. No CFR search was added, because a new search family was not measured against this panel. Docker was not running, so `tools/check_build.sh` has not passed and this checkout is not marked container-compatible.
