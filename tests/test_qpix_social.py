"""Publication-focused checks for the plain-text QPIX social renderer."""

import contextlib
import copy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from qpix_social import load_verified_report, main, render_social_post, validate_report
from qpix_source_archive import _input_hash

DATE = "2026-11-19"


def make_report(count=22):
    players = []
    for index in range(count):
        away = index < count // 2
        players.append({
            "player_id": str(index), "game_id": "game-1", "name": f"Player {index}",
            "team": "NYK" if away else "MIN", "minutes": 28,
            "points": 10 if away else 11, "rebounds": 2 + index % 8,
            "assists": 2 + index % 10, "steals": index % 4, "blocks": index % 2,
            "turnovers": 2, "fgm": 4, "fga": 8, "fg3m": 1, "fg3a": 3,
            "ftm": 1 if away else 2, "fta": 2,
            "offensive_rating": 151, "defensive_rating": 111,
            "points_in_paint": 6, "fast_break_points": 2, "second_chance_points": 0,
            "score": 30 - index, "raw_qpix": 30 - index,
            "qpixR": 29 - index, "qpix_r": 29 - index,
        })
    games = [{
        "game_id": "game-1", "date_et": DATE, "status": "FINAL",
        "away_alias": "NYK", "home_alias": "MIN",
        "away_points": sum(p["points"] for p in players if p["team"] == "NYK"),
        "home_points": sum(p["points"] for p in players if p["team"] == "MIN"),
    }]
    return {
        "date_et": DATE, "phase": "regular", "status": "VERIFIED",
        "games": games, "players": players,
        "leaderboards": {
            "top10": [p["player_id"] for p in players[:10]],
            "bottom10": [p["player_id"] for p in reversed(players[-10:])],
        },
    }


def save_fixture(root, report=None):
    report = copy.deepcopy(report if report is not None else make_report())
    archive = {
        "date_et": DATE,
        "coverage": {"complete": True, "players": len(report["players"]), "games": len(report["games"])},
        "games": copy.deepcopy(report["games"]),
        "players": [{k: v for k, v in p.items() if k not in ("score", "raw_qpix", "qpixR", "qpix_r")}
                    for p in report["players"]],
    }
    archive["input_sha256"] = _input_hash(archive)
    archive_path = root / "data" / "historical" / "qpix_input" / f"{DATE}.json"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text(json.dumps(archive), encoding="utf-8")
    report["source_archive"] = {
        "path": str(archive_path.relative_to(root)), "complete": True,
        "input_sha256": archive["input_sha256"],
    }
    report_path = root / "data" / "daily" / f"{DATE}.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report, archive, report_path, archive_path


