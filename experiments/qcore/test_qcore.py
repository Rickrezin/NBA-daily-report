import copy
import json
from pathlib import Path
import unittest
from evaluate import build, fit, split_games, metrics
from infer import infer
from model import predict
from sources import parse_espn, read_export, export_basic

FIX = Path(__file__).resolve().parent/'fixtures'

class QCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((FIX/'espn-401909924.json').read_text(encoding='utf-8'))
        cls.result = build()

    def test_all_archived_identities_and_counts_match(self):
        r = self.result['reconciliation']
        self.assertEqual(len(r),334)
        self.assertTrue(all(set(x['differences']) <= {'mp'} for x in r))

    def test_fixture_identity_join_dnp_and_team_totals(self):
        m = self.result['manifest']
        self.assertEqual(len(m['fixture_matches']),12)
        self.assertEqual(len(m['excluded_dnp_bbref_ids']),3)
        self.assertEqual(len({x['bbref_id'] for x in m['fixture_matches']}),12)
        game = parse_espn(self.payload)
        total = read_export(FIX/'mil-20261104-basic.xls')[-1]
        self.assertEqual(export_basic(total),game['teams']['MIL'])
        self.assertEqual(game['teams']['MIL']['tov'],15)
        self.assertEqual(sum(p['basic']['tov'] for p in game['players'] if p['team']=='MIL'),14)

    def test_external_reference_agreement_and_zero_usage(self):
        rows = [r for r in self.result['rows'] if r['cohort']=='espn_nov4']
        for k in ('q_offr','q_defr'):
            self.assertLess(metrics(rows,k)['max_abs'],1)
        sims = next(r for r in rows if r['name']=='Jericho Sims')
        self.assertIsNone(sims['prediction']['q_offr'])
        self.assertEqual(sims['reference']['q_offr'],0)
        self.assertIsNotNone(sims['prediction']['q_defr'])

    def test_all_participants_retained_even_rounded_zero(self):
        rows = [r for r in self.result['rows'] if r['cohort']=='espn_nov2']
        self.assertEqual(len(rows),334)
        zero = [r for r in rows if r['minutes']==0]
        self.assertEqual(len(zero),2)
        self.assertTrue(all(r['prediction']['q_defr'] is None for r in zero))
        self.assertTrue(all('active_player_minutes_rounded_to_zero' in r['prediction']['flags'] for r in zero))

    def test_no_game_leakage_and_stable_partition(self):
        split = self.result['manifest']['split']
        self.assertEqual(len(split['train']),10)
        self.assertEqual(len(split['test']),5)
        self.assertFalse(set(split['train']) & set(split['test']))
        self.assertEqual(split,split_games(reversed(split['train']+split['test'])))

    def test_test_labels_cannot_change_fit(self):
        rows = [r for r in self.result['rows'] if r['cohort']=='espn_nov2']
        before = {k:fit(rows,k) for k in ('q_offr','q_defr')}
        rows = copy.deepcopy(rows)
        for r in rows:
            if r['split'] != 'train':
                r['reference'] = {'q_offr':-99999,'q_defr':99999}
        self.assertEqual(before,{k:fit(rows,k) for k in before})

    def test_no_qpix_or_reference_feature_leakage(self):
        g = parse_espn(self.payload)
        p = g['players'][0]
        t, o = g['teams']['MIL'],g['teams']['BOS']
        initial = predict(p['basic'],t,o)
        poisoned = dict(p['basic'], offensive_rating=9999, defensive_rating=-9999,
                        qpixR=1000000, bpm=1000, score=42, plus_minus=99999)
        self.assertEqual(initial,predict(poisoned,t,o))

    def test_missing_stat_is_not_zero(self):
        payload = copy.deepcopy(self.payload)
        group = payload['boxscore']['players'][0]['statistics'][0]
        group['labels'][group['labels'].index('PF')] = 'UNKNOWN'
        with self.assertRaises(KeyError):
            parse_espn(payload)

    def test_invalid_counts_rejected(self):
        g = parse_espn(self.payload)
        p = dict(g['players'][0]['basic'], fg=999)
        with self.assertRaises(ValueError):
            predict(p,g['teams']['MIL'],g['teams']['BOS'])

    def test_duplicate_identity_rejected(self):
        payload = copy.deepcopy(self.payload)
        group = payload['boxscore']['players'][0]['statistics'][0]
        group['athletes'].append(copy.deepcopy(group['athletes'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            parse_espn(payload)

    def test_nonfinal_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['header']['competitions'][0]['status']['type']['completed'] = False
        with self.assertRaises(ValueError):
            parse_espn(payload)

    def test_overtime_duration(self):
        payload = json.loads((FIX/'espn-401909914.json').read_text(encoding='utf-8'))
        game = parse_espn(payload)
        self.assertEqual({t['mp'] for t in game['teams'].values()},{265})

    def test_replay_deterministic(self):
        self.assertEqual(self.result,build())
        self.assertEqual(infer(self.payload),infer(self.payload))

    def test_inference_does_not_need_labels(self):
        result = infer(self.payload)
        self.assertFalse(result['production_authorized'])
        self.assertEqual(len(result['players']),len(parse_espn(self.payload)['players']))
        self.assertTrue(all('reference' not in p for p in result['players']))

if __name__ == '__main__':
    unittest.main()
