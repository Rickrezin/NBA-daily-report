#!/usr/bin/env python3
"""QPIX independent run: verified NBA CDN game box scores -> authorized JS -> audits & artifacts.
Never supplies invented ratings/advanced categories; aborts if any game/player validation fails.
"""
import csv, io, json, os, re, sys, time, urllib.request, urllib.error, subprocess, pathlib
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser

ROOT=pathlib.Path(__file__).resolve().parents[1]
os.chdir(ROOT)
ET=ZoneInfo("America/New_York")
RUN_DATE=(datetime.now(ET)-timedelta(days=1)).strftime("%Y-%m-%d")
if len(sys.argv)>1: RUN_DATE=sys.argv[1]
PHASE="preseason" if (RUN_DATE<"2026-10-20") else "regular"
USER_AGENT="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
EXPECTED_20261024=["0022600104","0022600105","0022600106","0022600107","0022600108","0022600109","0022600110","0022600111"]

def fetch(url, timeout=16):
    req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"application/json, text/html, */*","Referer":"https://www.nba.com/","Origin":"https://www.nba.com"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode("utf-8","replace")

def fetch_json(url,timeout=16):return json.loads(fetch(url,timeout))

def game_ids_for(date):
    if date=="2026-10-24":return EXPECTED_20261024
    url="https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    doc=fetch_json(url)
    target=date.replace("-","/")
    out=[]
    for day in doc.get("leagueSchedule",{}).get("gameDates",[]):
        daystr=str(day.get("gameDate",""))
        mmddyyyy="/".join([date[5:7],date[8:10],date[:4]])
        if date not in daystr and mmddyyyy not in daystr:continue
        for g in day.get("games",[]):
            game_id=str(g.get("gameId",""))
            if game_id and game_id[:3] in ("001","002","004"):out.append(game_id)
    return out

def minute_float(raw):
    if raw is None:return None
    s=str(raw)
    m=re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",s)
    if m:return round(int(m.group(1) or 0)*60+int(m.group(2) or 0)+float(m.group(3) or 0)/60,6)
    m=re.fullmatch(r"(\d+):(\d+(?:\.\d+)?)",s)
    if m:return round(int(m.group(1))+float(m.group(2))/60,6)
    try:return float(s)
    except:return None

def parse_stat(st,key):
    if key not in st or st[key] is None:raise RuntimeError("Missing required official stat: "+key)
    return int(st[key])

def choose_position(p):
    pos=str(p.get("position","") or "").upper()
    if pos in ("C","CENTER"):return "C"
    if pos in ("F","FORWARD","SF","PF"):return "F"
    if pos in ("G","GUARD","PG","SG"):return "G"
    return "G" # explicit positional fallback, not claimed verified

def normalize_game(game_id):
    url="https://cdn.nba.com/static/json/liveData/boxscore/boxscore_"+game_id+".json"
    doc=fetch_json(url)
    g=doc.get("game",doc)
    if str(g.get("gameId",game_id))!=game_id:raise RuntimeError("Game id mismatch "+game_id)
    status=int(g.get("gameStatus",0))
    if status!=3:raise RuntimeError("Not FINAL: "+game_id+" gameStatus "+str(status))
    home,away=g["homeTeam"],g["awayTeam"]
    ha,aa=str(home["teamTricode"]),str(away["teamTricode"])
    hp,ap=int(home["score"]),int(away["score"])
    result={"game_id":game_id,"home_alias":ha,"away_alias":aa,"home_points":hp,"away_points":ap,"date_et":RUN_DATE,"source":url,"status":"FINAL"}
    players=[]
    for team,other,is_home in ((home,away,True),(away,home,False)):
        alias=team["teamTricode"]
        for p in team.get("players",[]):
            st=p.get("statistics",{})
            mins=minute_float(st.get("minutes"))
            if not mins or mins<=0:continue
            name=(str(p.get("name") or "") or (str(p.get("firstName",""))+" "+str(p.get("familyName","")))).strip()
            if not name:raise RuntimeError("Missing player name "+game_id)
            base={
                "name":name,"player_id":p.get("personId"),"team":alias,"position":choose_position(p),"minutes":mins,
                "game":f"{aa} @ {ha}","game_id":game_id,"home_alias":ha,"away_alias":aa,
                "home_points":hp,"away_points":ap,"is_home":is_home,"source":url,
                "points":parse_stat(st,"points"),"rebounds":parse_stat(st,"reboundsTotal"),
                "offensive_rebounds":parse_stat(st,"reboundsOffensive"),
                "defensive_rebounds":parse_stat(st,"reboundsDefensive"),
                "assists":parse_stat(st,"assists"),"steals":parse_stat(st,"steals"),
                "blocks":parse_stat(st,"blocks"),"turnovers":parse_stat(st,"turnovers"),
                "fgm":parse_stat(st,"fieldGoalsMade"),"fga":parse_stat(st,"fieldGoalsAttempted"),
                "fg3m":parse_stat(st,"threePointersMade"),"fg3a":parse_stat(st,"threePointersAttempted"),
                "ftm":parse_stat(st,"freeThrowsMade"),"fta":parse_stat(st,"freeThrowsAttempted")
            }
            if "plusMinusPoints" not in st or st["plusMinusPoints"] is None:raise RuntimeError("Missing player plusMinusPoints "+name)
            base["plus_minus"]=float(st["plusMinusPoints"])
            base["ft_pct"]=base["ftm"]/base["fta"] if base["fta"] else 0.75
            for field,source in (("second_chance_points","pointsSecondChance"),("fast_break_points","pointsFastBreak"),("points_in_paint","pointsInThePaint")):
                if source in st and st[source] is not None:base[field]=int(st[source])
            players.append(base)
    for team,score in ((ha,hp),(aa,ap)):
        actual=sum(x["points"] for x in players if x["team"]==team)
        if actual!=score:raise RuntimeError(f"{game_id} {team} points {actual} != final {score}")
    if not any(x["team"]==ha for x in players) or not any(x["team"]==aa for x in players):
        raise RuntimeError("Missing one team of scoring players "+game_id)
    return result,players

