"""QPIX C6 source adapters. Never manufacture missing player statistics.

Official NBA LiveData and BoxScoreMiscV3 use different field names.
Only source-backed integer values are attached to player rows. No team
statistics or estimated values may substitute for individual results.
"""
import re

C6_ALIASES = {
    "points_in_paint": ("pointsPaint", "pointsInThePaint", "points_in_paint", "PTS_PAINT"),
    "fast_break_points": ("pointsFastBreak", "fastBreakPoints", "fast_break_points", "PTS_FB"),
    "second_chance_points": ("pointsSecondChance", "secondChancePoints", "second_chance_points", "PTS_2ND_CHANCE"),
}
C6_FIELDS = tuple(C6_ALIASES)

def read_c6_fields(stats):
    """Return existing nonnegative integral values; leave absent data absent."""
    result = {}
    if not isinstance(stats, dict):
        return result
    for destination, aliases in C6_ALIASES.items():
        for alias in aliases:
            if alias not in stats or stats[alias] is None:
                continue
            raw = stats[alias]
            if isinstance(raw, bool):
                raise ValueError("Boolean is not a valid C6 score: " + alias)
            if isinstance(raw, str):
                if not re.fullmatch(r"\\d+", raw.strip()):
                    raise ValueError("Invalid C6 score " + alias + ": " + repr(raw))
                raw = int(raw.strip())
            if not isinstance(raw, (int, float)) or int(raw) != raw or raw < 0:
                raise ValueError("Invalid C6 score " + alias + ": " + repr(raw))
            result[destination] = int(raw)
            break
    return result

def misc_v3_player_rows(payload):
    """Support the nba_api V3 list and NBA's home/away nested response shapes."""
    box = payload.get("boxScoreMisc", payload) if isinstance(payload, dict) else {}
    rows = box.get("playerStats", []) if isinstance(box, dict) else []
    if isinstance(rows, list) and rows:
        return rows
    nested=[]
    for team in ("homeTeam", "awayTeam"):
        obj=box.get(team,{}) if isinstance(box,dict) else {}
        nested.extend(obj.get("players",[]) if isinstance(obj,dict) else [])
    return nested

def apply_c6_rows(players, rows, source_name):
    """Merge by unique, nonempty personId only; never guess a player by name."""
    by_id = {}
    for row in rows:
        if not isinstance(row,dict):
            continue
        pid=row.get("personId") or row.get("person_id")
        if pid is None:
            continue
        key=str(pid)
        if key in by_id:
            raise ValueError("Duplicate source player ID " + key + " in " + source_name)
        by_id[key]=row
    matched=0
    assigned=0
    for player in players:
        pid=player.get("player_id")
        if pid is None or str(pid) not in by_id:
            continue
        row=by_id[str(pid)]
        source_fields=read_c6_fields(row.get("statistics", row))
        if not source_fields:
            continue
        matched+=1
        for key,value in source_fields.items():
            if key in player and player[key]!=value:
                raise ValueError(f"Conflicting {key} for {pid}: {player[key]} != {value}")
            if key not in player:
                player[key]=value
                assigned+=1
    coverage={key:sum(key in p for p in players) for key in C6_FIELDS}
    return {"source":source_name,"matched_players":matched,"new_fields":assigned,"coverage":coverage,"total":len(players)}
