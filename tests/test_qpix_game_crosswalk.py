import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from qpix_game_crosswalk import resolve

class CrosswalkTests(unittest.TestCase):
    fixtures=[
        {"espn_event_id":"401909922","away_alias":"CHI","home_alias":"NYK"},
        {"espn_event_id":"401909923","away_alias":"BOS","home_alias":"PHI"},
    ]
    def test_verified_crosswalk_two_games(self):
        def fake(url,timeout=12):
            if "V2_1" in url:raise OSError("CDN blocked")
            return {"leagueSchedule":{"gameDates":[{"gameDate":"2026-11-04T00:00:00",
                "games":[{"gameId":"0022600159","awayTeam":{"teamTricode":"CHI"},"homeTeam":{"teamTricode":"NYK"}},
                         {"gameId":"0022600160","awayTeam":{"teamTricode":"BOS"},"homeTeam":{"teamTricode":"PHI"}}]}]}}
        found,audit=resolve("2026-11-04",self.fixtures,fake)
        self.assertEqual(len(found),2)
        self.assertEqual(found["401909922"],"0022600159")
    def test_fallback_to_second_schedule(self):
        def fake(url,timeout=12):
            if url.endswith("scheduleLeagueV2.json"):raise OSError("CDN 403")
            return {"leagueSchedule":{"gameDates":[{"gameDate":"11/04/2026","games":[
                {"gameId":"0022600159","awayTeam":{"teamTricode":"CHI"},"homeTeam":{"teamTricode":"NYK"}}]}]}}
        found,audit=resolve("2026-11-04",self.fixtures,fake)
        self.assertEqual(len(found),1)
        self.assertEqual(audit["resolved"],1)
        self.assertEqual(audit["attempts"][0]["status"],"failed")
    def test_mismatched_fixture_never_assigns_id(self):
        def fake(url,timeout=12):
            return {"leagueSchedule":{"gameDates":[{"gameDate":"2026-11-04","games":[
                {"gameId":"0022600159","awayTeam":{"teamTricode":"ORL"},"homeTeam":{"teamTricode":"NYK"}}]}]}}
        found,audit=resolve("2026-11-04",self.fixtures,fake)
        self.assertEqual(found,{})
        self.assertEqual(audit["resolved"],0)
    def test_duplicate_game_ids_abort(self):
        def fake(url,timeout=12):
            return {"leagueSchedule":{"gameDates":[{"gameDate":"2026-11-04","games":[
                {"gameId":"0022600159","awayTeam":{"teamTricode":"CHI"},"homeTeam":{"teamTricode":"NYK"}},
                {"gameId":"0022600159","awayTeam":{"teamTricode":"BOS"},"homeTeam":{"teamTricode":"PHI"}}]}]}}
        with self.assertRaisesRegex(ValueError,"Duplicate NBA IDs"):
            resolve("2026-11-04",self.fixtures,fake)

if __name__=="__main__":unittest.main()
