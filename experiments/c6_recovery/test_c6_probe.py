import unittest
from c6_probe import game_map, player_data, nba_field

class TestC6(unittest.TestCase):
    def test_game_ids_from_html(self):
        h='<a href="/game/chi-vs-nyk-0022600177">x</a><a href="https://www.nba.com/game/atl-vs-was-0022600174/box-score">y</a>'
        self.assertEqual(game_map(h),{("CHI","NYK"):"0022600177",("ATL","WAS"):"0022600174"})
    def test_live_player_fields_and_team_reconciliation(self):
        t=lambda ab,id,n:{"teamTricode":ab,"players":[{"personId":id,"statistics":{"pointsInThePaint":n,"pointsFastBreak":2,"pointsSecondChance":1}}],
           "statistics":{"pointsInThePaint":n,"pointsFastBreak":2,"pointsSecondChance":1}}
        p={"game":{"awayTeam":t("CHI",1,4),"homeTeam":t("NYK",2,6)}}
        self.assertEqual(player_data(p,"live")[1]["players"][0]["points_in_paint"],6)
        p["game"]["homeTeam"]["statistics"]["pointsInThePaint"]=7
        with self.assertRaises(ValueError):player_data(p,"live")
    def test_misc_schema_and_missing(self):
        self.assertEqual(nba_field({"pointsPaint":4},("pointsInThePaint","pointsPaint")),4)
        self.assertIsNone(nba_field({},("pointsSecondChance",)))
    def test_reject_invalid_stats(self):
        with self.assertRaises(ValueError):nba_field({"pointsFastBreak":-1},("pointsFastBreak",))
if __name__=="__main__":unittest.main()
