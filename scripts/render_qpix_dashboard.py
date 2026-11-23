#!/usr/bin/env python3
"""Build the QPIX HTML dashboard from the most recent date-scoped published report.
Presentation only: never calculates or modifies QPIX scores.
"""
import argparse
import html
import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "daily"
OUT = ROOT / "dashboard" / "index.html"

def esc(value):
    return html.escape(str(value if value is not None else "N/A"), quote=True)

def num(value):
    return "N/A" if value is None else f"{float(value):.1f}"

def find_report():
    candidates = []
    for path in DATA.glob("????-??-??*.json"):
        name = path.name
        if name.endswith(".audit.json"):
            continue
        if name.endswith(".provisional.json"):
            priority = 0
        elif len(name) == len("2026-11-18.json"):
            priority = 1
        else:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("date_et") and isinstance(data.get("games"), list) and isinstance(data.get("players"), list) and isinstance(data.get("leaderboards"), dict):
                candidates.append((data["date_et"], priority, path, data))
        except (ValueError, OSError):
            continue
    if not candidates:
        raise SystemExit("No valid dated QPIX report JSON found; refusing placeholder deployment")
    candidates.sort(key=lambda v: (v[0], v[1]), reverse=True)
    return candidates[0][2], candidates[0][3]

def render():
    path, report = find_report()
    date_et = report["date_et"]
    display_date = date.fromisoformat(date_et).strftime("%A, %B %d, %Y").replace(" 0", " ")
    provisional = "provisional" in path.name or "PROVISIONAL" in str(report.get("status", "")).upper() or "SHADOW" in str(report.get("status", "")).upper()
    status = "PROVISIONAL / SHADOW — NOT OFFICIALLY CERTIFIED" if provisional else "PUBLISHED QPIX RESULTS"
    players = report["players"]
    def score(p, kind="raw"):
        keys = ["raw_qpix_shadow", "raw_qpix"] if kind == "raw" else ["qpix_r_shadow", "qpix_r"]
        if not provisional:
            keys.reverse()
        return next((p[k] for k in keys if p.get(k) is not None), None)

    by_id = {str(p.get("player_id")): p for p in players}
    ranked_players = sorted(players, key=lambda p: float(score(p)) if score(p) is not None else -float("inf"),
                            reverse=True)
    eligible = [p for p in ranked_players if float(p.get("minutes") or 0) > 8]
    lb = report["leaderboards"]
    def get_ranked(key, reverse):
        ranked = [by_id[str(pid)] for pid in lb.get(key, []) if str(pid) in by_id]
        ranked = [p for p in ranked if float(p.get("minutes") or 0) > 8]
        if len(ranked) != min(len(eligible), 10):
            ranked = eligible if reverse else list(reversed(eligible))
        return ranked[:10]

    top = get_ranked("top10", True)
    bottom = get_ranked("bottom10", False)
    games = "".join(
        '<div class="game"><small>FINAL</small><div>' + esc(g.get("away_alias")) + ' <b>' + esc(g.get("away_points")) + '</b></div><div>' + esc(g.get("home_alias")) + ' <b>' + esc(g.get("home_points")) + '</b></div></div>'
        for g in report["games"]
    )
    def leaderboard(items, bottom=False):
        rows = []
        for i, p in enumerate(items, 1):
            cells = (p.get("points"), p.get("rebounds"), p.get("assists"), p.get("2AST"), p.get("weighted_assists"))
            statistics = "".join("<td>" + esc(value) + "</td>" for value in cells)
            rows.append('<tr><td>' + str(i) + '</td><td><strong>' + esc(p.get("name")) + '</strong><span class="sub">' + esc(p.get("team")) + ' · ' + esc(p.get("game")) + '</span></td>' + statistics + '<td class="accent">' + esc(num(score(p))) + '</td>' + ('' if bottom else '<td>' + esc(num(score(p, "r"))) + '</td>') + '</tr>')
        return '<div class="table-wrap"><table><thead><tr><th>#</th><th>Player</th><th>PTS</th><th>REB</th><th>AST</th><th>2AST</th><th>Weighted AST</th><th>RAW</th>' + ('' if bottom else '<th>QPIX-R</th>') + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'

    all_rows = []
    for rank, p in enumerate(ranked_players, 1):
        details = '<details><summary>#' + str(rank) + ' · ' + esc(p.get("name")) + ' — ' + esc(p.get("team")) + ' · ' + esc(num(score(p))) + ' RAW</summary><div class="stats">Minutes: ' + esc(p.get("minutes")) + ' · PTS: ' + esc(p.get("points")) + ' · REB: ' + esc(p.get("rebounds")) + ' · AST: ' + esc(p.get("assists")) + ' · 2AST: ' + esc(p.get("2AST")) + ' · Weighted AST: ' + esc(p.get("weighted_assists")) + ' · STL: ' + esc(p.get("steals")) + ' · BLK: ' + esc(p.get("blocks")) + ' · TO: ' + esc(p.get("turnovers")) + ' · +/-: ' + esc(p.get("plus_minus")) + ' · QPIX-R: ' + esc(num(score(p, "r"))) + '</div></details>'
        all_rows.append(details)

    base = "https://github.com/Rickrezin/NBA-daily-report/blob/main/"
    suffix = ".provisional" if provisional else ""
    report_link = base + "docs/reports/" + date_et + suffix + ".md"
    json_link = base + "data/daily/" + date_et + suffix + ".json"
    csv_link = base + "data/daily/" + date_et + suffix + ".csv"
    html_page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QPIX™ NBA Performance Index | __DATE__</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#060e1a;color:#eef2f7;font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}