class SocialTextTest(unittest.TestCase):
    def test_authoritative_ids_and_public_facing_content(self):
        report = make_report()
        report["players"].reverse()
        report["data_quality"] = {"internal": "DO NOT PUBLISH THIS AUDIT"}
        report["players"][0]["notes"] = ["developer coefficient: 0.162", "@unexpected_tag", "🏀"]
        text = render_social_post(report, DATE)
        self.assertLess(text.index("FINAL SCORES"), text.index("TOP 10"))
        self.assertIn("Minnesota Timberwolves 121 — New York Knicks 110", text)
        self.assertIn("1. Player 0 (NYK)", text)
        self.assertIn("10. Player 9 (NYK)", text)
        self.assertIn("1. Player 21 (MIN) — Raw QPIX: 9.0", text)
        self.assertIn("Raw QPIX: 30.0 | QPIX-R: 29.0 | Q-OffR: N/A | Q-DefR: N/A", text)
        self.assertIn("10 PTS | 2 REB | 2 AST | 0 STL | 0 BLK | 2 TO | 28 MIN", text)
        self.assertIn("Player 0 leads the slate with 30.0 Raw QPIX", text)
        self.assertIn("https://rickrezin.github.io/NBA-daily-report/", text)
        self.assertIn("© 2026 QCore Labs", text)
        for forbidden in ("DO NOT PUBLISH", "coefficient", "0.162", "@", "**", "##", "VERIFIED"):
            self.assertNotIn(forbidden, text)
        self.assertIsNone(re.search(r"[\U0001f300-\U0001faff\u2600-\u27bf]", text))

    def test_proprietary_ratings_use_only_explicit_q_fields(self):
        report = make_report()
        report["players"][0].update({"qcore_q_offr": 154.25, "qcore_q_defr": 98.75})
        report["players"][1].update({"offImpact": 4.0, "defImpact": -0.1})
        text = render_social_post(report, DATE)
        self.assertIn("Q-OffR: 154.2 | Q-DefR: 98.8", text)
        self.assertIn("Q-OffR: N/A | Q-DefR: N/A", text)
        self.assertNotIn("Q-OffR: 151", text)
        self.assertNotIn("Q-DefR: 111", text)
        self.assertNotIn("Q-OffR: 4.0", text)

    def test_score_aliases_and_explicit_null_ratings(self):
        report = make_report()
        for player in report["players"]:
            del player["score"]
            del player["qpixR"]
            player["qcore_q_offr"] = None
            player["qcore_q_defr"] = None
        text = render_social_post(report, DATE)
        self.assertIn("Raw QPIX: 30.0 | QPIX-R: 29.0 | Q-OffR: N/A", text)

    def test_authoritative_tie_order_is_preserved(self):
        report = make_report()
        report["players"][1]["score"] = report["players"][1]["raw_qpix"] = 30
        report["leaderboards"]["top10"][:2] = ["1", "0"]
        text = render_social_post(report, DATE)
        self.assertLess(text.index("1. Player 1 (NYK)"), text.index("2. Player 0 (NYK)"))
        self.assertIn("Player 1 leads the slate", text)

    def test_short_slate_has_all_eligible_players_in_both_boards(self):
        report = make_report(6)
        text = render_social_post(report, DATE)
        self.assertIn("1 game | 6 players evaluated", text)
        self.assertIn("6. Player 5 (MIN)", text)
        self.assertIn("6. Player 0 (NYK) — Raw QPIX: 30.0", text)

    def test_publication_gates_reject_bad_reports(self):
        def set_score_nan(report):
            report["players"][0].update(score=float("nan"), raw_qpix=float("nan"))

        changes = {
            "unverified": lambda r: r.update(status="PROVISIONAL"),
            "wrong date": lambda r: r.update(date_et="2026-11-18"),
            "unfinished game": lambda r: r["games"][0].update(status="IN_PROGRESS"),
            "wrong game date": lambda r: r["games"][0].update(date_et="2026-11-18"),
            "duplicate participant": lambda r: r["players"][1].update(player_id="0"),
            "unknown leaderboard ID": lambda r: r["leaderboards"]["top10"].__setitem__(0, "missing"),
            "duplicate leaderboard ID": lambda r: r["leaderboards"]["top10"].__setitem__(1, "0"),
            "wrong board count": lambda r: r["leaderboards"]["top10"].pop(),
            "eight minute player": lambda r: r["players"][0].update(minutes=8),
            "wrong board order": lambda r: r["leaderboards"]["top10"].reverse(),
            "cutoff omission": lambda r: r["leaderboards"]["top10"].__setitem__(9, "10"),
            "nonfinite score": set_score_nan,
            "conflicting score aliases": lambda r: r["players"][0].update(raw_qpix=99),
            "boolean stat": lambda r: r["players"][0].update(assists=True),
            "conflicting Q aliases": lambda r: r["players"][0].update(qcore_q_offr=150, q_offr=151),
            "invalid Q rating": lambda r: r["players"][0].update(qcore_q_offr="151"),
            "tag in name": lambda r: r["players"][0].update(name="@Player"),
            "incorrect final score": lambda r: r["games"][0].update(home_points=122),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                report = make_report()
                change(report)
                with self.assertRaises(ValueError):
                    validate_report(report, DATE)

    def test_date_argument_must_be_canonical(self):
        for value in ("2026-11-9", "2026-11-31", "../2026-11-19", "20261119", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report(make_report(), value)


class SocialArchiveTest(unittest.TestCase):
    def test_cli_writes_exact_dated_text_after_archive_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, _, _, _ = save_fixture(root)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([DATE, "--root", str(root)]), 0)
            output = root / "docs" / "social" / f"{DATE}.facebook.txt"
            self.assertEqual(output.read_text(encoding="utf-8"), render_social_post(report, DATE))

    def test_archive_content_digest_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, archive, _, archive_path = save_fixture(root)
            archive["players"][0]["rebounds"] += 1
            archive_path.write_text(json.dumps(archive), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                load_verified_report(root, DATE)

    def test_complete_counts_and_archive_identity_are_checked(self):
        for field, value in (("complete", False), ("players", 23), ("games", 2)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, archive, _, archive_path = save_fixture(root)
                archive["coverage"][field] = value
                archive_path.write_text(json.dumps(archive), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_verified_report(root, DATE)

    def test_report_player_cannot_drift_from_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, _, report_path, _ = save_fixture(root)
            report["players"][0]["rebounds"] += 1
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "player statistics differ"):
                load_verified_report(root, DATE)

    def test_archive_path_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, _, report_path, _ = save_fixture(root)
            report["source_archive"]["path"] = "../outside.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                load_verified_report(root, DATE)

    @unittest.skipUnless((ROOT / "data" / "daily" / f"{DATE}.json").exists(), "November 19 fixture unavailable")
    def test_committed_verified_november_19_report(self):
        report = load_verified_report(ROOT, DATE)
        text = render_social_post(report, DATE)
        self.assertIn("4 games | 89 players evaluated", text)
        self.assertIn("1. Scoot Henderson (POR)", text)
        self.assertIn("New York Knicks 102 — Minnesota Timberwolves 99", text)
        self.assertIn("Raw QPIX: 77.4 | QPIX-R: 75.0 | Q-OffR: N/A | Q-DefR: N/A", text)


if __name__ == "__main__":
    unittest.main()
