import json,sys,pathlib,hashlib,math
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root/'experiments/qcore'))
from model import predict,VERSION
from sources import parse_espn
source=json.loads((root/'data/historical/qpix_input/2026-11-08.json').read_text())
raws={}
by_id={}
for game in source['games']:
    eid=game['espn_event_id']
    file=root/'source-raw/espn'/f'{eid}.json'
    payload=json.loads(file.read_text())
    raw=parse_espn(payload)
    key=set([game['away_alias'],game['home_alias']]);assert set(raw['teams'])==key,(eid,key,raw['teams'])
    raw_g={p['player_id']:p for p in raw['players']}
    raws[eid]=raw
    by_id[eid]=raw_g
players=[];missing=[];outliers=[]
for p in source['players']:
    eid=p['game_id'].removeprefix('ESPN_')
    q=by_id[eid].get(str(p['player_id']))
    if q is None:raise RuntimeError(f'Missing ESPN {eid} {p["player_id"]} {p["name"]}')
    if p['team']!=q['team'] or p['points']!=q['basic']['pts'] or p['fgm']!=q['basic']['fg'] or p['fga']!=q['basic']['fga']:
        raise RuntimeError(f'Basic stat mismatch ESPN {p["name"]}: {p} vs {q}')
    team=raws[eid]['teams'][p['team']]
    opp=raws[eid]['teams'][next(t for t in raws[eid]['teams'] if t!=p['team'])]
    try: pred=predict(q['basic'],team,opp)
    except Exception as exc:
        raise RuntimeError(f'Qcore model predict failed {eid} {p["name"]}: {exc}')
    if pred['q_offr'] is None or pred['q_defr'] is None:missing.append({'player_id':p['player_id'],'name':p['name'],'team':p['team'],'flags':pred['flags']})
    if math.isfinite(q['basic']['mp']) and abs(q['basic']['mp']-p['minutes'])>1.1:outliers.append({'name':p['name'],'raw_mp':q['basic']['mp'],'archived_mp':p['minutes']})
    players.append({**p,'personal_fouls':int(q['basic']['pf']),'offensive_rating':round(pred['q_offr'],6) if pred['q_offr'] is not None else None,'defensive_rating':round(pred['q_defr'],6) if pred['q_defr'] is not None else None,'qcore_q_offr':round(pred['q_offr'],2) if pred['q_offr'] is not None else None,'qcore_q_defr':round(pred['q_defr'],2) if pred['q_defr'] is not None else None,'rating_source':'EXPERIMENTAL_QCORE_NOV05_PROTOTYPE_NOT_BBREF_OR_NBA','rating_flags':pred['flags'],'rating_features':pred['features'],'points_in_paint':None,'fast_break_points':None,'second_chance_points':None,'rolling_20_fta':None})
source_games=[]
for g in source['games']:
    source_games.append({k:g[k] for k in ('game_id','home_alias','away_alias','home_points','away_points')})
for g in source_games:
    if sum(x['points'] for x in players if x['game_id']==g['game_id'] and x['team']==g['away_alias']) != g['away_points']:raise RuntimeError('away points mismatch')
    if sum(x['points'] for x in players if x['game_id']==g['game_id'] and x['team']==g['home_alias']) != g['home_points']:raise RuntimeError('home points mismatch')
    for team in (g['home_alias'],g['away_alias']):
        s=[x for x in players if x['game_id']==g['game_id'] and x['team']==team]
        plus=sum(x['plus_minus'] for x in s)
        actual=(g['home_points']-g['away_points'])*(5 if team==g['home_alias'] else -5)
        if abs(plus-actual)>10:outliers.append({'team':team,'game':g['game_id'],'plus_minus_sum':plus,'expected_team_differential_times_5':actual})
        minutes=sum(x['minutes'] for x in s)
        if abs(minutes-240)>27:outliers.append({'team':team,'minutes':minutes,'expected':240})
out={'date_et':'2026-11-08','games':source_games,'players':players}
(root/'data').mkdir(exist_ok=True)
(root/'data/nba_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
audit={'date_et':'2026-11-08','source':'ESPN prior-day GitHub Actions pre-scoring canonical archive; raw ESPN summary used to retrieve personal fouls and team turnovers', 'canonical_input_sha256':source['input_sha256'],'qcore_version':VERSION,'qcore_branch':'dev/qcore-independent-ratings-20261105','verified_provider_C3_players':0,'qcore_estimate_available':sum(x['offensive_rating'] is not None for x in players),'qcore_missing':missing,'source_missing_C6':len(players),'source_missing_fastbreak_C11':len(players),'outliers':outliers,'raw_espn_minutes_precision':'whole_minutes','games':len(source_games),'players':len(players),'team_raw_audits':{eid:raws[eid]['audit'] for eid in raws}}
(root/'shadow').mkdir(exist_ok=True)
(root/'shadow/preflight-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
print(json.dumps({'games':len(source_games),'players':len(players),'qcore_available':audit['qcore_estimate_available'],'qcore_missing':len(missing),'outliers':outliers},indent=2))
