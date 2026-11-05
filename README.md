# QCore Labs — QPIX™ NBA Daily Performance Index

**QPIX™** is QCore Labs' player-performance index for NBA games. It scores the players who actually appeared in each game, using a checked-in 13-category scoring engine. **Raw QPIX** is the primary ranking; **QPIX-R** provides an accompanying referee/free-throw normalization, and **QPIX-SFA** is a separately displayed former-team familiarity adjustment where eligible.

This repository is an active research and engineering project. **The production dashboard, independent verified-report workflow, and experimental multi-source collector are distinct.** A successful box-score fetch does **not** mean that all advanced and context statistics have been retrieved.

> **Project status — November 5, 2026:** ESPN final-game/player collection succeeded on the 14-game November 4 slate (314 recorded participants). The experimental pipeline still lacks reliable live coverage for the individual offensive/defensive ratings and paint, fast-break, and second-chance inputs required to certify a full-category report. The shadow workflow correctly preserves its audit and refuses to publish incomplete scoring as complete. Do not treat an experimental run as a verified QPIX leaderboard.

## Current architecture

```text
Final games and complete participant identities
     └── ESPN scoreboard + per-game summary (primary collector)
              │
Supplemental individual statistics, independently verified
     ├── Basketball-Reference-style individual ORtg/DRtg (C3/C4)
     ├── NBA Stats Advanced V3 (separate on-court methodology; audit only)
     ├── NBA Stats Misc V3 / NBA LiveData (C6/C11)
     └── Other individually validated providers when adapters are implemented
              │
Reconcile games, dates, teams, player identities, box lines, field coverage
              │
Write QCore input JSON + source-provenance and failure checkpoints
              │
Full-category validation gate
              │
Checked-in generate-report.js (authorized QPIX scoring logic)
              │
Raw QPIX rankings + QPIX-R / eligible QPIX-SFA
              │
Public report, CSV, scored JSON and dashboard (production only)
```

**Source policy.** ESPN is the verified source of complete game/participant coverage in the recent large-slate tests. Each supplementary field must be tied to an actual player record; neither a team-level number nor a guessed/absent zero is an observed individual statistic. The collector must not confuse ESPN event IDs (such as `401909922`) with NBA game IDs (such as `0022600177`). An NBA ID is only accepted after reconciliation against the date and matchup.

`swar/nba_api` is a **third-party Python client** describing NBA Stats endpoints. Its `BoxScoreAdvancedV3` and `BoxScoreMiscV3` modules define parameter and result schemas; the GitHub source code is **not** a continuously updated archive of per-game response JSON. In particular, NBA Stats `offensiveRating`/`defensiveRating` denote NBA on-court advanced metrics and are **not interchangeable** with Basketball-Reference's Dean Oliver individual offensive and defensive ratings used by QPIX C3.

### QPIX engine: 13 components

The **authoritative scoring rules are in [`generate-report.js`](generate-report.js)**. The following is an input/feature overview, not a replacement implementation or a guarantee that every input is available every day.

| Category | Purpose / principal inputs |
|---|---|
| C1 | Base production: points, rebounds, assists, steals, blocks, turnovers |
| C2 | Shooting efficiency, including true shooting |
| C3 | Individual offensive and defensive rating impact; correct methodology required |
| C4 | Defensive activity, including defensive-rating context |
| C5 | Playmaking quality and turnovers |
| C6 | Offensive context: points in paint, fast-break points and second-chance points |
| C7 | Scoring gravity and shot/usage context |
| C8 | Environment-gated, context-weighted plus/minus |
| C9 | Multi-category production bonuses |
| C10 | Fatigue/minutes-curve effects |
| C11 | Momentum and fast-break context |
| C12 | Second-unit/bench anchor context |
| C13 | **QPIX-R** referee/whistle normalization; separate from Raw QPIX |

**Raw QPIX** ranks the daily leaderboard. **QPIX-R** and eligible **QPIX-SFA** are presented alongside it rather than replacing Raw QPIX. The checked-in `generate-report.js` owns the exact coefficients, threshold gates, contextual modifiers and presentation logic. The familiarity reference lives in `former_team_familiarity.json` (or its checked-in equivalent referenced by the engine). Do not derive new formulas from the simplified, obsolete weights previously shown in this README.

