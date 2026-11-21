"""Fresh, reconciled Basketball-Reference individual ORtg/DRtg for QPIX.

This module never substitutes NBA on-court ratings or invents missing values.
A raw page is archived before parsing; participant identity and the complete
basic box line must reconcile before its individual advanced ratings are used.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlparse

ALIASES = {
    "NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP", "WSH": "WAS",
    "UTAH": "UTA", "BRK": "BKN", "PHO": "PHX", "CHO": "CHA",
}
BREF_CODES = {"BKN": "BRK", "PHX": "PHO", "CHA": "CHO"}
BOX_FIELDS = {
    "points": "pts", "rebounds": "trb", "assists": "ast", "steals": "stl",
    "blocks": "blk", "turnovers": "tov", "fgm": "fg", "fga": "fga",
    "fg3m": "fg3", "fg3a": "fg3a", "ftm": "ft", "fta": "fta",
    "offensive_rebounds": "orb", "defensive_rebounds": "drb",
}


def alias(value):
    text = str(value).upper()
    return ALIASES.get(text, text)


def normalized_name(value):
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def minutes(value):
    text = str(value)
    if re.fullmatch(r"\d+:\d{2}", text):
        mm, ss = text.split(":")
        if int(ss) >= 60:
            raise ValueError("Invalid minutes")
        return int(mm) + int(ss) / 60
    number = float(text)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Invalid minutes")
    return number


def integer(value):
    # Missing/blank cells are never read as observed zero.
    if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value).strip()):
        raise ValueError("Missing or invalid integer")
    return int(value)


def rating(value):
    if value is None or isinstance(value, bool) or not str(value).strip():
        raise ValueError("Missing rating")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Nonfinite or invalid rating")
    return number


class BoxPage(HTMLParser):
    """Read only full-game tables, preserving provider identities and totals."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonical = []
        self.tables = {}
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical.append(attrs.get("href", ""))
        if tag == "table":
            match = re.fullmatch(r"box-([A-Z]{2,3})-game-(basic|advanced)", attrs.get("id", ""))
            if match:
                key = (alias(match[1]), match[2])
                if key in self.tables:
                    raise ValueError("Duplicate full-game table " + str(key))
                self.table = key
                self.tables[key] = []
        if self.table is None:
            return
        if tag == "tr":
            self.row = {}
        if tag in ("th", "td") and self.row is not None:
            self.cell = [attrs.get("data-stat"), []]
            if attrs.get("data-stat") == "player" and attrs.get("data-append-csv"):
                self.row["player_id"] = attrs["data-append-csv"]
        if tag == "a" and self.cell is not None and self.cell[0] == "player":
            match = re.fullmatch(r"/players/[a-z]/([a-z0-9]+)\.html", attrs.get("href", ""))
            if match:
                if self.row.get("player_id") not in (None, match[1]):
                    raise ValueError("Inconsistent Basketball-Reference player identity")
                self.row["player_id"] = match[1]

    def handle_data(self, text):
        if self.cell is not None:
            self.cell[1].append(text)

    def handle_endtag(self, tag):
        if self.table is None:
            return
        if tag in ("th", "td") and self.cell is not None:
            if self.cell[0]:
                self.row[self.cell[0]] = "".join(self.cell[1]).strip()
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.tables[self.table].append(self.row)
            self.row = None
        if tag == "table":
            self.table = None
            self.row = None
            self.cell = None

    def handle_comment(self, text):
        # Basketball-Reference can place complete stat tables in HTML comments.
        if re.search(r'<table\b[^>]*\bid=["\x27]box-[A-Z]{2,3}-game-(?:basic|advanced)', text):
            other = BoxPage()
            other.feed(text)
            for key, rows in other.tables.items():
                if key in self.tables:
                    raise ValueError("Duplicate full-game table in comment " + str(key))
                self.tables[key] = rows


