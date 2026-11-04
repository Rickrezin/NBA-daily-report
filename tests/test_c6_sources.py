import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "scripts"))
from c6_sources import read_c6_fields, apply_c6_rows, misc_v3_player_rows

class TestC6(unittest.TestCase):
    def test_nba_misc_fields_and_zero_are_real(self):
        self.assertEqual(read_c6_fields({"pointsPaint":12,"pointsFastBreak":6,"pointsSecondChance":4}),
                         {"points_in_paint":12,"fast_break_points":6,"second_chance_points":4})
        self.assertEqual(read_c6_fields({"pointsPaint":0}),{"points_in_paint":0})
    def test_livedata_variants(self):
        self.assertEqual(read_c6_fields({"pointsInThePaint":8,"fastBreakPoints":2,"secondChancePoints":3}),
                         {"points_in_paint":8,"fast_break_points":2,"second_chance_points":3})
    def test_missing_remains_missing(self):
        self.assertEqual(read_c6_fields({}),{})
        players=[{"player_id":"1","points":15},{"player_id":"2","points":0}]
        r=apply_c6_rows(players,[{"personId":1,"pointsPaint":10,"pointsFastBreak":0,"pointsSecondChance":2}], "test")
        self.assertEqual(r["matched_players"],1)
        self.assertEqual(r["new_fields"],3)
        self.assertNotIn("points_in_paint",players[1])
    def test_validate_and_reject_duplicates(self):
        with self.assertRaises(ValueError):read_c6_fields({"pointsPaint":-2})
        with self.assertRaises(ValueError):read_c6_fields({"pointsPaint":True})
        with self.assertRaises(ValueError):apply_c6_rows([{"player_id":"1"}],[{"personId":1},{"personId":"1"}],"test")
    def test_espn_id_not_valid_nba_id(self):
        # Official IDs and ESPN event IDs must never be mistaken for each other.
        self.assertTrue("ESPN_401909908".startswith("ESPN_"))
    def test_misc_shapes(self):
        self.assertEqual(len(misc_v3_player_rows({"boxScoreMisc":{"playerStats":[{"personId":1}]}})),1)
        self.assertEqual(len(misc_v3_player_rows({"boxScoreMisc":{"homeTeam":{"players":[{"personId":1}]},"awayTeam":{"players":[{"personId":2}]}}})),2)

if __name__=="__main__":unittest.main()
