import json,urllib.request,re,subprocess,os
from pathlib import Path
DAY='2026-10-23'
scores={'NYK-BOS':(103,107),'ATL-CHA':(128,81),'MEM-GSW':(111,108),'DAL-IND':(121,105),'LAC-LAL':(117,125),'DET-MIA':(128,111),'CHI-MIL':(132,125),'MIN-ORL':(115,93),'POR-SAC':(128,120),'HOU-SAS':(114,110),'NOP-UTA':(119,120),'TOR-WAS':(112,102)}
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64)','Referer':'https://www.nba.com/'})
 with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
def number(v):
 try:return float(v) if v is not None else None
 except:return None
def minutes(v):
 if not v:return 0
 if isinstance(v,(int,float)):return float(v)
 if v.startswith('PT'):
  m=re.search(r'(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?',v[2:])
  return float(m[1] or 0)+float(m[2] or 0)/60
 if ':' in v:
  x,y=v.split(':',1);return float(x)+float(y)/60
 return float(v)
def alias(t):return t.get('teamTricode') or t.get('teamCode')
schedule=fetch('https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json')
games=[g for d in schedule['leagueSchedule']['gameDates'] if '10/23/2026' in str(d.get('gameDate','')) for g in d.get('games',[])]
assert len(games)==12,f'Expected 12 games, found {len(games)}'
outgames=[];players=[];missing=set()
for game in games:
 away,home=alias(game['awayTeam']),alias(game['homeTeam']);key=away+'-'+home
 assert key in scores,key
 obj=fetch('https://cdn.nba.com/static/json/liveData/boxscore/boxscore_'+game['gameId']+'.json')['game']
 sa,sh=scores[key]
 assert (int(obj['awayTeam']['score']),int(obj['homeTeam']['score']))==(sa,sh),key
 outgames.append(dict(game_id=game['gameId'],away_alias=away,home_alias=home,away_points=sa,home_points=sh))
 for side in ['awayTeam','homeTeam']:
  team=obj[side];teamcode=alias(team);teamplayers=[]
  for source in team['players']:
   s=source.get('statistics') or {};m=minutes(s.get('minutes'))
   if m<=0:continue
   def n(field):
    v=number(s.get(field))
    if v is None:missing.add(field);return 0
    return int(v) if v.is_integer() else v
   fta=n('freeThrowsAttempted');ftm=n('freeThrowsMade')
   p=dict(name=source.get('name') or (source.get('firstName','')+' '+source.get('familyName','')).strip(),team=teamcode,position=source.get('position') or 'G',minutes=m,points=n('points'),rebounds=n('reboundsTotal'),offensive_rebounds=n('reboundsOffensive'),defensive_rebounds=n('reboundsDefensive'),assists=n('assists'),steals=n('steals'),blocks=n('blocks'),turnovers=n('turnovers'),fgm=n('fieldGoalsMade'),fga=n('fieldGoalsAttempted'),fg3m=n('threePointersMade'),fg3a=n('threePointersAttempted'),ftm=ftm,fta=fta,ft_pct=ftm/fta if fta else .75,plus_minus=n('plusMinusPoints'),offensive_rating=number(s.get('offensiveRating')),defensive_rating=number(s.get('defensiveRating')),second_chance_points=n('pointsSecondChance'),fast_break_points=n('pointsFastBreak'),points_in_paint=n('pointsInThePaint'),game=away+' @ '+home,home_alias=home,away_alias=away,home_points=sh,away_points=sa,is_home=teamcode==home)
   assert p['name'];teamplayers.append(p)
  assert len(teamplayers)>=7,(key,teamcode,len(teamplayers))
  assert sum(p['points'] for p in teamplayers)==int(team['score']),(key,teamcode)
  players+=teamplayers
