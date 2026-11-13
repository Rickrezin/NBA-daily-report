#!/usr/bin/env python3
"""Independently audit pregame FTA baselines for the Nov 12 QPIX shadow slate.

No scorer coefficients are modified. Uses individual 2026-27 regular-season
ESPN game logs and confirms the target-game event ID and recorded FTA.
"""
import concurrent.futures
import datetime
import json
from pathlib import Path
import re
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATE='2026-11-12'
SCORED=ROOT/'data/daily'/f'{DATE}.provisional.json'
OUT=ROOT/'data/historical/qpix_fta'/f'{DATE}.json'
TARGET=json.loads(SCORED.read_text())
PLAYERS=TARGET['players']
URL='https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{}/gamelog?season=2027'
ET=ZoneInfo('America/New_York')

def fetch(player):
    pid=str(player['player_id'])
    target_game=str(player['game_id']).removeprefix('ESPN_')
    url=URL.format(pid)
    errors=[]
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={
                'User-Agent':'Mozilla/5.0 (QCore Labs data audit)',
                'Accept':'application/json',
            })
            with urllib.request.urlopen(req,timeout=22) as resp:
                data=json.load(resp)
            labels=data['labels']
            names=data.get('names') or []
            if 'FT' in labels:
                ft_index=labels.index('FT')
            else:
                ft_index=next(i for i,n in enumerate(names) if n.lower().startswith('freethrow'))
            event_info=data.get('events',{})
            types=[x for x in data.get('seasonTypes',[]) if 'Regular Season' in x.get('displayName','')]
            if len(types)!=1:
                raise ValueError('Could not uniquely identify 2026-27 regular season')
            events=[]
            for category in types[0].get('categories',[]):
                for e in category.get('events',[]):
                    eid=str(e.get('eventId') or '')
                    if not eid:continue
                    meta=event_info.get(eid,{}) if isinstance(event_info,dict) else {}
                    raw_date=meta.get('date','')
                    if not raw_date:
                        raise ValueError('Event has no verifiable date '+eid)
                    utc=datetime.datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                    local_date=utc.astimezone(ET).date().isoformat()
                    ft=e['stats'][ft_index]
                    m=re.fullmatch(r'(\d+)-(\d+)',str(ft))
                    if not m:
                        raise ValueError('Invalid made-attempted FT entry '+repr(ft))
                    made,attempted=map(int,m.groups())
                    if made>attempted:raise ValueError('FT makes exceed attempts')
                    events.append({'event_id':eid,'date_et':local_date,'ftm':made,'fta':attempted})
            matching=[e for e in events if e['event_id']==target_game]
            if len(matching)!=1:
                raise ValueError('Target game absent or duplicate: '+target_game)
            current=matching[0]
            if current['date_et']!=DATE or current['fta']!=player['fta'] or current['ftm']!=player['ftm']:
                raise ValueError(f"Current game mismatch {current} vs {player['fta']} FTA")
            previous=sorted((e for e in events if e['date_et']<DATE),
                            key=lambda e:(e['date_et'],e['event_id']))
            # ESPN regular-season game log is complete to its available timestamp;
            # target-date is independently present and matches today's box score.
            trailing=previous[-20:]
            n=len(trailing)
            baseline=sum(e['fta'] for e in trailing)/n if n else None
            return {'player_id':pid,'name':player['name'],'team':player['team'],
                    'source_url':url,'status':'ESPN_GAMELOG_VERIFIED',
                    'current_game_id':target_game,'current_fta':current['fta'],
                    'previous_games':len(previous),'rolling20_games':n,
                    'pregame_rolling20_fta':baseline,
                    'prior_season_game_rows':previous}
        except Exception as ex:
            errors.append(str(ex))
            time.sleep((attempt+1)*0.7)
    return {'player_id':pid,'name':player['name'],'team':player['team'],
            'source_url':url,'status':'UNAVAILABLE','errors':errors}

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        result=list(pool.map(fetch,PLAYERS))
    keyed={r['player_id']:r for r in result}
    if len(keyed)!=len(PLAYERS):raise RuntimeError('Duplicate player identity')
    status_counts={}
    for item in result:status_counts[item['status']]=status_counts.get(item['status'],0)+1
    archive={'date_et':DATE,'season':'2026-27','provider':'ESPN_ATHLETE_GAMELOG',
             'source':'site.web.api.espn.com',
             'current_game_excluded':True,'status_counts':status_counts,
             'player_count':len(PLAYERS),'players':keyed}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(archive,indent=2,ensure_ascii=False)+'\n')
    trae=next((r for r in result if r['name']=='Trae Young'),None)
    print('GAMELOG_AUDIT',json.dumps({'counts':status_counts,'Trae':{
        k:trae.get(k) for k in ['status','previous_games','pregame_rolling20_fta',
                               'current_fta','errors']} if trae else None}))
    # fail closed if less than 75% of target roster verified
    if status_counts.get('ESPN_GAMELOG_VERIFIED',0)<68:
        raise SystemExit('Incomplete roster-wide gamelog coverage: do not publish recalculation')

if __name__=='__main__':main()
