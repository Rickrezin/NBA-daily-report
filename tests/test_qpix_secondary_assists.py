from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from qpix_secondary_assists import (apply_secondary_assists, collect_secondary_assists,
                                    require_secondary_assist_coverage)
import render_qpix_dashboard as dashboard

DATE = "2026-07-04"
GAME = {"date_et": DATE, "game_id": "ESPN_40", "nba_game_id": "0022500001", "status": "FINAL",
        "away_alias": "AAA", "home_alias": "BBB", "away_points": 0, "home_points": 0, "source": "test fixture"}


def player(pid, team, **fields):
    return {"name": f"Player {pid}", "game": "AAA @ BBB", "team": team, "position": "G",
            "game_id": GAME["game_id"], "nba_game_id": GAME["nba_game_id"], "player_id": str(10000 + pid),
            "nba_player_id": str(pid), "away_alias": "AAA", "home_alias": "BBB", "minutes": 22,
            "points": 9, "rebounds": 10, "assists": 9, "steals": 0, "blocks": 0, "turnovers": 2,
            "fgm": 4, "fga": 8, "fg3m": 1, "fg3a": 3, "ftm": 0, "fta": 0, "ft_pct": .75,
            "plus_minus": 0, "offensive_rating": 110, "defensive_rating": 110,
            "points_in_paint": 0, "second_chance_points": 0, "fast_break_points": 0, **fields}


def source(away=2, home=0):
    def team(id_, alias, pid, count):
        return {"teamId": id_, "teamTricode": alias, "statistics": {"secondaryAssists": count},
                "players": [{"personId": pid, "statistics": {
                    "secondaryAssists": count, "passes": 18, "minutes": "22:00"}}]}
    return {"boxScorePlayerTrack": {"gameId": GAME["nba_game_id"], "awayTeamId": 11, "homeTeamId": 12,
            "awayTeam": team(11, "AAA", 1, away), "homeTeam": team(12, "BBB", 2, home)}}