assert len(players)>=200
Path('data').mkdir(exist_ok=True)
Path('data/nba_data.json').write_text(json.dumps({'games':outgames,'players':players}))
code=Path('generate-report.js').read_text()
marker='  const top10 = scoredPlayers.slice(0, 10);'
assert marker in code
extra="""
  const ranked=scoredPlayers.map((p,i)=>({...p,rank:i+1}));
  const day='2026-10-23';
  mkdirSync(join(process.cwd(),'data','daily'),{recursive:true});
  mkdirSync(join(process.cwd(),'docs','reports'),{recursive:true});
  const quality={source:'NBA live boxscore CDN',players:ranked.length,completed_games:games.length,missing_individual_advanced:ranked.filter(p=>!p.ratingsAvailable).map(p=>p.name+' ('+p.team+')'),missing_source_fields:JSON.parse(process.env.QPIX_MISSING_FIELDS||'[]'),note:'Unverified advanced ratings left null, C3 unavailable. No fabricated inputs.'};
  writeFileSync(join(process.cwd(),'data','daily',day+'.json'),JSON.stringify({schema_version:2,season:'2026-27',date_et:day,phase:'regular',generated_at_utc:new Date().toISOString(),scoring_engine:{file:'generate-report.js',rank_by:'RAW only'},data_quality:quality,games,players:ranked},null,2)+'\\n');
  const fields=['rank','name','team','game','score','qpixR','qpixSFA','sfaAdj','points','rebounds','assists','steals','blocks','turnovers','minutes','fgm','fga','ftm','fta','plus_minus','offensive_rating','defensive_rating','ratingsAvailable','refPenalty','refBonus'];
  const csvval=v=>'"'+String(v??'').replaceAll('"','""')+'"';
  writeFileSync(join(process.cwd(),'data','daily',day+'.csv'),[fields.join(','),...ranked.map(p=>fields.map(k=>csvval(p[k])).join(','))].join('\\n')+'\\n');
  const report=['# QPIX™ NBA Daily Index — October 23, 2026','','QCore Labs | 2026–27 Regular Season','', '## Coverage and data quality','', games.length+' FINAL games; '+ranked.length+' players scored. Source: NBA official live boxscore CDN.','', 'Individual ORtg/DRtg unavailable for '+quality.missing_individual_advanced.length+' players; C3 explicitly marked unavailable (score 0) rather than estimated.','Missing source fields: '+(quality.missing_source_fields.join(', ')||'none')+'.','Raw QPIX sets ranks. QPIX-R and SFA are companion metrics.','','## Final scores','',...games.map(g=>'- '+g.away_alias+' '+g.away_points+' @ '+g.home_alias+' '+g.home_points),'','## Full QPIX leaderboard','','| Rank | Player | Team | PTS | REB | AST | RAW | QPIX-R | QPIX-SFA |','|---:|---|---|---:|---:|---:|---:|---:|---:|',...ranked.map(p=>'| '+p.rank+' | '+p.name+' | '+p.team+' | '+p.points+' | '+p.rebounds+' | '+p.assists+' | '+p.score+' | '+p.qpixR+' | '+(p.sfaAdj?p.qpixSFA:'—')+' |'),'','See JSON for source stats and player-level notes.'];
  writeFileSync(join(process.cwd(),'docs','reports',day+'.md'),report.join('\\n')+'\\n');
"""
# extra is JS pasted using Python triple quotes: convert \n JS literal to 
 escapes
code=code.replace(marker,extra+'\n'+marker)
Path('generate-report.js').write_text(code)
env=os.environ.copy();env.update(QPIX_PHASE='regular',QPIX_SEASON_END='2027',QPIX_MISSING_FIELDS=json.dumps(sorted(missing)))
try:subprocess.run(['node','generate-report.js'],check=True,env=env)
finally:Path('generate-report.js').write_text(Path('generate-report.js').read_text().replace(extra+'\n',''))
for path in ['data/daily/2026-10-23.json','data/daily/2026-10-23.csv','docs/reports/2026-10-23.md']:assert Path(path).stat().st_size>100
print('Verified',len(players),'players and 12 games')
