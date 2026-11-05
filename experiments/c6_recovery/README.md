# QPIX C6 source recovery — experimental
No production QPIX engine files changed.

The official NBA LiveData player box score exposes pointsInThePaint, pointsFastBreak and pointsSecondChance. The NBA Stats BoxScoreMiscV3 exposes pointsPaint, pointsFastBreak and pointsSecondChance. This probe retrieves NBA game IDs from the public NBA.com daily games page, crosschecks against the completed ESPN slate, tries both C6 sources, matches team identities and final scores, and reconciles available player totals to team totals. Missing inputs are null, never fabricated zeroes. All request failures are recorded in the audit JSON.

Run:
python -m unittest discover -s experiments/c6_recovery -p 'test_*.py' -v
python experiments/c6_recovery/c6_probe.py --date 2026-11-04

The workflow runs on a GitHub runner and uploads the audit even if remote endpoints block access. ESPN athlete IDs do NOT match NBA personIds; downstream integration must use a verified player identity crosswalk. This diagnoses retrieval only, not C6 production activation. Second-chance opportunities are different from second-chance points.
