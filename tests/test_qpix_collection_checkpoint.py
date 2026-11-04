import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from qpix_collection_checkpoint import CollectionCheckpoint

class TestCollectionCheckpoint(unittest.TestCase):
    def test_write_on_entry_then_checkpoint_each_game(self):
        with tempfile.TemporaryDirectory() as root:
            cp=CollectionCheckpoint(root,"2026-11-04")
            self.assertTrue(cp.path.exists())
            initial=json.loads(cp.path.read_text())
            self.assertEqual(initial["stage"],"started")
            self.assertEqual(initial["completed_games"],[])
            cp.stage("schedule_verified",expected_game_ids=["a","b"])
            game={"game_id":"a","away_alias":"CHI","home_alias":"NYK",
                  "away_points":101,"home_points":102,"source":"https://example.test"}
            rows=[{"player_id":"1","name":"Test Player","points":102}]
            cp.game(game,rows)
            current=json.loads(cp.path.read_text())
            self.assertEqual(len(current["completed_games"]),1)
            self.assertEqual(current["completed_games"][0]["players"],rows)
            cp.game(game,rows)
            self.assertEqual(len(json.loads(cp.path.read_text())["completed_games"]),1)
            cp.fail(RuntimeError("C6 request timed out"))
            failed=json.loads(cp.path.read_text())
            self.assertEqual(failed["status"],"failed")
            self.assertEqual(failed["failure"]["type"],"RuntimeError")
            self.assertIn("C6",failed["failure"]["message"])
            self.assertEqual(len(failed["completed_games"]),1)
    def test_failure_before_first_game_is_durable(self):
        with tempfile.TemporaryDirectory() as root:
            cp=CollectionCheckpoint(root,"2026-11-04")
            cp.fail(ValueError("No scoreboard"))
            state=json.loads(cp.path.read_text())
            self.assertEqual(state["completed_games"],[])
            self.assertIn("No scoreboard",state["failure"]["message"])
    def test_completed_source_archive_link(self):
        with tempfile.TemporaryDirectory() as root:
            cp=CollectionCheckpoint(root,"2026-11-04")
            cp.done("data/historical/qpix_input/2026-11-04.json","abc123")
            state=json.loads(cp.path.read_text())
            self.assertEqual(state["canonical_archive"]["sha256"],"abc123")
            self.assertEqual(state["status"],"complete")

if __name__=="__main__": unittest.main()
