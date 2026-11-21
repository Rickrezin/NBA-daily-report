import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qpix_nba_live import NBAClient, BOX_PREFIX, apply_live_boxscore

GAME_ID = "0022600270"
DATE = "2026-11-19"


def fixture():
    game = {"game_id": "ESPN_401910019", "date_et": DATE, "away_alias": "GSW",
            "home_alias": "MEM", "away_points": 10, "home_points": 12}
    players = []
    teams = {}
    for side, alias, name, pid, points in (
        ("away", "GSW", "André O'Neal", 101, 10),
        ("home", "MEM", "John Doe Jr.", 102, 12),
    ):
        player = {
            "game_id": game["game_id"], "player_id": "espn_" + str(pid),
            "team": alias, "name": name, "minutes": 30.0, "points": points,
            "rebounds": 5, "offensive_rebounds": 1, "defensive_rebounds": 4,
            "assists": 2, "steals": 1, "blocks": 0, "turnovers": 2,
            "fgm": 4, "fga": 10, "fg3m": 1, "fg3a": 3,
            "ftm": points - 9, "fta": points - 9, "plus_minus": -2 if side == "away" else 2,
        }
        stats = {
            "minutes": "PT30M25.00S", "points": points, "reboundsTotal": 5,
            "reboundsOffensive": 1, "reboundsDefensive": 4, "assists": 2,
            "steals": 1, "blocks": 0, "turnovers": 2, "fieldGoalsMade": 4,
            "fieldGoalsAttempted": 10, "threePointersMade": 1,
            "threePointersAttempted": 3, "freeThrowsMade": points - 9,
            "freeThrowsAttempted": points - 9, "plusMinusPoints": player["plus_minus"],
            "pointsFastBreak": 0, "pointsInThePaint": 4, "pointsSecondChance": 2,
        }
        row = {"name": "Andre O-Neal" if side == "away" else "John Doe Jr",
               "personId": pid, "played": "1", "statistics": stats}
        players.append(player)
        teams[side + "Team"] = {"teamTricode": alias, "score": points, "players": [row]}
    payload = {"game": {"gameId": GAME_ID, "gameStatus": 3,
                        "gameTimeUTC": "2026-11-20T01:00:00Z", **teams}}
    return game, players, payload


