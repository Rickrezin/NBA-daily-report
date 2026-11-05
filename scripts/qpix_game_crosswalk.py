"""Resolve ESPN event fixtures to verified NBA game IDs via official schedule data.

Do not derive NBA IDs from sequence arithmetic: cup games and postponements
make it unsafe. Every ID is accepted only after exact team/date reconciliation.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

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
    if len(set(crosswalk.values()))!=len(crosswalk):
        raise ValueError("Duplicate NBA IDs for distinct ESPN fixtures")
    audit["resolved"]=len(crosswalk)
    audit["unresolved_espn_ids"]=sorted(set(expected)-set(crosswalk))
    return crosswalk,audit
