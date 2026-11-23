"""Build a C2 shadow sidecar from archived NBA shot groups and season rates."""

import argparse
import json
from pathlib import Path


SHOT_VALUES = {"2PT under 10 ft": 2, "2PT at least 10 ft": 2, "3PT": 3}
PRESSURES = ("contested", "open")


def build_sidecar(players, calibration, season):
    groups = calibration["seasons"][season]["groups"]
    rates = {}
    for group in SHOT_VALUES:
        cells = groups[group]
        pooled = sum(cells[p]["makes"] for p in PRESSURES) / sum(cells[p]["attempts"] for p in PRESSURES)
        rates[group] = {pressure: pooled - cells[pressure]["fg_rate"] for pressure in PRESSURES}

    rows = []
    for player in players:
        key = f"{player['game_id']}/{player['player_id']}"
        if player["status"] not in ("reconciled", "partial_classification"):
            raise ValueError(f"NBA shot classification unavailable or unreconciled for {key}")
        official = player["official_fga"]
        adjustment = 0.0
        classified = 0
        for group, value in SHOT_VALUES.items():
            for pressure in PRESSURES:
                attempts = player["cells"][group][pressure]["attempts"]
                if type(attempts) is not int or attempts < 0:
                    raise ValueError(f"Invalid classified attempts for {key}")
                classified += attempts
                adjustment += value * attempts * rates[group][pressure]
        if classified != player["classified_attempts"] or classified > official:
            raise ValueError(f"Classified attempts do not reconcile for {key}")
        rows.append({"game_id": player["game_id"], "player_id": player["player_id"], "fga": official,
                     "classified_fga": classified, "points_adjustment": adjustment})
    return {"calibration_season": season, "players": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shot-groups", required=True, type=Path)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--date", required=True, help="Eastern date in YYYY-MM-DD format")
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = [row for row in json.loads(args.shot_groups.read_bytes())["players"] if row["date_et"] == args.date]
    if not rows:
        parser.error(f"no shot-group rows for {args.date}")
    result = build_sidecar(rows, json.loads(args.calibration.read_bytes()), args.season)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, allow_nan=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
