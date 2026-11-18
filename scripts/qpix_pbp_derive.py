#!/usr/bin/env python3
"""Lossless ESPN event derivation + box reconciliation; research only. No QPIX scores."""
import argparse,collections,datetime,hashlib,json,pathlib
def read(p):return json.loads(p.read_text(encoding="utf-8"))
def integer(v):
    try:return int(str(v).replace("+",""))
    except:return None
def box_players(summary):
    out={};teams={};dnp=[]
    for group in summary["boxscore"]["players"]:
        t=group["team"];tid=str(t["id"]);teams[tid]={"id":tid,"name":t["displayName"],"alias":t["abbreviation"]}
        for section in group["statistics"]:
            keys=section["names"]
            for a in section["athletes"]:
                pid=str(a["athlete"]["id"]);stats=dict(zip(keys,a["stats"]))
                if pid in out:continue
                minutes=stats.get("MIN","")
                if a.get("didNotPlay") or minutes in ("--","DNP","0:00",""):
                    dnp.append({"player_id":pid,"team_id":tid,"name":a["athlete"]["displayName"]});continue
                r={"player_id":pid,"team_id":tid,"name":a["athlete"]["displayName"],"starter":bool(a.get("starter")),"minutes":minutes,"source":"ESPN_original_summary_boxscore"}
                for key,field in (("PTS","points"),("REB","rebounds"),("AST","assists"),("TO","turnovers"),("STL","steals"),("BLK","blocks"),("OREB","offensive_rebounds"),("DREB","defensive_rebounds"),("PF","personal_fouls"),("+/-","plus_minus")):r[field]=integer(stats.get(key))
                for key,prefix in (("FG","fg"),("3PT","three"),("FT","ft")):
                    s=str(stats.get(key,""))
                    if "-" in s:
                        a1,a2=s.split("-",1);r[prefix+"m"]=integer(a1);r[prefix+"a"]=integer(a2)
                    else:r[prefix+"m"]=r[prefix+"a"]=None
                out[pid]=r
    return out,teams,dnp
def elapsed(p):
    try:
        q=int(p["period"]["number"]);s=str(p["clock"]["displayValue"])
        m,ss=s.split(":") if ":" in s else ("0",s)
        return min(q-1,4)*720+max(0,q-5)*300+(720 if q<=4 else 300)-float(m)*60-float(ss)
    except:return None