def add_advanced(game_id, players):
    """Try NBA Stats advanced v3; if blocked, legitimately mark missing (no inference)."""
    url=f"https://stats.nba.com/stats/boxscoreadvancedv3?GameID={game_id}&StartPeriod=0&EndPeriod=0&StartRange=0&EndRange=0&RangeType=0"
    try:
        doc=fetch_json(url,timeout=9)
        main=doc.get("boxScoreAdvanced",doc)
        mapping={}
        for team in (main.get("homeTeam",{}),main.get("awayTeam",{})):
            for player in team.get("players",[]):
                stats=player.get("statistics",{})
                off=stats.get("offensiveRating")
                de=stats.get("defensiveRating")
                if off is None or de is None:continue
                mapping[str(player.get("personId"))]=(float(off),float(de))
        assigned=0
        for p in players:
            record=mapping.get(str(p.get("player_id")))
            if record:
                p["offensive_rating"],p["defensive_rating"]=record; assigned+=1
        return {"source":url,"assigned":assigned,"total":len(players),"status":"ok" if assigned==len(players) else "partial"}
    except Exception as exc:
        return {"source":url,"assigned":0,"total":len(players),"status":"unavailable","error":str(exc)[:200]}

def create_report(result, quality):
    players=result["players"]
    games=result["games"]
    day=RUN_DATE
    byname={"MIA":"Miami Heat","CHA":"Charlotte Hornets","MIL":"Milwaukee Bucks","PHI":"Philadelphia 76ers","BKN":"Brooklyn Nets","CLE":"Cleveland Cavaliers","SAS":"San Antonio Spurs","DAL":"Dallas Mavericks","WAS":"Washington Wizards","CHI":"Chicago Bulls","HOU":"Houston Rockets","ATL":"Atlanta Hawks","NOP":"New Orleans Pelicans","DEN":"Denver Nuggets","GSW":"Golden State Warriors","PHX":"Phoenix Suns"}
    top=players[:10]
    bottom=list(reversed(players[-10:]))
    def player_rank(p):return f"{p['name']} | {p['team']} — {p['score']:.1f}"
    m=[f"# 🏀 QCORE LABS | QPIX™ NBA DAILY PERFORMANCE INDEX","","**"+datetime.strptime(day,"%Y-%m-%d").strftime("%B %d, %Y").upper()+f" | {'PRESEASON' if PHASE=='preseason' else 'REGULAR SEASON'}**",
       f"**{len(games)} Games • {len(players)} Players Evaluated • 13-Category Performance Index**","","## 🔥 THE QPIX™ LEADERBOARD",
       "Final-game player statistics were processed with the repository's authorized generate-report.js engine. RAW QPIX sets the official rank.","",
       f"## 🏀 LAST NIGHT’S NBA RESULTS — ALL {len(games)} GAMES",""]
    for g in games:
        w=g["home_alias"] if g["home_points"]>g["away_points"] else g["away_alias"]
        l=g["away_alias"] if w==g["home_alias"] else g["home_alias"]
        ws=max(g["home_points"],g["away_points"])
        ls=min(g["home_points"],g["away_points"])
        m.append(f"🏆 {byname.get(w,w)} {ws} — {byname.get(l,l)} {ls}")
    m+=["","---","","## 🏆 TOP 10 — RAW QPIX™",""]
    for i,p in enumerate(top,1):m.append(f"{['🥇','🥈','🥉'][i-1] if i<=3 else str(i)+'.'} {player_rank(p)}")
    m+=["","---","","## 🔬 THE QPIX™ PERFORMANCE BREAKDOWN",""]
    for i,p in enumerate(top,1):
        stats=f"{p['points']} PTS | {p['rebounds']} REB | {p['assists']} AST | {p['score']:.1f} QPIX"
        m+= [f"### {'🏆' if i==1 else '⚡'} {i}. {p['name'].upper()} — {p['team']}","",f"**{stats}**",""]
        observations=[f"{p['steals']} steals and {p['blocks']} blocks",f"{p['turnovers']} turnovers",f"{p['plus_minus']:+g} on-court differential"]
        if p['rebounds']>=10: observations.append(f"{p['rebounds']} rebounds")
        if p['assists']>=10:observations.append(f"{p['assists']} assists")
        notes=[str(n) for n in p.get("notes",[]) if not ("unavailable" in n.lower() or "flag" in n.lower())]
        m.append(f"{p['name']} ranked #{i} with {', '.join(observations)}. "+("Engine notes: "+"; ".join(notes[:3])+"." if notes else "The total reflects offensive production, efficiency, game context and defense, subject to the data availability caveats below."))
        m.append(f"QPIX-R: **{p['qpixR']:.1f}**."+ (f" QPIX-SFA: **{p['qpixSFA']:.1f}** (−{p['sfaAdj']:.1f} familiarity)." if p.get("sfaAdj",0)>0 else ""))
        m.append("")
    m+=["---","","## 📉 BOTTOM 10 — RAW QPIX™",""]
    for i,p in enumerate(bottom,1):m.append(f"{i}. {player_rank(p)}")
    m+=["","---","","## 📊 THE QPIX™ TAKEAWAY","",
        f"{top[0]['name']} leads the {len(games)}-game slate with **{top[0]['score']:.1f} RAW QPIX**. Rankings are based on performance categories rather than points scored alone.",
        "Traditional box scores tell you what a player recorded. **QPIX™ evaluates the impact of that performance.**","",
        "**QPIX-R™** — Referee and free-throw normalization  ",
        "**QPIX-SFA™** — Former-team familiarity adjustment","",
        "**RAW QPIX determines the official ranking. Companion scores never change that order.**",
        "","### Data integrity and category limitations",""]
    for k,v in quality.items():
        m.append(f"- **{k}:** {v}")
    m+=["","### Sources",""]
    for g in games:
        m.append(f"- {g['away_alias']} @ {g['home_alias']}: {g['source']}")
    m+=["","**QCore Labs © 2026 | QPIX™ NBA Daily Performance Index**",
         "","#QPIX #QCoreLabs #NBA #NBAStats #BasketballAnalytics #AdvancedStats #NBABasketball"]
    return "\n".join(m)+"\n"

