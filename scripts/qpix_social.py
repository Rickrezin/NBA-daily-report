#!/usr/bin/env python3
"""Render a Facebook-ready QPIX post from one verified, dated report.

This module only formats existing results. It neither calculates QPIX scores nor
publishes to a social service. Proprietary Q ratings must be explicitly present;
Basketball Reference ratings and engine impact components are never substitutes.
"""

import argparse
from datetime import date
import json
import math
from pathlib import Path
import re

try:
    from .qpix_source_archive import _input_hash
except ImportError:
    from qpix_source_archive import _input_hash


DASHBOARD_URL = "https://rickrezin.github.io/NBA-daily-report/"
TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}
STAT_FIELDS = (
    "points", "rebounds", "assists", "steals", "blocks", "turnovers",
    "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
)
# These names explicitly identify QCore ratings. Do not add generic ORtg/DRtg.
Q_RATING_FIELDS = {
    "offense": ("qcore_q_offr", "q_offr", "q_ortg"),
    "defense": ("qcore_q_defr", "q_defr", "q_drtg"),
}


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected an exact YYYY-MM-DD game date")
    return date.fromisoformat(value)


def _number(value, label, *, nonnegative=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if nonnegative and value < 0:
        raise ValueError(f"{label} cannot be negative")
    if integer and value != int(value):
        raise ValueError(f"{label} must be an integer")
    return value


def _identifier(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError(f"{label} is unavailable")
    return str(value)


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or "@" in value:
        raise ValueError(f"{label} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} must be a single line")
    return value.strip()


def _aliased_number(player, keys, label, *, optional=False):
    values = [_number(player[key], label) for key in keys if player.get(key) is not None]
    if not values:
        if optional:
            return None
        raise ValueError(f"{label} is unavailable")
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"Conflicting {label} aliases")
    return values[0]


def _raw(player):
    return _aliased_number(player, ("score", "raw_qpix"), "Raw QPIX")


def _referee(player):
    return _aliased_number(player, ("qpixR", "qpix_r"), "QPIX-R")


def _q_rating(player, side):
    return _aliased_number(player, Q_RATING_FIELDS[side], f"QCore {side} rating", optional=True)


def validate_report(report, date_et):
    """Validate publication inputs and return players indexed by their string IDs.

    The supplied leaderboard order is retained, including tie order. Scores are
    checked for consistency but are never recalculated.
    """
    _date(date_et)
    if not isinstance(report, dict) or report.get("date_et") != date_et or report.get("status") != "VERIFIED":
        raise ValueError("The selected report must be VERIFIED for the requested date")
    games = report.get("games")
    players = report.get("players")
    if not isinstance(games, list) or not games or not isinstance(players, list) or not players:
        raise ValueError("The report must contain final games and participants")

    game_lookup = {}
    for game in games:
        if not isinstance(game, dict) or game.get("status") != "FINAL" or game.get("date_et") != date_et:
            raise ValueError("Every game must be FINAL for the requested date")
        gid = _identifier(game.get("game_id"), "Game ID")
        if gid in game_lookup:
            raise ValueError("Duplicate game ID")
        for side in ("away", "home"):
            alias = _text(game.get(f"{side}_alias"), "Team alias")
            if alias not in TEAM_NAMES:
                raise ValueError(f"Unknown team alias: {alias}")
            _number(game.get(f"{side}_points"), "Final score", nonnegative=True, integer=True)
        if game["away_alias"] == game["home_alias"] or game["away_points"] == game["home_points"]:
            raise ValueError("Invalid final matchup or tied final score")
        game_lookup[gid] = game

    player_lookup = {}
    for player in players:
        if not isinstance(player, dict):
            raise ValueError("Invalid player record")
        pid = _identifier(player.get("player_id"), "Player ID")
        gid = _identifier(player.get("game_id"), "Player game ID")
        if pid in player_lookup:
            raise ValueError("Duplicate participant ID")
        if gid not in game_lookup:
            raise ValueError("Player does not belong to a reported game")
        game = game_lookup[gid]
        if player.get("team") not in (game["away_alias"], game["home_alias"]):
            raise ValueError("Player team does not match the reported game")
        _text(player.get("name"), "Player name")
        if _number(player.get("minutes"), "Minutes", nonnegative=True) <= 0:
            raise ValueError("Every reported participant must have positive minutes")
        for field in STAT_FIELDS:
            _number(player.get(field), field, nonnegative=True, integer=True)
        for made, attempted in (("fgm", "fga"), ("fg3m", "fg3a"), ("ftm", "fta")):
            if player[made] > player[attempted]:
                raise ValueError("Shooting makes cannot exceed attempts")
        _raw(player)
        _referee(player)
        _q_rating(player, "offense")
        _q_rating(player, "defense")
        player_lookup[pid] = player

    for gid, game in game_lookup.items():
        for side in ("away", "home"):
            total = sum(p["points"] for p in players
                        if str(p["game_id"]) == gid and p["team"] == game[f"{side}_alias"])
            if total != game[f"{side}_points"]:
                raise ValueError("Participant points do not reconcile with a final score")

    boards = report.get("leaderboards")
    eligible = {pid: p for pid, p in player_lookup.items() if p["minutes"] > 8}
    if not isinstance(boards, dict) or not eligible:
        raise ValueError("Eligible leaderboard participants are unavailable")
    for key, descending in (("top10", True), ("bottom10", False)):
        entries = boards.get(key)
        if not isinstance(entries, list) or len(entries) != min(10, len(eligible)):
            raise ValueError(f"{key} participant count is inconsistent")
        ids = [_identifier(pid, "Leaderboard player ID") for pid in entries]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{key} contains duplicate players")
        if any(pid not in eligible for pid in ids):
            raise ValueError(f"{key} must reference existing players with more than eight minutes")
        scores = [_raw(eligible[pid]) for pid in ids]
        if scores != sorted(scores, reverse=descending):
            raise ValueError(f"{key} is not in Raw QPIX order")
        other_scores = [_raw(player) for pid, player in eligible.items() if pid not in ids]
        if other_scores and ((descending and min(scores) < max(other_scores)) or
                             (not descending and max(scores) > min(other_scores))):
            raise ValueError(f"{key} omits a player ahead of its cutoff")
    return player_lookup


def load_verified_report(root, date_et):
    """Load the exact date and verify its complete, content-matched input archive."""
    _date(date_et)
    root = Path(root).resolve()
    report = json.loads((root / "data" / "daily" / f"{date_et}.json").read_text(encoding="utf-8"))
    player_lookup = validate_report(report, date_et)
    reference = report.get("source_archive", {})
    if not isinstance(reference, dict) or reference.get("complete") is not True:
        raise ValueError("A complete verified source archive is required")
    path = reference.get("path")
    if not isinstance(path, str) or not path or Path(path).is_absolute():
        raise ValueError("The source archive must be a repository-relative path")
    archive_path = (root / path).resolve()
    if not archive_path.is_relative_to(root):
        raise ValueError("The source archive is outside the repository")
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    coverage = archive.get("coverage", {})
    if archive.get("date_et") != date_et or coverage.get("complete") is not True:
        raise ValueError("The source archive is incomplete or has a different date")
    if coverage.get("players") != len(player_lookup) or coverage.get("games") != len(report["games"]):
        raise ValueError("Source archive participant or game counts differ")
    digest = reference.get("input_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid source archive digest")
    if archive.get("input_sha256") != digest or _input_hash(archive) != digest:
        raise ValueError("Source archive content does not match its recorded digest")
    if archive.get("games") != report["games"]:
        raise ValueError("Report games differ from the verified source archive")
    source_players = archive.get("players")
    if not isinstance(source_players, list) or len(source_players) != len(player_lookup):
        raise ValueError("Source archive participant count differs")
    seen = set()
    fields = ("game_id", "team", "name", "minutes") + STAT_FIELDS
    for source in source_players:
        pid = _identifier(source.get("player_id"), "Archived player ID")
        if pid in seen or pid not in player_lookup:
            raise ValueError("Source archive participant identities differ")
        seen.add(pid)
        if any(source.get(field) != player_lookup[pid].get(field) for field in fields):
            raise ValueError("Report player statistics differ from the verified source archive")
    return report


def _decimal(value):
    return "N/A" if value is None else f"{value:.1f}"


def _stat_line(player):
    labels = (("points", "PTS"), ("rebounds", "REB"), ("assists", "AST"),
              ("steals", "STL"), ("blocks", "BLK"), ("turnovers", "TO"))
    parts = [f"{int(player[field])} {label}" for field, label in labels]
    parts.append(f"{player['minutes']:g} MIN")
    return " | ".join(parts)


def _highlights(top):
    leader = top[0]
    lines = [
        f"{leader['name']} leads the slate with {_raw(leader):.1f} Raw QPIX after "
        f"{int(leader['points'])} points, {int(leader['rebounds'])} rebounds and "
        f"{int(leader['assists'])} assists.",
    ]
    remaining = top[1:]
    if remaining:
        defender = max(remaining, key=lambda p: p["steals"] + p["blocks"])
        if defender["steals"] + defender["blocks"] >= 3:
            lines.append(f"{defender['name']} added {int(defender['steals'])} steals "
                         f"and {int(defender['blocks'])} blocks to his Top 10 performance.")
            remaining = [p for p in remaining if p is not defender]
    if remaining:
        passer = max(remaining, key=lambda p: p["assists"])
        rebounder = max(remaining, key=lambda p: p["rebounds"])
        if passer["assists"] >= 5:
            lines.append(f"{passer['name']} paired {int(passer['assists'])} assists "
                         f"with {int(passer['turnovers'])} turnovers.")
        elif rebounder["rebounds"] >= 10:
            lines.append(f"{rebounder['name']} contributed {int(rebounder['rebounds'])} "
                         f"rebounds alongside {int(rebounder['points'])} points.")
    return lines


def render_social_post(report, date_et):
    """Return deterministic plain text, using the report's authoritative board IDs."""
    lookup = validate_report(report, date_et)
    day = _date(date_et)
    top = [lookup[str(pid)] for pid in report["leaderboards"]["top10"]]
    bottom = [lookup[str(pid)] for pid in report["leaderboards"]["bottom10"]]
    phase = {"regular": "Regular season", "preseason": "Preseason", "postseason": "Postseason"}.get(report.get("phase"))
    date_label = f"{day.strftime('%B')} {day.day}, {day.year}"
    game_label = "game" if len(report["games"]) == 1 else "games"
    lines = ["QCORE LABS | QPIX™ NBA DAILY PERFORMANCE INDEX",
             date_label + (f" | {phase}" if phase else ""),
             f"{len(report['games'])} {game_label} | {len(lookup)} players evaluated", "", "FINAL SCORES"]
    for game in report["games"]:
        winner, loser = ("home", "away") if game["home_points"] > game["away_points"] else ("away", "home")
        lines.append(f"{TEAM_NAMES[game[f'{winner}_alias']]} {int(game[f'{winner}_points'])} — "
                     f"{TEAM_NAMES[game[f'{loser}_alias']]} {int(game[f'{loser}_points'])}")

    lines.extend(["", "TOP 10 — RAW QPIX"])
    for rank, player in enumerate(top, 1):
        lines.extend(["", f"{rank}. {player['name']} ({player['team']})",
                      f"Raw QPIX: {_raw(player):.1f} | QPIX-R: {_referee(player):.1f} | "
                      f"Q-OffR: {_decimal(_q_rating(player, 'offense'))} | "
                      f"Q-DefR: {_decimal(_q_rating(player, 'defense'))}",
                      _stat_line(player),
                      f"FG {int(player['fgm'])}/{int(player['fga'])} | "
                      f"3PT {int(player['fg3m'])}/{int(player['fg3a'])} | "
                      f"FT {int(player['ftm'])}/{int(player['fta'])}"])
    lines.extend(["", "PERFORMANCE NOTES", *_highlights(top), "", "BOTTOM 10 — RAW QPIX"])
    for rank, player in enumerate(bottom, 1):
        lines.append(f"{rank}. {player['name']} ({player['team']}) — "
                     f"Raw QPIX: {_raw(player):.1f} | QPIX-R: {_referee(player):.1f}")
    lines.extend([
        "", "THE QPIX TAKEAWAY",
        f"{top[0]['name']} finishes first in Raw QPIX. The complete results include every "
        "player who logged minutes; Top 10 and Bottom 10 eligibility requires more than eight minutes.",
        "", "Raw QPIX determines the official ranking.",
        "QPIX-R is the companion score adjusted for referee and free-throw context.",
        "Q-OffR and Q-DefR are QCore offensive and defensive ratings. N/A means unavailable for this report.",
        "", f"Full results: {DASHBOARD_URL}",
        f"© {day.year} QCore Labs | QPIX™ NBA Daily Performance Index",
        "#QPIX #QCoreLabs #NBA #BasketballAnalytics",
    ])
    return "\n".join(lines) + "\n"


def write_social_post(root, date_et):
    """Validate the saved report and write docs/social/YYYY-MM-DD.facebook.txt."""
    root = Path(root).resolve()
    report = load_verified_report(root, date_et)
    text = render_social_post(report, date_et)
    output = root / "docs" / "social" / f"{date_et}.facebook.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date_et", help="Exact Eastern game date (YYYY-MM-DD)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Repository root (defaults to this script's repository)")
    args = parser.parse_args(argv)
    try:
        output = write_social_post(args.root, args.date_et)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f"QPIX social generation failed: {exc}\n")
    print(f"Social post written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
