"""Safety regressions for fresh, independently reconciled BRef C3 ingestion."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qpix_bref_ratings import BOX_FIELDS, collect_game_ratings

DATE = "2026-11-19"
GAME = {"game_id": "ESPN_123", "home_alias": "SAS", "away_alias": "NYK",
        "home_points": 4, "away_points": 6, "date_et": DATE}


def player(name, team, points):
    row = {field: 0 for field in BOX_FIELDS}
    row.update(name=name, player_id=name, team=team, game_id="ESPN_123", minutes=35,
               points=points, fgm=points // 2, fga=4,
               rebounds=2, offensive_rebounds=1, defensive_rebounds=1)
    return row


PLAYERS = [player("New York Player", "NY", 6), player("San Antonio Player", "SA", 4)]


def cell(key, value):
    return '<td data-stat="' + key + '">' + str(value) + '</td>'


def source_row(row, pid, advanced=False, **overrides):
    values = {"mp": "35:00"}
    values.update({"off_rtg": "120", "def_rtg": "110"} if advanced else
                  {column: row[field] for field, column in BOX_FIELDS.items()})
    values.update(overrides)
    head = ('<th data-stat="player" data-append-csv="' + pid + '"><a href="/players/p/' +
            pid + '.html">' + row["name"] + '</a></th>')
    return '<tr>' + head + ''.join(cell(k, v) for k, v in values.items()) + '</tr>'


def page(canonical="202611190SAS", override=None, comment_advanced=False, duplicate_basic=False):
    html = '<link rel="canonical" href="https://www.basketball-reference.com/boxscores/' + canonical + '.html">'
    for row, team, pid in zip(PLAYERS, ["NYK", "SAS"], ["playera01", "playerb01"]):
        for kind in ("basic", "advanced"):
            changes = (override or {}).get((team, kind), {})
            entry = source_row(row, pid, advanced=kind == "advanced", **changes)
            if duplicate_basic and team == "NYK" and kind == "basic":
                entry += entry
            totals = '<tr><th data-stat="player">Team Totals</th>' + cell("pts", row["points"]) + '</tr>'
            table = '<table id="box-' + team + '-game-' + kind + '">' + entry + totals + '</table>'
            html += '<!--' + table + '-->' if comment_advanced and kind == "advanced" else table
    return html


class BRefRatingsTests(unittest.TestCase):
    def run_case(self, raw=None, players=None, game=None):
        players = copy.deepcopy(PLAYERS if players is None else players)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = collect_game_ratings(
                GAME if game is None else game, players, DATE, root,
                lambda *args, **kwargs: page() if raw is None else raw
            )
            self.assertTrue((root / "data/historical/qpix_bref_raw" / DATE / "202611190SAS.html").exists())
            self.assertTrue((root / "data/historical/qpix_bref_raw" / DATE / "202611190SAS.audit.json").exists())
        return audit, players

    def test_reconciles_aliases_and_preserves_separate_provider_id(self):
        audit, players = self.run_case()
        self.assertEqual(audit["status"], "fully_reconciled")
        self.assertEqual(audit["assigned"], 2)
        self.assertEqual(players[0]["player_id"], "New York Player")
        self.assertEqual(players[0]["bref_player_id"], "playera01")
        self.assertEqual(players[1]["defensive_rating"], 110)
        self.assertEqual(len(audit["raw_sha256"]), 64)

    def test_commented_full_game_tables_are_parsed(self):
        audit, _ = self.run_case(page(comment_advanced=True))
        self.assertEqual(audit["assigned"], 2)

    def test_wrong_page_date_rejects_all_additions(self):
        audit, players = self.run_case(page(canonical="202611180SAS"))
        self.assertEqual(audit["status"], "validation_failed")
        self.assertTrue(all("offensive_rating" not in p for p in players))

    def test_wrong_team_score_rejects_all_additions(self):
        game = dict(GAME, home_points=5)
        audit, players = self.run_case(game=game)
        self.assertEqual(audit["assigned"], 0)
        self.assertTrue(all("defensive_rating" not in p for p in players))

    def test_changed_rebounds_never_receive_ratings(self):
        players = copy.deepcopy(PLAYERS)
        players[0]["rebounds"] = 3
        audit, players = self.run_case(players=players)
        self.assertEqual(audit["status"], "partial")
        self.assertEqual(audit["assigned"], 1)
        self.assertNotIn("offensive_rating", players[0])
        self.assertEqual(audit["issues"][0]["fields"], ["rebounds"])

    def test_nonfinite_and_missing_ratings_remain_absent(self):
        for value in ("NaN", "inf", ""):
            with self.subTest(value=value):
                audit, players = self.run_case(page(override={("NYK", "advanced"): {"off_rtg": value}}))
                self.assertEqual(audit["assigned"], 1)
                self.assertNotIn("offensive_rating", players[0])

    def test_observed_zero_rating_is_preserved(self):
        audit, players = self.run_case(page(override={("NYK", "advanced"): {"off_rtg": "0"}}))
        self.assertEqual(audit["assigned"], 2)
        self.assertEqual(players[0]["offensive_rating"], 0)

    def test_duplicate_provider_identity_rejects_all_additions(self):
        audit, players = self.run_case(page(duplicate_basic=True))
        self.assertEqual(audit["status"], "validation_failed")
        self.assertTrue(all("offensive_rating" not in p for p in players))

    def test_incomplete_participant_set_rejects_all_additions(self):
        audit, players = self.run_case(players=PLAYERS[:1])
        self.assertEqual(audit["assigned"], 0)
        self.assertNotIn("offensive_rating", players[0])

    def test_conflicting_existing_rating_aborts_game_atomically(self):
        players = copy.deepcopy(PLAYERS)
        players[1]["offensive_rating"] = 999
        players[1]["defensive_rating"] = 999
        audit, players = self.run_case(players=players)
        self.assertEqual(audit["assigned"], 0)
        self.assertNotIn("offensive_rating", players[0])
        self.assertEqual(players[1]["offensive_rating"], 999)

    def test_retrieval_failure_does_not_reuse_old_raw_page(self):
        players = copy.deepcopy(PLAYERS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collect_game_ratings(GAME, copy.deepcopy(players), DATE, root, lambda *a, **kw: page())
            def unavailable(*args, **kwargs):
                raise TimeoutError("provider unavailable")
            audit = collect_game_ratings(GAME, players, DATE, root, unavailable)
        self.assertEqual(audit["status"], "retrieval_failed")
        self.assertEqual(audit["assigned"], 0)
        self.assertTrue(all("offensive_rating" not in p for p in players))


if __name__ == "__main__":
    unittest.main()

