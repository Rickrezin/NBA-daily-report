# QCore independent box-score rating prototype

Status: experimental, offline validated on the November 2, 2026 archive and the
user-supplied Milwaukee November 4 basic/advanced exports. No production wiring.
Start with [the measured validation report](results/report.md).

## What this implements

`model.py` independently computes Oliver-style Q-OffR and Q-DefR from basic player,
team and opponent counts. These experimental names identify our implementation;
they are not a claim of a newly invented statistic or exact BBRef equivalence.
The mathematical reference is [Basketball-Reference's individual-rating method](https://www.basketball-reference.com/about/ratings.html).
Possession estimates and percentage definitions follow its
[glossary](https://www.basketball-reference.com/about/glossary.html).
Some finite-sample conventions remain unresolved; residuals are retained.

BBRef's Dean Oliver ratings allocate estimated individual production and stops.
NBA Advanced on-court ratings measure team efficiency during a player's court
time ([NBA glossary](https://www.nba.com/stats/help/glossary)). They are different
targets. Neither NBA on-court ratings nor BBRef advanced values enter inference.

`infer.py` reads a standard saved ESPN summary without any BBRef files. The
optional capture utility saves ESPN JSON and retrieval provenance. Evaluation
uses BBRef labels only after predictions exist. It does not import or execute
`generate-report.js`, consume QPIX-R, or modify C3/C4, historical inputs, reports,
or dashboards. The dependency direction is basic data -> features -> experimental
ratings; a future authorized QPIX consumer would be downstream, preventing a
QPIX-R feedback loop.

## Replay and routine inference

Python 3.11+; standard library only. Run from repository root:

```sh
python -m unittest discover -s experiments/qcore -p 'test_*.py' -v
python experiments/qcore/evaluate.py
python experiments/qcore/infer.py experiments/qcore/fixtures/espn-401909924.json
```

Evaluation writes only `experiments/qcore/results/`. It is offline and deterministic.
Raw captures, including both original HTML-in-XLS exports, are checked in. Their
original bytes are protected from Git line-ending conversion. Do not open/save
the fixtures in Excel. The existing November 2 archive is read in place.

To explicitly capture another game, without scoring or publishing QPIX:

```sh
python experiments/qcore/fetch_fixtures.py --event 401909924
```

Without `--event`, that utility captures the fixed validation slate. Existing raw
captures are never overwritten. Endpoint failures raise errors; no missing stats
are filled with a fabricated zero. This is a separate experimental entrypoint,
not a scheduled production replacement. The branch CI runs tests, offline replay,
checks result drift and uploads artifacts with read-only repository permissions.

## Feature contract

Only the following finite, nonnegative basic fields are admitted by the model:

| Fields | Unit and source |
|---|---|
| `mp` | Player minutes; team/opponent aggregate player minutes (240 regulation, 265 one OT). ESPN periods determine duration. |
| `pts`, `fg`, `fga`, `fg3`, `fg3a`, `ft`, `fta` | Points and shooting makes/attempts, from ESPN player counts; reconciled to team shooting and final scores. |
| `orb`, `drb`, `ast`, `stl`, `blk`, `pf` | Player basic counts; team sums. PF is required for estimated missed-free-throw stops. |
| `tov` | Player turnovers for individual use; ESPN **totalTurnovers** including team-only turnovers for team/opponent context. Milwaukee's 14 player turnovers plus 1 team turnover must be 15. |

| Derived feature | Definition / role |
|---|---|
| `ts`, `efg` | True shooting and effective FG fractions; denominator-zero diagnostics use zero, not claimed observed shooting percentages. |
| `usage_pct`, `ast_pct`, `orb_pct`, `drb_pct`, `stl_pct`, `blk_pct` | Percent-point diagnostics recomputed from player counts, minutes and both teams. No advanced-provider dependency. |
| `team_possessions` | Two-sided average of estimated possessions; FT weight 0.4 and offensive-rebound adjustment 1.07. Team possessions differ from individual possessions. |
| `qast` | Estimated assisted fraction derived from minutes and team/player assists and makes. Values outside [0,1] are flagged, not silently clipped. |
| `scoring_possessions`, `individual_possessions`, `points_produced` | Allocation of scoring, assist and rebound credit; shooting misses and turnovers contribute to possessions. Q-OffR is 100 times produced points divided by positive individual possessions. |
| `stops`, `stop_pct`, `team_defr` | Estimated individual defensive stops and team context. Q-DefR applies the published 0.2 individual adjustment to team defense. |

TS and usage diagnostics use FT weight 0.44; possession/scoring algebra uses 0.4.
Both constants are intentional. No plus/minus, BPM, box-score advanced rating,
QPIX score or referee adjustment is a model input. All intermediate features are
saved so a residual can be traced through the actual computation.

Zero attempts yield zero contribution for the corresponding algebraic term.
Non-positive individual possessions yield null Q-OffR with a flag; this includes
zero-usage rows where BBRef displays 0, and pathological negative estimates.
No arbitrary league-average fallback or rating clipping is applied. Active
ESPN rows rounded to 0 minutes remain participants with null predictions. DNPs
are explicitly excluded; all other participants, including <=8 minutes, remain.
Short-minute flags indicate precision risk, not a confidence interval. The exact
minute diagnostic uses BBRef data only to isolate that risk and is not advertised
as an ESPN-only solution. Negative/non-finite counts, missing fields, duplicate
identities, nonfinal games and incomplete team reconciliation fail explicitly.

## Evaluation design and provenance

The 15 November 2 games are sorted by SHA-256 of `qcore-v1:` plus game ID; first
five are test, remaining ten train. All teammates and opponents stay together.
The 334 ESPN IDs must match the archive exactly. Every basic counting-stat field
is compared; all agree, while 329 minute values differ. The Milwaukee exports
join by BBRef ID; a unique normalized name plus team plus exact counting-stat
line establishes the ESPN ID crosswalk saved in the manifest. The 12 active
Milwaukee rows are external test; three DNPs are recorded separately. Boston
opponent counts come from ESPN because no Boston BBRef export was supplied.

The primary analytical model has no learned coefficients. A separate ordinary
least-squares affine comparator is fitted for each target on ESPN training rows
only, excluding null predictions. It loses to the raw model on both held-out
MAEs and is not used by inference. Test-label mutation tests verify that fitting
cannot consume test labels. The small two-date sample is exploratory; repeated
inspection of these fixtures does not establish prospective generalization.

`results/manifest.json` records the reviewed repository base, source-branch head,
exact split, fit coefficients, raw-source/code digests and identity crosswalk.
The existing historical archive hash uses canonical LF line endings to avoid
platform-dependent Git checkout differences; raw captures use byte-exact hashes.
Raw ESPN files have URL, retrieval UTC time and byte digest sidecars. Source
files are immutable captures; results are reproducible derivative artifacts.
`rows.json` contains every reference, prediction, intermediate, flag and signed
residual (prediction minus BBRef). `metrics.json` reports coverage, bias, MAE,
RMSE, maximum error, within-one counts and minute-weighted MAE, separately for
<=8 and >8 minutes. `outliers.json` lists largest held-out/external residuals;
the report additionally identifies training outliers explicitly.

## Adoption gate

This implements automated experimental calculations; it does **not** eliminate
the need for verified production ratings yet. Resolve minute precision,
out-of-range qAST and zero-possession conventions, validate additional independent
dates and evaluate the intended C3/C4 scale before requesting explicit adoption
approval. No daily export is required to run this prototype. No existing result
is rewritten. C6 source availability remains a separate issue.
