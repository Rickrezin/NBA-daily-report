#!/usr/bin/env python3
"""Date-scoped daily supplemental QPIX audit; NEVER changes scoring or published ranks."""
import argparse,collections,csv,datetime,hashlib,html.parser,json,pathlib,re,time,unicodedata,urllib.parse,urllib.request
P=pathlib.Path
HEAD={'User-Agent':'QCoreLabs-QPIX-Research/1.0 (https://github.com/Rickrezin/NBA-daily-report)','Accept':'application/json,text/html'}
ALIASES={'WSH':'WAS','NO':'NOP','GS':'GSW','UTAH':'UTA','BRK':'BKN','PHO':'PHX'}
def alias(s):return ALIASES.get(s,s)
def norm(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()
 return re.sub('[^a-z0-9]','',re.sub(r'\b(jr|sr|ii|iii|iv)\b','',s))
def dump(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
def fetch(url,path,timeout=15):
 if path.exists() and path.stat().st_size>200:return path.read_bytes()
 with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=timeout) as r:b=r.read(3500000)
 if not b:raise RuntimeError('Empty response')
 path.write_bytes(b);return b
class BRef(html.parser.HTMLParser):
 def __init__(self):super().__init__();self.table=None;self.row=None;self.cell=None;self.href=None;self.rows=[]
 def handle_starttag(self,t,attrs):
  d=dict(attrs)
  if t=='table' and re.fullmatch(r'box-[A-Z]{2,3}-game-advanced',d.get('id','')):self.table=alias(d['id'].split('-')[1])
  if self.table is None:return
  if t=='tr':self.row={'team':self.table}
  if t in ('td','th') and self.row is not None:self.cell=[d.get('data-stat'),[]]
  if t=='a' and self.cell is not None and self.cell[0]=='player':self.href=d.get('href')
 def handle_data(self,x):
  if self.cell is not None:self.cell[1].append(x)
 def handle_endtag(self,t):
  if self.table is None:return
  if t in ('td','th') and self.cell is not None:
   if self.cell[0]:self.row[self.cell[0]]=''.join(self.cell[1]).strip()
   if self.cell[0]=='player' and self.href:self.row['profile']=self.href
   self.cell=None;self.href=None
  if t=='tr' and self.row is not None:
   if self.row.get('player') and self.row.get('off_rtg') and self.row.get('def_rtg'):self.rows.append(self.row)
   self.row=None
  if t=='table':self.table=None
def clock(e):
 try:
  z=e['clock'];z=z.get('displayValue') if isinstance(z,dict) else z
  per=e['period'];per=per.get('number') if isinstance(per,dict) else per
  mm,ss=(z.split(':',1) if ':' in z else ('0',z))
  return int(per),int(mm)*60+float(ss)
 except (KeyError,TypeError,ValueError,AttributeError):return None
def transitions(events):
 counts=collections.Counter();samples=[];exclusions=collections.Counter()
 for i,e in enumerate(events):
  if e.get('class')!='field_goal_attempt' or not e.get('original',{}).get('scoringPlay'):continue
  end=clock(e)
  if not end:exclusions['clock_missing']+=1;continue
  team=e.get('team_id')
  for prior in reversed(events[:i]):
   start=clock(prior)
   if not start:continue
   if start[0]!=end[0]:break
   dt=start[1]-end[1]
   if dt>13:break
   if dt<0:continue
   kind=prior.get('class')
   if kind=='offensive_rebound' and prior.get('team_id')==team:exclusions['off_reb_interrupt']+=1;break
   if kind in ('substitution','foul') and dt>0:exclusions['stoppage']+=1;break
   origin=(kind=='defensive_rebound' and prior.get('team_id')==team) or (kind=='turnover' and prior.get('team_id')!=team)
   if origin:
    pts=e.get('original',{}).get('scoreValue',0)
    try:pts=int(pts)
    except (TypeError,ValueError):pts=0
    if pts>0:
     band='0-4' if dt<4 else '4-8' if dt<8 else '8-12' if dt<12 else '12-13'
     counts[(kind,band)]+=pts
     samples.append({'scoring_event_id':e.get('event_id'),'origin_event_id':prior.get('event_id'),'display_elapsed':dt,'origin':kind,'candidate_points':pts,'band':band,'status':'EXPERIMENTAL_NOT_OFFICIAL'})
    break
 return {'point_bands':[{'origin':a,'band':b,'candidate_points':v} for (a,b),v in sorted(counts.items())],'event_candidates':samples,'excluded_reasons':dict(exclusions)}
def main(date):
 base=P('data/historical/qpix_pbp_derived')/f'{date}.json'
 if not base.exists():raise SystemExit('Missing ESPN historical derivation for '+date)
 data=json.loads(base.read_text()); games=data.get('games',[])
 out=P('data/historical/qpix_multisource_daily')/date;out.mkdir(parents=True,exist_ok=True)
 report=P('data/daily')/f'{date}.provisional.json'
 if not report.exists():report=P('data/daily')/f'{date}.json'
 published=json.loads(report.read_text()) if report.exists() else {}
 official_date_audit=P('docs/reports')/f'{date}.audit.json'
 a=json.loads(official_date_audit.read_text()) if official_date_audit.exists() else {}
 known={str(k):str(v) for k,v in a.get('verified_nba_id_crosswalk',{}).items()}
 if date=='2026-11-18':
  known.update({'401910007':'0022600258','401910008':'0022600259','401910009':'0022600260','401910010':'0022600261','401910011':'0022600262','401910012':'0022600263','401910013':'0022600264','401910014':'0022600265','401910015':'0022600266','401910016':'0022600267','401910017':'0022600268','401910018':'0022600269'})
 catalog=[];status=[]
 if len(known)<len(games):
  y=int(date[:4]) if int(date[5:7])>=10 else int(date[:4])-1
  u='https://api.pbpstats.com/get-games/nba?'+urllib.parse.urlencode({'Season':f'{y}-{str(y+1)[-2:]}','SeasonType':'Regular Season'})
  try:catalog=json.loads(fetch(u,out/'pbpstats_game_index.json',18)).get('results',[])
  except Exception as exc:status.append({'source':'PBPStats game index','error':str(exc)})
 rows=[];details=[]
 for g in games:
  eid=str(g['espn_event_id']);teammap={str(k):alias(v['alias']) for k,v in g['teams'].items()}
  teamset=set(teammap.values());final=g['final_scores'];nbi=known.get(eid)
  c=next((x for x in catalog if x.get('Date')==date and {x.get('HomeTeamAbbreviation'),x.get('AwayTeamAbbreviation')}==teamset and x.get('AwayPoints')==final['away'] and x.get('HomePoints')==final['home']),None)
  if not nbi and c:nbi=c['GameId']
  q={'espn_event_id':eid,'nba_game_id':nbi,'issues':[]}
  if not nbi:q['issues'].append('NBA_GAME_ID_UNRESOLVED')
  home=c.get('HomeTeamAbbreviation') if c else None
  if not home:
   for game in published.get('games',[]):
    if str(game.get('espn_event_id'))==eid or ({alias(game.get('home_alias')),alias(game.get('away_alias'))}==teamset and game.get('home_points')==final['home']):home=alias(game['home_alias']);break
  pstat={};br={}
  if nbi:
   url='https://api.pbpstats.com/get-game-stats?'+urllib.parse.urlencode({'GameId':nbi,'Type':'Player'})
   try:
    j=json.loads(fetch(url,out/f'{nbi}_pbpstats.json',14));ps=j.get('stats',{})
    if isinstance(ps,dict):
     for side in ('Away','Home'):
      for v in ps.get(side,{}).get('FullGame',[]):
       if isinstance(v,dict) and v.get('Name')!='Team':pstat[norm(v.get('Name',''))]=v
    else:q['issues'].append('PBPSTATS_UNEXPECTED_RESPONSE_SHAPE')
   except Exception as exc:q['issues'].append('PBPStats '+str(exc))
  if home:
   h={'BKN':'BRK','PHX':'PHO'}.get(home,home)
   url=f'https://www.basketball-reference.com/boxscores/{date.replace("-","")}0{h}.html'
   try:
    raw=fetch(url,out/f'{nbi or eid}_bref.html',17);parse=BRef();parse.feed(raw.decode('utf-8','replace'))
    br={(x['team'],norm(x['player'])):x for x in parse.rows}
   except Exception as exc:q['issues'].append('BRef '+str(exc))
  else:q['issues'].append('HOME_TEAM_UNRESOLVED')
  for b in g.get('official_ESPN_box_players',{}).values():
   team=teammap.get(str(b['team_id']));name=norm(b['name'])
   bx=br.get((team,name));px=pstat.get(name)
   if px and px.get('Points') is not None and int(px['Points'])!=b.get('points'):
    q['issues'].append('PBP_PLAYER_POINTS_MISMATCH_'+b['name']);px=None
   rows.append({'date_et':date,'espn_event_id':eid,'nba_game_id':nbi,'espn_player_id':b['player_id'],'nba_player_id':px.get('EntityId') if px else None,'team':team,'name':b['name'],'espn_points':b.get('points'),'espn_minutes':b.get('minutes'),'bref_player':bx.get('profile') if bx else None,'bref_off_rtg':bx.get('off_rtg') if bx else None,'bref_def_rtg':bx.get('def_rtg') if bx else None,'pbpstats_second_chance_points':px.get('SecondChancePoints') if px else None,'second_chance_quality':'PBPSTATS_REPORTED' if px and 'SecondChancePoints' in px else 'MISSING_OR_ZERO_SUPPRESSED','fast_break_points':None,'points_in_paint':None,'context_quality':'EXPERIMENTAL_NOT_SCORED'})
  # Coordinate coverage is measurable, but physical paint geometry remains uncalibrated.
  shot_events=[e for e in g.get('events',[]) if e.get('class')=='field_goal_attempt']
  made_shots=[e for e in shot_events if e.get('original',{}).get('scoringPlay')]
  q['paint_coordinate_audit']={'field_goal_attempts':len(shot_events),'attempts_with_coordinates':sum(e.get('original',{}).get('coordinate') is not None for e in shot_events),'made_field_goals':len(made_shots),'made_with_coordinates':sum(e.get('original',{}).get('coordinate') is not None for e in made_shots),'quality':'COORDINATES_OBSERVED_PAINT_BOUNDARIES_NOT_CALIBRATED'}
  candidate=transitions(g.get('events',[]));dump(out/f'{eid}_fastbreak_timing.json',candidate)
  q['fastbreak_candidate_bands']=candidate['point_bands']
  q['players_espn']=len(g.get('official_ESPN_box_players',{}))
  q['bref_matched']=sum(x['bref_off_rtg'] is not None and x['bref_def_rtg'] is not None for x in rows if x['espn_event_id']==eid)
  q['pbpstats_matched']=sum(x['nba_player_id'] is not None for x in rows if x['espn_event_id']==eid)
  details.append(q);print('QPREFIX_GAME',date,eid,nbi,q['players_espn'],q['bref_matched'],q['pbpstats_matched'],q['issues'],flush=True)
  dump(out/'partial.json',{'games':details,'players':rows,'warnings':status})
  time.sleep(2)
 summary={'date_et':date,'games':len(details),'espn_player_records':len(rows),'published_player_records':len(published.get('players',[])) if published else None,'bref_rating_pairs':sum(x['bref_off_rtg'] is not None and x['bref_def_rtg'] is not None for x in rows),'pbpstats_players':sum(x['nba_player_id'] is not None for x in rows),'explicit_second_chance_values':sum(x['pbpstats_second_chance_points'] is not None for x in rows),'unresolved':sum(len(x['issues']) for x in details),'quality':'RESEARCH_ONLY_NO_SCORE_UPDATES'}
 dump(out/'audit.json',{'summary':summary,'games':details,'players':rows,'warnings':status})
 with (out/'players.csv').open('w',newline='') as f:
  if rows:
   writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 print('QPIX_MULTI_SOURCE_DAILY_AUDIT',json.dumps(summary),flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--date-et',required=True);args=ap.parse_args();datetime.date.fromisoformat(args.date_et);main(args.date_et)
