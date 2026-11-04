"""QPIX C6 adapters: ESPN/LiveData/MiscV3 field discovery and strict player merge.

Missing C6 is never recorded as observed zero. Team-level numbers are never
accepted as individual statistics. Cross-provider identity requires verified
team + unique normalized name when personId differs.
"""
import re
import unicodedata

C6_ALIASES={
    "points_in_paint":("pointsPaint","pointsInThePaint","points_in_paint","PTS_PAINT"),
    "fast_break_points":("pointsFastBreak","fastBreakPoints","fast_break_points","PTS_FB"),
    "second_chance_points":("pointsSecondChance","secondChancePoints","second_chance_points","PTS_2ND_CHANCE"),
}
C6_FIELDS=tuple(C6_ALIASES)

def read_c6_fields(stats):
    out={}
    if not isinstance(stats,dict):return out
    for target,aliases in C6_ALIASES.items():
        values=[]
        for alias in aliases:
            if alias not in stats or stats[alias] is None:continue
            raw=stats[alias]
            if isinstance(raw,bool):raise ValueError("Boolean C6 value for "+alias)
            if isinstance(raw,str):
                if not re.fullmatch(r"\d+",raw.strip()):
                    raise ValueError("Invalid integer C6 value "+alias+": "+repr(raw))
                raw=int(raw.strip())
            if not isinstance(raw,(int,float)) or int(raw)!=raw or raw<0:
                raise ValueError("Invalid C6 value "+alias+": "+repr(raw))
            values.append(int(raw))
        if values:
            if len(set(values))!=1:raise ValueError("Conflicting C6 aliases for "+target)
            out[target]=values[0]
    return out

def misc_v3_player_rows(payload):
    box=payload.get("boxScoreMisc",payload) if isinstance(payload,dict) else {}
    rows=box.get("playerStats",[]) if isinstance(box,dict) else []
    if isinstance(rows,list) and rows:return rows
    nested=[]
    for side in ("homeTeam","awayTeam"):
        team=box.get(side,{}) if isinstance(box,dict) else {}
        if not isinstance(team,dict):continue
        alias=team.get("teamTricode")
        for p in team.get("players",[]):
            copy=dict(p)
            copy.setdefault("teamTricode",alias)
            nested.append(copy)
    return nested

def _namekey(value):
    name=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",name)

def _row_name(row):
    return row.get("name") or row.get("displayName") or (str(row.get("firstName") or "")+" "+str(row.get("familyName") or "")).strip()

def _team(row):
    v=(row.get("teamTricode") or row.get("team") or row.get("team_abbreviation") or "")
    return {"SA":"SAS","GS":"GSW","NO":"NOP","NY":"NYK","WSH":"WAS","UTAH":"UTA"}.get(str(v).upper(),str(v).upper())

def apply_c6_rows(players,rows,source_name):
    by_id={}
    by_name={}
    for row in rows:
        if not isinstance(row,dict):continue
        pid=row.get("personId") or row.get("person_id")
        if pid is not None:
            key=str(pid)
            if key in by_id:raise ValueError("Duplicate source personId "+key)
            by_id[key]=row
        name=_row_name(row);team=_team(row)
        if name and team:
            key=(team,_namekey(name))
            if key in by_name:raise ValueError("Duplicate C6 player/team "+str(key))
            by_name[key]=row
    count=0;new=0; matched_by_name=0;missing_ids=[]
    for player in players:
        pid=str(player.get("player_id") or "")
        row=by_id.get(pid) if pid else None
        if row and _team(row) and _team(row)!=player.get("team"):
            raise ValueError("C6 player ID/team conflict for "+player["name"])
        if row is None:
            key=(player.get("team"),_namekey(player.get("name")))
            row=by_name.get(key)
            if row is not None:matched_by_name+=1
        if row is None:
            missing_ids.append(pid)
            continue
        fields=read_c6_fields(row.get("statistics",row))
        if not fields:continue
        count+=1
        for key,val in fields.items():
            if key in player and player[key]!=val:
                raise ValueError("C6 conflicting "+key+" for "+player["name"])
            if key not in player:player[key]=val;new+=1
    coverage={k:sum(k in p for p in players) for k in C6_FIELDS}
    return {"source":source_name,"matched_players":count,"name_team_crosswalks":matched_by_name,
            "new_fields":new,"coverage":coverage,"total":len(players),"unmatched_id_count":len(missing_ids)}
