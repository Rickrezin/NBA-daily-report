"""Validate canonical QCore input archive using November 2 source-verified fixture."""
import json,sys,unittest,tempfile,subprocess
from copy import deepcopy
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

class TestArchiveRevisions(unittest.TestCase):
    def setUp(self):
        # Explicit synthetic input isolates archive behavior from live sources.
        self.date="2026-11-19"
        self.games=[{"game_id":"ESPN_test","home_alias":"NYK","away_alias":"MIN",
                     "home_points":2,"away_points":1}]
        self.players=[{"game_id":"ESPN_test","player_id":"1","team":"NYK","name":"Home","points":2},
                      {"game_id":"ESPN_test","player_id":"2","team":"MIN","name":"Away","points":1}]
        self.partial=canonical_snapshot(self.games,self.players,self.date,{"test_only":True},False)
        full_players=[dict(p,offensive_rating=100,defensive_rating=110,
                           points_in_paint=0,fast_break_points=0,second_chance_points=0)
                      for p in self.players]
        self.complete=canonical_snapshot(self.games,full_players,self.date,{"test_only":True})

    def test_revision_preserves_original_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=write_snapshot(self.partial,tmp)
            original_bytes=base.read_bytes()
            with self.assertRaisesRegex(ValueError,"Historical archive conflict"):
                write_snapshot(self.complete,tmp)
            revision=write_snapshot(self.complete,tmp,allow_revision=True)
            self.assertEqual(revision.name,self.date+"."+self.complete["input_sha256"]+".json")
            self.assertEqual(base.read_bytes(),original_bytes)
            self.assertTrue(json.loads(revision.read_text())["coverage"]["complete"])
            revision_bytes=revision.read_bytes()
            repeated=deepcopy(self.complete)
            repeated["generated_at_utc"]="2026-11-21T00:00:00+00:00"
            repeated["source_audit"]={"another_attempt":True}
            self.assertEqual(write_snapshot(repeated,tmp,allow_revision=True),revision)
            self.assertEqual(revision.read_bytes(),revision_bytes)
            self.assertEqual(base.read_bytes(),original_bytes)

    def test_tampered_existing_revision_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=write_snapshot(self.partial,tmp)
            revision=write_snapshot(self.complete,tmp,allow_revision=True)
            altered=json.loads(revision.read_text())
            altered["players"][0]["fast_break_points"]=1
            revision.write_text(json.dumps(altered))
            altered_bytes=revision.read_bytes()
            with self.assertRaisesRegex(ValueError,"Historical archive content conflict"):
                write_snapshot(self.complete,tmp,allow_revision=True)
            self.assertEqual(revision.read_bytes(),altered_bytes)
            self.assertFalse(json.loads(base.read_text())["coverage"]["complete"])

    def test_snapshot_hash_must_describe_actual_inputs(self):
        altered=deepcopy(self.complete)
        altered["players"][0]["fast_break_points"]=1
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"Snapshot input hash"):
                write_snapshot(altered,tmp,allow_revision=True)
            self.assertFalse((Path(tmp)/"data").exists())

    def _coverage_cli(self,tmp,*extra):
        return subprocess.run([sys.executable,str(ROOT/"scripts/qpix_coverage_audit.py"),
                               self.date,"--root",tmp,*extra],capture_output=True,text=True)

    def test_explicit_coverage_reads_revision_instead_of_stale_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_snapshot(self.partial,tmp)
            revision=write_snapshot(self.complete,tmp,allow_revision=True)
            result=self._coverage_cli(tmp,"--source",str(revision.relative_to(tmp)))
            self.assertEqual(result.returncode,0,result.stderr)
            audit=Path(tmp)/"data/historical/qpix_audits"/(self.date+".coverage.json")
            report=json.loads(audit.read_text())
            self.assertEqual(report["input_archive"],str(revision))
            self.assertEqual(report["input_sha256"],self.complete["input_sha256"])
            by_category={r["category"]:r for r in report["categories"]}
            self.assertEqual(by_category["C3 Individual O/D"]["present"],2)
            self.assertEqual(by_category["C6 Offensive context"]["present"],2)

    def test_explicit_coverage_missing_or_wrong_date_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_snapshot(self.partial,tmp)
            missing=self._coverage_cli(tmp,"--source","missing.json")
            self.assertNotEqual(missing.returncode,0)
            self.assertIn("Explicit input archive is unavailable",missing.stderr)
            wrong=Path(tmp)/"wrong-date.json"
            snapshot=deepcopy(self.complete)
            snapshot["date_et"]="2026-11-18"
            wrong.write_text(json.dumps(snapshot))
            result=self._coverage_cli(tmp,"--source",str(wrong))
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Input archive date does not match",result.stderr)
            self.assertFalse((Path(tmp)/"data/historical/qpix_audits").exists())

if __name__=="__main__":unittest.main()

