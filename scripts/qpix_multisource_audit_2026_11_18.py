#!/usr/bin/env python3
"""2026-11-18 full-slate source audit. Read-only: never modify QPIX scoring."""
import collections,csv,datetime,hashlib,html.parser,json,pathlib,re,time,unicodedata,urllib.request,urllib.error,urllib.parse
ROOT=pathlib.Path.cwd()
DATE='2026-11-18'
OUT=ROOT/'data/historical/qpix_multisource_audit'/DATE
OUT.mkdir(parents=True,exist_ok=True)
ESPN=json.loads((ROOT/'data/historical/qpix_pbp_derived'/f'{DATE}.json').read_text())
HEAD={'User-Agent':'QCoreLabs-QPIX-Statistical-Research/1.0 (+https://github.com/Rickrezin/NBA-daily-report)','Accept':'application/json,text/html'}
def save(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def request(url,sec=25):
    with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=sec) as resp:
        b=resp.read(2400000)
        return b,resp.status
def norm(n):
    n=unicodedata.normalize('NFKD',str(n)).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]','',re.sub(r'\b(jr|sr|ii|iii|iv)\b','',n))
class BRefParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__();self.table=None;self.cell=None;self.row=None;self.entries=[];self.anchor=None
    def handle_starttag(self,t,a):
        at=dict(a)
        if t=='table' and re.fullmatch(r'box-[A-Z]{2,3}-game-advanced',at.get('id','')):
            self.table=at['id'];self.team=self.table.split('-')[1]
        if self.table is None:return
        if t=='tr':self.row={'team':self.team};self.row_class=at.get('class','')
        if t in ('td','th') and self.row is not None:
            self.cell={'key':at.get('data-stat'),'text':[]}
        if t=='a' and self.cell is not None and self.cell['key']=='player':self.anchor=at.get('href')
    def handle_data(self,d):
        if self.cell is not None:self.cell['text'].append(d)
    def handle_endtag(self,t):
        if self.table is None:return
        if t in ('td','th') and self.cell is not None:
            if self.cell['key']:self.row[self.cell['key']]=''.join(self.cell['text']).strip()
            if self.cell['key']=='player' and self.anchor:self.row['profile_href']=self.anchor
            self.cell=None;self.anchor=None
        if t=='tr' and self.row is not None:
            if self.row.get('player') and self.row.get('off_rtg') is not None:
                self.entries.append(self.row)
            self.row=None
        if t=='table':self.table=None
def eps_players(g):
    result=[]
    for p in g.get('official_ESPN_box_players',{}).values():
        if p.get('player_id') and p.get('name'):
            result.append(p)
    return result
pbpbase='https://api.pbpstats.com'
# Date-scoped game IDs have already been independently verified against ESPN scores.
# Avoid repeating a high-latency season-wide request; use the checked-in verified crosswalk.
crosswalk=(ROOT/'docs/qpix-source-schema-crosswalk-2026-11-18.md').read_text()
sourcegames=[]
for line in crosswalk.splitlines():
    pieces=[v.strip() for v in line.split('|')]
    if len(pieces)==7 and re.fullmatch(r'401\d{6}',pieces[1]) and re.fullmatch(r'002\d{7}',pieces[2]):
        away,home=pieces[3],pieces[4]
        scores=re.findall(r'\d+',pieces[5])
        if len(scores)==2:
            sourcegames.append({'GameId':pieces[2],'Date':DATE,'HomeTeamAbbreviation':home,'AwayTeamAbbreviation':away,'HomePoints':int(scores[1]),'AwayPoints':int(scores[0])})
assert len(sourcegames)==12,('Crosswalk extraction error',len(sourcegames))
pbpbase='https://api.pbpstats.com'
matches=[]
for g in ESPN['games']:
    teams=g['teams'];alias_map={'WSH':'WAS','NO':'NOP','GS':'GSW','UTAH':'UTA'};aliases={alias_map.get(v['alias'],v['alias']) for v in teams.values()}
    away,home=g['final_scores']['away'],g['final_scores']['home']
    m=[x for x in sourcegames if {x['AwayTeamAbbreviation'],x['HomeTeamAbbreviation']}==aliases and x['AwayPoints']==away and x['HomePoints']==home]
    assert len(m)==1,('Ambiguous game join',g['espn_event_id'],m)
    matches.append((g,m[0]))
