#!/usr/bin/env python3
"""Nov 11 ESPN original audit and November 5 experimental QCore rating fallback.
Authoritative QPIX category functions are never reimplemented here.
"""
import json, sys, hashlib, math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments'/'qcore'))
from model import predict, VERSION
DATE='2026-11-11'
j=json.loads((ROOT/f'data/historical/qpix_input/{DATE}.json').read_text())
players=j['players'];games=j['games']
assert j['date_et']==DATE and len(games)==10 and len(players)==223, 'Wrong date/partial slate'
prov=json.loads((ROOT/'data/espn_raw/provenance.json').read_text())
assert len(prov['captures'])==10 and all(x['status']=='STATUS_FINAL' for x in prov['captures'])
BY={(p['game_id'].removeprefix('ESPN_'),str(p['player_id'])):p for p in players}
assert len(BY)==len(players),'duplicate ESPN identities'
aliases={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','PHO':'PHX','UTAH':'UTA','WSH':'WAS'}
norm=lambda a:aliases.get(a,a)
audit={'game_date_et':DATE,'status':'PROVISIONAL','source_engine_git_blob_sha':'390833f45ee5191092813647f0735f1598cfeab1','qcore_model':VERSION,'provider_ratings_observed':0,'provider_ratings_error':'NBA Advanced V3 timed out; NBA LiveData HTTP 403','individual_C6_observed':0,'individual_fast_break_C11_observed':0,'games':[],'model_errors':[],'starter_conflicts':[],'player_source_discrepancies':[],'source_provenance':prov}
def basic(s):return {k:s[k] for k in ('mp','pts','fg','fga','fg3','fg3a','ft','fta','orb','drb','ast','stl','blk','tov','pf')}
for g in games:
 eid=str(g['espn_event_id']);f=ROOT/f'data/espn_raw/{eid}.json'
 original=f.read_bytes();pnext=next(x for x in prov['captures'] if x['event_id']==eid)
 assert hashlib.sha256(original).hexdigest()==pnext['sha256'], 'ESPN original bytes changed'
 obj=json.loads(original);header=obj['header']['competitions'][0]
 assert header['status']['type']['completed'] and header['status']['type']['name']=='STATUS_FINAL'
 periods=int(header['status'].get('period',4));mp=240+25*max(0,periods-4)
 totals={};team_extra={}
 for grp in obj['boxscore']['teams']:
  team=norm(grp['team']['abbreviation']);d={x['name']:x['displayValue'] for x in grp['statistics']}
  shoots=lambda k: list(map(int,d[k].split('-')))
  fg,fga=shoots('fieldGoalsMade-fieldGoalsAttempted');fg3,fg3a=shoots('threePointFieldGoalsMade-threePointFieldGoalsAttempted');ft,fta=shoots('freeThrowsMade-freeThrowsAttempted')
  tm={'mp':mp,'pts':g['home_points'] if team==g['home_alias'] else g['away_points'],'fg':fg,'fga':fga,'fg3':fg3,'fg3a':fg3a,'ft':ft,'fta':fta,'orb':int(d['offensiveRebounds']),'drb':int(d['defensiveRebounds']),'ast':int(d['assists']),'stl':int(d['steals']),'blk':int(d['blocks']),'tov':int(d['totalTurnovers']),'pf':int(d['fouls'])}
  assert tm['pts']==2*fg+fg3+ft,'team points not reconciled'
  totals[team]=tm
  team_extra[team]=int(d['teamTurnovers'])
 assert set(totals)=={g['home_alias'],g['away_alias']}
 matched=set()
 for grp in obj['boxscore']['players']:
  team=norm(grp['team']['abbreviation']);stat=grp['statistics'][0]
  assert 'PF' in stat['labels']
  for athlete in stat['athletes']:
   if athlete.get('didNotPlay') or not athlete.get('stats'):continue
   st=dict(zip(stat['labels'],athlete['stats']))
   key=(eid,str(athlete['athlete']['id']))
   assert key in BY and key not in matched,'unmatched or duplicate player'
   matched.add(key)
   p=BY[key];assert p['team']==team
   p['personal_fouls']=int(st['PF']);p['source_starter']=bool(athlete['starter'])
   if p['source_starter'] and p['minutes']<=0:raise ValueError('Starter zero minutes')
   assert float(st['MIN'])==p['minutes']
   for k,s in [('points','PTS'),('rebounds','REB'),('assists','AST'),('steals','STL'),('blocks','BLK'),('turnovers','TO'),('offensive_rebounds','OREB'),('defensive_rebounds','DREB')]:
    if p[k]!=int(st[s]):audit['player_source_discrepancies'].append([eid,p['name'],k,p[k],st[s]])
   for pfx,canon in [('FG',('fgm','fga')),('3PT',('fg3m','fg3a')),('FT',('ftm','fta'))]:
    x,y=map(int,st[pfx].split('-'));assert (p[canon[0]],p[canon[1]])==(x,y)
   assert float(st['+/-'])==p['plus_minus']
   p['source_provenance']={'basic_stats':'ESPN observed original raw','personal_fouls':'ESPN observed original raw','starter':'ESPN observed original raw','provider_OffR_DefR':None,'C6_individual':None,'C11_fast_break_individual':None}
 assert matched=={k for k in BY if k[0]==eid},'not all canon participants matched'
 checks={}
 for team,tm in totals.items():
  side=[p for p in players if p['game_id']==g['game_id'] and p['team']==team]
  pts=sum(p['points'] for p in side);mins=sum(p['minutes'] for p in side);pm=sum(p['plus_minus'] for p in side)
  diff=g['home_points']-g['away_points'];expect=5*diff*(1 if team==g['home_alias'] else -1)
  starters=sum(p['source_starter'] for p in side);tov=sum(p['turnovers'] for p in side)
  assert pts==tm['pts'] and pm==expect and starters==5
  assert abs(mins-tm['mp'])<=len(side)*.5+1,'minutes failed rounded-precision reconciliation'
  assert tov+team_extra[team]==tm['tov']
  checks[team]={'player_count':len(side),'points_reported':tm['pts'],'points_from_players':pts,'minutes_sum':mins,'minutes_expected':tm['mp'],'plus_minus_sum':pm,'plus_minus_expected':expect,'starter_count':starters,'player_plus_team_turnovers':tov+team_extra[team],'reported_team_turnovers':tm['tov']}
 for p in [x for x in players if x['game_id']==g['game_id']]:
  t=totals[p['team']];o=totals[g['away_alias'] if p['team']==g['home_alias'] else g['home_alias']]
  fields={'mp':p['minutes'],'pts':p['points'],'fg':p['fgm'],'fga':p['fga'],'fg3':p['fg3m'],'fg3a':p['fg3a'],'ft':p['ftm'],'fta':p['fta'],'orb':p['offensive_rebounds'],'drb':p['defensive_rebounds'],'ast':p['assists'],'stl':p['steals'],'blk':p['blocks'],'tov':p['turnovers'],'pf':p['personal_fouls']}
  try: res=predict(fields,basic(t),basic(o))
  except Exception as e:
   audit['model_errors'].append({'player_id':p['player_id'],'player':p['name'],'error':str(e)})
   res={'q_offr':None,'q_defr':None,'flags':['model_error'],'features':{}}
  p['qcore_q_offr']=round(res['q_offr'],2) if res['q_offr'] is not None else None
  p['qcore_q_defr']=round(res['q_defr'],2) if res['q_defr'] is not None else None
  p['qcore_flags']=res['flags'];p['qcore_model_features']=res['features']
  p['qcore_model_version']=VERSION;p['rating_source']='EXPERIMENTAL_QCORE_NOV05_MODEL_NOT_BBREF_OR_NBA'
  p['quality']={'basic_stats':'ESPN_OBSERVED','PF':'ESPN_OBSERVED','starter':'ESPN_OBSERVED','C3':'QCORE_EXPERIMENTAL_ESTIMATE_UNVALIDATED_CURRENT_DATE' if res['q_offr'] is not None and res['q_defr'] is not None else 'UNAVAILABLE','C4_defensive_rating':'QCORE_EXPERIMENTAL_ESTIMATE' if res['q_defr'] is not None else 'UNAVAILABLE','C6':'UNAVAILABLE_NOT_OBSERVED_ZERO','C11':'PARTIAL_MISSING_FAST_BREAK_POINTS','minutes':'ESPN_ROUNDED_WHOLE_MINUTES'}
  if p['qcore_q_offr'] is not None:p['offensive_rating']=p['qcore_q_offr']
  if p['qcore_q_defr'] is not None:p['defensive_rating']=p['qcore_q_defr']
 audit['games'].append({'event_id':eid,'home':g['home_alias'],'away':g['away_alias'],'team_checks':checks,'status':'FINAL'})
assert not audit['player_source_discrepancies'] and len(audit['games'])==10
audit['participating_players']=len(players);audit['eligible_strictly_gt8']=sum(p['minutes']>8 for p in players)
audit['qcore_both']=sum(p['qcore_q_offr'] is not None and p['qcore_q_defr'] is not None for p in players)
audit['qcore_missing_both']=len(players)-audit['qcore_both']
(ROOT/'data/nba_data.json').write_text(json.dumps({'date_et':DATE,'games':games,'players':players,'original_input_sha256':j['input_sha256']},ensure_ascii=False,indent=2))
(ROOT/f'docs/reports/{DATE}.audit.json').parent.mkdir(parents=True,exist_ok=True)
(ROOT/f'docs/reports/{DATE}.audit.json').write_text(json.dumps(audit,indent=2))
print(json.dumps({'game_date_et':DATE,'games':len(games),'players':len(players),'ratings_both':audit['qcore_both'],'missing':audit['qcore_missing_both'],'eligible':audit['eligible_strictly_gt8']}))
