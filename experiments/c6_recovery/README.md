# QPIX C6 source recovery — experimental
No production QPIX engine files changed.

The official NBA LiveData player box score exposes pointsInThePaint, pointsFastBreak and pointsSecondChance. The NBA Stats BoxScoreMiscV3 exposes pointsPaint, pointsFastBreak and pointsSecondChance. This probe retrieves NBA game IDs from the public NBA.com daily games page, crosschecks against the completed ESPN slate, tries both C6 sources, matches team identities and final scores, and reconciles available player totals to team totals. Missing inputs are null, never fabricated zeroes. All request failures are recorded in the audit JSON.

Run:
python -m unittest discover -s experiments/c6_recovery -p 'test_*.py' -v
python experiments/c6_recovery/c6_probe.py --date 2026-11-04

The workflow runs on a GitHub runner and uploads the audit even if remote endpoints block access. ESPN athlete IDs do NOT match NBA personIds; downstream integration must use a verified player identity crosswalk. This diagnoses retrieval only, not C6 production activation. Second-chance opportunities are different from second-chance points.

## Measured November 4 GitHub runner result

- All 14 finalized ESPN fixtures were matched to official NBA game IDs through NBA.com's daily schedule.
- The 4 local/runner parser regression tests passed.
- NBA LiveData returned HTTP 403 for **all 14 games**; BoxScoreMiscV3 timed out for **all 14 games** on the GitHub-hosted runner. Confirmed player C6 coverage therefore remains **0/14 games**, despite successful schedule and player-field mapping code.
- The failed retrieval step is intentional: missing C6 does not get presented as observed zeros. The complete per-game failure record is retained in the Actions artifact.
- A separate investigation of 15 cached November 2 ESPN play-by-play games found that a naive paint-shot coordinate geometry matched ESPN team paint totals exactly for 13 of 30 team-games; this is *not yet accurate enough for production player C6*. Rebounding state can approximate second-chance scoring but requires event-level validation. Fast-break attribution remains unconfirmed.

Sources: GitHub Actions run 42063018854; NBA LiveData and NBA Stats endpoint schemas; existing QCore November 2 ESPN fixtures.
