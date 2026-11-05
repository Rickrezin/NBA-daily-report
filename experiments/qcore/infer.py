"""Infer experimental ratings from a saved ESPN summary: python infer.py game.json.

Writes JSON to stdout only; no labels, fitting, QPIX or production writes.
"""
import argparse
import json
from pathlib import Path
from model import VERSION, predict
from sources import parse_espn

def infer(payload):
    game = parse_espn(payload)
    rows = []
    for p in game['players']:
        opponent = next(t for t in game['teams'] if t != p['team'])
        result = predict(p['basic'], game['teams'][p['team']], game['teams'][opponent])
        if p['basic']['mp'] == 0:
            result['flags'] = ['active_player_minutes_rounded_to_zero']
        rows.append({**p, **result})
    return {'model':VERSION, 'experimental':True, 'production_authorized':False,
            'game_id':game['game_id'], 'players':rows, 'source_audit':game['audit']}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary',type=Path)
    args = parser.parse_args()
    print(json.dumps(infer(json.loads(args.summary.read_text(encoding='utf-8'))), indent=2, allow_nan=False))