save(OUT/'game_crosswalk.json',[{'espn_event_id':g['espn_event_id'],'nba_game_id':x['GameId'],'away':x['AwayTeamAbbreviation'],'home':x['HomeTeamAbbreviation'],'away_score':x['AwayPoints'],'home_score':x['HomePoints']} for g,x in matches])
audit=[];players=[];sources=[]
for idx,(g,ng) in enumerate(matches,1):
    nbaid=ng['GameId'];home=ng['HomeTeamAbbreviation']
    rec={'nba_game_id':nbaid,'espn_event_id':g['espn_event_id'],'teams':home+'/'+ng['AwayTeamAbbreviation'],'errors':[]}
    pbp=None;bres=[]
    try:
        cache=OUT/f'{nbaid}_pbpstats.json'
        if cache.is_file():
            raw=cache.read_bytes();status=200;rec['pbpstats_cache_reused']=True
        else:
            raw,status=request(pbpbase+'/get-game-stats?'+urllib.parse.urlencode({'GameId':nbaid,'Type':'Player'}),sec=15)
            cache.write_bytes(raw)
        pbp=json.loads(raw)
        rec['pbpstats_http']=status;rec['pbpstats_records']=len(pbp.get('stats',[]))
        rec['pbpstats_stats_shape']=type(pbp.get('stats')).__name__
        rec['pbpstats_sha256']=hashlib.sha256(raw).hexdigest()
    except Exception as e:rec['errors'].append('PBPStats '+repr(e))
    time.sleep(1.25)
    home_bref={'BKN':'BRK','PHX':'PHO'}.get(home,home)
    brefurl=f'https://www.basketball-reference.com/boxscores/{DATE.replace("-","")}0{home_bref}.html'
    try:
        cache=OUT/f'{nbaid}_bref.html'
        if cache.is_file():
            raw=cache.read_bytes();status=200;rec['bref_cache_reused']=True
        else:
            raw,status=request(brefurl,sec=18)
            cache.write_bytes(raw)
        p=BRefParser();p.feed(raw.decode('utf-8','replace'));bres=p.entries
        rec['bref_http']=status;rec['bref_records']=len(bres)
        rec['bref_sha256']=hashlib.sha256(raw).hexdigest()
    except Exception as e:rec['errors'].append('BRef '+repr(e))
    time.sleep(3.5)
    raw_stats=(pbp or {}).get('stats',{})
    ps=[]
    if isinstance(raw_stats,dict) and 'Away' in raw_stats and 'Home' in raw_stats:
        rec['pbpstats_collection_type']='team_period_fullgame'
        for side,team_alias in [('Away',ng['AwayTeamAbbreviation']),('Home',ng['HomeTeamAbbreviation'])]:
            for item in raw_stats.get(side,{}).get('FullGame',[]):
                if isinstance(item,dict) and item.get('Name')!='Team':
                    ps.append(dict(item,source_team_alias=team_alias))
    elif isinstance(raw_stats,list):
        rec['pbpstats_collection_type']='array'
        ps=[p for p in raw_stats if isinstance(p,dict)]
    else:
        rec['pbpstats_collection_type']='UNSUPPORTED'

    pbn=collections.defaultdict(list);brn=collections.defaultdict(list)
    for p in ps:
        pbn[(p.get('source_team_alias'),norm(p.get('Name','')))].append(p)
    for p in bres:
        brn[({'BRK':'BKN','PHO':'PHX'}.get(p['team'],p['team']),norm(p.get('player','')))].append(p)
    used_pbp=set();used_bref=set()
    for ep in eps_players(g):
        e_team=alias_map.get(g['teams'].get(str(ep.get('team_id')),{}) .get('alias'),g['teams'].get(str(ep.get('team_id')),{}) .get('alias'))
        key=norm(ep['name'])
        candidates=pbn.get((e_team,key),[])
        b_candidates=brn.get((e_team,key),[])
        pbm=candidates[0] if len(candidates)==1 else None
        brm=b_candidates[0] if len(b_candidates)==1 else None
        if pbm is not None and (pbm.get('Points') is not None and int(pbm.get('Points'))!=ep.get('points')):
            rec['errors'].append('PBPStats points mismatch '+ep['name']);pbm=None
        if pbm is not None:
            token=str(pbm['EntityId'])
            if token in used_pbp:rec['errors'].append('Duplicate PBPStats player '+ep['name']);pbm=None
            else:used_pbp.add(token)
        if brm is not None:
            token=(e_team,brm.get('profile_href',brm['player']))
            if token in used_bref:rec['errors'].append('Duplicate BRef '+ep['name']);brm=None
            else:used_bref.add(token)
        pentry={'game_id_espn':g['espn_event_id'],'game_id_nba':nbaid,'team':e_team,'name_espn':ep['name'],'espn_player_id':ep['player_id'],'points_espn':ep.get('points'),
          'nba_player_id':pbm.get('EntityId') if pbm else None,'pbp_name':pbm.get('Name') if pbm else None,
          'second_chance_points':pbm.get('SecondChancePoints') if pbm else None,
          'second_chance_value_status':'PBPSTATS_REPORTED' if pbm and 'SecondChancePoints' in pbm else 'MISSING_OR_ZERO_SUPPRESSED',
          'live_ball_turnovers':pbm.get('LiveBallTurnovers') if pbm else None,
          'dead_ball_turnovers':pbm.get('DeadBallTurnovers') if pbm else None,
          'pbp_off_possessions':pbm.get('OffPoss') if pbm else None,
          'bref_profile':brm.get('profile_href') if brm else None,'bref_off_rtg':brm.get('off_rtg') if brm else None,
          'bref_def_rtg':brm.get('def_rtg') if brm else None,'bref_minutes':brm.get('mp') if brm else None,
          'bref_bpm':brm.get('bpm') if brm else None,
          'source_quality':{'pbpstats':'MATCHED_POINTS_ID' if pbm else 'UNMATCHED','bref':'MATCHED_NAME_TEAM' if brm else 'UNMATCHED'}}
        players.append(pentry)
    rec['espn_player_count']=len(eps_players(g))
    rec['matched_pbpstats']=sum(p['source_quality']['pbpstats']!='UNMATCHED' for p in players if p['game_id_nba']==nbaid)
    rec['matched_bref']=sum(p['source_quality']['bref']!='UNMATCHED' for p in players if p['game_id_nba']==nbaid)
    rec['pbpstats_unmatched_records']=len(ps)-len(used_pbp)
    rec['bref_unmatched_records']=len(bres)-len(used_bref)
    audit.append(rec)
    print('GAME',idx,nbaid,rec['teams'],'ESPN',rec['espn_player_count'],'PBP',rec.get('pbpstats_records'),'BR',rec.get('bref_records'),'matched',rec['matched_pbpstats'],rec['matched_bref'],'errors',rec['errors'],flush=True)
save(OUT/'player_crosswalk.json',players)
with (OUT/'player_crosswalk.csv').open('w',newline='',encoding='utf-8') as f:
    cols=[k for k in players[0] if k!='source_quality']
    wr=csv.DictWriter(f,fieldnames=cols);wr.writeheader()
    for p in players:wr.writerow({k:p.get(k) for k in cols})
summary={'date_et':DATE,'games':len(audit),'espn_players':len(players),
 'pbpstats_matched':sum(a['matched_pbpstats'] for a in audit),
 'bref_matched':sum(a['matched_bref'] for a in audit),
 'explicit_second_chance_values':sum(p['second_chance_points'] is not None for p in players),
 'bref_ratings_pairs':sum(p['bref_off_rtg'] is not None and p['bref_def_rtg'] is not None for p in players),
 'games_audit':audit,
 'quality':'AUDIT_ONLY_DO_NOT_FEED_UNVERIFIED_TO_QPIX',
 'unverified':['fast_break_points','points_in_paint','PBPStats_second_chance_zero_omission_semantics']}
save(OUT/'audit.json',summary)
print('FINAL_QPIX_MULTISOURCE_AUDIT',json.dumps({k:v for k,v in summary.items() if k!='games_audit'}),flush=True)