def _page_candidates(game, players, date_et, raw, expected_url):
    """Validate the game and stage player additions without mutating inputs."""
    page = BoxPage()
    page.feed(raw.decode("utf-8", "replace"))
    if len(page.canonical) != 1:
        raise ValueError("Missing or ambiguous page canonical URL")
    actual = urlparse(page.canonical[0])
    expected = urlparse(expected_url)
    if actual.netloc != expected.netloc or actual.path != expected.path:
        raise ValueError("Page date/home-team identity mismatch")
    if game.get("date_et") not in (None, date_et):
        raise ValueError("Input game date mismatch")
    home, away = alias(game["home_alias"]), alias(game["away_alias"])
    if home == away:
        raise ValueError("Home and away team are identical")
    required = {(team, kind) for team in (home, away) for kind in ("basic", "advanced")}
    if set(page.tables) != required:
        raise ValueError("Full-game table teams or basic/advanced coverage mismatch")
    scores = {home: integer(game["home_points"]), away: integer(game["away_points"])}
    active = {}
    advanced = {}
    for team in (home, away):
        basic_rows = page.tables[(team, "basic")]
        totals = [r for r in basic_rows if not r.get("player_id") and r.get("player") == "Team Totals"]
        if len(totals) != 1 or integer(totals[0].get("pts")) != scores[team]:
            raise ValueError("Final team total mismatch for " + team)
        seen_basic = set()
        team_points = 0
        for row in basic_rows:
            pid = row.get("player_id")
            if not pid:
                continue
            if pid in seen_basic:
                raise ValueError("Duplicate basic player identity " + pid)
            seen_basic.add(pid)
            # DNP/inactive rows have no minutes; zero-minute rows are not participants.
            if not row.get("mp"):
                continue
            if minutes(row["mp"]) <= 0:
                continue
            key = (team, pid)
            active[key] = row
            team_points += integer(row.get("pts"))
        if team_points != scores[team]:
            raise ValueError("Player point sum does not reconcile for " + team)
        for row in page.tables[(team, "advanced")]:
            pid = row.get("player_id")
            if not pid:
                continue
            key = (team, pid)
            if key in advanced:
                raise ValueError("Duplicate advanced player identity " + pid)
            advanced[key] = row

    # Both sources must describe the same minute-positive participant set.
    source_names = defaultdict(list)
    for key, row in active.items():
        source_names[(key[0], normalized_name(row.get("player", "")))].append(key)
    target_names = defaultdict(list)
    for index, player in enumerate(players):
        team = alias(player["team"])
        if team not in scores or minutes(player["minutes"]) <= 0:
            raise ValueError("Unexpected target participant")
        if str(player.get("game_id")) != str(game.get("game_id")):
            raise ValueError("Target player game identity mismatch")
        target_names[(team, normalized_name(player["name"]))].append(index)
    if any(len(v) != 1 for v in source_names.values()) or any(len(v) != 1 for v in target_names.values()):
        raise ValueError("Ambiguous normalized player identity")
    if set(source_names) != set(target_names):
        raise ValueError("Minute-positive participant set differs from Basketball-Reference")

    pending = []
    issues = []
    for name_key, indices in target_names.items():
        player = players[indices[0]]
        source_key = source_names[name_key][0]
        basic = active[source_key]
        advanced_row = advanced.get(source_key)
        issue = {"name": player["name"], "team": alias(player["team"])}
        if advanced_row is None:
            issues.append(dict(issue, reason="advanced_player_missing"))
            continue
        if normalized_name(advanced_row.get("player", "")) != normalized_name(basic["player"]):
            raise ValueError("Basic/advanced player name mismatch")
        try:
            mismatches = [field for field, column in BOX_FIELDS.items()
                          if integer(player.get(field)) != integer(basic.get(column))]
            observed_minutes = minutes(player["minutes"])
            source_minutes = minutes(basic.get("mp"))
            # ESPN rounds to whole minutes. Precise sources must agree within a second.
            tolerance = 1.01 if observed_minutes.is_integer() else (1.01 / 60)
            if abs(observed_minutes - source_minutes) > tolerance:
                mismatches.append("minutes")
            if abs(minutes(advanced_row.get("mp")) - source_minutes) > (1.01 / 60):
                mismatches.append("basic_advanced_minutes")
            if mismatches:
                issues.append(dict(issue, reason="box_line_mismatch", fields=mismatches))
                continue
            off = rating(advanced_row.get("off_rtg"))
            defense = rating(advanced_row.get("def_rtg"))
        except (TypeError, ValueError, KeyError) as exc:
            issues.append(dict(issue, reason="missing_or_invalid_observation", error=str(exc)))
            continue
        if ("offensive_rating" in player or "defensive_rating" in player) and (
                player.get("offensive_rating") != off or player.get("defensive_rating") != defense):
            raise ValueError("Existing rating conflicts with observed Basketball-Reference value for " + player["name"])
        pending.append((indices[0], off, defense, source_key[1]))
    return pending, issues


def collect_game_ratings(game, players, date_et, root, fetch_text):
    """Fetch, archive, reconcile, and apply fresh individual ratings for one game.

    fetch_text(url, timeout=17) must return bytes or UTF-8 text. Retrieval,
    structural, or identity failures leave every input player untouched.
    A player with an incomplete or mismatched box line receives no ratings.
    """
    date.fromisoformat(date_et)
    home = alias(game["home_alias"])
    home_code = BREF_CODES.get(home, home)
    if not re.fullmatch(r"[A-Z]{3}", home_code):
        raise ValueError("Invalid home-team code")
    page_id = date_et.replace("-", "") + "0" + home_code
    url = "https://www.basketball-reference.com/boxscores/" + page_id + ".html"
    destination = Path(root) / "data" / "historical" / "qpix_bref_raw" / date_et
    destination.mkdir(parents=True, exist_ok=True)
    raw_path = destination / (page_id + ".html")
    audit = {
        "source": url, "date_et": date_et, "game_id": game.get("game_id"),
        "provider": "Basketball-Reference", "methodology": "individual Dean Oliver ORtg/DRtg",
        "players": len(players), "assigned": 0, "status": "unavailable", "issues": [],
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        response = fetch_text(url, timeout=17)
        raw = response if isinstance(response, bytes) else response.encode("utf-8")
        if not raw:
            raise ValueError("Empty page")
        raw_path.write_bytes(raw)
        audit.update(raw_path=str(raw_path.relative_to(root)), raw_sha256=sha256(raw).hexdigest())
        pending, issues = _page_candidates(game, players, date_et, raw, url)
        # Commit all validated additions together after game-wide safety checks.
        for index, off, defense, pid in pending:
            players[index].update(
                offensive_rating=off, defensive_rating=defense,
                bref_player_id=pid, bref_source=url, bref_source_sha256=audit["raw_sha256"],
            )
        audit.update(assigned=len(pending), issues=issues,
                     status="fully_reconciled" if len(pending) == len(players) else "partial")
    except Exception as exc:
        audit.update(status="validation_failed" if "raw_sha256" in audit else "retrieval_failed",
                     issues=[{"reason": type(exc).__name__, "error": str(exc)[:300]}])
    (destination / (page_id + ".audit.json")).write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return audit

