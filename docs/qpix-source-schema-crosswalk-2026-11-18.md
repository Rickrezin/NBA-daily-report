# QPIX Source Identity & Metric Crosswalk — 2026-11-18

**Status:** Verified source structures and example responses. **Not a scoring-engine change.**

## Grounding

- ESPN original `games/<ESPN_EVENT_ID>/summary.json` and `plays.json`, archived by QPIX ESPN raw workflow for 2026-11-18; source fields inspected directly.
- PBPStats 2026-27 `GET /get-games/nba?Season=2026-27&SeasonType=Regular+Season` returned HTTP 200; 12 games/date confirmed. `GET /get-game-stats?GameId=0022600267&Type=Player` returned HTTP 200, sample player record confirmed.
- Basketball-Reference `/boxscores/202611180DAL.html` returned HTTP 200 and 2 named advanced tables `box-GSW-game-advanced` / `box-DAL-game-advanced`.
- Successful GitHub workflows: [PBPStats contract probe](https://github.com/Rickrezin/NBA-daily-report/actions/runs/44556979275), [PBPStats player game](https://github.com/Rickrezin/NBA-daily-report/actions/runs/44557129843), [BRef advanced](https://github.com/Rickrezin/NBA-daily-report/actions/runs/44557395573).

## Entity key and game mapping

**NEVER** treat ESPN event ID and NBA GameId as interchangeable. Join on `date_et + home_team + away_team + final score`; validate unique match and retain both values.

| ESPN event ID | NBA GameId | Away | Home | Final away-home |
|---|---|---|---|---|
| 401910007 | 0022600258 | MEM | CLE | 124–121 |
| 401910008 | 0022600259 | HOU | IND | 119–104 |
| 401910009 | 0022600260 | MIL | MIA | 130–137 |
| 401910010 | 0022600261 | PHI | ORL | 121–116 |
| 401910011 | 0022600262 | CHI | BKN | 137–107 |
| 401910012 | 0022600263 | WAS | TOR | 103–99 |
| 401910013 | 0022600264 | DET | NOP | 122–109 |
| 401910014 | 0022600265 | ATL | OKC | 117–112 |
| 401910015 | 0022600266 | BOS | DEN | 101–105 |
| 401910016 | 0022600267 | GSW | DAL | 94–116 |
| 401910017 | 0022600268 | UTA | LAL | 109–97 |
| 401910018 | 0022600269 | PHX | SAC | 128–107 |

### Player identity

- **ESPN:** `boxscore.players[].statistics[].athletes[].athlete.id` — ESPN athlete ID; `stats[]` positional strings, interpreted using the sibling `keys[]`. ESPN team identity must be included.
- **PBPStats:** `stats[]` record `EntityId` — NBA player ID; `Name`, `ShortName`; NBA game ID from request. NBA and ESPN player IDs are different namespaces.
- **Basketball-Reference:** team-specific advanced HTML table `id=box-<TEAM>-game-advanced`; rows have `data-stat` columns; BRef player profile identifiers must be preserved when present. Join by date, team and normalized player identity with manual disambiguation on collisions, **not name alone**.
- Log ID mapping provenance and exact matched box-score statistics. Reject collisions, traded-player ambiguities, and unpaired records.

## Provider shapes

### ESPN original summary JSON

- Event: `header.id`, `header.competitions`, `plays[]`.
- Basic player box: `boxscore.players[].statistics[]` has `keys[]`, `labels[]`, `athletes[]`. Each athlete has `athlete.id`, `starter`, `stats[]`; use `keys` rather than hard-coded array offsets.
- Example standard keys: `minutes`, `points`, `fieldGoalsMade-fieldGoalsAttempted`, `threePointFieldGoalsMade-threePointFieldGoalsAttempted`, `freeThrowsMade-freeThrowsAttempted`, `rebounds`, `assists`, `turnovers`, `steals`, `blocks`, `offensiveRebounds`, `defensiveRebounds`, `fouls`, `plusMinus`.
- Team statistics: `boxscore.teams[].statistics[]` entries `name`, `displayValue` including `fastBreakPoints` and `pointsInPaint`. Team totals are **not** individual observations.
- Play: `plays[]` items have `id`, `sequenceNumber`, `type`, `text`, `period.number`, `clock.displayValue`, `awayScore`, `homeScore`, `scoringPlay`, `scoreValue`, `participants[].athlete.id`, `team.id`, `wallclock`, `coordinate`, `pointsAttempted`.
- `clock.displayValue` is game clock precision dependent; `wallclock` is not a substitute for exact game-clock elapsed duration.

### PBPStats hosted API

- OpenAPI `https://api.pbpstats.com/openapi.json`; **case-sensitive** query parameters `Season`, `SeasonType`, `GameId`, `Type`, `EntityType`, `EntityId`.
- Game lookup `/get-games/nba?Season=2026-27&SeasonType=Regular+Season` → `results[]` with `GameId`, `Date`, `HomeTeamAbbreviation`, `AwayTeamAbbreviation`, `HomePoints`, `AwayPoints`, `HomeTeamId`, `AwayTeamId`, `HomePossessions`, `AwayPossessions`.
- Player game `/get-game-stats?GameId=0022600267&Type=Player` → `stats[]`, `team_results`, home/away metadata, season, date.
- Confirmed player record named fields: `EntityId`, `Name`, `Minutes` (string `MM:SS`), `OffPoss`, `DefPoss`, `Points`, `SecondChancePoints`, `SecondChanceFtPoints` (schema), `SecondChanceOffPoss`, `LiveBallTurnovers` / `DeadBallTurnovers` (schema), `Usage`.
- PBPStats `SecondChancePoints` is a **PBPStats-calculated statistic**, not automatically an official NBA-scored total. Retain provider label and definition. Some absent keys in individual records may be zero-omissions; **do not silently convert missing fields to zero without checking the documented response semantics**.

### Basketball-Reference

- HTML pages, e.g. `/boxscores/202611180DAL.html`. The game date + **home team abbreviation** selects the page.
- Tables `box-<TEAM>-game-advanced`, each player row with cell `data-stat` keys.
- Confirmed named columns: `off_rtg`, `def_rtg`, `ts_pct`, `efg_pct`, `orb_pct`, `drb_pct`, `trb_pct`, `ast_pct`, `stl_pct`, `blk_pct`, `tov_pct`, `usg_pct`, `bpm`, `mp`, `player`.
- Individual BRef ORtg/DRtg methodology is **not** NBA on-court rating or PBPStats lineup `OffPoss`/`DefPoss`. Never substitute without explicit methodology review.
- Some cells may be blank/NA, and table can contain totals or DNP rows; exclude nonplayers and preserve source missingness.

## Canonical metric crosswalk

| Canonical QPIX input | Preferred confirmed source path | Data type | Quality / caveat |
|---|---|---|---|
| `points` and basic box | ESPN `athletes[].stats[]` keyed by sibling `keys[]` | integer; minutes float | independently reconcile points/FGA/FTA/reb/assists/TO |
| `offensive_rating_bref` | BRef advanced `data-stat=off_rtg` | numeric | provider-observed only after matching exact player and date |
| `defensive_rating_bref` | BRef advanced `data-stat=def_rtg` | numeric | BRef individual methodology; no on-court substitution |
| `second_chance_points` | PBPStats player `SecondChancePoints` | integer | **PBPStats-derived, verify against independent category source if possible** |
| `fast_break_points` | no player-level field confirmed among these sources | nullable integer | ESPN team `fastBreakPoints` is verification target only; classifier experimental |
| `points_in_paint` | no player-level field confirmed among these sources | nullable integer | ESPN team `pointsInPaint` is verification target only |
| `live_ball_turnovers` | PBPStats `LiveBallTurnovers` | integer | provider-calculated; reconcile |
| `dead_ball_turnovers` | PBPStats `DeadBallTurnovers` | integer | provider-calculated; reconcile |
| `possession_start_time` | PBPStats shot / possession datasets | provider field | not equivalent to ESPN `wallclock` |

## Data quality rules

1. Store original unaltered response and timestamp/source URL; capture source SHA256.
2. Join games by ET date + matching team pairing and final scores. Join players by verified player identity; keep `espn_athlete_id`, `nba_player_id`, `bref_player_id` separately.
3. Compare team points, player minutes/shooting/stat lines and count; raise explicit unmatched/collision report rather than silently coerce.
4. Preserve source **name and methodology** for individual ORtg/DRtg. Use only intended compatible source for official C3.
5. Preserve `value:null` for missing/unverified C6/C11 fields and explicit confidence flags; never pretend `0` is an observed total.
6. PBPStats may zero-suppress individual nonstandard keys. Establish this empirically before assuming missing = 0.
7. Do **not** run or modify `generate-report.js` until independent source coverage and quality gates are satisfied.
