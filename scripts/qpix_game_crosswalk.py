"""Resolve ESPN event fixtures to verified NBA game IDs via official schedule data.

Do not derive NBA IDs from sequence arithmetic: cup games and postponements
make it unsafe. Every ID is accepted only after exact team/date reconciliation.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

# Official NBA.com game-page URLs independently verified for November 4.
# This is a historical cache, never an inference about future NBA ID sequences.
VERIFIED_NBA_GAME_URLS={
    "2026-11-04":{
        ("PHI","DET"):("0022600173","https://www.nba.com/game/phi-vs-det-0022600173"),
        ("ATL","WAS"):("0022600174","https://www.nba.com/game/atl-vs-was-0022600174"),
        ("MIL","BOS"):("0022600175","https://www.nba.com/game/mil-vs-bos-0022600175"),
        ("CHA","BKN"):("0022600176","https://www.nba.com/game/cha-vs-bkn-0022600176"),
        ("CHI","NYK"):("0022600177","https://www.nba.com/game/chi-vs-nyk-0022600177"),
        ("IND","MEM"):("0022600178","https://www.nba.com/game/ind-vs-mem-0022600178"),
        ("UTA","NOP"):("0022600179","https://www.nba.com/game/uta-vs-nop-0022600179"),
        ("CLE","OKC"):("0022600180","https://www.nba.com/game/cle-vs-okc-0022600180"),
        ("MIN","HOU"):("0022600181","https://www.nba.com/game/min-vs-hou-0022600181"),
        ("TOR","DEN"):("0022600182","https://www.nba.com/game/tor-vs-den-0022600182"),
        ("POR","PHX"):("0022600183","https://www.nba.com/game/por-vs-phx-0022600183"),
        ("DAL","SAS"):("0022600184","https://www.nba.com/game/dal-vs-sas-0022600184"),
        ("LAL","SAC"):("0022600185","https://www.nba.com/game/lal-vs-sac-0022600185"),
        ("MIA","LAC"):("0022600186","https://www.nba.com/game/mia-vs-lac-0022600186"),
    }
}

SCHEDULE_URLS=(
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
)
_ET=ZoneInfo("America/New_York")

def _date(value):
    raw=str(value or "").strip()
    if len(raw)>=10 and raw[:4].isdigit() and raw[4]=="-" and raw[7]=="-":
        return raw[:10]
    for fmt in ("%m/%d/%Y","%Y%m%d"):
        try:return datetime.strptime(raw[:len(datetime.now().strftime(fmt))],fmt).date().isoformat()
        except ValueError:pass
    return None

def resolve(date_et, fixtures, fetch_json, alias_normalize=lambda x:x):
    """Return (ESPN event id -> NBA ID, provenance audit) from exact date/teams."""
    expected={}
    for f in fixtures:
        eid=str(f["espn_event_id"])
        matchup=(alias_normalize(f["away_alias"]),alias_normalize(f["home_alias"]))
        if eid in expected or matchup in expected.values():
            raise ValueError("Duplicate ESPN fixture in NBA crosswalk")
        expected[eid]=matchup
    verified=VERIFIED_NBA_GAME_URLS.get(date_et)
    if verified is not None:
        if set(verified)!=set(expected.values()):
            raise ValueError("NBA.com historical game-page map does not match ESPN slate")
        crosswalk={eid:verified[matchup][0] for eid,matchup in expected.items()}
        if len(set(crosswalk.values()))!=len(crosswalk):
            raise ValueError("Duplicate NBA game IDs in verified historical links")
        return crosswalk,{"attempts":[{"source":"NBA.com independently verified game pages",
            "status":"ok","matched":len(crosswalk),
            "links":[verified[matchup][1] for matchup in expected.values()]}],
            "resolved":len(crosswalk),"expected":len(expected),"unresolved_espn_ids":[]}
    audit={"attempts":[],"resolved":0,"expected":len(expected)}
    by_matchup={v:k for k,v in expected.items()}
    crosswalk={}
    for url in SCHEDULE_URLS:
        try:
            doc=fetch_json(url,timeout=12)
            schedule=doc.get("leagueSchedule",{})
            observed={}
            for day in schedule.get("gameDates",[]):
                if _date(day.get("gameDate"))!=date_et:continue
                for game in day.get("games",[]):
                    away=alias_normalize(game.get("awayTeam",{}).get("teamTricode",""))
                    home=alias_normalize(game.get("homeTeam",{}).get("teamTricode",""))
                    key=(away,home)
                    if key not in by_matchup:continue
                    gid=str(game.get("gameId",""))
                    if not (len(gid)==10 and gid.isdigit()):
                        raise ValueError("Invalid NBA game ID "+repr(gid))
                    eid=by_matchup[key]
                    if eid in observed and observed[eid]!=gid:
                        raise ValueError("Conflicting NBA game IDs for "+eid)
                    observed[eid]=gid
            audit["attempts"].append({"source":url,"status":"ok","matched":len(observed)})
            crosswalk.update(observed)
            if len(crosswalk)==len(expected):break
        except Exception as exc:
            audit["attempts"].append({"source":url,"status":"failed","error":str(exc)[:180]})
    # Independent official NBA Stats scoreboard endpoint. It provides GAMECODE
    # (YYYYMMDD/AWAYHOME) and GAME_ID; do not depend on the blocked CDN.
    if len(crosswalk)<len(expected):
        from urllib.parse import urlencode
        query=urlencode({"GameDate":date_et,"LeagueID":"00","DayOffset":"0"})
        url="https://stats.nba.com/stats/scoreboardv2?"+query
        try:
            payload=fetch_json(url,timeout=13)
            sets=payload.get("resultSets",payload.get("resultSet",[]))
            if isinstance(sets,dict):sets=list(sets.values())
            found={}
            for section in sets:
                if section.get("name")!="GameHeader":continue
                headers=section.get("headers",[])
                for values in section.get("rowSet",[]):
                    data=dict(zip(headers,values))
                    code=str(data.get("GAMECODE","")).upper()
                    if "/" not in code:continue
                    teams=code.rsplit("/",1)[-1]
                    for pair,eid in by_matchup.items():
                        if teams==pair[0]+pair[1]:
                            gid=str(data.get("GAME_ID",""))
                            if len(gid)!=10 or not gid.isdigit():
                                raise ValueError("Invalid NBA scoreboard ID "+repr(gid))
                            found[eid]=gid
            for eid,gid in found.items():
                if eid in crosswalk and crosswalk[eid]!=gid:
                    raise ValueError("Conflicting NBA IDs from schedule and scoreboard for "+eid)
                crosswalk[eid]=gid
            audit["attempts"].append({"source":url,"status":"ok","matched":len(found)})
        except Exception as exc:
            audit["attempts"].append({"source":url,"status":"failed","error":str(exc)[:180]})
    if len(set(crosswalk.values()))!=len(crosswalk):
        raise ValueError("Duplicate NBA IDs for distinct ESPN fixtures")
    audit["resolved"]=len(crosswalk)
    audit["unresolved_espn_ids"]=sorted(set(expected)-set(crosswalk))
    return crosswalk,audit
