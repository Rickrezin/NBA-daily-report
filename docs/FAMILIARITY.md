# QPIX — Opponent and arena familiarity

This addition produces `dashboard/familiarity.json` on each successful daily run. It does **not** alter the C1–C13 engine, RAW QPIX, QPIX-R, or ranking order.

## Data stores

- `data/opponent_familiarity.json` contains verified, keyed player-versus-opponent history.
- `data/arena_familiarity.json` contains verified arena identifiers and player-versus-arena history.
- `dashboard/familiarity.json` is an export of current-game player scores joined to those histories, included in the GitHub Pages artifact.

### Sample opponent entry (illustrative only — do not treat as real NBA data)

```json
{"player_opponents":{"PLAYER_ID":{"BOS":{"games":3,"avg_qpix":42.5,"last_meeting":"2026-10-20","source":"verified-game-ledger"}}}}
```

### Sample arena entry (illustrative only — do not treat as real NBA data)

```json
{"arenas":{"VERIFIED_ARENA_ID":{"name":"Verified venue name","team":"BOS","source":"official venue schedule"}},"player_arenas":{"PLAYER_ID":{"VERIFIED_ARENA_ID":{"games":2,"avg_qpix":41.2,"source":"verified-game-ledger"}}}}
```

Only write validated entries. The current NBA CDN text importer does **not** provide player IDs, official game IDs, or confirmed arena IDs, and its home/away derivation is not independently verified. Until those identifiers are added, arena familiarity is intentionally `null`. Name-based player matching is a provisional fallback, not safe for archival joins.

## Roll-forward requirements

A season-long accumulation job must ingest final, deduplicated games with genuine game IDs, player IDs, dates, official home/away teams, arena IDs, and historical QPIX outputs; then update both source JSON stores on the default branch. Do not increment aggregates directly from a daily workflow rerun, or preseason and regular-season overlaps will be double-counted. Preserve preseason versus regular-season splits and provide provenance for every aggregate. `familiarity.json` itself is a daily *snapshot*, not persistent history.

## DJ / sound reports

If venue DJ or sound-environment reporting is intended, collect it separately as opt-in, source-backed observations (arena ID, game ID, measured/observed attributes, provenance). Do not infer music, decibels, or crowd pressure from venue names and do not apply an unvalidated adjustment to QPIX.
