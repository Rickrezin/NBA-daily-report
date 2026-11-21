"""Archived NBA live CDN retrieval and atomic, cross-provider C6 enrichment.

The live CDN transport is independent of stats.nba.com/V3. ESPN identity and
basic box lines remain intact; only reconciled official individual C6 is added.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import unicodedata
from zoneinfo import ZoneInfo

from c6_sources import C6_FIELDS, read_c6_fields

SCHEDULE_URLS = {
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
}
BOX_PREFIX = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_"
_ET = ZoneInfo("America/New_York")
_BASIC_FIELDS = {
    "points": "points", "rebounds": "reboundsTotal",
    "offensive_rebounds": "reboundsOffensive",
    "defensive_rebounds": "reboundsDefensive", "assists": "assists",
    "steals": "steals", "blocks": "blocks", "turnovers": "turnovers",
    "fgm": "fieldGoalsMade", "fga": "fieldGoalsAttempted",
    "fg3m": "threePointersMade", "fg3a": "threePointersAttempted",
    "ftm": "freeThrowsMade", "fta": "freeThrowsAttempted",
    "plus_minus": "plusMinusPoints",
}


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected an exact YYYY-MM-DD game date")
    return value


class NBAClient:
    """Use nba_api defaults and archive every received body before interpreting it."""

    def __init__(self, root, date_et):
        self.root = Path(root)
        self.date_et = _date(date_et)
        self.directory = self.root / "data/historical/qpix_raw" / self.date_et / "nba_live"
        self.raw_paths = {}
        self._cache = {}
        # nba_api's live HTTP class shares a requests session.
        self._lock = threading.RLock()

    def _archive(self, url, response):
        raw = response.get_response()
        if not isinstance(raw, str):
            raise ValueError("NBA client did not provide its raw response text")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        name = url.rsplit("/", 1)[-1].removesuffix(".json")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (name + "_" + digest + ".json")
        # Content-addressed names preserve earlier revisions instead of overwriting.
        path.write_text(raw, encoding="utf-8")
        self.raw_paths[url] = str(path)

    def fetch_json(self, url, timeout=12):
        """Fetch only approved official schedules or exact 10-digit boxscore IDs."""
        match = re.fullmatch(re.escape(BOX_PREFIX) + r"(\d{10})\.json", url)
        if url not in SCHEDULE_URLS and match is None:
            raise ValueError("Unsupported NBA CDN URL: " + str(url))
        with self._lock:
            if url in self._cache:
                return deepcopy(self._cache[url])
            # Lazy imports permit offline validation/tests without network packages.
            if match:
                from nba_api.live.nba.endpoints.boxscore import BoxScore
                endpoint = BoxScore(game_id=match.group(1), timeout=timeout, get_request=False)
                try:
                    endpoint.get_request()
                finally:
                    # get_request assigns nba_response before JSON decoding/load_response.
                    # Thus HTML errors and invalid schema bodies are retained too.
                    if endpoint.nba_response is not None:
                        self._archive(url, endpoint.nba_response)
                response = endpoint.nba_response
            else:
                from nba_api.live.nba.library.http import NBALiveHTTP

                class NBAStaticHTTP(NBALiveHTTP):
                    base_url = "https://cdn.nba.com/static/json/staticData/{endpoint}"

                response = NBAStaticHTTP().send_api_request(
                    endpoint=url.rsplit("/", 1)[-1], parameters={}, timeout=timeout,
                )
                self._archive(url, response)
            payload = response.get_dict()
            if not isinstance(payload, dict):
                raise ValueError("NBA CDN returned a non-object JSON payload")
            self._cache[url] = payload
            return deepcopy(payload)


NBALiveClient = NBAClient


def _alias(value):
    alias = str(value or "").strip().upper()
    return {"SA": "SAS", "GS": "GSW", "NO": "NOP", "NY": "NYK",
            "WSH": "WAS", "PHO": "PHX", "UTAH": "UTA"}.get(alias, alias)


def _name(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _integer(value, label, signed=False):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing or invalid " + label)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid " + label) from None
    if not math.isfinite(number) or number != int(number) or (number < 0 and not signed):
        raise ValueError("Invalid integer " + label)
    return int(number)


def _minutes(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing or invalid player minutes")
    raw = str(value).strip()
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", raw)
    if match and any(part is not None for part in match.groups()):
        number = int(match[1] or 0) * 60 + int(match[2] or 0) + float(match[3] or 0) / 60
    elif re.fullmatch(r"\d+:\d{2}(?:\.\d+)?", raw):
        mins, seconds = raw.split(":")
        if float(seconds) >= 60:
            raise ValueError("Invalid seconds in minutes")
        number = int(mins) + float(seconds) / 60
    else:
        try:
            number = float(raw)
        except ValueError:
            raise ValueError("Invalid player minutes") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError("Invalid player minutes")
    return number


def _game_date(game):
    for key in ("gameTimeUTC", "gameEt", "gameTimeLocal", "gameTimeHome", "gameTimeAway"):
        value = game.get(key)
        if not value:
            continue
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid NBA game time: " + key) from None
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("NBA game time lacks a UTC offset: " + key)
        return stamp.astimezone(_ET).date().isoformat()
    raise ValueError("NBA game has no offset-aware game time")


def apply_live_boxscore(game, players, payload, nba_game_id, date_et):
    """Validate a full game, then atomically add official C6 and separate NBA IDs.

    Missing C6 remains missing. Returns an audit; raises before any mutation for
    identity, date, score, base-box-line, minute, or existing-field conflicts.
    """
    _date(date_et)
    nba_game_id = str(nba_game_id)
    if not re.fullmatch(r"\d{10}", nba_game_id):
        raise ValueError("Invalid requested NBA game ID")
    official = payload.get("game") if isinstance(payload, dict) else None
    if not isinstance(official, dict):
        raise ValueError("NBA CDN payload has no game object")
    if str(official.get("gameId", "")) != nba_game_id:
        raise ValueError("NBA game ID mismatch")
    if _integer(official.get("gameStatus"), "gameStatus") != 3:
        raise ValueError("NBA game is not FINAL")
    if _game_date(official) != date_et or game.get("date_et", date_et) != date_et:
        raise ValueError("NBA/ESPN Eastern game date mismatch")
    if game.get("nba_game_id") not in (None, nba_game_id):
        raise ValueError("Existing NBA game ID conflict")
    teams = {}
    for side in ("away", "home"):
        team = official.get(side + "Team")
        if not isinstance(team, dict):
            raise ValueError("Missing NBA " + side + " team")
        alias = _alias(team.get("teamTricode"))
        if not alias or alias != _alias(game.get(side + "_alias")):
            raise ValueError("NBA/ESPN " + side + " team mismatch")
        score = _integer(team.get("score"), "NBA final score")
        if score != _integer(game.get(side + "_points"), "ESPN final score"):
            raise ValueError("NBA/ESPN final score mismatch for " + alias)
        if alias in teams:
            raise ValueError("Duplicate NBA home/away team")
        teams[alias] = (team, score)

    nba_rows = {}
    nba_ids = set()
    for alias, (team, score) in teams.items():
        rows = team.get("players")
        if not isinstance(rows, list):
            raise ValueError("Missing NBA team player list")
        points_total = 0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid NBA player row")
            stats = row.get("statistics", {})
            if not isinstance(stats, dict):
                raise ValueError("Invalid NBA player statistics")
            if stats.get("minutes") is None and (row.get("played") in (0, "0") or row.get("status") == "INACTIVE"):
                continue
            minutes = _minutes(stats.get("minutes"))
            if minutes <= 0:
                continue
            name = row.get("name") or (str(row.get("firstName") or "") + " " + str(row.get("familyName") or "")).strip()
            key = (alias, _name(name))
            if not key[1] or key in nba_rows:
                raise ValueError("Missing or duplicate NBA player/team identity: " + str(key))
            pid = _integer(row.get("personId"), "NBA personId")
            if pid <= 0 or pid in nba_ids:
                raise ValueError("Missing or duplicate NBA personId")
            nba_ids.add(pid)
            nba_rows[key] = (row, stats, minutes, pid)
            points_total += _integer(stats.get("points"), "NBA player points")
        if points_total != score:
            raise ValueError("NBA player points do not reconcile for " + alias)

    expected = {}
    player_ids = set()
    for player in players:
        if _minutes(player.get("minutes")) <= 0:
            raise ValueError("Expected only minute-positive input players")
        key = (_alias(player.get("team")), _name(player.get("name")))
        pid = player.get("player_id")
        if key[0] not in teams or not key[1] or key in expected or pid is None or str(pid) in player_ids:
            raise ValueError("Missing or duplicate input player identity: " + str(key))
        if player.get("game_id") != game.get("game_id"):
            raise ValueError("Input player belongs to a different game")
        player_ids.add(str(pid))
        expected[key] = player
    if set(expected) != set(nba_rows):
        missing = sorted(set(expected) - set(nba_rows))
        extra = sorted(set(nba_rows) - set(expected))
        raise ValueError("NBA/ESPN player identities differ; missing=" + repr(missing) + "; extra=" + repr(extra))
    if not expected:
        raise ValueError("No minute-positive players to reconcile")

    staged = []
    new_fields = 0
    source = BOX_PREFIX + nba_game_id + ".json"
    for key, player in expected.items():
        row, stats, minutes, nba_pid = nba_rows[key]
        for field, nba_field in _BASIC_FIELDS.items():
            left = _integer(player.get(field), "input " + field, signed=field == "plus_minus")
            right = _integer(stats.get(nba_field), "NBA " + nba_field, signed=field == "plus_minus")
            if left != right:
                raise ValueError("NBA/ESPN " + field + " mismatch for " + player["name"])
        input_minutes = _minutes(player.get("minutes"))
        raw_minutes = str(player.get("minutes"))
        precise = ":" in raw_minutes or raw_minutes.startswith("PT") or not input_minutes.is_integer()
        tolerance = 1 / 60 + 1e-6 if precise else 1.0 + 1e-6
        if abs(input_minutes - minutes) > tolerance:
            raise ValueError("NBA/ESPN minutes mismatch for " + player["name"])
        if player.get("nba_player_id") is not None and str(player["nba_player_id"]) != str(nba_pid):
            raise ValueError("Existing NBA player ID conflict for " + player["name"])
        if player.get("nba_game_id") not in (None, nba_game_id):
            raise ValueError("Existing player NBA game ID conflict for " + player["name"])
        fields = read_c6_fields(stats)
        for field, value in fields.items():
            if value > _integer(player["points"], "player points"):
                raise ValueError("NBA " + field + " exceeds player points for " + player["name"])
            if field in player and player[field] is not None and player[field] != value:
                raise ValueError("Existing " + field + " conflict for " + player["name"])
            if field not in player or player[field] is None:
                new_fields += 1
        staged.append((player, fields, nba_pid))

    # Every validation above is completed before mutating any player or game.
    for player, fields, nba_pid in staged:
        player.update(fields)
        player["nba_player_id"] = str(nba_pid)
        player["nba_game_id"] = nba_game_id
        player["nba_live_source"] = source
        player["nba_live_c6_fields"] = sorted(fields)
    game["nba_game_id"] = nba_game_id
    coverage = {field: sum(player.get(field) is not None for player in players) for field in C6_FIELDS}
    return {
        "status": "ok" if all(count == len(players) for count in coverage.values()) else "partial",
        "source": source, "nba_game_id": nba_game_id, "date_et": date_et,
        "matched_players": len(staged), "total": len(players), "coverage": coverage,
        "source_coverage": {field: sum(field in fields for _, fields, _ in staged) for field in C6_FIELDS},
        "new_fields": new_fields, "identity_method": "unique_normalized_name_and_team",
        "validation": "final_date_teams_scores_all_basic_box_fields_and_minutes",
    }
