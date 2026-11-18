#!/usr/bin/env python3
"""Archive ESPN NBA summary + event feeds for a single ET final-game slate.

Collection only. Never modifies QPIX scoring, ratings, or daily reports.
Missing event coverage is explicitly flagged, never inferred as zero.
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
HEADERS = {"User-Agent": "QCoreLabs-QPIX-Source-Archive/1.0", "Accept": "application/json"}


def fetch_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_date_et(event):
    raw = event.get("date") or (event.get("competitions") or [{}])[0].get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")
        ).date().isoformat()
    except ValueError:
        return None


def final_status(event):
    status = event.get("status", {}).get("type", {})
    return status.get("completed") is True and status.get("name") in (
        "STATUS_FINAL", "STATUS_FINAL_OT"
    )


def collect(date_et, root):
    scoreboard = fetch_json(BASE + "scoreboard?dates=" + date_et.replace("-", ""))
    save(root / "scoreboard.json", scoreboard)
    games = []
    errors = []
    for event in scoreboard.get("events", []):
        event_id = str(event.get("id", ""))
        if not event_id.isdigit() or event_date_et(event) != date_et:
            continue
        if not final_status(event):
            continue
        summary_url = BASE + "summary?event=" + event_id
        game_dir = root / "games" / event_id
        try:
            summary = fetch_json(summary_url)
            save(game_dir / "summary.json", summary)
            plays = summary.get("plays")
            if not isinstance(plays, list):
                plays = []
            save(game_dir / "plays.json", plays)
            periods = sorted({
                int(p["period"]["number"])
                for p in plays
                if isinstance(p, dict)
                and isinstance(p.get("period"), dict)
                and str(p["period"].get("number", "")).isdigit()
            })
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors", [])
            scores = {
                c.get("homeAway"): {
                    "team_id": str(c.get("team", {}).get("id", "")),
                    "alias": c.get("team", {}).get("abbreviation"),
                    "points": int(c.get("score", 0))
                } for c in competitors if c.get("homeAway") in ("home", "away")
            }
            score_events = [p for p in plays if isinstance(p, dict)]
            last_score = ({
                "away": score_events[-1].get("awayScore"),
                "home": score_events[-1].get("homeScore")
            } if score_events else {})
            valid_score = (
                "home" in scores and "away" in scores
                and last_score.get("home") == scores["home"]["points"]
                and last_score.get("away") == scores["away"]["points"]
            )
            event_ids = [str(p.get("id")) for p in score_events if p.get("id") is not None]
            has_four = set(range(1, 5)).issubset(periods)
            complete = has_four and valid_score and len(plays) >= 100 and len(event_ids) == len(set(event_ids))
            games.append({
                "espn_event_id": event_id,
                "game_date_et": date_et,
                "status": "FINAL",
                "home": scores.get("home"), "away": scores.get("away"),
                "events": len(plays), "periods": periods,
                "terminal_score": last_score,
                "terminal_score_matches": valid_score,
                "event_ids_unique": len(event_ids) == len(set(event_ids)),
                "coverage": "FOUR_PERIOD_SCORE_RECONCILED" if complete else "INCOMPLETE_UNVERIFIED",
                "raw_summary": "games/" + event_id + "/summary.json",
                "raw_plays": "games/" + event_id + "/plays.json",
                "source_url": summary_url,
            })
        except Exception as exc:
            errors.append({"event_id": event_id, "error": str(exc)})
            games.append({
                "espn_event_id": event_id, "game_date_et": date_et,
                "coverage": "FETCH_FAILED", "source_url": summary_url
            })
    manifest = {
        "schema": "qpix_espn_pbp_raw_v1",
        "date_et": date_et,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN scoreboard and game summary JSON",
        "final_games": len(games),
        "reconciled_games": sum(x["coverage"] == "FOUR_PERIOD_SCORE_RECONCILED" for x in games),
        "games": games,
        "errors": errors,
        "note": "Raw source only; no player-level C6/C11 or advanced ratings inferred."
    }
    save(root / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    if errors or any(x["coverage"] != "FOUR_PERIOD_SCORE_RECONCILED" for x in games):
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-et")
    parser.add_argument("--output", default="data/historical/qpix_pbp_raw")
    args = parser.parse_args()
    date = args.date_et or (datetime.now(ZoneInfo("America/New_York")) - timedelta(days=1)).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        parser.error("--date-et must be YYYY-MM-DD")
    output = Path(args.output) / date
    output.mkdir(parents=True, exist_ok=True)
    try:
        sys.exit(collect(date, output))
    except Exception as exc:
        save(output / "failure.json", {"date_et": date, "error": str(exc)})
        raise
