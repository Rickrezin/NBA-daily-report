#!/usr/bin/env python3
"""Add explicitly sourced fast-break metrics to published QPIX JSON and CSV.

Does not calculate scores, classify events, or infer zeros.
Use null for unverified fields; preserve all existing raw QPIX values and history.
"""
import argparse
import csv
import io
import json
from pathlib import Path

FIELDS = (
    "fast_break_points",
    "fast_break_assists",
    "fast_break_initiations",
    "fast_break_scoring_opportunities",
    "fast_break_turnovers",
    "fast_break_conversion_rate",
)
NULL_TOKEN = ""
QUALITY = "UNVERIFIED_NOT_OBSERVED_ZERO"

def enrich(json_path, csv_path):
    report = json.loads(json_path.read_text(encoding="utf-8"))
    players = report.get("players")
    if not isinstance(players, list):
        raise ValueError("Missing every-player JSON records")
    original_scores = [(p.get("player_id"), p.get("raw_qpix_shadow"), p.get("qpix_r_shadow"), p.get("category_contributions")) for p in players]
    changed = False
    for p in players:
        for field in FIELDS:
            if field not in p:
                p[field] = None
                changed = True
        if "fast_break_source" not in p:
            p["fast_break_source"] = None
            changed = True
        if "fast_break_quality" not in p:
            p["fast_break_quality"] = QUALITY
            changed = True
        # Never promote a missing metric to a verified observation.
        p.setdefault("fast_break_event_ids", [])
    report.setdefault("metric_definitions", {})
    if "fast_break" not in report["metric_definitions"]:
        report["metric_definitions"]["fast_break"] = {
            "status": "EXPERIMENTAL_PENDING_EVENT_RECONCILIATION",
            "points": "Individual points officially attributed to transition scoring (not yet available)",
            "assists": "Assists on qualifying transition baskets",
            "initiations": "Documented plays initiating a qualifying transition",
            "scoring_opportunities": "Documented transition scoring opportunities",
            "turnovers": "Documented turnovers during a qualifying transition",
            "conversion_rate": "Converted qualifying opportunities / qualifying opportunities",
            "null_policy": "null means missing or unverified; never observed zero",
            "source_policy": "Unverified ESPN play-by-play inference may be stored separately, never as certified values",
        }
        changed = True
    if original_scores != [(p.get("player_id"), p.get("raw_qpix_shadow"), p.get("qpix_r_shadow"), p.get("category_contributions")) for p in players]:
        raise AssertionError("Scoring values changed during enrichment")
    if changed:
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if csv_path.is_file():
        source = csv_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(source))
        columns = list(reader.fieldnames or [])
        rows = list(reader)
        needed = list(FIELDS) + ["fast_break_source", "fast_break_quality"]
        new_columns = columns + [field for field in needed if field not in columns]
        if new_columns != columns or any(row.get("fast_break_quality", "") == "" for row in rows):
            by_id = {str(p.get("player_id")): p for p in players}
            for row in rows:
                p = by_id.get(str(row.get("player_id")))
                if p is None:
                    raise ValueError("CSV player missing from every-player JSON: " + str(row.get("player_id")))
                for field in needed:
                    value = p.get(field)
                    row[field] = NULL_TOKEN if value is None else str(value)
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=new_columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            csv_path.write_text(out.getvalue(), encoding="utf-8")
            changed = True
    elif csv_path.suffix == ".csv":
        raise FileNotFoundError("Expected companion CSV: " + str(csv_path))
    reread = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(reread["players"]) == len(players)
    assert all(all(f in p for f in FIELDS) for p in reread["players"])
    assert all(p["fast_break_quality"] != "VERIFIED" for p in reread["players"] if all(p[f] is None for f in FIELDS))
    print(json.dumps({"report": str(json_path), "players": len(players), "changed": changed, "fields": list(FIELDS)}))
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-et", required=True)
    args = ap.parse_args()
    date = args.date_et
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        ap.error("Invalid YYYY-MM-DD")
    base = Path("data/daily")
    candidate = base / f"{date}.provisional.json"
    if not candidate.exists():
        candidate = base / f"{date}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"No published JSON for {date}")
    companion = candidate.with_suffix(".csv")
    enrich(candidate, companion)

if __name__ == "__main__":
    main()
