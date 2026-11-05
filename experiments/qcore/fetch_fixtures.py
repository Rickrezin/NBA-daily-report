"""Explicit, optional network capture; replay never requires network."""
import hashlib
import argparse
import json
from pathlib import Path
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent / 'fixtures'

def capture(url, name):
    path = ROOT / name
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    obj = json.loads(raw)
    path.write_bytes(raw)
    path.with_suffix('.provenance.json').write_text(json.dumps({
        'url': url, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)
    }, indent=2) + '\n', encoding='utf-8')
    return obj

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', action='append', default=[], help='Capture a specific ESPN event instead of the validation slate')
    args = parser.parse_args()
    if args.event:
        for gid in args.event:
            if not gid.isdigit():
                parser.error('Event ID must be numeric')
            capture('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+gid, 'espn-'+gid+'.json')
        raise SystemExit(0)
    archive = json.loads((ROOT.parents[2] / 'data/daily/2026-11-02.json').read_text(encoding='utf-8'))
    board = capture('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261104&limit=100', 'espn-board-20261104.json')
    ids = [g['game_id'] for g in archive['games']]
    for event in board['events']:
        aliases = {c['team']['abbreviation'] for c in event['competitions'][0]['competitors']}
        if aliases == {'MIL', 'BOS'}:
            ids.append(event['id'])
    for gid in ids:
        capture('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=' + gid, 'espn-' + gid + '.json')
        print(gid, flush=True)
