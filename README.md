# QCore Labs — QPIX™ NBA Daily Performance Index

**QPIX™** is QCore Labs' player-performance index for NBA games. The repository collects final-game player statistics, reconciles the required inputs across providers, runs the checked-in scoring engine, and produces a dated report and HTML dashboard.

**Raw QPIX determines the ranking.** QPIX-R is the referee/free-throw normalization companion, and QPIX-SFA records the former-team familiarity adjustment where eligible. The authoritative coefficients and scoring rules live in [`generate-report.js`](generate-report.js).

**Live dashboard:** [Open QPIX](https://rickrezin.github.io/NBA-daily-report/)

**Generated HTML:** [`dashboard/index.html`](dashboard/index.html)

## Current production path

The daily workflow on `main` now uses [`scripts/qpix_independent_run.py`](scripts/qpix_independent_run.py) for verified collection and scoring, followed by [`scripts/qpix_render_verified.py`](scripts/qpix_render_verified.py) for the selected date's HTML. It saves the report and source records to the repository before deploying `dashboard/` to GitHub Pages.

**Verified milestone — November 20, 2026, Eastern:** the repaired collector processed the November 19 slate of **4 final games and 89 minute-positive players** on a GitHub-hosted runner. All 89 players had reconciled individual offensive/defensive ratings and NBA player-level paint, fast-break, and second-chance points. Scoring and HTML rendering both completed on `main`, and all 52 regression tests passed. See the [successful source/scoring/HTML run](https://github.com/Rickrezin/NBA-daily-report/actions/runs/44867096900) and [regression run](https://github.com/Rickrezin/NBA-daily-report/actions/runs/44867096859).

That milestone establishes a working collection path for the tested slate. Every subsequent run still validates its own sources and completeness. A shadow run produces reviewable artifacts; publication is a separate workflow action.

### Sources and reconciliation

| Source | Role in the verified collector |
|---|---|
| ESPN scoreboard and game summaries | Final fixtures, complete minute-positive participant set, final scores, and base player box scores. ESPN player IDs remain the primary participant identifiers. |
| NBA live CDN through `nba_api` | Official schedule data resolves NBA game IDs by date and matchup. Live box scores supply individual `pointsFastBreak`, `pointsInThePaint`, and `pointsSecondChance`. NBA player IDs are retained separately. |
| Basketball Reference | Fresh basic and advanced box-score tables supply individual Dean Oliver ORtg/DRtg after participant identities, final scores, basic statistics, and minutes reconcile. A fully verified same-date historical report can also supply matching ratings. |
| ESPN play-by-play and PBPStats supplemental audits | Separate source archives and research checks. Experimental transition estimates or supplemental coverage do not replace the verified collector's individual input requirements. |

[`requirements.txt`](requirements.txt) pins **`nba_api==1.12.0`**, the client version verified against the live NBA CDN in GitHub Actions. The active workflows set `ENABLE_NBA_CDN=true` and `ENABLE_NBA_V3=false`. CDN collection is independent of the `stats.nba.com` AdvancedV3/MiscV3 path, whose separate diagnostic requests timed out during the repair. Endpoint availability must be assessed from the actual response; an earlier failure in a different client is not proof that every NBA endpoint is inaccessible.

The `nba_api` package is a third-party client for NBA endpoints, not a repository of continuously updated game responses. NBA Stats on-court offensive/defensive ratings are **not interchangeable** with the individual Basketball Reference ratings used by QPIX C3.

The collector follows this sequence:

1. Verify the requested Eastern-calendar slate and every final game's participants and point totals.
2. Resolve official NBA game IDs using exact date and away/home matchups; never substitute an ESPN event ID or guess a numeric sequence.
3. Archive received NBA JSON and Basketball Reference HTML, then reconcile identities and box-score lines before merging supplementary fields.
4. Save the normalized pre-scoring input snapshot and field-coverage audit. **Absent values remain absent; an observed zero is a separate value.**
5. Require all five critical fields for every participant: individual offensive rating, individual defensive rating, paint points, fast-break points, and second-chance points.
6. Execute the authorized JavaScript scoring engine, write the dated outputs, and render that exact verified report.

A source failure that leaves required inputs missing, a nonfinal game, an identity conflict, or an incomplete required field set stops verified report publication. The job preserves available diagnostics so the source failure can be investigated.

## HTML dashboard

**Generated HTML:** [`dashboard/index.html`](dashboard/index.html). The dashboard contains final game scores, the Raw QPIX Top 10 and Bottom 10, every minute-positive participant, and source/report links. Both leaderboards require **more than eight minutes played**; lower-minute players remain in the complete results.

The production renderer is a two-part path:

- [`scripts/qpix_render_verified.py`](scripts/qpix_render_verified.py) selects `data/daily/YYYY-MM-DD.json`, requires its `VERIFIED` status, and checks its date, complete source archive, input digest, participant count, and score aliases.
- [`scripts/render_qpix_dashboard.py`](scripts/render_qpix_dashboard.py) supplies the HTML presentation. The verified wrapper selects the exact collected date so an older or differently dated report cannot replace it during that render.

The scored JSON exposes `raw_qpix = score` and `qpix_r = qpixR` for the dashboard, plus `leaderboards.top10` and `leaderboards.bottom10` player IDs. These are presentation fields derived from the engine's existing output, not new scoring formulas.

**Generation and deployment are distinct checks.** A successful render creates HTML in the runner or local checkout. A successful publishing workflow saves the report and generated files and completes GitHub Pages deployment. For a live-site issue, inspect the deployment result and displayed game date as well as the source/HTML job.

## GitHub Actions and schedules

### Facebook Page publication

The optional Facebook publisher prepares a dedicated plain-text social post for the [QPIX Page](https://www.facebook.com/people/QPIX-NBA-player-performance-index/61583650594496/) after successful dashboard publication. It uses the exact deployed, verified report and a durable Page/date receipt to prevent automatic duplicate attempts. Publishing stays disabled until a Page access token is stored in Actions secrets and `QPIX_FACEBOOK_ENABLED=true` is set. Manual operations preview text, check the connection, or reconcile an existing receipt; they never create a post. See [Facebook setup, previews, and recovery](docs/FACEBOOK.md).

### Report workflows

Times below are **America/New_York**. The scheduled collectors use paired UTC entries and a daylight-saving offset gate to select the intended Eastern slot. GitHub may start a scheduled run late.

| Workflow | Schedule or trigger | Effect |
|---|---|---|
| [NBA Daily Report](.github/workflows/nba-daily.yml) | **9:00 a.m. Eastern** daily; manual dispatch on `main` | Collects and validates the previous Eastern date, scores, renders its HTML, preserves artifacts, commits verified outputs and source records, and deploys GitHub Pages. |
| [QPIX Independent Verified Report](.github/workflows/qpix-independent.yml) | **Manual dispatch only** on `main` | Runs the same verified collection and exact-date rendering path, then commits successful outputs. Its completion can trigger the HTML deployment workflow. Code changes do not automatically publish through this workflow. |
| [QPIX Unified Sources — Daily Shadow Test](.github/workflows/qpix-unified-shadow.yml) | **9:30 a.m. Eastern**; manual dispatch; selected collector/control-file pushes | Tests the current collector and production engine on `main`, including HTML rendering. Repository access is read-only and results are uploaded as artifacts. It does not publish reports or rankings. |
| [QPIX HTML Dashboard Deploy](.github/workflows/qpix-dashboard-deploy.yml) | Selected report/renderer pushes, successful configured publication workflows, or manual dispatch | Renders the latest stored dated report, validates the generated HTML, and deploys `dashboard/` to GitHub Pages. This workflow does not collect missing source statistics. |
| [QPIX ESPN Play-by-Play Daily Raw Archive](.github/workflows/qpix-espn-pbp-daily.yml) | **8:30 a.m. Eastern**; manual dispatch; workflow-file pushes | Preserves ESPN event feeds and research-only derivations. It does not calculate the verified QPIX leaderboard. |
| [QPIX Daily Multi-Source Verification](.github/workflows/qpix-daily-multisource-verify.yml) | **9:00 a.m. and 10:30 a.m. Eastern**, plus configured source events/manual dispatch | Supplemental Basketball Reference, PBPStats, and ESPN coverage audits; no official score publication. |
| [QPIX multi-source regression tests](.github/workflows/qpix-multi-source-tests.yml) | Relevant pushes to `main` or the ingestion feature branch; manual dispatch | Exercises source adapters, reconciliation, missing-value behavior, archive protection, and historical fixtures without publishing. |

The shadow workflow now checks `main`; it no longer checks out the historical `feature/qpix-multi-source-ingestion-20261104` branch. That branch and older dated probes remain development/history references. [`scripts/fetch_nba_data.py`](scripts/fetch_nba_data.py), which reads the older Elias text feed, is not the active daily report entry point. The HTTP and V3 diagnostic workflows are troubleshooting tools rather than publication gates.

### Run through GitHub

- To collect and publish the normal previous-day report, open **Actions → NBA Daily Report → Run workflow** on `main`.
- To inspect source collection, scoring, and HTML without publishing, open **Actions → QPIX Unified Sources - Daily Shadow Test → Run workflow**. Its optional `date_et` selects an Eastern game date; leaving it blank selects the previous Eastern date.
- To publish a verified report manually through the independent workflow, choose **Actions → QPIX Independent Verified Report → Run workflow** on `main`.

Normal publishing workflows select the previous Eastern date. A dated shadow run is useful for source replay; historical backfills also need their scoring-date and season assumptions checked before publication.

## Run locally

Use **Python 3.12** and **Node.js 24**, matching the Actions workflows. From the repository root, the following Bash commands collect the previous Eastern date and render its verified HTML:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

export ENABLE_NBA_CDN=true
export ENABLE_NBA_V3=false
RUN_DATE="$(python -c 'from datetime import datetime, timedelta; from zoneinfo import ZoneInfo; print((datetime.now(ZoneInfo("America/New_York")) - timedelta(days=1)).date().isoformat())')"

python scripts/qpix_independent_run.py "$RUN_DATE"
python scripts/qpix_render_verified.py "$RUN_DATE"
python -m http.server 8000 --directory dashboard
```

Open `http://localhost:8000/` for the generated dashboard. These local commands create files; they do not commit or deploy them. If collection fails, examine the source audit before attempting to render or publish a complete report.

Run the regression suite with:

```bash
python -m unittest discover -s tests -v
```

For coverage of a particular run, use the exact archive path recorded in its report's `source_archive.path` or the collector's `input_archive` Actions output:

```bash
python scripts/qpix_coverage_audit.py YYYY-MM-DD --source data/historical/qpix_input/EXACT-ARCHIVE.json
```

An explicit missing or wrong-date archive is rejected. This prevents an older incomplete base snapshot from being mistaken for the newest collection.

## Reports, raw sources, and archives

| Path | Role |
|---|---|
| `data/nba_data.json` | Normalized input consumed by the authorized scoring engine. |
| `data/daily/YYYY-MM-DD.json` | Verified scored player records, source/quality metadata, exact source-archive reference, and leaderboard IDs. |
| `data/daily/YYYY-MM-DD.csv` | Complete scored-player CSV, including participants below the leaderboard minute threshold. |
| `docs/reports/YYYY-MM-DD.md` | Human-readable daily QPIX report. |
| `docs/reports/YYYY-MM-DD.audit.json` | Run summary, quality audit, and source-archive reference. |
| `data/historical/qpix_raw/YYYY-MM-DD/nba_live/` | Received official schedule and live box-score JSON; filenames include content hashes. |
| `data/historical/qpix_bref_raw/YYYY-MM-DD/` | Basketball Reference HTML plus retrieval/reconciliation audits and source digests. |
| `data/historical/qpix_input/YYYY-MM-DD.json` | Original normalized pre-scoring snapshot for the date. Inspect its completeness; its existence alone does not certify a report. |
| `data/historical/qpix_input/YYYY-MM-DD.<input_sha256>.json` | A changed input revision, preserving the original snapshot. The run/report identifies the exact revision used. |
| `data/historical/qpix_input/YYYY-MM-DD.partial.json` | Collection checkpoint, completed games, source stages, and failure information. |
| `data/historical/qpix_audits/YYYY-MM-DD.coverage.json` | Per-category/per-game coverage and the input archive inspected. |
| `dashboard/index.html` | Generated dashboard HTML. |
| `dashboard/familiarity.json` | Auxiliary familiarity output from the authorized engine. |

The canonical input digest covers the game/player payload. Existing snapshots are not silently overwritten: changed input can create a content-addressed revision, and repeated revisions are checked against their actual content. Missing fields are preserved in partial diagnostics rather than manufactured as zeros.

Successful publishing workflows commit the selected date's reports and source records. Actions also retain available artifacts after failures: the daily and independent workflows currently retain them for **30 days**, and the shadow workflow for **7 days**. Artifact retention is not a substitute for the committed source history of a published report.

## QPIX engine: 13 components

This is an input overview. [`generate-report.js`](generate-report.js) owns the exact formulas, thresholds, contextual modifiers, and companion-score rules.

| Category | Purpose / principal inputs |
|---|---|
| C1 | Base production: points, rebounds, assists, steals, blocks, turnovers |
| C2 | Shooting efficiency, including true shooting |
| C3 | Individual offensive and defensive rating impact |
| C4 | Defensive activity, including individual defensive-rating context |
| C5 | Playmaking quality and turnovers |
| C6 | Offensive context: paint, fast-break, and second-chance points |
| C7 | Scoring gravity and shot/usage context |
| C8 | Environment-gated, context-weighted plus/minus |
| C9 | Multi-category production bonuses |
| C10 | Fatigue/minutes-curve effects |
| C11 | Momentum and fast-break context |
| C12 | Second-unit/bench anchor context |
| C13 | QPIX-R referee/whistle normalization, separate from Raw QPIX |

Raw QPIX determines official rank; companion scores do not reorder it. The familiarity references used by the engine include [`data/venue_familiarity.json`](data/venue_familiarity.json) and [`data/former_team_familiarity.json`](data/former_team_familiarity.json). Collection and rendering fixes must not silently change scoring mathematics.

Every recorded player with positive minutes belongs in the full results. Both displayed leaderboards require **minutes > 8**, with no minimum field-goal-attempt filter.

## Troubleshooting

| Symptom | Check |
|---|---|
| No games or a nonfinal game | Requested Eastern date, ESPN scoreboard, and the partial collection checkpoint. An empty or unfinished slate is not a complete scored report. |
| NBA ID unresolved | Official schedule attempts and exact date/away/home reconciliation. ESPN event IDs and NBA game IDs are different namespaces. |
| CDN or Stats HTTP error | Endpoint-specific response and installed client version. The production CDN transport is independent of disabled Stats V3 diagnostics. |
| Missing C3/C6 fields | Exact run coverage and provider audits. Never fill individual gaps with team totals, different rating methodologies, estimates, or assumed zeros. |
| Player box lines disagree | The named player, team aliases, provider IDs, minutes, and changed statistics. Later source corrections may reconcile on a subsequent fetch; do not bypass the check. |
| HTML absent | Collection/completeness outcome, dated verified JSON, its referenced archive, and the **Render** step. The renderer must not turn an incomplete collection into a verified page. |
| HTML exists but live page is stale | Successful report commit, Pages deployment result, served game date, and the latest deployment workflow. A local or shadow render alone does not update the website. |
| Old archive shows zero coverage | Use the current report's `source_archive.path` or the run's `input_archive` output; an original incomplete snapshot is deliberately preserved. |

Historical fixtures remain useful for regression checks. In particular, the November 2 fixture contains 334 verified individual rating pairs but incomplete C6 data; it tests rating replay and the completeness gate, not complete contemporary source coverage.

## Maintenance and project identity

Update this README alongside material changes to source mappings, output schemas, schedules, archive layout, workflow names, or scoring rules. Preserve the distinction between source availability, successful validation, generated HTML, and deployment.

QPIX™, QPIX-R, and QPIX-SFA are QCore Labs project terminology. This repository is not operated by or affiliated with the NBA, ESPN, or Basketball Reference. See [`LICENSE`](LICENSE) for the repository's CC0 1.0 Universal dedication.