def derive_game(game,root):
    eid=game["espn_event_id"];plays=read(root/game["raw_plays"]);source=read(root/game["raw_summary"]);box,teams,dnp=box_players(source)
    away=str(game["away"]["team_id"]);home=str(game["home"]["team_id"])
    counters=collections.defaultdict(collections.Counter);periods=collections.defaultdict(lambda:{"away":0,"home":0})
    lineups={t:set(p for p,b in box.items() if b["team_id"]==t and b["starter"]) for t in [away,home]}
    known={t:len(lineups[t])==5 for t in [away,home]}
    minutes=collections.defaultdict(float);plusminus=collections.defaultdict(int);last_clock=0.0
    events=[];issues=[];previous=(0,0);ids=set();subs=0
    for i,p in enumerate(plays):
        pid=str(p.get("id",i));q=int((p.get("period") or {}).get("number",0));text=str(p.get("text",""));typ=str((p.get("type") or {}).get("text",""))
        team=str((p.get("team") or {}).get("id",""));participants=[str(a.get("athlete",{}).get("id","")) for a in (p.get("participants") or [])]
        tag=None;flags=[];now=elapsed(p)
        if now is not None and now>=last_clock:
            for t in (away,home):
                if known[t]:
                    for aid in lineups[t]:minutes[aid]+=(now-last_clock)/60
            last_clock=now
        else:flags.append("clock_unparsed_or_nonmonotonic")
        if pid in ids:issues.append({"type":"duplicate_event_id","event_id":pid})
        ids.add(pid)
        score=(integer(p.get("awayScore")),integer(p.get("homeScore")))
        delta=[None,None]
        if all(n is not None for n in score):
            delta=[score[0]-previous[0],score[1]-previous[1]]
            if min(delta)<0:issues.append({"type":"score_correction_or_rollback","event_id":pid,"delta":delta})
            if delta[0]>0:periods[q]["away"]+=delta[0]
            if delta[1]>0:periods[q]["home"]+=delta[1]
            for t,opp,points in ((away,home,delta[0]),(home,away,delta[1])):
                if points>0:
                    if known[t]:
                        for aid in lineups[t]:plusminus[aid]+=points
                    if known[opp]:
                        for aid in lineups[opp]:plusminus[aid]-=points
            previous=score
        else:flags.append("score_missing")
        if p.get("shootingPlay") and p.get("pointsAttempted") in (2,3):
            tag="field_goal_attempt"
            if participants and participants[0] in box:
                a=participants[0];counters[a]["fga"]+=1
                if p.get("scoreValue") in (2,3) and p.get("scoringPlay"):counters[a]["fgm"]+=1
                if p["pointsAttempted"]==3:
                    counters[a]["threea"]+=1
                    if p.get("scoreValue")==3 and p.get("scoringPlay"):counters[a]["threem"]+=1
                if "blocks" in text.lower() and len(participants)>1 and participants[1] in box:counters[participants[1]]["blocks"]+=1
                if "assist" in text.lower() and p.get("scoringPlay") and len(participants)>1 and participants[1] in box:counters[participants[1]]["assists"]+=1
            else:flags.append("shooter_unidentified")
        elif p.get("shootingPlay") and (p.get("pointsAttempted")==1 or "Free Throw" in typ):
            tag="free_throw_attempt"
            if participants and participants[0] in box:
                a=participants[0];counters[a]["fta"]+=1
                if p.get("scoreValue")==1:counters[a]["ftm"]+=1
            else:flags.append("free_throw_shooter_unidentified")
        elif typ in ("Offensive Rebound","Defensive Rebound"):
            tag="offensive_rebound" if typ.startswith("Offensive") else "defensive_rebound"
            if participants and participants[0] in box:
                a=participants[0];counters[a]["rebounds"]+=1;counters[a][tag+"s"]+=1
            else:flags.append("team_rebound_or_unidentified")
        elif "Turnover" in typ or typ=="Traveling":
            tag="turnover"
            if participants and participants[0] in box:counters[participants[0]]["turnovers"]+=1
            else:flags.append("team_turnover")
            if "steal" in text.lower() and len(participants)>1 and participants[1] in box:counters[participants[1]]["steals"]+=1
        elif "Foul" in typ or typ=="Offensive Charge":
            tag="foul"
            if participants and participants[0] in box:counters[participants[0]]["personal_fouls"]+=1
            else:flags.append("foul_unassigned")
        elif typ=="Substitution":
            tag="substitution";subs+=1
            if team not in lineups or len(participants)<2:issues.append({"type":"substitution_missing_identifiers","event_id":pid})
            else:
                a,b=participants[:2]
                if a not in box or b not in box or b not in lineups[team] or a in lineups[team]:
                    issues.append({"type":"substitution_lineup_inconsistency","event_id":pid,"in":a,"out":b});known[team]=False
                else:lineups[team].remove(b);lineups[team].add(a)
        events.append({"event_id":pid,"period":q,"clock":p.get("clock"),"wallclock":p.get("wallclock"),"team_id":team or None,"player_ids":participants,"class":tag,"score_delta":delta,"flags":flags,"original":p,"source_event_index":i})
    differences=[];compared=0
    for aid,b in box.items():
        x=counters[aid]
        fields=("fgm","fga","threem","threea","ftm","fta","rebounds","offensive_rebounds","defensive_rebounds","assists","turnovers","steals","blocks","personal_fouls")
        observed={k:x.get(k) if k in x else None for k in fields}
        if "fgm" in x or "ftm" in x:observed["points"]=x.get("fgm",0)*2+x.get("threem",0)+x.get("ftm",0)
        else:observed["points"]=None
        for k,v in observed.items():
            if v is None:continue
            compared+=1
            if v!=b.get(k):differences.append({"type":"event_vs_ESPN_box","player_id":aid,"name":b["name"],"metric":k,"pbp":v,"box":b.get(k)})
        b["derived_observed_stats"]=observed
        b["experimental_minutes"]=round(minutes[aid],3) if known.get(b["team_id"]) else None
        b["experimental_plus_minus"]=plusminus[aid] if known.get(b["team_id"]) else None
        if b["experimental_plus_minus"] is not None and b["plus_minus"] is not None and b["experimental_plus_minus"]!=b["plus_minus"]:
            differences.append({"type":"lineup_plus_minus_vs_box","player_id":aid,"name":b["name"],"pbp":b["experimental_plus_minus"],"box":b["plus_minus"]})
        if b["experimental_minutes"] is not None:
            try:
                if abs(b["experimental_minutes"]-float(b["minutes"]))>1.1:
                    differences.append({"type":"lineup_minutes_vs_box","player_id":aid,"name":b["name"],"pbp":b["experimental_minutes"],"box":b["minutes"]})
            except:pass
    if list(previous)!=[game["away"]["points"],game["home"]["points"]]:
        issues.append({"type":"terminal_score_mismatch","pbp":previous,"box":[game["away"]["points"],game["home"]["points"]]})
    return {"espn_event_id":eid,"date_et":game["game_date_et"],"teams":teams,"final_scores":{"away":previous[0],"home":previous[1]},"official_ESPN_box_players":box,"dnp":dnp,"period_scoring":dict(periods),"substitution_count":subs,"lineup_experimental":True,"lineup_issues":issues,"box_comparisons":differences,"observed_metrics_compared":compared,"events":events,"flags":{"paint_points":"missing_provider_validated_player_level","fast_break_points":"missing_provider_validated_player_level","second_chance_points":"missing_provider_validated_player_level","C3":"missing_compatible_individual_ratings","C6":"unverified","C11":"unverified","do_not_feed_invalid_derived_stats_to_scoring":True}}
def main():
    p=argparse.ArgumentParser();p.add_argument("--date-et",required=True);p.add_argument("--raw-root",default="data/historical/qpix_pbp_raw");p.add_argument("--out-root",default="data/historical/qpix_pbp_derived");a=p.parse_args()
    root=pathlib.Path(a.raw_root)/a.date_et;m=read(root/"manifest.json")
    assert m["date_et"]==a.date_et and m["final_games"]>0
    games=[derive_game(g,root) for g in m["games"]];n=sum(len(g["events"]) for g in games)
    assert len(games)==m["final_games"] and n==sum(g["events"] for g in m["games"])
    totals=collections.Counter(d.get("type","unclassified") for g in games for d in g["box_comparisons"]+g["lineup_issues"])
    out={"schema":"qpix_pbp_derived_v1","date_et":a.date_et,"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":{"workflow":"QPIX ESPN Play-by-Play Daily Raw Archive","raw_manifest_sha256":hashlib.sha256((root/"manifest.json").read_bytes()).hexdigest(),"events":n,"games":len(games),"full_original_events_retained":True},"games":games,"discrepancy_summary":dict(totals),"experimental_context_only":True}
    target=pathlib.Path(a.out_root)/(a.date_et+".json");target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    check=read(target);assert sum(len(g["events"]) for g in check["games"])==n
    print("ESPN PBP derived and readback verified:",a.date_et,len(games),"games",n,"events",dict(totals))
if __name__=="__main__":main()
