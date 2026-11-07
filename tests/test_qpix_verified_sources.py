"""Regression tests for exact-date, player-level archived rating reconciliation."""
import sys,unittest,json,copy,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from qpix_verified_sources import populate_verified_ratings

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"data"/"daily"/"2026-11-02.json"

@unittest.skipUnless(ARCHIVE.exists(),"November 2 verified archive not present")
class RatingArchiveTest(unittest.TestCase):
    def setup_archive(self):
        original=json.loads(ARCHIVE.read_text(encoding="utf-8"))
        participants=[]
        for row in original["players"]:
            item={k:v for k,v in row.items() if k not in ("offensive_rating","defensive_rating")}
            participants.append(item)
        return original,participants
    def test_all_334_individual_ratings_restore(self):
        original,players=self.setup_archive()
        result=populate_verified_ratings(players,"2026-11-02",ROOT)
        self.assertEqual(result["assigned"],334)
        self.assertEqual(result["status"],"fully_reconciled")
        self.assertEqual(len(players),334)
    def test_bad_box_line_blocks_rating_reuse(self):
        original,players=self.setup_archive()
        players[0]["points"]+=1
        result=populate_verified_ratings(players,"2026-11-02",ROOT)
        self.assertEqual(result["assigned"],333)
        self.assertIn("points",result["mismatches"][0]["fields"])
        self.assertNotIn("offensive_rating",players[0])
    def test_other_dates_never_inherit_old_ratings(self):
        _,players=self.setup_archive()
        result=populate_verified_ratings(players,"2026-11-03",ROOT)
        self.assertEqual(result["assigned"],0)

if __name__=="__main__":unittest.main()
