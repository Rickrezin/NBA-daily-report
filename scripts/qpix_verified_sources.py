"""QPIX strict per-player C3 ratings from a previously validated Basketball-Reference archive.

This is a replay/verification source, not a source of fresh ratings. A game/date,
ESPN identity and core box-score line must reconcile before any value is reused.
NBA.com's on-court OFF_RATING/DEF_RATING are NOT substitutes for the individual
Dean Oliver ORtg/DRtg required by the authorized QPIX engine.
"""
import json
from pathlib import Path

CORE_FIELDS=("points","rebounds","assists","steals","blocks","turnovers",
             "fgm","fga","fg3m","fg3a","ftm","fta","offensive_rebounds","defensive_rebounds")

def populate_verified_ratings(players, date_et, root):
    file=Path(root)/"data"/"daily"/(date_et+".json")
    audit={"source":str(file),"status":"absent","assigned":0,"players":len(players),"mismatches":[]}
    if not file.exists():return audit
    data=json.loads(file.read_text(encoding="utf-8"))
    if data.get("date_et")!=date_et:raise ValueError("C3 archive date mismatch")
    if data.get("data_quality",{}).get("individual_ratings_verified") != len(data.get("players",[])):
        raise ValueError("C3 archive was not fully verified")
    records={}
    for p in data["players"]:
        key=(str(p["player_id"]),p["team"],p["game"])
        if key in records:raise ValueError("Duplicate archived participant "+str(key))
        records[key]=p
    matched=0
    for p in players:
        key=(str(p.get("player_id")),p["team"],p["game"])
        rec=records.get(key)
        if rec is None:
            audit["mismatches"].append({"name":p["name"],"reason":"not archived"})
            continue
        differences=[f for f in CORE_FIELDS if int(p[f])!=int(rec[f])]
        if abs(float(p["minutes"])-float(rec["minutes"])) > 1.01:
            differences.append("minutes")
        if differences:
            audit["mismatches"].append({"name":p["name"],"fields":differences})
            continue
        off=rec.get("offensive_rating");de=rec.get("defensive_rating")
        if not isinstance(off,(int,float)) or not isinstance(de,(int,float)):
            audit["mismatches"].append({"name":p["name"],"reason":"individual ratings missing"})
            continue
        if "offensive_rating" in p or "defensive_rating" in p:
            if p.get("offensive_rating")!=off or p.get("defensive_rating")!=de:
                raise ValueError("C3 ratings conflicting for "+p["name"])
        p["offensive_rating"]=off
        p["defensive_rating"]=de
        matched+=1
    audit.update({"status":"fully_reconciled" if matched==len(players) else "partial",
                  "assigned":matched,"archive_count":len(records)})
    return audit
