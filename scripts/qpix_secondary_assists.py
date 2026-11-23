"""Join NBA-tracked secondary assists to independently verified game/player IDs."""
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qpix_nba_live import _alias, _game_date, _minutes


def tracking_url(game_id):
    if not re.fullmatch(r"[0-9]{10}", str(game_id)):
        raise ValueError("Invalid NBA game ID for player tracking")
    query = urlencode({"GameID": game_id, "LeagueID": "00", "startPeriod": 0, "endPeriod": 0,
                       "startRange": 0, "endRange": 0, "rangeType": 0})
    return "https://stats.nba.com/stats/boxscoreplayertrackv3?" + query


def fetch_tracking_response(url, timeout):
    accept = "text/html" if url.startswith("https://www.nba.com/") else "application/json"
    request = Request(url, headers={"User-Agent": "QCoreLabs-QPIX/1.0", "Accept": accept})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _tracked_minutes(value):
    # Tracking displays some rounded seconds as MM:60. They still describe
    # played rows and are used here only to distinguish them from DNPs.
    rollover = re.fullmatch(r"(\d+):60(?:\.0+)?", str(value))
    return int(rollover[1]) + 1 if rollover else _minutes(value)


def apply_secondary_assists(game, players, payload, date_et):
    """Apply verified counts atomically. Unmatched or untracked rows stay null."""
    game_id = game.get("nba_game_id")
    tracking_url(game_id)  # Validate that this is an NBA game ID, not an ESPN ID.
    if date.fromisoformat(date_et).isoformat() != date_et or game.get("date_et") != date_et:
        raise ValueError("Tracking input does not match the verified Eastern game date")
    if game.get("status") != "FINAL":
        raise ValueError("Secondary assists require a final game")
    box = payload.get("boxScorePlayerTrack")
    if not isinstance(box, dict) or str(box.get("gameId")) != str(game_id):
        raise ValueError("NBA tracking payload has the wrong game ID")
    if any(box.get(field) for field in ("gameTimeUTC", "gameEt")) and _game_date(box) != date_et:
        raise ValueError("Tracking payload has the wrong Eastern game date")
    if "gameStatus" in box and box["gameStatus"] != 3:
        raise ValueError("NBA tracking payload is not final")

    teams = {}
    tracked_teams = {}
    for side in ("away", "home"):
        team = box.get(side + "Team") or {}
        alias = _alias(team.get("teamTricode"))
        if not alias or alias != _alias(game.get(side + "_alias")) or alias in teams:
            raise ValueError("NBA tracking payload has the wrong teams")
        team_id = team.get("teamId")
        if type(team_id) is not int or team_id <= 0 or team_id != box.get(side + "TeamId"):
            raise ValueError("NBA tracking payload has the wrong team ID")
        team_rows = team.get("players")
        if not isinstance(team_rows, list):
            raise ValueError("NBA tracking is missing the player roster")
        roster = {}
        for row in team_rows:
            stats = row.get("statistics") or {}
            minutes = stats.get("minutes")
            if not minutes or _tracked_minutes(minutes) <= 0:
                continue
            person_id = row.get("personId")
            if type(person_id) is not int or person_id <= 0 or str(person_id) in tracked_teams:
                raise ValueError("NBA tracking has an invalid or duplicate active player ID")
            tracked_teams[str(person_id)] = alias
            roster[str(person_id)] = stats

        # The feed can return zero-filled placeholders. Require observed tracking
        # activity for the team before treating any recorded zero as a real count.
        if not any((_count(stats.get("passes")) or 0) > 0 for stats in roster.values()):
            teams[alias] = {}
            continue
        counts = {pid: _count(stats.get("secondaryAssists")) for pid, stats in roster.items()}
        team_count = _count((team.get("statistics") or {}).get("secondaryAssists"))
        if team_count is not None and all(count is not None for count in counts.values()):
            if sum(counts.values()) != team_count:
                raise ValueError("NBA tracking secondary assists do not reconcile for " + alias)
        teams[alias] = counts

    staged = []
    seen = set()
    for player in players:
        if player.get("game_id") != game.get("game_id"):
            raise ValueError("Secondary-assist player belongs to a different game")
        pid = str(player.get("nba_player_id") or "")
        player_game_id = player.get("nba_game_id")
        if not pid or player_game_id is None:
            staged.append((player, None))
            continue
        alias = _alias(player.get("team"))
        if (str(player_game_id) != str(game_id) or not re.fullmatch(r"[1-9][0-9]*", pid)
                or alias not in teams or pid in seen):
            raise ValueError("Secondary-assist player has a conflicting verified identity")
        seen.add(pid)
        count = teams[alias].get(pid)
        if tracked_teams.get(pid, alias) != alias:
            raise ValueError("Secondary-assist player appeared for the wrong NBA team")
        staged.append((player, count))

    missing = []
    for player, count in staged:
        player["2AST"] = count
        if count is None:
            missing.append(str(player["player_id"]))
    return {
        "nba_game_id": str(game_id), "date_et": date_et, "total": len(staged),
        "verified": len(staged) - len(missing), "missing_player_ids": missing,
        "status": "complete" if not missing else ("partial" if len(missing) < len(staged) else "unavailable"),
    }


