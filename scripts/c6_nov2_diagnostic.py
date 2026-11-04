"""Read-only November 2 C6 source replay. Never publishes or scores."""
import sys,json,urllib.request,urllib.error,time,collections,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from c6_sources import read_c6_fields, misc_v3_player_rows
BASE="https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DATE="20261102"
NBA_GAME="0022600159" # NBA.com confirms DET @ CHA game ID
def fetch(url,timeout=10):
    try:
        request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121 Safari/537.36","Accept":"application/json","Referer":"https://www.nba.com/","Origin":"https://www.nba.com"})
        with urllib.request.urlopen(request,timeout=timeout) as r:
            obj=json.loads(r.read())
            return {"status":r.status,"json":obj}
    except urllib.error.HTTPError as e:return {"status":e.code,"error":str(e)}
    except Exception as e:return {"status":"ERR","error":str(e)[:180]}
def one(event):
    result=fetch(BASE+"/summary?event="+event["id"])
    if result["status"]!=200:return {"id":event["id"],"status":result["status"],"error":result.get("error")}
    data=result["json"]
    active=[]
    records=[]
    for team in data.get("boxscore",{}).get("players",[]):
        for stat in team.get("statistics",[]):
            for row in stat.get("athletes",[]):
                if row.get("didNotPlay"):continue
                labels=stat.get("labels",[])
                vals=row.get("stats",[])
                if not vals or not labels:continue
                if str(vals[labels.index("MIN")]) in ("0","0:00") if "MIN" in labels else False:continue
                active.append(row.get("athlete",{}).get("id"))
                fields=read_c6_fields(dict(zip(labels,vals)))
                if fields:records.append(fields)
    return {"id":event["id"],"status":200,"players":len(active),"c6_players":len(records),"c6_fields":{k:sum(k in p for p in records) for k in ("points_in_paint","fast_break_points","second_chance_points")},"plays":len(data.get("plays",[]))}
board=fetch(BASE+"/scoreboard?dates="+DATE+"&limit=100")
print("SCOREBOARD",json.dumps({"status":board["status"],"error":board.get("error")}),flush=True)
if board["status"]!=200:sys.exit(2)
games=[e for e in board["json"].get("events",[]) if e.get("status",{}).get("type",{}).get("completed")]
print("SLATE",len(games),flush=True)
if len(games)!=15:sys.exit(3)
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:stats=list(pool.map(one,games))
print("GAMES",json.dumps(stats),flush=True)
print("ESPN_C6_COVERAGE",json.dumps({"valid_games":sum(x.get("status")==200 for x in stats),"players":sum(x.get("players",0) for x in stats),"c6_player_records":sum(x.get("c6_players",0) for x in stats)}),flush=True)
misc="https://stats.nba.com/stats/boxscoremiscv3?GameID="+NBA_GAME+"&StartPeriod=0&EndPeriod=0&StartRange=0&EndRange=0&RangeType=0"
test=fetch(misc,timeout=13)
print("MISC_V3",json.dumps({"nba_game_id":NBA_GAME,"http_status":test["status"],"error":test.get("error")}),flush=True)
if test["status"]==200:
    rows=misc_v3_player_rows(test["json"])
    print("MISC_ROWS",len(rows),"SAMPLE_KEYS",list(rows[0]) if rows else [],flush=True)
    print("MISC_FIELDS",json.dumps({k:sum(k in read_c6_fields(row.get("statistics",row)) for row in rows) for k in ("points_in_paint","fast_break_points","second_chance_points")}),flush=True)
# Exit successful for diagnostic collection even if provider blocked; source failure reported explicitly.
