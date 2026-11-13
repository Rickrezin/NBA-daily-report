#!/usr/bin/env python3
"""Rebuild a provenance-aware NBA season ledger from published QPIX source archives.

This is an independent data publication step. It does not rewrite QPIX scoring
formulas or silently substitute incomplete historical FTA averages into QPIX-R.
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
FIELDS = ("points", "rebounds", "assists", "steals", "blocks", "turnovers",
          "fga", "fgm", "fta", "ftm", "offensive_rebounds", "defensive_rebounds")

def load(path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)

def numeric(value, field, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: nonnumeric {field}: {value!r}")
    if not (0 <= value <= 150):
        raise ValueError(f"{label}: out-of-range {field}: {value}")
    return value

def get_sources(season_start, through):
    """One highest-priority snapshot per date, not a mix of conflicting feeds."""
    options = defaultdict(list)
    for directory, priority in (
        ("data/historical/qpix_input", 0),
        ("data/daily", 1),
        ("data/shadow", 2),
    ):
        for path in (ROOT / directory).glob("*.json"):
            date = path.name[:10]
            if not DATE_RE.fullmatch(date) or not (season_start <= date <= through):
                continue
            if directory == "data/historical/qpix_input":
                if path.name != date + ".json":  # exclude partial archives
                    continue
            elif path.name not in (date + ".json", date + ".provisional.json"):
                continue
            options[date].append((priority, path))
    return [(date, sorted(paths, key=lambda item: (item[0], str(item[1])))[0][1])
            for date, paths in sorted(options.items())]

def extract(date, path):
    source = load(path)
    players = source.get("players", [])
    if not isinstance(players, list) or not players:
        return [], {"date": date, "path": str(path.relative_to(ROOT)), "status": "no_players"}
    expected = source.get("coverage", {})
    expected_count = (expected.get("participating_players") if isinstance(expected, dict)
                      else None)
    if isinstance(expected_count, int) and expected_count != len(players):
        raise ValueError(f"{path}: player count mismatch {len(players)} vs {expected_count}")
    accepted = []
    skipped = defaultdict(int)
    for p in players:
        if not isinstance(p, dict):
            skipped["not_object"] += 1
            continue
        player_id = str(p.get("player_id") or p.get("espn_athlete_id") or "")
        game_id = str(p.get("game_id") or "")
        # Older shadow exports store the verified ESPN event ID as "game".
        # Preserve its provider namespace rather than treating it as an NBA ID.
        if not game_id and re.fullmatch(r"\d{9}", str(p.get("game") or "")):
            game_id = "ESPN_" + str(p["game"])
        if not player_id or not game_id or not p.get("name") or not p.get("team"):
            skipped["missing_stable_player_or_game_id"] += 1
            continue
        minutes = p.get("minutes")
        if not isinstance(minutes, (int, float)) or minutes <= 0:
            skipped["non_positive_or_missing_minutes"] += 1
            continue
        stats = {}
        # Never coerce missing values to observed zero.
        if any(p.get(k) is None for k in ("fga", "fta", "ftm", "points")):
            skipped["missing_essential_box_stat"] += 1
            continue
        for field in FIELDS:
            if p.get(field) is not None:
                stats[field] = numeric(p[field], field, f"{date}/{game_id}/{player_id}")
        if stats["ftm"] > stats["fta"] or (stats.get("fgm", 0) > stats["fga"]):
            raise ValueError(f"{path}: impossible made/attempted for {player_id}")
        accepted.append({
            "date_et": date,
            "game_id": game_id,
            "player_id": player_id,
            "name": p["name"],
            "team": p["team"],
            "minutes": minutes,
            "stats": stats,
            "source_file": str(path.relative_to(ROOT)),
        })
    return accepted, {"date": date, "path": str(path.relative_to(ROOT)),
                      "status": "partial" if skipped else "accepted",
                      "players_in_source": len(players), "players_accepted": len(accepted),
                      "skipped_by_reason": dict(skipped)}

def summarize(games):
    totals = {k: sum(g["stats"].get(k, 0) for g in games) for k in FIELDS}
    counts = {k: sum(k in g["stats"] for g in games) for k in FIELDS}
    averages = {k: round(totals[k] / counts[k], 4) if counts[k] else None for k in FIELDS}
    return totals, averages, counts

def generate(season, start, through):
    by_player = defaultdict(list)
    sources = []
    identity = {}
    seen = {}
    for date, path in get_sources(start, through):
        records, audit = extract(date, path)
        sources.append(audit)
        for row in records:
            key = (row["date_et"], row["game_id"], row["player_id"])
            if key in seen:
                if seen[key] != row:
                    raise ValueError(f"conflicting duplicate game record {key}")
                continue
            seen[key] = row
            player_id = row["player_id"]
            prior = identity.get(player_id)
            if prior is not None and prior != row["name"]:
                # Names can change; retain the most recent displayed name while
                # preserving stable identity by the provider player ID.
                pass
            identity[player_id] = row["name"]
            by_player[player_id].append(row)
    players = {}
    for pid, games in sorted(by_player.items()):
        games.sort(key=lambda g: (g["date_et"], g["game_id"]))
        previous = []
        prepared = []
        for game in games:
            trailing = previous[-20:]
            # This is a pregame value: current game never enters its own baseline.
            base = round(sum(x["stats"]["fta"] for x in trailing) / len(trailing), 4) if (
                trailing and all("fta" in x["stats"] for x in trailing)) else None
            game = dict(game)
            game["pregame_rolling20_fta"] = base
            game["pregame_observed_games"] = len(previous)
            prepared.append(game)
            previous.append(game)
        totals, averages, counts = summarize(prepared)
        rolling_totals, rolling_averages, rolling_counts = summarize(prepared[-20:])
        players[pid] = {
            "player_id": pid, "name": identity[pid],
            "games_recorded": len(prepared), "latest_team": prepared[-1]["team"],
            "season_totals": totals,
            "season_averages_per_recorded_game": averages,
            "field_observation_counts": counts,
            "rolling20_games": len(prepared[-20:]),
            "rolling20_averages_per_recorded_game": rolling_averages,
            "rolling20_observation_counts": rolling_counts,
            "games": prepared,
        }
    # Overlay complete, individually verified ESPN FTA game logs where present.
    # Keep partial daily-box averages intact and separately labeled; never claim
    # the incomplete player-ledger window is a certified league-wide season.
    fta_archives = []
    fta_dir = ROOT / "data" / "historical" / "qpix_fta"
    for fta_path in sorted(fta_dir.glob("*.json")):
        date = fta_path.name[:10]
        if not DATE_RE.fullmatch(date) or not (start <= date <= through):
            continue
        fta_archive = load(fta_path)
        if fta_archive.get("date_et") != date:
            raise ValueError("Incorrect archived FTA date " + str(fta_path))
        for pid, observed in fta_archive.get("players", {}).items():
            if observed.get("status") != "ESPN_GAMELOG_VERIFIED" or pid not in players:
                continue
            current = next((g for g in players[pid]["games"]
                            if g["date_et"] == date and
                            str(g["game_id"]).removeprefix("ESPN_") ==
                            str(observed["current_game_id"])), None)
            if current is None:
                continue
            if current["stats"].get("fta") != observed["current_fta"]:
                raise ValueError("FTA archive current-game mismatch: " + pid)
            historical = observed["prior_season_game_rows"]
            if len(historical) != observed["previous_games"]:
                raise ValueError("Missing preceding game log rows: " + pid)
            all_fta = [x["fta"] for x in historical] + [observed["current_fta"]]
            recent = all_fta[-20:]
            players[pid]["verified_espn_fta"] = {
                "as_of_date_et": date,
                "source_file": str(fta_path.relative_to(ROOT)),
                "complete_to_observed_game": True,
                "game_count": len(all_fta),
                "season_fta_total": sum(all_fta),
                "season_fta_per_game": round(sum(all_fta) / len(all_fta), 4),
                "rolling20_games": len(recent),
                "rolling20_fta_per_game": round(sum(recent) / len(recent), 4),
                "pregame_rolling20_fta": observed["pregame_rolling20_fta"],
                "current_game_fta": observed["current_fta"],
            }
        fta_archives.append(str(fta_path.relative_to(ROOT)))
    checked = {a["date"] for a in sources}
    start_d, end_d = dt.date.fromisoformat(start), dt.date.fromisoformat(through)
    missing = [(start_d + dt.timedelta(days=i)).isoformat()
               for i in range((end_d - start_d).days + 1)
               if (start_d + dt.timedelta(days=i)).isoformat() not in checked]
    # Missing dates can be off-days; this is a coverage warning, NOT evidence
    # games occurred. No independent schedule completeness proof is performed.
    return {
        "schema_version": 1, "season": season, "season_start_et": start,
        "through_date_et": through, "status": "PARTIAL_UNVERIFIED_SEASON_COVERAGE",
        "baseline_policy": {
            "current_game_excluded_from_pregame_average": True,
            "rolling_window_games": 20,
            "safe_for_official_qpix_r": False,
            "reason": "No independent complete-season NBA schedule/player-participation audit. "
                      "Do not automatically substitute these partial observed-game averages.",
        },
        "coverage": {"source_dates": len(sources), "player_game_records": len(seen),
                     "unique_players": len(players),
                     "calendar_dates_without_selected_snapshot": missing,
                     "source_audits": sources,
                     "verified_espn_fta_archives": fta_archives},
        "players": players,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--start", default="2026-10-20")
    parser.add_argument("--through", default=(dt.datetime.now(dt.timezone.utc) -
                        dt.timedelta(days=1)).date().isoformat())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not DATE_RE.fullmatch(args.start) or not DATE_RE.fullmatch(args.through):
        parser.error("date must be YYYY-MM-DD")
    result = generate(args.season, args.start, args.through)
    out = ROOT / "data" / "seasonal" / args.season / "players.json"
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8") != payload:
            raise SystemExit("Seasonal file out of sync")
        print("SEASONAL_READ_BACK_OK", result["coverage"]["player_game_records"])
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print("SEASONAL_REBUILT", out, json.dumps(result["coverage"], ensure_ascii=False)[:650])
if __name__ == "__main__":
    main()
