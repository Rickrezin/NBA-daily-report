"""Strict source adapters. Labels are kept separate from basic model inputs."""
from html.parser import HTMLParser
import re
import unicodedata
from model import FIELDS, basic

ARCHIVE_KEYS = dict(zip(FIELDS, ('minutes','points','fgm','fga','fg3m','fg3a','ftm','fta',
                               'offensive_rebounds','defensive_rebounds','assists','steals','blocks','turnovers','personal_fouls')))

def alias(s):
    return {'NY':'NYK','WSH':'WAS','NO':'NOP','UTAH':'UTA','SA':'SAS','GS':'GSW'}.get(s,s)

def minutes(s):
    if ':' in str(s):
        m, sec = str(s).split(':')
        return float(m)+float(sec)/60
    return float(s)

def name_key(name):
    return re.sub('[^a-z0-9]', '', unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower())

class Export(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.key, self.text = [], None, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'tr':
            self.row = {}
        if tag in ('th', 'td') and self.row is not None:
            self.key, self.text = a.get('data-stat'), []
            if a.get('data-append-csv'):
                self.row['bbref_id'] = a['data-append-csv']

    def handle_data(self, data):
        if self.key:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.key:
            self.row[self.key] = ''.join(self.text).strip()
            self.key = None
        if tag == 'tr' and self.row is not None:
            if self.row.get('bbref_id') or self.row.get('player') == 'Team Totals':
                self.rows.append(self.row)
            self.row = None

def read_export(path):
    parser = Export()
    parser.feed(path.read_text(encoding='utf-8-sig'))
    if not parser.rows:
        raise ValueError('Expected HTML Basketball-Reference export, not binary XLS')
    ids = [r['bbref_id'] for r in parser.rows if 'bbref_id' in r]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate BBRef identity')
    return parser.rows

def export_basic(row):
    return basic({k: minutes(row[k]) if k == 'mp' else float(row[k]) for k in FIELDS})

def archive_basic(row):
    return basic({k: row[v] for k, v in ARCHIVE_KEYS.items()})

def parse_espn(payload):
    comp = payload['header']['competitions'][0]
    if comp['status']['type']['completed'] is not True:
        raise ValueError('Game is not final')
    gid = str(comp['id'])
    competitors = {alias(c['team']['abbreviation']): c for c in comp['competitors']}
    if len(competitors) != 2:
        raise ValueError('Expected two teams')
    periods = {len(c['linescores']) for c in comp['competitors']}
    if len(periods) != 1 or min(periods) < 4:
        raise ValueError('Missing regulation/overtime periods')
    duration = 48+5*(next(iter(periods))-4)
    players, teams, audit = [], {}, []
    seen = set()
    single = {'pts':'PTS','orb':'OREB','drb':'DREB','ast':'AST','stl':'STL','blk':'BLK','tov':'TO','pf':'PF'}
    for block in payload['boxscore']['players']:
        team = alias(block['team']['abbreviation'])
        if team not in competitors:
            raise ValueError('Unknown team')
        for group in block['statistics']:
            labels = group['labels']
            for row in group['athletes']:
                if row.get('didNotPlay'):
                    continue
                if len(labels) != len(row['stats']):
                    raise ValueError('ESPN label/value mismatch')
                s = dict(zip(labels, row['stats']))
                p = {'mp': minutes(s['MIN'])}
                # Positive sub-minute appearances shown as 0 cannot be inferred.
                if p['mp'] < 0:
                    raise ValueError('Negative player minutes')
                for k, label in single.items():
                    p[k] = int(s[label])
                for label, made, attempted in [('FG','fg','fga'),('3PT','fg3','fg3a'),('FT','ft','fta')]:
                    p[made], p[attempted] = map(int, s[label].split('-'))
                if p['orb']+p['drb'] != int(s['REB']):
                    raise ValueError('Rebounds do not reconcile')
                pid = str(row['athlete']['id'])
                if pid in seen:
                    raise ValueError('Duplicate ESPN participant')
                seen.add(pid)
                players.append({'player_id': pid, 'game_id': gid, 'team': team,
                                'name': row['athlete']['displayName'], 'basic': basic(p),
                                'minute_precision': 'seconds' if ':' in s['MIN'] else 'whole_minutes'})
    for block in payload['boxscore']['teams']:
        team = alias(block['team']['abbreviation'])
        rows = [p['basic'] for p in players if p['team'] == team]
        t = {k: sum(p[k] for p in rows) for k in FIELDS}
        t['mp'] = duration*5
        stats = {s['name']: s['displayValue'] for s in block['statistics']}
        if t['pts'] != int(competitors[team]['score']):
            raise ValueError('Team score mismatch')
        for label, made, attempted in [('fieldGoalsMade-fieldGoalsAttempted','fg','fga'),
                                       ('threePointFieldGoalsMade-threePointFieldGoalsAttempted','fg3','fg3a'),
                                       ('freeThrowsMade-freeThrowsAttempted','ft','fta')]:
            if tuple(map(int, stats[label].split('-'))) != (t[made], t[attempted]):
                raise ValueError('Team shooting mismatch')
        # Team-only turnovers affect possessions; do not lose them when summing
        # individual lines. The supplied BBRef basic total confirms this policy.
        audit.append({'team':team, 'player_minutes_sum':sum(p['mp'] for p in rows),
                      'game_minutes':duration, 'player_turnovers':t['tov'],
                      'espn_total_turnovers':int(stats['totalTurnovers']),
                      'espn_team_turnovers':int(stats['teamTurnovers']),
                      'team_totals_policy':'sum_player_counts_except_total_turnovers; duration_from_periods'})
        t['tov'] = int(stats['totalTurnovers'])
        if abs(sum(p['mp'] for p in rows)-duration*5) > len(rows):
            raise ValueError('Incomplete player minutes')
        teams[team] = basic(t)
    if set(teams) != set(competitors) or {p['team'] for p in players} != set(teams):
        raise ValueError('Incomplete team coverage')
    return {'game_id':gid, 'date_utc':comp['date'], 'teams':teams, 'players':players, 'audit':audit}
