"""Durable, atomic collection checkpoints for a QPIX shadow run.

Partial records are not a published QPIX score or certified final archive.
They are diagnostic snapshots created on entry and updated after each source
step. The final input archive is written separately by qpix_source_archive.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

class CollectionCheckpoint:
    def __init__(self, root, date_et):
        self.path=Path(root)/"data"/"historical"/"qpix_input"/(date_et+".partial.json")
        self.state={
            "schema_version":1,
            "date_et":date_et,
            "status":"collecting",
            "started_at_utc":datetime.now(timezone.utc).isoformat(),
            "updated_at_utc":None,
            "expected_game_ids":[],
            "completed_games":[],
            "source_audits":{},
            "stage":"started",
            "failure":None
        }
        self.save()
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.state["updated_at_utc"]=datetime.now(timezone.utc).isoformat()
        # The destination is atomically replaced so a crash cannot leave torn JSON.
        fd,tmp=tempfile.mkstemp(prefix=".qpix-",suffix=".json",dir=str(self.path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump(self.state,stream,indent=2,ensure_ascii=False,allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def stage(self, stage, **fields):
        self.state["stage"]=stage
        self.state.update(fields)
        self.save()
    def game(self, game, players):
        record={
            "game_id":game["game_id"],
            "away_alias":game["away_alias"],
            "home_alias":game["home_alias"],
            "away_points":game["away_points"],
            "home_points":game["home_points"],
            "player_count":len(players),
            "source":game.get("source"),
            "players":players
        }
        existing={str(g["game_id"]):i for i,g in enumerate(self.state["completed_games"])}
        gid=str(game["game_id"])
        if gid in existing:self.state["completed_games"][existing[gid]]=record
        else:self.state["completed_games"].append(record)
        self.stage("collecting_games")
    def fail(self, error):
        self.state["status"]="failed"
        self.state["failure"]={"type":type(error).__name__,"message":str(error)[:2000],
                               "time_utc":datetime.now(timezone.utc).isoformat()}
        self.save()
    def done(self, archive_path, sha256):
        self.state["status"]="complete"
        self.state["stage"]="source_validation_complete"
        self.state["canonical_archive"]={"path":str(archive_path),"sha256":sha256}
        self.save()
