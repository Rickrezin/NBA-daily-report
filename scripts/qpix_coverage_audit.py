#!/usr/bin/env python3
"""QPIX shadow-run per-category input coverage report.

Reads the canonical pre-scoring QCore archive; does not modify scoring data.
Missing fields are unavailable, not zero. Emits a Markdown table and JSON audit
so a failed completeness gate still yields actionable, per-game diagnostics.
"""
import argparse
import json
from pathlib import Path

CATEGORIES = {
    "C1 Base production": ("points", "rebounds", "assists", "steals", "blocks", "turnovers"),
    "C2 Shooting efficiency": ("points", "fga", "fta", "ftm"),
    "C3 Individual O/D": ("offensive_rating", "defensive_rating"),
    "C4 Defensive activity": ("steals", "blocks", "defensive_rebounds", "defensive_rating", "minutes"),
    "C5 Playmaking": ("assists", "turnovers"),
    "C6 Offensive context": ("points_in_paint", "fast_break_points", "second_chance_points"),
    "C7 Gravity": ("fga", "fta", "points", "assists"),
    "C8 Environment +/-": ("plus_minus",),
    "C9 Multi-category": ("points", "rebounds", "assists", "steals", "blocks"),
    "C10 Fatigue": ("minutes", "points", "fga", "fta"),
    "C11 Momentum": ("points", "plus_minus", "fast_break_points"),
    "C12 Bench anchor": ("minutes", "plus_minus"),
    "C13 QPIX-R": ("fta", "ftm"),
}

def coverage(snapshot):
    players=snapshot.get("players",[])
    games=snapshot.get("games",[])
    if not players or not games:
        raise ValueError("No canonical players or games")
    total=len(players)
    report={"date_et":snapshot["date_et"],"players":total,"games":len(games),"categories":[],"games_detail":[]}
    def present(row,key):
        return key in row and row[key] is not None
    for category,fields in CATEGORIES.items():
        complete=sum(all(present(p,key) for key in fields) for p in players)
        counts={key:sum(present(p,key) for p in players) for key in fields}
        report["categories"].append({"category":category,"present":complete,"unavailable":total-complete,"field_coverage":counts})
    for game in games:
        rows=[p for p in players if str(p.get("game_id"))==str(game["game_id"])]
        g={"game_id":game["game_id"],"matchup":f'{game["away_alias"]} @ {game["home_alias"]}',"players":len(rows),"categories":{}}
        for category,fields in CATEGORIES.items():
            g["categories"][category]={"present":sum(all(present(p,key) for key in fields) for p in rows),"unavailable":sum(not all(present(p,key) for key in fields) for p in rows)}
        report["games_detail"].append(g)
    return report

def markdown(report):
    out=[f'## QPIX source coverage — {report["date_et"]}',f'**{report["games"]} games | {report["players"]} participants**',
         "", "| Category | Available | Unavailable |", "|---|---:|---:|"]
    for item in report["categories"]:
        out.append(f'| {item["category"]} | {item["present"]}/{report["players"]} | {item["unavailable"]} |')
    out+=["", "### C3 / C6 by game", "| Matchup | Players | C3 complete | C6 complete |", "|---|---:|---:|---:|"]
    for g in report["games_detail"]:
        out.append(f'| {g["matchup"]} | {g["players"]} | {g["categories"]["C3 Individual O/D"]["present"]} | {g["categories"]["C6 Offensive context"]["present"]} |')
    out+=["", "Availability means that all required player fields are present; it does not certify source methodology or event-level correctness.",
          "C8/C11/C12 also depend on verified game context; C13 may use the authorized historical/positional FTA fallback.",
          "Missing C6 values are **unavailable**, not observed zero."]
    return "\n".join(out)+"\n"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--root",default=".")
    args=parser.parse_args()
    root=Path(args.root)
    source=root/"data"/"historical"/"qpix_input"/(args.date+".json")
    if not source.exists():
        report={"date_et":args.date,"status":"source_archive_unavailable",
                "reason":"Collector did not produce a canonical input JSON; see preceding workflow logs.",
                "expected_archive":str(source),"games":0,"players":0,
                "categories":[],"games_detail":[]}
        audit=root/"data"/"historical"/"qpix_audits"/(args.date+".coverage.json")
        audit.parent.mkdir(parents=True,exist_ok=True)
        audit.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        summary=(f"## QPIX source coverage — {args.date}\n"
                 "**Pre-scoring archive unavailable.** The source collector failed before "
                 "producing the canonical player input; inspect the workflow logs.\n")
        print(summary)
        import os
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as stream:
                stream.write("\n"+summary)
        return 0
    report=coverage(json.loads(source.read_text(encoding="utf-8")))
    audit=root/"data"/"historical"/"qpix_audits"/(args.date+".coverage.json")
    audit.parent.mkdir(parents=True,exist_ok=True)
    audit.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    summary=markdown(report)
    print(summary)
    import os
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("\n"+summary)
    return 0

if __name__=="__main__":raise SystemExit(main())
