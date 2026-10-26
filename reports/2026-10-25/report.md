# QPIX™ NBA Daily Performance Index — October 25, 2026 (Eastern)

**Independent, verified-basic-stat run; incomplete advanced-stat coverage. Not the full-measurement official index.** Scored directly through the checked-in QCore Labs `generate-report.js` C1–C12, QPIX-R, QPIX-SFA functions; code blob SHA `ef7b46da7c5dde2835424750119c483cdb705a6f`, phase `regular`. Date window October 25, 2026 ET; 7 final games, 157 box-score participant rows. Games validated by independent reported final scores. No Wolfram or manually reconstructed scoring formulas.

## All FINAL games

- **LAL 132 – UTA 123** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_LAL@UTA/)
- **IND 136 – BKN 109** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_IND@BKN/)
- **ORL 111 – NYK 102** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_ORL@NY/)
- **TOR 94 – MIN 117** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_TOR@MIN/)
- **LAC 101 – OKC 108** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_LAC@OKC/)
- **DET 106 – PHI 93** — [box score](https://www.cbssports.com/nba/gametracker/boxscore/NBA_20261025_DET@PHI/)
- **MEM 123 – SAC 112** — [box score](https://fantasydata.com/nba/boxscore/23995-memphis-grizzlies-vs-sacramento-kings-oct-25-2026)

## Raw QPIX Top 20 (partial-coverage scores)

| # | Player | Team | PTS | REB | AST | Raw QPIX | QPIX-R |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Luka Doncic | LAL | 52 | 8 | 10 | 117.2 | 117.2 |
| 2 | Tyrese Haliburton | IND | 24 | 4 | 10 | 94.1 | 92.1 |
| 3 | Cade Cunningham | DET | 26 | 8 | 8 | 85.9 | 82.2 |
| 4 | Ty Jerome | MEM | 31 | 4 | 6 | 81.2 | 70.9 |
| 5 | Shai Gilgeous-Alexander | OKC | 34 | 6 | 5 | 79.8 | 79.8 |
| 6 | Kris Dunn | LAC | 15 | 4 | 6 | 79.1 | 79.1 |
| 7 | Franz Wagner | ORL | 23 | 13 | 9 | 74.2 | 74.2 |
| 8 | Alex Caruso | OKC | 12 | 7 | 6 | 72.4 | 72.4 |
| 9 | Austin Reaves | LAL | 29 | 1 | 4 | 70.3 | 61.8 |
| 10 | Anthony Black | ORL | 18 | 3 | 5 | 69.7 | 69.7 |
| 11 | Tyrese Maxey | PHI | 29 | 5 | 4 | 69.7 | 69.7 |
| 12 | Keyonte George | UTA | 24 | 9 | 10 | 68.3 | 66.0 |
| 13 | LaMelo Ball | MIN | 15 | 1 | 8 | 65.7 | 67.6 |
| 14 | Pascal Siakam | IND | 21 | 7 | 6 | 64.0 | 64.0 |
| 15 | Zach LaVine | SAC | 37 | 2 | 5 | 63.7 | 58.8 |
| 16 | Jaylen Wells | MEM | 16 | 5 | 3 | 63.1 | 63.1 |
| 17 | Karl-Anthony Towns | NYK | 22 | 14 | 4 | 62.2 | 60.4 |
| 18 | Keon Ellis | BKN | 9 | 1 | 3 | 61.0 | 62.9 |
| 19 | Jay Huff | IND | 14 | 2 | 3 | 60.5 | 62.8 |
| 20 | Isaiah Stewart | MEM | 13 | 5 | 2 | 58.2 | 58.2 |

## Scope and integrity

- All 157 **participants in accessible basic game box scores** included (not DNPs), including the 0:01 substitution for Sacramento. In some cases CBS supplies minutes rounded to whole numbers; Memphis–Sacramento minutes come from FantasyData second precision.
- **C3 unavailable**: player-specific ORtg and DRtg from a definition-compatible, verified advanced feed could not be retrieved. Code properly suppresses C3 rather than using synthetic 110/110 values. Any C4 defensive-rating anchor bonus is also unavailable.
- **C6 unavailable**: individual second-chance points, fast-break points and paint points could not be verified. Inputs explicitly `null`; the unmodified engine treats missing values as zero, but the reported categories are marked `null`, meaning *unavailable*, not actual zero.
- **C11 partial**: outcome/plus-minus/scoring component computed, but the fast-break contribution unavailable. Other C1,C2,C4 (stocks and defensive rebounds),C5,C7,C8,C9,C10,C12 use observed box-score data. Raw scores are **lower-information partial scores**, not comparable to fully populated prior-date scores.
- **QPIX-R** evaluated by exact existing October 26 checked-in logic: activation at **±1.5 FTA** against rolling 20 (not supplied), named 2025–26 seasonal fallback, otherwise position. The discussed 4–5-FTA tolerance has **not** been implemented in the authorized engine. Per-player position is normalized to G/F/C for fallback, occasionally inferred when source only abbreviated player name; affects QPIX-R, not raw.
- **QPIX-SFA** flags former-team relationships per authorized configuration, but **positive companion-adjustment qualification cannot be determined without C3 inputs**. The attached per-player records retain the engine's raw QPIX-SFA fields and clearly mark qualification `null` when applicable; do not interpret a reported 0 adjustment as proven lack of a former-team effect.
- CBS score totals and player plus/minus team sums match all 14 verified teams. All rows verified against `PTS = 2×FGM + 3PM + FTM`. Some source player names are abbreviated and intentionally preserved to avoid fabricated identity matches.
- The existing `scripts/fetch_nba_data.py` contains 110/110 placeholder ratings, zeroed plus-minus, and zeroed offensive context, and does not provide a validated full-data QPIX run. This report **does not** feed those placeholder values into scoring or overwrite the live dashboard.

## Individual player records

See `players.json` (all source inputs, field-level missingness, category scores and engine outputs) and `players.csv` (one row per participating player). Each player's `source` points to the game box score. JSON `category_scores.C3` and `.C6` are `null` when absent, not synthetic zero.