class TrackingJoinTests(unittest.TestCase):
    def test_counts_join_by_verified_ids_and_keep_assists(self):
        players = [player(2, "BBB", name="Same name"), player(1, "AAA", name="Same name")]
        players.append(player(3, "AAA", nba_player_id=None))
        tracked = source()
        tracked["boxScorePlayerTrack"]["awayTeam"]["players"][0]["statistics"]["minutes"] = "21:60"
        audit = apply_secondary_assists(GAME, players, tracked, DATE)
        self.assertEqual([p["2AST"] for p in players], [0, 2, None])
        self.assertEqual([p["assists"] for p in players], [9, 9, 9])
        self.assertEqual(audit["status"], "partial")

    def test_missing_and_zero_filled_placeholder_stay_null(self):
        payload = source(away=None)
        payload["boxScorePlayerTrack"]["homeTeam"]["players"][0]["statistics"]["passes"] = 0
        players = [player(1, "AAA"), player(2, "BBB")]
        audit = apply_secondary_assists(GAME, players, payload, DATE)
        self.assertEqual(audit["verified"], 0)
        self.assertEqual([p["2AST"] for p in players], [None, None])
        require_secondary_assist_coverage(False, 0, 2)
        with self.assertRaisesRegex(ValueError, "0/2"):
            require_secondary_assist_coverage(True, 0, 2)

    def test_date_game_team_and_duplicate_validation_is_atomic(self):
        players = [player(1, "AAA"), player(2, "BBB")]
        before = deepcopy(players)
        payload = source()
        for wrong_game in ({**GAME, "date_et": "2026-07-03"}, {**GAME, "nba_game_id": "0022501234"},
                           {**GAME, "away_alias": "CCC"}):
            with self.assertRaises(ValueError):
                apply_secondary_assists(wrong_game, players, payload, DATE)
            self.assertEqual(players, before)
        payload["boxScorePlayerTrack"]["homeTeam"]["players"][0]["personId"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate"):
            apply_secondary_assists(GAME, players, payload, DATE)
        self.assertEqual(players, before)

    def test_official_page_fallback_archives_both_responses_and_keeps_conflicts_null(self):
        payload = source(away=1, home=None)
        later = {**source(away=2, home=0)["boxScorePlayerTrack"], "gameStatus": 3,
                 "gameTimeUTC": "2026-07-05T02:30:00Z"}
        page_data = {"props": {"pageProps": {"game": later}}}
        candidates = iter([json.dumps(payload), '<script id="__NEXT_DATA__">'+json.dumps(page_data)+'</script>'])
        players = [player(1, "AAA"), player(2, "BBB")]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = collect_secondary_assists(GAME, players, DATE, root, lambda *_args, **_kw: next(candidates))
            self.assertEqual(audit["conflicts"], {"10001": [1, 2]})
            self.assertEqual([p["2AST"] for p in players], [None, 0])
            self.assertTrue(all((root / attempt["raw_path"]).is_file() for attempt in audit["attempts"]))


@unittest.skipUnless(shutil.which("node"), "Node.js required for engine integration")
class ProductionIntegrationTests(unittest.TestCase):
    def test_c5_rules_regression_and_ranked_html(self):
        with TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            (sandbox / "data").mkdir()
            players = [
                player(1, "AAA", **{"2AST": 2}),
                player(2, "BBB", **{"2AST": 0}),
                player(3, "AAA", minutes=8, points=40, **{"2AST": 0}),
                player(4, "AAA", minutes=8 + 1 / 60, **{"2AST": 0}),
                *[player(n, "BBB", **{"2AST": 0}) for n in range(5, 25)],
            ]

            def run(enabled, weight="0.75"):
                (sandbox / "data/nba_data.json").write_text(json.dumps({"games": [GAME], "players": players}),
                                                          encoding="utf-8")
                env = {**os.environ, "QPIX_ENABLE_SECONDARY_ASSISTS": str(enabled),
                       "QPIX_SECONDARY_ASSIST_WEIGHT": weight, "QPIX_SCORED_OUTPUT": "scored.json",
                       "QPIX_PHASE": "regular"}
                env.pop("GITHUB_ENV", None)
                return subprocess.run(["node", str(ROOT / "generate-report.js")], cwd=sandbox, env=env,
                                      capture_output=True, encoding="utf-8", errors="replace")

            self.assertEqual(run(0).returncode, 0)
            baseline = json.loads((sandbox / "scored.json").read_text(encoding="utf-8"))
            enabled = run(1)
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            after = json.loads((sandbox / "scored.json").read_text(encoding="utf-8"))
            by_id = lambda report: {p["player_id"]: p for p in report["players"]}
            before_players, after_players = by_id(baseline), by_id(after)
            for pid, row in after_players.items():
                old = before_players[pid]
                self.assertEqual(row["score"], old["score"] + (3 if pid == "10001" else 0))
                self.assertEqual(row["refPenalty"], old["refPenalty"])
                self.assertEqual(row["refBonus"], old["refBonus"])
                self.assertEqual(row["assists"], 9)
            self.assertEqual(after_players["10001"]["weighted_assists"], 10.5)
            self.assertTrue(after_players["10004"]["top10_eligible"])
            self.assertNotIn("10003", after["leaderboards"]["top10"] + after["leaderboards"]["bottom10"])
            self.assertEqual(len(after["leaderboards"]["top10"]), 10)
            self.assertEqual(len(after["leaderboards"]["bottom10"]), 10)
            self.assertEqual(len(after["players"]), 24)
            html = (sandbox / "dashboard/index.html").read_text(encoding="utf-8")
            for marker in ("Weighted AST", "Bottom 10", "Complete QPIX Rankings"):
                self.assertIn(marker, html)
            self.assertEqual(run(1, "0").returncode, 0)
            zero_weight = by_id(json.loads((sandbox / "scored.json").read_text(encoding="utf-8")))
            self.assertEqual(zero_weight["10001"]["score"], before_players["10001"]["score"])
            players[1]["2AST"] = None
            self.assertIn("requires verified tracking", run(1).stderr)
            self.assertEqual(run(0).returncode, 0)
            missing = by_id(json.loads((sandbox / "scored.json").read_text(encoding="utf-8")))["10002"]
            self.assertIsNone(missing["2AST"])
            self.assertIsNone(missing["weighted_assists"])

    def test_production_exports_and_published_renderer_with_historical_guard(self):
        starting_cwd = Path.cwd()
        import qpix_independent_run as production
        players = [player(1, "AAA", **{"2AST": 2}), player(2, "BBB", **{"2AST": 0})]
        fixture = {**GAME, "away_points": 9, "home_points": 9}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("generate-report.js", "package.json", "scripts/familiarity.js"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            try:
                os.chdir(root)
                config = {"ROOT": root, "RUN_DATE": DATE, "PHASE": "regular", "ENABLE_NBA_V3": False,
                          "ENABLE_NBA_CDN": False, "SCORE_SECONDARY_ASSISTS": True, "COLLECT_SECONDARY_ASSISTS": True}
                with (
                    patch.multiple(production, **config),
                    patch.object(production, "game_ids_for", return_value=[GAME["game_id"]]),
                    patch.object(production, "normalize_game", return_value=(fixture, players)),
                    patch.object(production, "collect_secondary_assists", return_value={"verified": 2, "total": 2}),
                    patch.dict(os.environ, {"QPIX_ENABLE_SECONDARY_ASSISTS": "true", "QPIX_SECONDARY_ASSIST_WEIGHT": "0.75"}),
                ):
                    production.main()
                    path = root / f"data/daily/{DATE}.json"
                    blob = path.read_bytes()
                    report = json.loads(blob)
                    with (root / f"data/daily/{DATE}.csv").open(newline="", encoding="utf-8") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual((rows[0]["AST"], rows[0]["2AST"], rows[0]["weighted_assists"]), ("9", "2", "10.5"))
                    self.assertEqual(report["players"][0]["weighted_assists"], 10.5)
                    with self.assertRaisesRegex(RuntimeError, "Existing dated report preserved"):
                        production.main()
                    self.assertEqual(blob, path.read_bytes())
                    import qpix_render_verified as verified_renderer
                    with (
                        patch.object(verified_renderer, "__file__", str(root / "scripts/qpix_render_verified.py")),
                        patch.object(dashboard, "find_report"),
                        patch.object(dashboard, "OUT", root / "dashboard/index.html"),
                    ):
                        verified_renderer.main(DATE)
                        report["players"][0]["2AST"] = None
                        path.write_text(json.dumps(report), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "Weighted assists differ"):
                            verified_renderer.main(DATE)
                    html = (root / "dashboard/index.html").read_text(encoding="utf-8")
                    self.assertIn("2/2 player records", html)
                    self.assertIn("Weighted AST: 10.5", html)
            finally:
                os.chdir(starting_cwd)


if __name__ == "__main__":
    unittest.main()
