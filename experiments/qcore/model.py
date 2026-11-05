"""QCore experimental Oliver-style box-score ratings. No scoring-engine imports.

Pure inference accepts ONLY basic counting stats and minutes. Reference labels,
BPM, QPIX, QPIX-R and NBA on-court ratings are never model features.
"""
import math

VERSION = 'qcore-oliver-box-v0.1'
FIELDS = ('mp', 'pts', 'fg', 'fga', 'fg3', 'fg3a', 'ft', 'fta',
          'orb', 'drb', 'ast', 'stl', 'blk', 'tov', 'pf')

def basic(row):
    out = {k: float(row[k]) for k in FIELDS}
    if any(not math.isfinite(v) or v < 0 for v in out.values()):
        raise ValueError('Non-finite or negative basic statistic')
    for made, attempted in [('fg', 'fga'), ('fg3', 'fg3a'), ('ft', 'fta')]:
        if out[made] > out[attempted]:
            raise ValueError('Makes exceed attempts')
    if out['fg3'] > out['fg'] or out['fg3a'] > out['fga']:
        raise ValueError('Three-point totals exceed field goals')
    if out['pts'] != 2 * out['fg'] + out['fg3'] + out['ft']:
        raise ValueError('Points do not reconcile')
    return out

def ratio(n, d):
    return n / d if d else 0.0

def ft_scoring(s):
    return (1 - (1 - ratio(s['ft'], s['fta'])) ** 2) * .4 * s['fta']

def possessions(t, o):
    def side(a, b):
        return a['fga'] + .4*a['fta'] - 1.07*ratio(a['orb'], a['orb']+b['drb'])*(a['fga']-a['fg']) + a['tov']
    return .5 * (side(t, o) + side(o, t))

def predict(player, team, opponent):
    p, t, o = map(basic, (player, team, opponent))
    if p['mp'] <= 0:
        return {'q_offr': None, 'q_defr': None, 'flags': ['did_not_play'], 'features': {}}
    if t['mp'] <= 0 or o['mp'] <= 0 or p['mp'] > t['mp']/5 + 1:
        raise ValueError('Invalid game minutes')
    for k in FIELDS[1:]:
        if p[k] > t[k]:
            raise ValueError('Player exceeds team total: ' + k)
    poss = possessions(t, o)
    if poss <= 0 or not t['fg'] or not o['fg']:
        raise ValueError('Insufficient team/opponent context')
    flags = ['short_minutes'] if p['mp'] <= 8 else []
    share = p['mp'] / (t['mp']/5)
    qden = t['fg']*share - p['fg']
    qast = share*1.14*ratio(t['ast']-p['ast'], t['fg']) + ratio(t['ast']*share-p['ast'], qden)*(1-share)
    if abs(qden) < 1e-8:
        flags.append('qast_zero_denominator')
    if not 0 <= qast <= 1:
        flags.append('qast_outside_unit_interval')
    ts = ratio(p['pts'], 2*(p['fga']+.44*p['fta']))
    efg = ratio(p['fg']+.5*p['fg3'], p['fga'])
    torb = ratio(t['orb'], t['orb']+o['drb'])
    tsp = t['fg'] + ft_scoring(t)
    play = ratio(tsp, t['fga']+.4*t['fta']+t['tov'])
    orb_weight = ratio((1-torb)*play, (1-torb)*play+torb*(1-play))
    retain = 1-ratio(t['orb'], tsp)*orb_weight*play
    fg_credit = 1-.5*ratio(p['pts']-p['ft'], 2*p['fga'])*qast
    ast_part = .5*ratio(t['pts']-t['ft']-p['pts']+p['ft'], 2*(t['fga']-p['fga']))*p['ast']
    orb_part = p['orb']*orb_weight*play
    sc = (p['fg']*fg_credit+ast_part+ft_scoring(p))*retain+orb_part
    used = sc+(p['fga']-p['fg'])*(1-1.07*torb)+.4*p['fta']*(1-ratio(p['ft'], p['fta']))**2+p['tov']
    produced = (2*(p['fg']+.5*p['fg3'])*fg_credit +
                2*ratio(t['fg']-p['fg']+.5*(t['fg3']-p['fg3']), t['fg']-p['fg'])*ast_part+p['ft'])*retain+orb_part*ratio(t['pts'], tsp)
    if used <= 1e-9:
        off = None
        flags.append('no_positive_individual_possessions')
    else:
        off = 100*produced/used
    dor = ratio(o['orb'], o['orb']+t['drb'])
    dfg = ratio(o['fg'], o['fga'])
    fm = ratio(dfg*(1-dor), dfg*(1-dor)+(1-dfg)*dor)
    stops1 = p['stl']+p['blk']*fm*(1-1.07*dor)+p['drb']*(1-fm)
    stops2 = ((o['fga']-o['fg']-t['blk'])/t['mp']*fm*(1-1.07*dor)+(o['tov']-t['stl'])/t['mp'])*p['mp'] + ratio(p['pf'], t['pf'])*.4*o['fta']*(1-ratio(o['ft'], o['fta']))**2
    stop_pct = (stops1+stops2)*o['mp']/(poss*p['mp'])
    team_def = 100*o['pts']/poss
    defense = team_def+.2*(100*ratio(o['pts'], o['fg']+ft_scoring(o))*(1-stop_pct)-team_def)
    features = dict(ts=ts, efg=efg, usage_pct=100*ratio(p['fga']+.44*p['fta']+p['tov'], share*(t['fga']+.44*t['fta']+t['tov'])),
                    ast_pct=100*ratio(p['ast'], qden), orb_pct=100*ratio(p['orb'], share*(t['orb']+o['drb'])),
                    drb_pct=100*ratio(p['drb'], share*(t['drb']+o['orb'])),
                    stl_pct=100*ratio(p['stl'], share*poss), blk_pct=100*ratio(p['blk'], share*(o['fga']-o['fg3a'])),
                    qast=qast, scoring_possessions=sc, individual_possessions=used, points_produced=produced,
                    team_possessions=poss, team_defr=team_def, stops=stops1+stops2, stop_pct=stop_pct)
    if any(not math.isfinite(v) for v in features.values()) or not math.isfinite(defense) or (off is not None and not math.isfinite(off)):
        raise ValueError('Non-finite model result')
    return {'q_offr': off, 'q_defr': defense, 'features': features, 'flags': flags}
