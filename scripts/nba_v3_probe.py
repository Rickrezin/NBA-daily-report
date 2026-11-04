"""Read-only NBA Stats V3 / LiveData connectivity probe for QPIX.
Do not treat NBA on-court ratings as Basketball-Reference/Dean Oliver ratings.
"""
import json, time, urllib.request, urllib.error
GAME = "0022600159"  # Detroit 124 Charlotte 91, 2026-11-02
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}
def probe(label,url):
    start=time.time()
    try:
        req=urllib.request.Request(url,headers=HEADERS)
        with urllib.request.urlopen(req,timeout=14) as res:
            payload=res.read()
            print("FETCH", json.dumps({"label":label,"status":res.status,"seconds":round(time.time()-start,2),"bytes":len(payload)}))
            return json.loads(payload)
    except urllib.error.HTTPError as e:
        print("FETCH",json.dumps({"label":label,"status":e.code,"seconds":round(time.time()-start,2)}))
    except Exception as e:
        print("FETCH_ERROR",json.dumps({"label":label,"error":str(e)[:200],"seconds":round(time.time()-start,2)}))
    return None

try:
    from nba_api.stats.endpoints import boxscoreadvancedv3
    print("NBA_API", "installed")
    try:
        obj=boxscoreadvancedv3.BoxScoreAdvancedV3(game_id=GAME,timeout=14)
        data=obj.get_dict()
        print("V3_LIBRARY_SUCCESS",json.dumps({"topKeys":list(data),"boxKeys":list(data.get("boxScoreAdvanced",{}))}))
        rows=data.get("boxScoreAdvanced",{}).get("playerStats",[])
        print("V3_PLAYERS",len(rows))
        for p in rows:
            if p.get("familyName") in ("Cunningham","Robinson"):
                print("V3_SAMPLE",json.dumps({k:p.get(k) for k in ("personId","firstName","familyName","offensiveRating","defensiveRating","estimatedOffensiveRating","estimatedDefensiveRating","minutes")}))
    except Exception as e:
        print("V3_LIBRARY_ERROR",str(e)[:250])
except ImportError as e: print("NBA_API_IMPORT_ERROR",str(e))
# Standalone test so a library failure still yields explicit HTTP information.
v3url="https://stats.nba.com/stats/boxscoreadvancedv3?GameID="+GAME+"&StartPeriod=0&EndPeriod=0&StartRange=0&EndRange=0&RangeType=0"
v3=probe("stats_v3_direct",v3url)
if v3:
    rows=v3.get("boxScoreAdvanced",{}).get("playerStats",[])
    print("V3_DIRECT_PLAYERS",len(rows))
    for p in rows:
        if p.get("familyName") in ("Cunningham","Robinson"):
            print("V3_DIRECT_SAMPLE",json.dumps({k:p.get(k) for k in ("personId","firstName","familyName","offensiveRating","defensiveRating")}))
cdn=probe("nba_cdn_live_boxscore","https://cdn.nba.com/static/json/liveData/boxscore/boxscore_"+GAME+".json")
if cdn:
    game=cdn.get("game",{})
    players=[p for team in (game.get("homeTeam",{}),game.get("awayTeam",{})) for p in team.get("players",[])]
    print("CDN_PLAYERS",len(players))
    for p in players:
        if p.get("familyName") in ("Cunningham","Robinson"):
            print("CDN_SAMPLE",json.dumps({"name":p.get("name"),"stats":{k:v for k,v in p.get("statistics",{}).items() if "point" in k.lower() or "rating" in k.lower()}}))