class MergeTests(unittest.TestCase):
    def reject(self, mutate):
        game, players, payload = fixture()
        mutate(game, players, payload)
        before = copy.deepcopy((game, players))
        with self.assertRaises(ValueError):
            apply_live_boxscore(game, players, payload, GAME_ID, DATE)
        self.assertEqual((game, players), before, "A failed game must not be partially merged")

    def test_valid_merge_preserves_espn_ids_and_observed_zero(self):
        game, players, payload = fixture()
        ids = [player["player_id"] for player in players]
        report = apply_live_boxscore(game, players, payload, GAME_ID, DATE)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["coverage"], {"points_in_paint": 2, "fast_break_points": 2, "second_chance_points": 2})
        self.assertEqual([player["player_id"] for player in players], ids)
        self.assertEqual([player["nba_player_id"] for player in players], ["101", "102"])
        self.assertEqual(players[0]["fast_break_points"], 0)
        self.assertEqual(game["nba_game_id"], GAME_ID)

    def test_missing_is_absent_not_zero(self):
        game, players, payload = fixture()
        stats = payload["game"]["awayTeam"]["players"][0]["statistics"]
        del stats["pointsFastBreak"]
        stats["pointsSecondChance"] = None
        report = apply_live_boxscore(game, players, payload, GAME_ID, DATE)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["coverage"]["fast_break_points"], 1)
        self.assertNotIn("fast_break_points", players[0])
        self.assertNotIn("second_chance_points", players[0])

    def test_utc_is_converted_to_eastern_and_time_requires_offset(self):
        self.reject(lambda g, p, d: d["game"].update(gameTimeUTC="2026-11-20T06:00:00Z"))
        self.reject(lambda g, p, d: d["game"].update(gameTimeUTC="2026-11-19T20:00:00"))
        game, players, payload = fixture()
        del payload["game"]["gameTimeUTC"]
        payload["game"]["gameEt"] = "2026-11-19T20:00:00-05:00"
        self.assertEqual(apply_live_boxscore(game, players, payload, GAME_ID, DATE)["status"], "ok")

    def test_wrong_id_nonfinal_team_or_score_rejected(self):
        cases = [
            lambda g, p, d: d["game"].update(gameId="0022600271"),
            lambda g, p, d: d["game"].update(gameStatus=2),
            lambda g, p, d: d["game"]["homeTeam"].update(teamTricode="NYK"),
            lambda g, p, d: d["game"]["homeTeam"].update(score=13),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.reject(mutate)

    def test_missing_duplicate_and_nickname_identities_rejected(self):
        cases = [
            lambda g, p, d: p.pop(),
            lambda g, p, d: p.append(copy.deepcopy(p[0])),
            lambda g, p, d: d["game"]["awayTeam"]["players"].append(copy.deepcopy(d["game"]["awayTeam"]["players"][0])),
            lambda g, p, d: d["game"]["homeTeam"]["players"][0].update(name="Johnny Doe Jr"),
            lambda g, p, d: d["game"]["homeTeam"]["players"][0].update(personId=101),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.reject(mutate)

    def test_basic_box_fields_and_late_failure_are_atomic(self):
        for field in ("assists", "steals", "blocks", "turnovers", "reboundsTotal",
                      "reboundsOffensive", "reboundsDefensive", "fieldGoalsMade",
                      "fieldGoalsAttempted", "threePointersMade", "threePointersAttempted",
                      "freeThrowsMade", "freeThrowsAttempted", "plusMinusPoints"):
            with self.subTest(field=field):
                self.reject(lambda g, p, d: d["game"]["homeTeam"]["players"][0]["statistics"].update({field: 99}))

    def test_c6_bounds_integrality_and_existing_conflict(self):
        for value in (-1, 13, 0.5, True):
            with self.subTest(value=value):
                self.reject(lambda g, p, d: d["game"]["homeTeam"]["players"][0]["statistics"].update(pointsFastBreak=value))
        self.reject(lambda g, p, d: p[-1].update(fast_break_points=1))

    def test_minutes_whole_precision_and_decimal_precision(self):
        # Whole-minute input accepts a seconds difference of less than one minute.
        self.reject(lambda g, p, d: p[-1].update(minutes=28))
        self.reject(lambda g, p, d: p[-1].update(minutes=30.1))
        game, players, payload = fixture()
        players[0]["minutes"] = 30.42
        self.assertEqual(apply_live_boxscore(game, players, payload, GAME_ID, DATE)["status"], "ok")


class ClientTests(unittest.TestCase):
    @staticmethod
    def modules(raw, fail=False):
        class Response:
            def get_response(self):
                return raw
            def get_dict(self):
                return json.loads(raw)
        class BoxScore:
            def __init__(self, **kwargs):
                self.nba_response = None
            def get_request(self):
                self.nba_response = Response()
                if fail:
                    self.nba_response.get_dict()
        class LiveHTTP:
            def send_api_request(self, **kwargs):
                return Response()
        modules = {name: types.ModuleType(name) for name in (
            "nba_api", "nba_api.live", "nba_api.live.nba", "nba_api.live.nba.endpoints",
            "nba_api.live.nba.endpoints.boxscore", "nba_api.live.nba.library",
            "nba_api.live.nba.library.http",
        )}
        modules["nba_api.live.nba.endpoints.boxscore"].BoxScore = BoxScore
        modules["nba_api.live.nba.library.http"].NBALiveHTTP = LiveHTTP
        return modules

    def test_archives_original_text_and_caches_without_mutation_leaks(self):
        raw = '{ "game": {"value": 1} }\n'
        url = BOX_PREFIX + GAME_ID + ".json"
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, self.modules(raw)):
            client = NBAClient(folder, DATE)
            payload = client.fetch_json(url)
            payload["game"]["value"] = 99
            self.assertEqual(client.fetch_json(url)["game"]["value"], 1)
            self.assertEqual(Path(client.raw_paths[url]).read_text(), raw)

    def test_archives_invalid_json_even_when_library_decode_fails(self):
        raw = "<html>403 Access denied</html>"
        url = BOX_PREFIX + GAME_ID + ".json"
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, self.modules(raw, fail=True)):
            client = NBAClient(folder, DATE)
            with self.assertRaises(ValueError):
                client.fetch_json(url)
            self.assertEqual(Path(client.raw_paths[url]).read_text(), raw)

    def test_schedule_uses_allowlist_and_archives_before_parse(self):
        url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
        raw = '{"leagueSchedule": {"gameDates": []}}'
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, self.modules(raw)):
            client = NBAClient(folder, DATE)
            self.assertIn("leagueSchedule", client.fetch_json(url))
            self.assertEqual(Path(client.raw_paths[url]).read_text(), raw)
            for invalid in ("https://stats.nba.com/stats/scoreboardv2", url + "?a=1",
                            BOX_PREFIX + "401910019.json", "https://example.com/scheduleLeagueV2.json"):
                with self.assertRaises(ValueError):
                    client.fetch_json(invalid)


if __name__ == "__main__":
    unittest.main()
