#!/usr/bin/env python3
"""Experimental QPIX C6 availability probe; cannot alter QPIX scores."""
import argparse
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

FIELDS={"points_in_paint":("pointsInThePaint","pointsPaint"),
        "fast_break_points":("pointsFastBreak",),
        "second_chance_points":("pointsSecondChance",)}
GAME_URL=re.compile(r"/game/([a-z]{2,3})-vs-([a-z]{2,3})-(\d{10})(?=[/?#\"' ]|$)",re.I)

class Links(HTMLParser):
    def __init__(self):super().__init__();self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            self.hrefs.extend(v for k,v in attrs if k=="href" and v and "/game/" in v)

def game_map(page):
    p=Links();p.feed(page)
    out={}
    for link in p.hrefs:
        m=GAME_URL.search(link)
        if not m:continue
        away,home,gid=m.groups()
        pair=(away.upper(),home.upper())
        if pair in out and out[pair]!=gid:raise ValueError("Conflicting NBA IDs for "+str(pair))
        out[pair]=gid
    return out

def get(url):
    h={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*","Referer":"https://www.nba.com/"}
    with urlopen(Request(url,headers=h),timeout=18) as r:return r.read().decode("utf-8")
def get_json(url):return json.loads(get(url))

def nba_field(row,keys):
    for key in keys:
        value=row.get(key)
        if value is None:continue
        if isinstance(value,bool) or not str(value).isdigit():
            raise ValueError("Invalid official value "+key+"="+repr(value))
        return int(value)
    return None

def player_data(payload,source):
    box=payload.get("game",payload) if source=="live" else payload.get("boxScoreMisc",payload)
    teams=[]
    for side in ("awayTeam","homeTeam"):
        team=box[side];code=team["teamTricode"]
        players=[];ids=set()
        for raw in team.get("players",[]):
            pid=raw.get("personId")
            if pid is None or str(pid) in ids:raise ValueError("Missing/duplicate NBA personId")
            ids.add(str(pid));stats=raw.get("statistics",{})
            players.append({"person_id":str(pid),
                            "name":raw.get("name") or (str(raw.get("firstName",""))+" "+str(raw.get("familyName",""))).strip(),
                            **{f:nba_field(stats,aliases) for f,aliases in FIELDS.items()}})
        sums={f:nba_field(team.get("statistics",{}),aliases) for f,aliases in FIELDS.items()}
        for field,wanted in sums.items():
            seen=[p[field] for p in players]
            if wanted is not None and all(v is not None for v in seen) and sum(seen)!=wanted:
                raise ValueError(f"{code} {field} player sum {sum(seen)} != team {wanted}")
        teams.append({"team":code,"players":players,"team_totals":sums})
    return teams

def espn_finals(board):
    games={}
    for event in board.get("events",[]):
        if not event.get("status",{}).get("type",{}).get("completed"):continue
        sides={x["homeAway"]:x for x in event["competitions"][0]["competitors"]}
        alias={"SA":"SAS","NY":"NYK","WSH":"WAS","UTAH":"UTA","NO":"NOP","GS":"GSW","PHO":"PHX"}
        pair=tuple(alias.get(sides[side]["team"]["abbreviation"].upper(),sides[side]["team"]["abbreviation"].upper()) for side in ("away","home"))
        games[pair]=(int(sides["away"]["score"]),int(sides["home"]["score"]))
    return games

def probe(day):
    ymd=day.replace("-","")
    final=espn_finals(get_json(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}&limit=100"))
    if not final:raise ValueError("No ESPN finals found")
    nba=game_map(get(f"https://www.nba.com/games?date={day}"))
    if set(final)-set(nba):raise ValueError("NBA schedule missing games: "+str(set(final)-set(nba)))
    output={"date":day,"expected_games":len(final),"games":[],"coverage":{f:0 for f in FIELDS}}
    for pair,score in sorted(final.items()):
        gid=nba[pair]
        entry={"matchup":pair,"nba_game_id":gid,"attempts":[],"source":None}
        for source,url in (
            ("live",f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"),
            ("misc",f"https://stats.nba.com/stats/boxscoremiscv3?GameID={gid}&StartPeriod=0&EndPeriod=0&StartRange=0&EndRange=0&RangeType=0")):
            try:
                payload=get_json(url)
                if source=="live":
                    g=payload.get("game",payload)
                    if int(g.get("gameStatus",0))!=3:raise ValueError("NBA game not final")
                    if (int(g["awayTeam"]["score"]),int(g["homeTeam"]["score"]))!=score:raise ValueError("Final score mismatch")
                teams=player_data(payload,source)
                if {t["team"] for t in teams}!=set(pair):raise ValueError("Team mismatch")
                coverage={k:sum(p[k] is not None for t in teams for p in t["players"]) for k in FIELDS}
                if not all(coverage.values()):raise ValueError("Missing one or more C6 fields "+str(coverage))
                entry.update(source=url,teams=teams,coverage=coverage)
                for field,n in coverage.items():output["coverage"][field]+=n
                break
            except Exception as err:entry["attempts"].append({"endpoint":source,"error":str(err)[:250]})
        output["games"].append(entry)
    output["complete_games"]=sum(bool(g["source"]) for g in output["games"])
    return output

def main():
    a=argparse.ArgumentParser();a.add_argument("--date",default="2026-11-04")
    a.add_argument("--output",default="experiments/c6_recovery/results/c6_probe.json");opt=a.parse_args()
    date.fromisoformat(opt.date)
    try:result=probe(opt.date)
    except Exception as e:result={"date":opt.date,"error":str(e),"coverage":{f:0 for f in FIELDS}}
    path=Path(opt.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:result.get(k) for k in ("expected_games","complete_games","coverage","error")},indent=2))
    if result.get("error") or result.get("complete_games")!=result.get("expected_games"):
        raise SystemExit(1)

if __name__=="__main__":main()