**Participation policy:** score all recorded players who played positive minutes; the daily Top 10 requires **more than eight minutes**. Do not exclude a participant simply because of low field-goal attempts. Players below the Top 10 minute threshold must remain eligible for the full results and bottom-of-report analysis.

## Active GitHub Actions workflows

| Workflow | Definition on `main` | Trigger and effect |
|---|---|---|
| **NBA Daily Report** | [`.github/workflows/nba-daily.yml`](.github/workflows/nba-daily.yml) | Scheduled `0 13 * * *` **UTC** and manual dispatch. Fetches data using `scripts/fetch_nba_data.py`, executes `generate-report.js`, deploys GitHub Pages. This is the existing dashboard workflow; it is **not** proof of full C3/C6 source coverage. |
| **QPIX Independent Verified Report** | [`.github/workflows/qpix-independent.yml`](.github/workflows/qpix-independent.yml) | Manual dispatch or qualifying code push. Runs `scripts/qpix_independent_run.py`, writes `data/daily/` and `docs/reports/` and pushes scored output to `main` only if the job succeeds. **There is currently no daily cron schedule in this workflow.** |
| **QPIX Unified Source Branch — Daily Shadow Test** | [`.github/workflows/qpix-unified-shadow.yml`](.github/workflows/qpix-unified-shadow.yml) | Scheduled `30 13 * * *` UTC, manual dispatch, or a control-file push. The workflow on `main` checks out the **feature branch** and tests its source collector. It has read-only repository permissions, does not push scoring results to production and always attempts to upload collection diagnostics. |

**Timezone:** GitHub cron values above are UTC. At present, `13:00 UTC` is 8:00 a.m. EST and `13:30 UTC` is 8:30 a.m. EST. During daylight saving time, fixed UTC schedules shift to 9:00/9:30 a.m. EDT; update the schedule if an unchanged Eastern local time is required. GitHub's scheduled starts can also be delayed.

### Experimental shadow branch

Branch: `feature/qpix-multi-source-ingestion-20261104`