header{background:#0b172a;border-bottom:1px solid #243347;padding:24px 18px}.wrap{max-width:1040px;margin:auto}
.kicker{color:#fb923c;font-size:12px;letter-spacing:2px;font-weight:800}h1{margin:6px 0;font-size:clamp(22px,4vw,36px)}
h2{font-size:18px;color:#fb923c;margin:0 0 16px}.muted,.sub{color:#94a3b8}.sub{display:block;font-size:12px}
main{max-width:1040px;margin:auto;padding:22px 16px 56px}.status{font-size:12px;color:#fbbf24;font-weight:700}
.summary{display:flex;gap:20px;flex-wrap:wrap;margin:16px 0}.summary span{background:#111f32;padding:9px 15px;border-radius:8px}
section{background:#0c1524;border:1px solid #243347;border-radius:12px;padding:18px;margin:18px 0}
.scores{display:flex;overflow-x:auto;gap:10px;padding-bottom:8px}.game{min-width:145px;padding:12px;background:#142238;border-radius:8px}
.game small{color:#86efac;font-weight:800}.game div{display:flex;justify-content:space-between;font-size:15px}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:570px}td,th{padding:11px 9px;border-bottom:1px solid #233145;text-align:center}
th{font-size:11px;color:#94a3b8;background:#132139}td:nth-child(2),th:nth-child(2){text-align:left}.accent{color:#fb923c;font-weight:800}
details{border-bottom:1px solid #26354b;padding:9px 4px}summary{cursor:pointer}.stats{padding:10px 5px;color:#cbd5e1;font-size:13px}
a{color:#fdba74}footer{margin:20px 0;color:#94a3b8;font-size:12px}
</style></head><body><header><div class="wrap"><div class="kicker">QCORE LABS · QPIX™</div><h1>NBA Daily Performance Index</h1><div class="muted">__DATE__</div><div class="status">__STATUS__</div></div></header>
<main><div class="summary"><span>__GAMES__ FINAL GAMES</span><span>__PLAYERS__ PLAYERS EVALUATED</span><span>__ELIGIBLE__ LEADERBOARD ELIGIBLE (&gt;8 MIN)</span></div>
<section><h2>Final NBA Scores</h2><div class="scores">__SCORES__</div></section>
<section><h2>RAW QPIX Top 10</h2><p class="muted">RAW determines rank. QPIX-R is the referee-adjusted companion.</p>__TOP__</section>
<section><h2>RAW QPIX Bottom 10</h2>__BOTTOM__</section>
<section><h2>Every Player — Full Slate</h2><p class="muted">Includes minutes-positive players outside the Top/Bottom 10.</p>__ALL__</section>
<section><h2>Sources and Certification</h2><p>__QUALITY__</p><p><a href="__REPORTLINK__">Daily narrative</a> · <a href="__JSONLINK__">Every-player JSON</a> · <a href="__CSVLINK__">Every-player CSV</a></p></section>
<footer>QCore Labs © 2026 · QPIX™ — Because the box score never tells the whole story.</footer></main></body></html>"""
    quality = ("Experimental QCore ratings; provider individual ORtg/DRtg and player-level paint, fast-break and second-chance inputs remain unverified. C6 and parts of C11 cannot be certified. Scores are provisional/shadow, not official." if provisional else "Published report; see the source audit for certification and metric availability.")
    tracking = report.get("data_quality", {}).get("Secondary assists")
    if isinstance(tracking, dict):
        if provisional:
            quality = "Shadow scoring preview. See the source audit for the inputs and coverage."
        quality += f" Secondary-assist coverage: {tracking['verified']}/{tracking['total']} player records."
        quality += " Weighted assists applied to C5." if tracking["score_enabled"] else " Baseline C5 scoring."
    substitutions = {
        "__DATE__": esc(display_date), "__STATUS__": esc(status), "__GAMES__": str(len(report["games"])), "__PLAYERS__": str(len(players)), "__ELIGIBLE__": str(len(eligible)),
        "__SCORES__": games, "__TOP__": leaderboard(top), "__BOTTOM__": leaderboard(bottom, True), "__ALL__": "".join(all_rows),
        "__QUALITY__": esc(quality), "__REPORTLINK__": esc(report_link), "__JSONLINK__": esc(json_link), "__CSVLINK__": esc(csv_link)
    }
    for marker, val in substitutions.items():
        html_page = html_page.replace(marker, val)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_page, encoding="utf-8")
    if display_date not in OUT.read_text(encoding="utf-8"):
        raise SystemExit("Dashboard read-back verification failed")
    print(f"Rendered {OUT}: {date_et}, {len(report['games'])} finals, {len(players)} players, {len(top)} top and {len(bottom)} bottom; provisional={provisional}")

if __name__ == "__main__":
    render()
