"""Keep the C2 penalty tied to traditional TS in the shot adjustment replay."""

import json
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
        scorer += "\nexport { computeC2 };\n"
        (cls.sandbox / "original.js").write_text(scorer, encoding="utf-8")

        # Reproduce the research replay by adjusting only the continuous term.
        # Once a candidate exists in the engine, invoke that path directly here.
        efficiency_term = "let score = (ts - 55) * 0.3;"
        if scorer.count(efficiency_term) != 1:
            raise AssertionError("Connect the C2 crossing fixtures to the live efficiency term")
        adjusted = scorer.replace(
            efficiency_term, "let score = (ts + p.testTsAdjustment - 55) * 0.3;"
        )
        (cls.sandbox / "adjusted.js").write_text(adjusted, encoding="utf-8")

    def assess(self, name, fixtures):
        players = [
            {"fga": fga, "fta": 0, "points": 2 * fga * ts / 100, "testTsAdjustment": adjustment}
            for fga, ts, adjustment, _ in fixtures
        ]
        probe = f"""
            import {{ computeC2 }} from './{name}.js';
            const players = {json.dumps(players)};
            console.log(JSON.stringify(players.map(p => computeC2(p))));
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
        self.assess("original", [
            (10, 37.999, 0, -9.1003),
            (10, 38.000, 0, -5.1000),
            (10, 38.001, 0, -5.0997),
        ])

    def test_adjusted_efficiency_cannot_toggle_penalty(self):
        self.assess("adjusted", [
            (10, 37.90, +0.20, -9.07),
            (10, 38.10, -0.20, -5.13),
            (10, 38.00, -0.20, -5.16),
        ])

    def test_penalty_requires_at_least_six_official_attempts(self):
        self.assess("adjusted", [
            (5, 37.90, +0.20, -5.07),
            (6, 37.90, +0.20, -9.07),
        ])

    def test_adjusted_efficiency_keeps_attempt_weighting(self):
        self.assess("adjusted", [
            (0, 55.00, +3.00, 0.00),
            (1, 55.00, +3.00, 0.30),
            (2, 55.00, +3.00, 0.60),
            (3, 55.00, +3.00, 0.90),
            (8, 55.00, +3.00, 0.90),
        ])