Review: [draft PR #36](https://github.com/Rickrezin/NBA-daily-report/pull/36)

The experimental branch currently contains these building blocks:

- `scripts/qpix_independent_run.py` — ESPN/game collection, reconciliation, advanced/misc attempts, completeness gate and scoring entrypoint.
- `scripts/qpix_game_crosswalk.py` — game-ID resolution, including independently verified date-specific NBA.com links and tested fallbacks.
- `scripts/c6_sources.py` — C6 field aliases and strict player matching across source identities.
- `scripts/qpix_verified_sources.py` — historical replay of previously verified *individual* ratings when the date and player box-score line match; **not** a live advanced-rating feed.
- `scripts/qpix_source_archive.py` — canonical pre-scoring JSON, coverage audit, input digest and conflict protection.
- `scripts/qpix_collection_checkpoint.py` — atomic, **write-on-entry** `.partial.json` diagnostics, updated as each game and data stage completes.
- `scripts/qpix_coverage_audit.py` — C1–C13 availability summary and per-game C3/C6 coverage.

The shadow workflow uses `if: always()` for its coverage step and artifact upload. Even an early failure should leave a diagnostic JSON and upload artifact. **Absence of a field is recorded as unavailable, not converted to an asserted zero.** The archive is retained as an Actions artifact, not committed to `main` by the shadow workflow.

**Known limitation (Nov 5):** GitHub-hosted runners returned HTTP 403 from NBA schedule CDN URLs; an NBA Stats scoreboard alternative timed out in testing. Exact, independently verified NBA.com game IDs allowed the November 4 replay to attempt supplemental endpoints, but endpoint availability and a complete fresh C3/C6 run must still be demonstrated. The advanced NBA on-court ratings remain a separate audit, **not** substitutes for the index's individual-rating formula.

## Reports and JSON archives

| Path | Role |
|---|---|
| `data/nba_data.json` | Normalized pre-scoring data consumed by `generate-report.js`. |
| `data/daily/YYYY-MM-DD.json` | Published daily scored player records with source/quality metadata when an independent report succeeds. |
| `data/daily/YYYY-MM-DD.csv` | CSV counterpart of the complete scored-player data. |
| `docs/reports/YYYY-MM-DD.md` | Human-readable QPIX report. |
| `docs/reports/YYYY-MM-DD.audit.json` | Independent-run summary and quality audit. |
| `data/historical/qpix_input/YYYY-MM-DD.json` | Canonical, verified pre-scoring input JSON created by the experimental collector; a shadow-run copy is uploaded as an artifact. |
| `data/historical/qpix_input/YYYY-MM-DD.partial.json` | Write-on-entry partial progress, including completed games, player rows, source audit steps, timestamps and any failure. |
| `data/historical/qpix_audits/YYYY-MM-DD.coverage.json` | Per-category and per-game availability diagnostics. |
| `dashboard/index.html` | Rendered dashboard output. |

A complete report must pass game/participant reconciliation **and** the expected-category completeness gate. A partial shadow archive is valuable for investigation but is **not** a publishable complete report. Canonical archives include a SHA-256 hash for the input game/player payload and reject conflicting overwrite attempts.

### Historic validation milestone

November 2, 2026: **15 final games, 334 participants**, with individual ORtg/DRtg verified in the historical scored JSON. A subsequent integration replay verified that all 334 archived individual ratings could be matched back to their respective player records. The C6 breakdown was not fully supplied by that historical source, so the replay is **not** evidence of a fully populated 13-category run.

November 4, 2026: ESPN collection validated **14 final games and 314 participants**. The first experimental shadow runs produced useful coverage/failure artifacts, but not a complete-source QPIX score. Source audits must be assessed before treating any follow-on score comparison as definitive.

## Running and troubleshooting

### Run the existing dashboard

Open **Actions → NBA Daily Report → Run workflow** on `main`. Alternatively, use the configured schedule. This workflow executes the existing dashboard path, **not** the experimental source-completeness gate.

### Run the independent verified report

Open **Actions → QPIX Independent Verified Report → Run workflow** on `main`. This can publish to the repository if source validation and scoring succeed, so do not use it for speculative collector debugging.

### Run the experimental collector

Open **Actions → QPIX Unified Source Branch - Daily Shadow Test → Run workflow** on `main`. The optional `date_et` input is an Eastern-calendar game date (`YYYY-MM-DD`); when omitted, it defaults to the previous Eastern date. The experimental branch is checked out by the workflow itself.

If the GitHub mobile client does not expose the manual dispatch control, use GitHub's desktop/web interface. The dedicated control file `.github/qpix-shadow-trigger.txt` is an additional configured push-trigger mechanism for this **shadow** workflow only.

### Interpreting failures

1. **No ESPN games or incomplete final scoreboard:** inspect the source-stage failure in the partial archive.
2. **ESPN/NBA ID mapping incomplete:** check the dated, matchup-verified crosswalk audit; do not assume an ESPN event ID is an NBA game ID.
3. **403 or timeout from NBA Stats/CDN:** inspect the endpoint status. Knowing a schema or finding a `nba_api` module does not imply live access to its JSON response.
4. **C3 or C6 incomplete:** inspect the category coverage table and source provenance. Do not silently replace missing individual values with team-level numbers, on-court metrics or zeros.
5. **Collector fails before scoring:** verify that the `if: always()` artifact step uploaded the partial checkpoint and coverage JSON.

For changes to the scoring formula, treat `generate-report.js` as authoritative and validate against existing historical fixtures; experimental source fixes should not silently change the scoring mathematics.

## Maintenance

### Independent QCore rating experiment

`dev/qcore-independent-ratings-20261105` adds an isolated
[Q-OffR/Q-DefR prototype](experiments/qcore/README.md) based on ESPN basic player,
team and opponent box scores. It includes both supplied Milwaukee November 4
BBRef exports, offline validation against the 334-player November 2 archive,
game-level training/test separation, residuals and replayable source hashes.
It does not replace authorized C3/C4, use QPIX-R as an input or publish historical
reports. See its [validation report](experiments/qcore/results/report.md) for
coverage limits, short-minute outliers and remaining adoption blockers.

**Every material change to the scoring engine, source mappings, output schema, scheduling, archive layout or workflow names should update this README in the same pull request.** Keep production behavior, tested experimental behavior and planned future capabilities explicitly separate.

QPIX™, QPIX-R and QPIX-SFA are QCore Labs project terminology. This repository is not operated by or affiliated with the NBA, ESPN or Basketball-Reference.