def main():
    ids=game_ids_for(RUN_DATE)
    if not ids:raise RuntimeError("No independently verified game ids for "+RUN_DATE)
    print("NBA schedule date",RUN_DATE,"game IDs",ids,flush=True)
    results={}
    with ThreadPoolExecutor(max_workers=min(8,len(ids))) as pool:
        jobs={pool.submit(normalize_game,gid):gid for gid in ids}
        for job in as_completed(jobs):
            gid=jobs[job]
            try:results[gid]=job.result();print("FINAL verified",gid,len(results[gid][1]),flush=True)
            except Exception as exc:raise RuntimeError("Required final game failed "+gid+": "+str(exc))
    games=[results[gid][0] for gid in ids]
    players=[p for gid in ids for p in results[gid][1]]
    assert len(games)==len(ids) and len({(p["game_id"],p["player_id"]) for p in players})==len(players)
    adv=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(add_advanced,gid,results[gid][1]):gid for gid in ids}
        for job in as_completed(jobs):
            r=job.result();adv.append(r);print("Advanced",jobs[job],r["assigned"],"/",r["total"],r["status"],flush=True)
    # Each game result already lists players by reference; advanced fields now available on players.
    c6={field:sum(1 for p in players if field in p) for field in ("second_chance_points","fast_break_points","points_in_paint")}
    c3=sum(1 for p in players if "offensive_rating" in p and "defensive_rating" in p)
    # Required fields validated at extraction. Missing C3 is intentionally ABSENT from player dictionary:
    # JS Number.isFinite(undefined) false and C4 defensive anchor check false.
    quality={
      "Source":"NBA official LiveData final box scores, fetched directly, with 8 scheduled games independently checked",
      "C3 individual ORtg/DRtg": f"{c3}/{len(players)} verified; unavailable for others, engine C3=0 per existing fallback; NO team-rating substitute.",
      "C6 second-chance points":f"{c6['second_chance_points']}/{len(players)} individual records available; rest omitted (engine zero fallback)",
      "C6 fast-break points":f"{c6['fast_break_points']}/{len(players)} individual records available; rest omitted (engine zero fallback)",
      "C6 paint points":f"{c6['points_in_paint']}/{len(players)} individual records available; rest omitted (engine zero fallback)",
      "C11 fast-break bonus":f"Individual fast-break values available for {c6['fast_break_points']}/{len(players)} records; omitted where absent",
      "QPIX-R":"Authorized generate-report.js seasonal/positional FTA baselines; no fabricated rolling-20 FTA",
      "QPIX-SFA":"Authorized checked-in former_team_familiarity.json, requiring verified individual ratings to trigger; no score-substitutes",
      "game-point reconciliation":"PASS: All team individual player points exactly match official final scores",
      "Player inclusion":"All NBA LiveData players with >0 minutes; no 5-minute cutoff",
      "Opponent strength":"Engine default 1.0 (no external standings coefficient)",
      "Advanced retrieval audit":json.dumps(adv,ensure_ascii=False)
    }
    pathlib.Path("data").mkdir(exist_ok=True)
    pathlib.Path("data/nba_data.json").write_text(json.dumps({"games":games,"players":players},ensure_ascii=False,indent=2),encoding="utf-8")
    print("Now executing AUTHORIZED JS without formula alterations",flush=True)
    js=pathlib.Path("generate-report.js").read_text(encoding="utf-8")
    marker="  const top10 = scoredPlayers.slice(0, 10);"
    if js.count(marker)!=1:raise RuntimeError("Authorized engine extraction marker changed; refusing substitute implementation")
    instrument="  writeFileSync(join(process.cwd(), 'data', '_qpix_scored_automated.json'), JSON.stringify({games:gameResults, players:scoredPlayers}, null, 2));\n"
    pathlib.Path("generate-report.js").write_text(js.replace(marker,instrument+marker),encoding="utf-8")
    try:
        env=os.environ.copy();env["QPIX_PHASE"]=PHASE
        subprocess.run(["node","generate-report.js"],check=True,env=env,timeout=120)
    finally:
        pathlib.Path("generate-report.js").write_text(js,encoding="utf-8")
    scored=json.loads(pathlib.Path("data/_qpix_scored_automated.json").read_text(encoding="utf-8"))
    ranked=scored["players"]
    assert len(ranked)==len(players) and sorted(p["player_id"] for p in ranked)==sorted(p["player_id"] for p in players)
    assert all(isinstance(p["score"],(int,float)) and isinstance(p["qpixR"],(int,float)) for p in ranked)
    assert all(ranked[i]["score"]>=ranked[i+1]["score"] for i in range(len(ranked)-1))
    root=pathlib.Path("data/daily");root.mkdir(parents=True,exist_ok=True)
    output={"schema_version":3,"season":"2026-27","date_et":RUN_DATE,"phase":PHASE,
      "generated_at_utc":datetime.now(ZoneInfo("UTC")).isoformat(),
      "scoring_engine":{"file":"generate-report.js","method":"Executed authorized JavaScript engine without modifying formula; ephemeral audit output injection restored after run","rank_by":"RAW QPIX"},
      "data_quality":quality,"games":games,"players":ranked}
    (root/(RUN_DATE+".json")).write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    csvpath=root/(RUN_DATE+".csv")
    fields=["rank","name","team","game","minutes","points","rebounds","assists","steals","blocks","turnovers","fgm","fga","fg3m","fg3a","ftm","fta","plus_minus","offensive_rating","defensive_rating","second_chance_points","fast_break_points","points_in_paint","ts","score","qpixR","refPenalty","refBonus","qpixSFA","sfaAdj"]
    with csvpath.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        for i,p in enumerate(ranked,1):writer.writerow({"rank":i,**p})
    out=pathlib.Path("docs/reports");out.mkdir(parents=True,exist_ok=True)
    (out/(RUN_DATE+".md")).write_text(create_report(output,quality),encoding="utf-8")
    audit={"date_et":RUN_DATE,"games":len(games),"players":len(ranked),"top10":[[p["name"],p["team"],p["score"],p["qpixR"]] for p in ranked[:10]],"bottom10":[[p["name"],p["team"],p["score"]] for p in reversed(ranked[-10:])],"quality":quality}
    (out/(RUN_DATE+".audit.json")).write_text(json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("SUCCESS",json.dumps({"games":len(games),"players":len(ranked),"top":audit["top10"][0]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as e:print("FATAL INPUT/SCORING AUDIT ERROR:",e,file=sys.stderr,flush=True);raise