def _tracking_page(game):
    away, home = (_alias(game.get(side + "_alias")).lower() for side in ("away", "home"))
    if not all(re.fullmatch(r"[a-z0-9]+", alias) for alias in (away, home)):
        raise ValueError("Game has invalid team abbreviations")
    return f'https://www.nba.com/game/{away}-vs-{home}-{game["nba_game_id"]}/box-score?type=tracking'


def _page_payload(body):
    section = re.search(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.DOTALL)
    if not section:
        raise ValueError("NBA tracking page has no embedded box score")
    return {"boxScorePlayerTrack": json.loads(section[1])["props"]["pageProps"]["game"]}


def collect_secondary_assists(game, players, date_et, root, fetch):
    """Archive the official tracking box score and use the public game page as fallback."""
    if date.fromisoformat(date_et).isoformat() != date_et:
        raise ValueError("Invalid Eastern date for secondary-assist archive")
    record = {"game_id": game["game_id"], "date_et": date_et, "nba_game_id": game.get("nba_game_id"),
              "verified": 0, "total": len(players), "missing_player_ids": [str(p["player_id"]) for p in players],
              "attempts": []}
    if not game.get("nba_game_id") or not any(p.get("nba_player_id") and p.get("nba_game_id") for p in players):
        return {**record, "status": "missing_verified_nba_identity"}
    observations = [set() for _ in players]
    sources = ((tracking_url(game["nba_game_id"]), json.loads, "json"),
               (_tracking_page(game), _page_payload, "html"))
    for endpoint, parse, extension in sources:
        attempt = {"source": endpoint}
        record["attempts"].append(attempt)
        try:
            raw = fetch(endpoint, timeout=12).encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            path = Path("data/historical/qpix_raw") / date_et / "nba_tracking" / f'{game["nba_game_id"]}_{digest}.{extension}'
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(raw)
            attempt.update({"raw_path": path.as_posix(), "sha256": digest})
            candidates = [dict(player) for player in players]
            attempt.update(apply_secondary_assists(game, candidates, parse(raw.decode("utf-8")), date_et))
            for values, candidate in zip(observations, candidates):
                if candidate["2AST"] is not None:
                    values.add(candidate["2AST"])
            if all(len(values) == 1 for values in observations):
                break
        except Exception as exc:
            attempt.update({"status": "unavailable_or_invalid", "error": str(exc)[:300]})
    conflicts = {}
    missing = []
    for player, values in zip(players, observations):
        pid = str(player["player_id"])
        player["2AST"] = next(iter(values)) if len(values) == 1 else None
        if player["2AST"] is None:
            missing.append(pid)
        if len(values) > 1:
            conflicts[pid] = sorted(values)
    verified = len(players) - len(missing)
    record.update({"verified": verified, "missing_player_ids": missing, "conflicts": conflicts,
                   "status": "complete" if not missing else ("partial" if verified else "unavailable")})
    return record


def require_secondary_assist_coverage(enabled, verified, total):
    if enabled and verified != total:
        raise ValueError(f"Secondary-assist scoring requires complete tracking coverage ({verified}/{total}); "
                         "baseline reports remain intact")
