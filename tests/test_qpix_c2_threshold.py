"""Keep the C2 penalty tied to traditional TS in the shot adjustment replay."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class C2ThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.sandbox = Path(temp.name)
        scripts = cls.sandbox / "scripts"
        scripts.mkdir()
        shutil.copyfile(ROOT / "scripts/familiarity.js", scripts / "familiarity.js")
        shutil.copyfile(ROOT / "package.json", cls.sandbox / "package.json")

        engine = (ROOT / "generate-report.js").read_text(encoding="utf-8")
        scorer, entry_point, _ = engine.rpartition("\nmain().catch(")
        if not entry_point:
            raise AssertionError("Could not isolate the report scorer from its CLI entry point")
        (cls.sandbox / "scorer.js").write_text(scorer + "\nexport { computeC2 };\n", encoding="utf-8")
        (cls.sandbox / "generate-report.js").write_text(engine, encoding="utf-8")

    def assess(self, fixtures):
        players = [
            {"fga": fga, "fta": 0, "points": 2 * fga * ts / 100, "pointsAdjustment": 2 * fga * adjustment / 100}
            for fga, ts, adjustment, _ in fixtures
        ]
        probe = f"""
            import {{ computeC2 }} from './scorer.js';
            const players = {json.dumps(players)};
            console.log(JSON.stringify(players.map(p => computeC2(p, p.pointsAdjustment))));
        """
        run = subprocess.run(
            ["node", "--input-type=module", "--eval", probe],
            cwd=self.sandbox, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        for fixture, result in zip(fixtures, json.loads(run.stdout), strict=True):
            fga, ts, adjustment, score = fixture
            with self.subTest(fga=fga, ts=ts, adjustment=adjustment):
                self.assertAlmostEqual(result["ts"], ts if fga else 0, places=10)
                self.assertAlmostEqual(result["score"], score, places=10)

    def test_original_penalty_is_strict_and_uses_unrounded_ts(self):
        self.assess([
            (10, 37.999, 0, -9.1003),
            (10, 38.000, 0, -5.1000),
            (10, 38.001, 0, -5.0997),
        ])

    def test_adjusted_efficiency_cannot_toggle_penalty(self):
        self.assess([
            (10, 37.90, +0.20, -9.07),
            (10, 38.10, -0.20, -5.13),
            (10, 38.00, -0.20, -5.16),
        ])

    def test_penalty_requires_at_least_six_official_attempts(self):
        self.assess([
            (5, 37.90, +0.20, -5.07),
            (6, 37.90, +0.20, -9.07),
        ])

    def test_adjusted_efficiency_keeps_attempt_weighting(self):
        self.assess([
            (0, 55.00, +3.00, 0.00),
            (1, 55.00, +3.00, 0.30),
            (2, 55.00, +3.00, 0.60),
            (3, 55.00, +3.00, 0.90),
            (8, 55.00, +3.00, 0.90),
        ])

    def test_shadow_entry_point_applies_id_join_and_writes_only_shadow_output(self):
        game_id = "0042500405"
        player = {
            "game_id": game_id, "player_id": "123", "name": "Fixture", "team": "SAS",
            "game": "NYK @ SAS", "home_alias": "SAS", "away_alias": "NYK", "minutes": 20,
            "points": 8, "fga": 10, "fta": 0, "rebounds": 0, "assists": 0,
            "steals": 0, "blocks": 0, "turnovers": 0,
        }
        game = {"game_id": game_id, "home_alias": "SAS", "away_alias": "NYK", "home_points": 8, "away_points": 9}
        data = self.sandbox / "data"
        data.mkdir()
        (data / "nba_data.json").write_text(json.dumps({"games": [game], "players": [player]}), encoding="utf-8")
        sidecar = self.sandbox / "sidecar.json"
        output = self.sandbox / "shadow.json"
        github_env = self.sandbox / "github-env"
        env = {**os.environ, "QPIX_C2_SHADOW_INPUT": str(sidecar), "QPIX_C2_SHADOW_OUTPUT": str(output),
               "QPIX_PHASE": "regular", "QPIX_SEASON_END": "2026", "GITHUB_ENV": str(github_env)}
        tracking = {"game_id": game_id, "player_id": "123", "fga": 10, "classified_fga": 10, "points_adjustment": -0.6}

        def run(rows):
            sidecar.write_text(json.dumps({"players": rows}), encoding="utf-8")
            return subprocess.run(["node", "generate-report.js"], cwd=self.sandbox, env=env,
                                  capture_output=True, text=True, encoding="utf-8")

        failure = run([{**tracking, "fga": 11}])
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn("identity or attempts do not reconcile", failure.stderr)
        self.assertFalse(output.exists())
        success = run([tracking])
        self.assertEqual(success.returncode, 0, success.stderr)
        c2 = json.loads(output.read_bytes())["players"][0]["c2"]
        self.assertEqual((c2["ts"], c2["efficiencyTs"], c2["lowEfficiencyPenalty"]), (40, 37, 0))
        self.assertFalse((self.sandbox / "dashboard").exists())
        self.assertFalse(github_env.exists())
