# QPIX C3/C4/C6 source access — verification notes (2026-11-05)

## Verified engine fields
Read from `generate-report.js` on production `main`:
- C3: `offensive_rating`, `defensive_rating`. Individual Basketball-Reference/Dean Oliver methodology. NBA Stats `offensiveRating` and `defensiveRating` describe **on-court** player rates and may not be silently substituted.
- C4: `steals`, `blocks`, `defensive_rebounds`, `minutes` (ESPN available), **and** `defensive_rating` for the elite-anchor bonus.
- C6: `points_in_paint`, `fast_break_points`, `second_chance_points`. C11 also uses fast-break data.

## NBA API schema
- `BoxScoreAdvancedV3`: `boxScoreAdvanced.homeTeam.players[].statistics.offensiveRating` and `defensiveRating`. Useful as a separate labeled NBA-on-court audit, **not** C3 replacement.
- `BoxScoreMiscV3`: `boxScoreMisc.homeTeam.players[].statistics.pointsPaint`, `pointsFastBreak`, `pointsSecondChance`; same under `awayTeam`.
- `nba_api.live.nba.endpoints.boxscore`: LiveData `game.homeTeam.players[].statistics.pointsInThePaint`, `pointsFastBreak`, `pointsSecondChance`; same for away players.
- V3 nested camelCase. V2 older `resultSets` arrays. AdvancedV2 and MiscV2 are deprecated and not usable for 2026-27 daily collection according to upstream `nba_api` v1.12.0 changelog.
- The `swar/nba_api` GitHub repository is **client source/schema**, not ongoing V3 game-response JSON archive.

## Source and access findings
- ESPN API: verified 14/14 games, 314 active players for November 4, 2026. Provides C4's basic inputs.
- On GitHub-hosted runners, NBA `cdn.nba.com` schedule URLs returned HTTP 403 and NBA Stats ScoreboardV2 timed out. Previous individual `boxscoremiscv3` probes also timed out. This is a network-access barrier, not a missing Python parser, token, or JSON schema.
- `shufinskiy/nba_data` maintains historical play-by-play archive tarballs, but its committed dataset listing currently ends at 2025. It does not supply current 2026-27 player misc/advanced responses.
- `EvanZ/nba-lineup-model` documents a reproducible local raw V3 cache, but the GitHub `data/raw/` directory currently has only `.gitkeep`; it is not a hosted, up-to-date source of boxscoremiscv3 JSON.
- `pseudo-r/Public-NBA-API` describes endpoints and documented metadata; it is not a hosted NBA game-response feed.
- Independent source docs report Akamai/TLS/browser fingerprint checks. Browser headers alone are NOT demonstrated to fix GitHub runner access.

## Recommended acquisition approach
1. Keep ESPN as the primary completed-game/participant feed.
2. For C6 test official NBA LiveData and MiscV3 from a legitimately permitted runtime/network, or a licensed/current partner dataset. Map explicit individual rows by NBA personId, team, and reconciled game ID; preserve provenance and explicit zero values.
3. For C3/C4 acquire **individual Dean Oliver** ratings from Basketball-Reference game-level advanced tables where legally accessible; do not substitute NBA on-court ORtg/DRtg. Keep missing defensive rating missing rather than claim a full C4.
4. If per-player C6 cannot be obtained, investigate reconstructing it from officially tagged play-by-play only after comparing per-player totals to a fully verified MiscV3/LiveData fixture; reject inferred fast breaks or second-chance definitions without a successful validation.
5. Write each raw source response to the QCore collection archive (respecting source redistribution rights), including endpoint, timestamp, response status, game and player identifiers, and content hash. Publish only after 100% field coverage and reconciled source methodology.
6. Operate source access checks as a dedicated feature-branch shadow diagnostic, not via production scoring changes.

## References
- https://github.com/swar/nba_api/blob/master/CHANGELOG.MD
- https://github.com/swar/nba_api/blob/master/src/nba_api/stats/endpoints/boxscoreadvancedv3.py
- https://github.com/swar/nba_api/blob/master/src/nba_api/stats/endpoints/boxscoremiscv3.py
- https://github.com/swar/nba_api/blob/master/docs/nba_api/live/endpoints/boxscore.md
- https://github.com/shufinskiy/nba_data
- https://github.com/EvanZ/nba-lineup-model
- https://github.com/pseudo-r/Public-NBA-API
