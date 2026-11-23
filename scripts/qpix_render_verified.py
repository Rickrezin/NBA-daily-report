#!/usr/bin/env python3
"""Render one verified, date-scoped report with the existing dashboard renderer."""
from datetime import date
import json
from math import isfinite
from pathlib import Path
import sys

import render_qpix_dashboard as dashboard


def main(date_et):
    if date.fromisoformat(date_et).isoformat() != date_et:
        raise ValueError("Expected YYYY-MM-DD")
    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "daily" / (date_et + ".json")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("date_et") != date_et or report.get("status") != "VERIFIED":
        raise ValueError("Requested report is not verified for this date")
    archive_info = report.get("source_archive", {})
    archive_path = (root / archive_info["path"]).resolve()
    if not archive_path.is_relative_to(root.resolve()):
        raise ValueError("Source archive is outside the repository")
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    if (archive.get("date_et") != date_et or not archive.get("coverage", {}).get("complete")
            or archive.get("input_sha256") != archive_info.get("input_sha256")):
        raise ValueError("Report source archive is incomplete or mismatched")
    players = report.get("players", [])
    if not players or len(players) != archive["coverage"]["players"]:
        raise ValueError("Report participant coverage is inconsistent")
    if not isinstance(report.get("leaderboards"), dict):
        raise ValueError("Report leaderboard schema is unavailable")
    secondary = report.get("scoring_engine", {}).get("secondary_assists", {})
    if secondary.get("enabled"):
        tracking = archive.get("source_audit", {}).get("NBA_secondary_assists", {})
        weight = secondary.get("weight")
        if (tracking.get("verified") != len(players) or type(weight) not in (int, float)
                or not isfinite(weight) or weight < 0):
            raise ValueError("Weighted C5 is missing verified secondary-assist coverage or its coefficient")
        inputs = {(p["game_id"], str(p["player_id"])): p for p in archive["players"]}
        for player in players:
            archived = inputs.get((player["game_id"], str(player["player_id"])), {})
            count = archived.get("2AST")
            if (type(count) is not int or count < 0 or player.get("2AST") != count
                    or player.get("AST") != archived.get("assists")
                    or player.get("weighted_assists") != player["AST"] + count * weight):
                raise ValueError("Weighted assists differ from verified scoring inputs")
    for player in players:
        if player.get("raw_qpix") != player.get("score") or player.get("qpix_r") != player.get("qpixR"):
            raise ValueError("Display scores differ from authorized engine output")
    # Reuse the existing presentation while selecting the exact collected date.
    dashboard.find_report = lambda: (path, report)
    dashboard.render()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: qpix_render_verified.py YYYY-MM-DD")
    main(sys.argv[1])
