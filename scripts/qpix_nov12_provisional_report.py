#!/usr/bin/env python3
"""Publish Nov 12 Facebook-ready provisional report from fully scored source-audited player JSON."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATE='2026-11-12'
j=json.loads((ROOT/f'data/daily/{DATE}.provisional.json').read_text())
audit_path=ROOT/f'docs/reports/{DATE}.audit.json'
audit=json.loads(audit_path.read_text())
players=j['players']
byid={str(p['player_id']):p for p in players}
top=[byid[str(i)] for i in j['leaderboards']['top10']]
bottom=[byid[str(i)] for i in j['leaderboards']['bottom10']]
assert len(j['games'])==4 and len(players)==90
assert len(top)==10 and len(bottom)==10 and all(p['minutes']>8 for p in top+bottom)
assert top[0]['name']=='Cade Cunningham' and top[0]['raw_qpix_shadow']==124.4
assert j['engine']['formulas_modified'] is False and j['engine']['git_blob_sha']=='390833f45ee5191092813647f0735f1598cfeab1'
audit['score_coverage']=j['coverage']
audit['score_engine']=j['engine']
audit['missing_field_policy']=j['quality']
audit['full_participant_records']=len(players)
audit['starter_context_mismatches']=j['starter_context_mismatches']
audit['top10_ids']=j['leaderboards']['top10']
audit['bottom10_ids']=j['leaderboards']['bottom10']
audit_path.write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
names={'TOR':'Toronto Raptors','PHI':'Philadelphia 76ers','DET':'Detroit Pistons','WAS':'Washington Wizards','DAL':'Dallas Mavericks','MIN':'Minnesota Timberwolves','CHA':'Charlotte Hornets','PHX':'Phoenix Suns'}
def fmt(p):return f"{p['raw_qpix_shadow']:.1f}"
def rfmt(p):return f"{p['qpix_r_shadow']:.1f}"
def box(p):return f"{p['points']} points, {p['rebounds']} rebounds, {p['assists']} assists, {p['steals']} steals, {p['blocks']} blocks and {p['turnovers']} turnovers in {p['minutes']:.0f} minutes"
lines=[
'QCORE LABS QPIX™ NBA DAILY PERFORMANCE INDEX',
'',
'Thursday, November 12, 2026',
f"4 FINAL GAMES | {len(players)} PLAYERS EVALUATED | {j['coverage']['eligible_gt8']} LEADERBOARD-ELIGIBLE",
'PROVISIONAL / SHADOW — NOT OFFICIALLY CERTIFIED','',
'NBA FINAL SCORES','']
for g in j['games']:
    lines.append(f"{names[g['away_alias']]} {g['away_points']} — {names[g['home_alias']]} {g['home_points']}")
lines+=['','CADE CUNNINGHAM MAKES HISTORY — 52 POINTS, 11 ASSISTS AND ZERO TURNOVERS','',
"Cade Cunningham authored the night's defining performance as Detroit outlasted Washington 144–140 in DOUBLE OVERTIME. He scored a career-high 52 points on 16-for-25 shooting, handed out 11 assists, grabbed five rebounds, recorded a steal and a block, and did not commit a single turnover in 48 minutes. He shot 17-for-18 at the foul line. His 124.4 provisional RAW QPIX led all 90 players evaluated; his referee-adjusted companion QPIX-R was 111.0.",
'',
'QPIX TOP 10 — PROVISIONAL RAW | QPIX-R COMPANION','']
for i,p in enumerate(top,1):
    lines.append(f"{i}. {p['name']} ({p['team']}) — RAW {fmt(p)} | QPIX-R {rfmt(p)}")
lines+=['','THE PERFORMANCES BEHIND THE NUMBERS','']
for name,title,comment in [
('Bones Hyland','BONES HYLAND — MINNESOTA',"Hyland was explosive in Minnesota's 133–94 demolition of Dallas. His 24 points came on 7-for-10 shooting with eight assists, three rebounds, two steals and just one turnover. He finished +15 in only 23 minutes. His 92.7 RAW was second overall, a reminder that per-minute productivity and efficient offense can stand out even in a short stint."),
('Ausar Thompson','AUSAR THOMPSON — DETROIT',"Thompson delivered a triple-double with 17 points, 11 rebounds and 11 assists, plus THREE steals and THREE blocks. That is six combined defensive stocks on a night when Detroit needed every contribution to survive double overtime. His 88.2 RAW placed third despite his team barely winning the possession battle."),
('Tyrese Maxey','TYRESE MAXEY — PHILADELPHIA',"Maxey paced Philadelphia's 123–112 comeback against Toronto with 27 points, eight assists, two steals and a block on 8-for-13 shooting. His +1 differential barely hinted at his scoring and playmaking role. The combination earned 78.2 RAW and fourth place."),
('Trae Young','TRAE YOUNG — WASHINGTON',"Young led Washington with 37 points and 14 assists in the two-overtime defeat. He made all 17 free throws he attempted and finished +7, but his four turnovers and heavily foul-line-driven scoring helped push his QPIX-R down to 67.5 from a 77.8 RAW. The two ratings are deliberately kept distinct."),
('Devin Booker','DEVIN BOOKER — PHOENIX',"Booker supplied 30 points, seven assists, three steals and a block on 12-for-20 shooting as Phoenix edged Charlotte 101–96. His 73.0 RAW earned ninth, showing that defensive activity and facilitating can help distinguish a scoring-led night."),
('Anthony Davis','ANTHONY DAVIS — WASHINGTON',"Davis paired 30 points with 15 rebounds, four assists and a steal in 44 minutes. He shot 13-for-21 and finished +3 in Washington's narrow double-overtime loss. His 72.3 RAW was good for tenth: an excellent individual scoring and rebounding display on the losing side.")
]:
    p=next(x for x in players if x['name']==name)
    lines += [title,'',comment,'']
lines+=['QPIX BOTTOM 10 — PROVISIONAL RAW','']
for i,p in enumerate(bottom,1):
    lines.append(f"{i}. {p['name']} ({p['team']}) — RAW {fmt(p)}")
lines+=['','THE OTHER END OF THE INDEX','',
"Morez Johnson Jr. managed no points on 0-for-4 shooting with two rebounds and two turnovers in 13 minutes during Dallas's 39-point defeat. His -29.1 RAW was the lowest qualifying score. Washington's Bub Carrington had two points on 1-for-6 shooting with two assists and no rebounds, finishing at -27.0. Toronto's Allen Graves went scoreless in 13 minutes, while Dallas's Walter Clayton Jr. scored five points in 22 minutes.",
'',
'These ratings evaluate the statistical production of one game; a poor score does not define a player or his season. All Top 10 and Bottom 10 placements use the strict greater-than-eight-minute eligibility rule.',
'',
'WHY QPIX LOOKS BEYOND POINTS','',
"Cunningham combined 52 points with 11 assists and no turnovers. Thompson's 17-point triple-double carried six stocks. Hyland reached second with only 23 minutes of work. Meanwhile, a 30-point scorer can rank below players who contribute more through defense, rebounding, playmaking or possession control. QPIX does not simply sort the scoring column. RAW determines the rankings; QPIX-R is a separately adjusted companion, and QPIXM is still experimental.",
'',
'DATA QUALITY / PUBLICATION','',
f"PROVISIONAL SHADOW ONLY: all four Eastern-day finals and all {len(players)} original ESPN participant records were reconciled for scoring, minutes, plus/minus and starter identities. The exact, unchanged main-branch JavaScript category formulas were executed for all players. Experimental November 5 QCore Q-OffR/Q-DefR estimates were available for {j['coverage']['qcore_both']} of {len(players)}, not provider-verified individual ratings. NBA Advanced/Misc V3 attempts timed out, and LiveData returned 403. Player-level paint, fast-break and second-chance points remain unavailable; C6 is NOT observed zero and C11 lacks verified fast-break context. The engine classified {j['coverage']['starter_context_mismatches']} players differently from observed starter/reserve status; sensitivity scores remain in the JSON. Results are not official certified RAW rankings.",
'',
'QCore Labs © 2026',
'QPIX™ — Because the box score never tells the whole story.',
'']
out=ROOT/f'docs/reports/{DATE}.provisional.md'
out.write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'wrote':str(out),'lines':len(lines),'top':[(p['name'],p['raw_qpix_shadow']) for p in top],'bottom':[(p['name'],p['raw_qpix_shadow']) for p in bottom]},ensure_ascii=False))
