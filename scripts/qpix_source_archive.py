"""QCore Labs QPIX canonical pre-scoring player archive.

Collect each source independently, then reconcile before any scoring. A valid
source-side zero is different from an absent value. Only the original
Basketball-Reference-style individual ratings count toward C3 completeness.
This module does NOT alter the authorized JavaScript scoring formulas.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

C3=("offensive_rating","defensive_rating")
C6=("points_in_paint","fast_break_points","second_chance_points")
REQUIRED=C3+C6

def canonical_snapshot(games, players, date_et, audits, require_complete=True):
    if not games or not players:
        raise ValueError("No final games or scored player records")
    if len({(g["away_alias"],g["home_alias"]) for g in games})!=len(games):
        raise ValueError("Duplicate game in QCore archive")
    by_game={}
    for game in games:
        key=game["game_id"]
        if key in by_game:raise ValueError("Duplicate game ID "+str(key))
        by_game[key]=game
    seen=set()
    coverage={field:0 for field in REQUIRED}
    missing={field:[] for field in REQUIRED}
    player_export=[]
    for player in players:
        pid=str(player.get("player_id") or "")
        gid=player.get("game_id")
        if not pid or gid not in by_game:
            raise ValueError("Unresolved player ID or game assignment")
        key=(str(gid),pid)
        if key in seen:raise ValueError("Duplicate scored player "+str(key))
        seen.add(key)
        game=by_game[gid]
        if player["team"] not in (game["home_alias"],game["away_alias"]):
            raise ValueError("Player team differs from game")
        record=dict(player)
        for field in REQUIRED:
            value=record.get(field)
            if value is None:
                record.pop(field,None)
                missing[field].append({"game_id":gid,"player_id":pid,"name":record.get("name")})
            else:
                if isinstance(value,bool) or not isinstance(value,(int,float)):
                    raise ValueError("Invalid "+field+" for "+str(key))
                if field in C6 and (value<0 or int(value)!=value):
                    raise ValueError("Invalid "+field+" for "+str(key))
                coverage[field]+=1
        player_export.append(record)
    for g in games:
        for team,score in ((g["home_alias"],g["home_points"]),(g["away_alias"],g["away_points"])):
            total=sum(p["points"] for p in player_export if p["game_id"]==g["game_id"] and p["team"]==team)
            if total!=score:raise ValueError("Team points mismatch "+str(g["game_id"])+":"+team)
    complete=all(n==len(player_export) for n in coverage.values())
    doc={
        "schema_version":1,
        "date_et":date_et,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "purpose":"Canonical QCore Labs QPIX input before authorized engine execution",
        "methodology":{"C3":"Individual Basketball-Reference/Dean Oliver ORtg/DRtg ONLY; NBA.com on-court ratings are not substituted",
                       "C6":"Individual player-level paint, fast-break and second-chance points; absent is not zero"},
        "source_audit":audits,
        "coverage":{"players":len(player_export),"games":len(games),"fields":coverage,
                    "complete":complete,"missing":missing},
        "games":games,"players":player_export
    }
    # Verify fully round-trippable, deterministic core content independent of timestamp.
    canonical=json.dumps({"games":games,"players":player_export},sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    doc["input_sha256"]=hashlib.sha256(canonical).hexdigest()
    if require_complete and not complete:
        counts={field:len(rows) for field,rows in missing.items() if rows}
        raise ValueError("Incomplete QPIX inputs: "+json.dumps(counts,sort_keys=True))
    return doc

def write_snapshot(snapshot, root):
    date=snapshot["date_et"]
    output=Path(root)/"data"/"historical"/"qpix_input"/(date+".json")
    output.parent.mkdir(parents=True,exist_ok=True)
    # Existing historical inputs must not silently be overwritten.
    new=json.dumps(snapshot,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if output.exists():
        existing=json.loads(output.read_text(encoding="utf-8"))
        if existing.get("input_sha256")!=snapshot["input_sha256"]:
            raise ValueError("Historical archive conflict; refuse overwrite "+str(output))
        return output
    output.write_text(new,encoding="utf-8")
    return output
