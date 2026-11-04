"""Validate canonical QCore input archive using November 2 source-verified fixture."""
import json,sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from qpix_source_archive import canonical_snapshot,write_snapshot
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"data/daily/2026-11-02.json"

class TestQCoreArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        obj=json.loads(ARCHIVE.read_text(encoding="utf-8"))
        cls.games=obj["games"]
        cls.players=obj["players"]
    def test_historical_missing_c6_identified_for_all_334(self):
        s=canonical_snapshot(self.games,self.players,"2026-11-02",{"source":"validated fixture"},require_complete=False)
        self.assertEqual(s["coverage"]["players"],334)
        self.assertEqual(s["coverage"]["fields"]["offensive_rating"],334)
        self.assertEqual(s["coverage"]["fields"]["defensive_rating"],334)
        for f in ("points_in_paint","fast_break_points","second_chance_points"):
            self.assertEqual(s["coverage"]["fields"][f],0)
            self.assertEqual(len(s["coverage"]["missing"][f]),334)
        self.assertFalse(s["coverage"]["complete"])
    def test_full_category_gate_fails_on_real_missing_inputs(self):
        with self.assertRaisesRegex(ValueError,"Incomplete QPIX inputs"):
            canonical_snapshot(self.games,self.players,"2026-11-02",{},require_complete=True)
    def test_complete_synthetic_c6_and_immutable_archive(self):
        # Zero here is explicit synthetic test input, not a live-game assertion.
        g=self.games[0]
        p=[dict(row) for row in self.players if row["game_id"]==g["game_id"]]
        for row in p:
            row.update({"points_in_paint":0,"fast_break_points":0,"second_chance_points":0})
        s=canonical_snapshot([g],p,"2026-11-02",{"test_only":True})
        self.assertTrue(s["coverage"]["complete"])
        with tempfile.TemporaryDirectory() as tmp:
            path=write_snapshot(s,tmp)
            self.assertEqual(json.loads(path.read_text())["input_sha256"],s["input_sha256"])
            self.assertEqual(path,write_snapshot(s,tmp))
            p[0]["points_in_paint"]=2
            different=canonical_snapshot([g],p,"2026-11-02",{"test_only":True})
            with self.assertRaisesRegex(ValueError,"Historical archive conflict"):
                write_snapshot(different,tmp)
    def test_missing_or_bad_player_identity_blocks(self):
        g=self.games[0]
        p=[dict(row) for row in self.players if row["game_id"]==g["game_id"]]
        p[0]["player_id"]=None
        with self.assertRaisesRegex(ValueError,"Unresolved player"):
            canonical_snapshot([g],p,"2026-11-02",{},False)

if __name__=="__main__":unittest.main()
