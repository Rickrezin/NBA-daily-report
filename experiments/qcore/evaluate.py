"""Offline reproducible evaluation; writes exclusively under experiments/qcore/results."""
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from model import VERSION, FIELDS, predict
from sources import read_export, export_basic, archive_basic, parse_espn, name_key

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIX = HERE / 'fixtures'

def digest(path):
    raw = path.read_bytes()
    # Existing archive has platform-dependent checkout endings. Record its Git
    # canonical LF bytes; immutable raw source captures are always byte-exact.
    if path == ROOT/'data/daily/2026-11-02.json':
        raw = raw.replace(b'\r\n', b'\n')
    return hashlib.sha256(raw).hexdigest()

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def split_games(ids):
    ordered = sorted(set(ids), key=lambda g: hashlib.sha256(('qcore-v1:'+g).encode()).hexdigest())
    n = max(1, len(ordered)//3)
    return {'train': sorted(ordered[n:]), 'test': sorted(ordered[:n])}

def fit(rows, target):
    pairs = [(r['prediction'][target], r['reference'][target]) for r in rows
             if r['split'] == 'train' and r['prediction'][target] is not None]
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    var = sum((x-mx)**2 for x in xs)
    slope = sum((x-mx)*(y-my) for x,y in pairs)/var if var else 0
    return {'intercept':my-slope*mx, 'slope':slope, 'n':len(pairs)}

def metrics(rows, target, calibrated=False):
    field = 'calibrated' if calibrated else 'prediction'
    pairs = [(r[field][target], r['reference'][target], r['minutes']) for r in rows if r[field][target] is not None]
    if not pairs:
        return {'rows':len(rows), 'scored':0}
    errors = [p-y for p,y,_ in pairs]
    return {'rows':len(rows), 'scored':len(pairs), 'unscorable':len(rows)-len(pairs),
            'mae':mean(abs(e) for e in errors), 'rmse':math.sqrt(mean(e*e for e in errors)),
            'bias':mean(errors), 'max_abs':max(abs(e) for e in errors),
            'within_1':sum(abs(e)<=1 for e in errors),
            'minute_weighted_mae':sum(abs(p-y)*m for p,y,m in pairs)/sum(m for _,_,m in pairs)}

def score_row(p, teams, reference, split, cohort):
    opp = next(t for t in teams if t != p['team'])
    pred = predict(p['basic'], teams[p['team']], teams[opp])
    if p['basic']['mp'] == 0 and p.get('minute_precision') == 'whole_minutes':
        pred['flags'] = ['active_player_minutes_rounded_to_zero']
    return {'game_id':p['game_id'], 'player_id':p['player_id'], 'name':p['name'], 'team':p['team'],
            'minutes':p['basic']['mp'], 'cohort':cohort, 'split':split,
            'prediction':pred, 'reference':reference}

def build():
    archive_path = ROOT / 'data/daily/2026-11-02.json'
    archive = load(archive_path)
    splits = split_games([g['game_id'] for g in archive['games']])
    sources = [archive_path, FIX/'mil-20261104-basic.xls', FIX/'mil-20261104-advanced.xls', FIX/'espn-board-20261104.json']
    rows, reconciliation, collection = [], [], []
    for game in sorted(archive['games'], key=lambda g:g['game_id']):
        gid = game['game_id']
        path = FIX/('espn-'+gid+'.json')
        sources.append(path)
        espn = parse_espn(load(path))
        if set(espn['teams']) != {game['home_alias'], game['away_alias']}:
            raise ValueError('Archive/ESPN matchup mismatch')
        if espn['teams'][game['home_alias']]['pts'] != game['home_points'] or espn['teams'][game['away_alias']]['pts'] != game['away_points']:
            raise ValueError('Archive/ESPN score mismatch')
        refs = {str(p['player_id']):p for p in archive['players'] if p['game_id']==gid}
        if set(refs) != {p['player_id'] for p in espn['players']}:
            raise ValueError('Archive/ESPN participant mismatch: '+gid)
        exact_teams = {t:{k:sum(archive_basic(p)[k] for p in refs.values() if p['team']==t) for k in FIELDS} for t in espn['teams']}
        for t in exact_teams:
            exact_teams[t]['tov'] = espn['teams'][t]['tov']
            exact_teams[t]['mp'] = espn['teams'][t]['mp']
        split = 'test' if gid in splits['test'] else 'train'
        collection.append({'game_id':gid, 'audit':espn['audit']})
        for p in espn['players']:
            ref = refs[p['player_id']]
            if p['team'] != ref['team']:
                raise ValueError('Player/team mismatch')
            exact = archive_basic(ref)
            differences = {k:{'espn':p['basic'][k], 'archive':exact[k]} for k in FIELDS if abs(p['basic'][k]-exact[k])>1e-6}
            reconciliation.append({'game_id':gid,'player_id':p['player_id'],'differences':differences})
            target = {'q_offr':ref['offensive_rating'],'q_defr':ref['defensive_rating']}
            rows.append(score_row(p, espn['teams'], target, split, 'espn_nov2'))
            rows.append(score_row(dict(p,basic=exact), exact_teams, target, split, 'archive_exact_minutes'))
    basic_rows = read_export(FIX/'mil-20261104-basic.xls')
    advanced_rows = read_export(FIX/'mil-20261104-advanced.xls')
    b = {p['bbref_id']:p for p in basic_rows if 'bbref_id' in p}
    a = {p['bbref_id']:p for p in advanced_rows if 'bbref_id' in p}
    if set(a) != set(b):
        raise ValueError('Basic/advanced BBRef identity mismatch')
    path = FIX/'espn-401909924.json'
    sources.append(path)
    espn = parse_espn(load(path))
    if set(espn['teams']) != {'MIL','BOS'}:
        raise ValueError('Nov 4 fixture matchup mismatch')
    mil = {name_key(p['name']):p for p in espn['players'] if p['team']=='MIL'}
    active = {i:r for i,r in b.items() if not r.get('reason')}
    if len(mil) != len(active) or len(mil) != len([p for p in espn['players'] if p['team']=='MIL']):
        raise ValueError('Ambiguous or incomplete Nov 4 identity match')
    fixture_matches = []
    for pid, row in active.items():
        p = mil[name_key(row['player'])]
        exact = export_basic(row)
        if row['mp'] != a[pid]['mp'] or a[pid].get('reason'):
            raise ValueError('BBRef basic/advanced minute mismatch')
        mismatches = {k:[p['basic'][k],exact[k]] for k in FIELDS if k!='mp' and p['basic'][k]!=exact[k]}
        if mismatches:
            raise ValueError('Nov 4 box-line mismatch: '+str(mismatches))
        fixture_matches.append({'bbref_id':pid,'espn_id':p['player_id'],'name':p['name'],
                                'bbref_minutes':exact['mp'],'espn_minutes':p['basic']['mp']})
        target = {'q_offr':float(a[pid]['off_rtg']), 'q_defr':float(a[pid]['def_rtg'])}
        rows.append(score_row(p, espn['teams'], target, 'external_test', 'espn_nov4'))
        rows.append(score_row(dict(p,basic=exact), espn['teams'], target, 'external_test', 'nov4_exact_player_minutes'))
    team_row = next(r for r in basic_rows if r.get('player')=='Team Totals')
    if export_basic(team_row) != espn['teams']['MIL']:
        raise ValueError('Milwaukee BBRef/ESPN team totals differ')
    coefficients = {k:fit([r for r in rows if r['cohort']=='espn_nov2'], k) for k in ('q_offr','q_defr')}
    for r in rows:
        r['calibrated'] = {k:None if r['prediction'][k] is None else coefficients[k]['intercept']+coefficients[k]['slope']*r['prediction'][k] for k in coefficients}
        r['residual'] = {k:None if r['prediction'][k] is None else r['prediction'][k]-r['reference'][k] for k in coefficients}
    summaries = {}
    for cohort in sorted({r['cohort'] for r in rows}):
        for split in ['overall']+sorted({r['split'] for r in rows if r['cohort']==cohort}):
            subset = [r for r in rows if r['cohort']==cohort and (split=='overall' or r['split']==split)]
            for bucket, selected in [('all',subset),('le8',[r for r in subset if r['minutes']<=8]),('gt8',[r for r in subset if r['minutes']>8])]:
                summaries['/'.join((cohort,split,bucket))] = {k:{'raw':metrics(selected,k), 'calibrated':metrics(selected,k,True)} for k in coefficients}
    outliers = {k:sorted([r for r in rows if r['cohort'].startswith('espn') and r['split']!='train' and r['residual'][k] is not None], key=lambda r:abs(r['residual'][k]), reverse=True)[:10] for k in coefficients}
    files = sources+sorted(HERE.glob('*.py'))+sorted(FIX.glob('*.provenance.json'))
    for sidecar in FIX.glob('*.provenance.json'):
        raw = sidecar.with_name(sidecar.name.replace('.provenance.json','.json'))
        if digest(raw) != load(sidecar)['sha256']:
            raise ValueError('Captured source digest mismatch: '+raw.name)
    manifest = {'model_version':VERSION, 'base_commit':'150492daaf846b131f915388bc3ea2f8617023a3',
                'reviewed_source_branch_head':'7b1d7a2', 'split_policy':'sha256(qcore-v1:game_id), first floor(n/3) test; no player split',
                'hash_policy':'Raw captures and code byte-exact SHA-256; existing data/daily archive uses canonical LF bytes for cross-platform Git replay.',
                'split':splits, 'coefficients_train_only':coefficients,
                'files':{str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in files},
                'fixture_matches':fixture_matches,
                'excluded_dnp_bbref_ids':[pid for pid in b if pid not in active],
                'bbref_fixture_provenance':{'basic_original_name':'sportsref_download.xls',
                    'advanced_original_name':'sportsref_download (1).xls',
                    'origin':'User supplied files from Downloads; referenced chat Daily QPIX Independent Run',
                    'matchup':'MIL at BOS', 'date_et':'2026-11-04',
                    'source_url':'https://www.basketball-reference.com/boxscores/202611040BOS.html',
                    'opponent_context':'ESPN basic team/player counts; no Boston BBRef export provided'},
                'production_authorized':False,
                'sources':['https://www.basketball-reference.com/about/ratings.html','https://www.basketball-reference.com/about/glossary.html', 'https://www.nba.com/stats/help/glossary']}
    return {'manifest':manifest,'metrics':summaries,'rows':rows,'outliers':outliers,
            'reconciliation':reconciliation,'collection_audit':collection}

def main():
    result = build()
    out = HERE/'results'
    out.mkdir(exist_ok=True)
    for name, value in result.items():
        (out/(name+'.json')).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)+'\n',encoding='utf-8')
    report = ['# QCore prototype validation', '', 'Experimental only; not authorized for production C3/C4.', '',
              '10 training games / 5 held-out games on November 2; Milwaukee November 4 is an external fixture. Each game stays in one split. No hyperparameter search; affine calibration uses only training labels. This is exploratory validation on two dates, not a prospective season test.', '',
              '| Cohort / split | Metric | Rows | Calculable | MAE | RMSE | Bias | Maximum absolute error |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    keys = ['espn_nov2/overall/all','espn_nov2/train/all','espn_nov2/test/all','espn_nov2/test/le8',
            'espn_nov2/test/gt8','espn_nov4/external_test/all','archive_exact_minutes/overall/all',
            'nov4_exact_player_minutes/external_test/all']
    for key in keys:
        for target in ('q_offr','q_defr'):
            m = result['metrics'][key][target]['raw']
            report.append(f"| {key} | {target} | {m['rows']} | {m['scored']} | {m['mae']:.3f} | {m['rmse']:.3f} | {m['bias']:.3f} | {m['max_abs']:.3f} |")
    report += ['', '## Calibration comparison (held-out November 2)', '', '| Metric | Raw MAE | Affine calibrated MAE |','|---|---:|---:|']
    for target in ('q_offr','q_defr'):
        m = result['metrics']['espn_nov2/test/all'][target]
        report.append(f"| {target} | {m['raw']['mae']:.3f} | {m['calibrated']['mae']:.3f} |")
    report += ['', 'The trained affine comparator worsens both held-out MAEs and is not used by inference.', '',
               '## Largest residuals across November 2 (training and test explicitly labeled)', '',
               '| Metric | Player | Game | Split | ESPN minutes | Prediction | BBRef | Residual |','|---|---|---|---|---:|---:|---:|---:|']
    for target in ('q_offr','q_defr'):
        candidates = [r for r in result['rows'] if r['cohort']=='espn_nov2' and r['residual'][target] is not None]
        for r in sorted(candidates,key=lambda r:abs(r['residual'][target]),reverse=True)[:8]:
            report.append(f"| {target} | {r['name']} | {r['game_id']} | {r['split']} | {r['minutes']:g} | {r['prediction'][target]:.3f} | {r['reference'][target]:g} | {r['residual'][target]:+.3f} |")
    report += ['', '## Limits and blockers', '',
               '- All 334 archived identities and basic counting-stat lines reconcile to ESPN. 329 minute values differ because ESPN supplies whole minutes. The exact-minute diagnostic uses BBRef basics and is explicitly not independent ESPN inference.',
               '- Positive appearances rounded to zero remain in results with null ratings. Non-positive estimated individual possessions produce null Q-OffR, including Jericho Sims in the external fixture (BBRef displays 0). These rows are counted in coverage, never silently dropped or assigned a league-average score.',
               '- qAST can exceed its expected probability range in short stints. The published algebra is retained and flagged; no undocumented clipping convention is inferred from test labels. Jaylin Sellers and Jordan Clarkson remain offensive outliers.',
               '- Bronny James has ESPN 1 minute versus archived 1:22. His raw defensive prediction changes from 42.927 to 64.382 with exact minutes; BBRef reports 63. Minute rounding does not explain every residual.',
               '- Need more independent dates, precise automated minutes, validated zero-possession/qAST conventions and explicit approval of the scale before any C3/C4 adoption. C6 coverage is a separate unresolved source task.',
               '', 'Every row, derived feature, reference, flag and residual is in rows.json. metrics.json includes minute buckets, weighted MAE and calibration. manifest.json records source/code SHA-256 digests, training coefficients and exact game splits. The retained source captures enable offline replay.', '']
    (out/'report.md').write_text('\n'.join(report),encoding='utf-8')
    for key in ['espn_nov2/test/all','espn_nov4/external_test/all','archive_exact_minutes/test/all','nov4_exact_player_minutes/external_test/all']:
        print(key, json.dumps(result['metrics'][key]))

if __name__ == '__main__':
    main()
