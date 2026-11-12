#!/usr/bin/env python3
"""Render copy-ready provisional Nov 11 social narrative and source audit, no engine edits."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DATE='2026-11-11'
j=json.loads((ROOT/f'data/daily/{DATE}.provisional.json').read_text())
audit_path=ROOT/f'docs/reports/{DATE}.audit.json'
a=json.loads(audit_path.read_text());p=j['players'];ps={str(x['player_id']):x for x in p}
top=[ps[str(x)] for x in j['leaderboards']['top10']]
bottom=[ps[str(x)] for x in j['leaderboards']['bottom10']]
assert len(p)==223 and len(top)==10 and len(bottom)==10 and all(x['minutes']>8 for x in top+bottom)
assert top[0]['name']=='Victor Wembanyama' and top[0]['raw_qpix_shadow']==104.2
a['score_coverage']=j['coverage'];a['score_engine']=j['engine'];a['missing_field_policy']=j['quality']
a['full_participant_records']=len(p)
a['top10_identifiers']=j['leaderboards']['top10'];a['bottom10_identifiers']=j['leaderboards']['bottom10']
a['context_mismatches']=j['starter_context_mismatches']
a['verified_nba_game_crosswalk']={
 '401909966':'0022600217','401909967':'0022600218','401909968':'0022600219','401909969':'0022600220',
 '401909970':'0022600221','401909971':'0022600222','401909972':'0022600223','401909973':'0022600224',
 '401909974':'0022600225','401909975':'0022600226'}
f=ROOT/'data/nba_v3/audit.json'
if f.exists():
 probe=json.loads(f.read_text());a['provider_probes']=probe
 a['provider_probe_summary']={'success':sum(z.get('status')=='ok' for z in probe),'failed':sum(z.get('status')=='failed' for z in probe)}
audit_path.write_text(json.dumps(a,indent=2)+'\n')
name={'WAS':'Washington Wizards','IND':'Indiana Pacers','CLE':'Cleveland Cavaliers','NYK':'New York Knicks','BOS':'Boston Celtics','TOR':'Toronto Raptors','SAS':'San Antonio Spurs','CHI':'Chicago Bulls','DEN':'Denver Nuggets','MEM':'Memphis Grizzlies','LAL':'Los Angeles Lakers','MIL':'Milwaukee Bucks','BKN':'Brooklyn Nets','NOP':'New Orleans Pelicans','ORL':'Orlando Magic','UTA':'Utah Jazz','GSW':'Golden State Warriors','HOU':'Houston Rockets','OKC':'Oklahoma City Thunder','POR':'Portland Trail Blazers'}
def score(x):return f"{x['raw_qpix_shadow']:.1f}"
def rate(x):return f"{x['qpix_r_shadow']:.1f}"
def box(x):
 return f"{x['points']} points, {x['rebounds']} rebounds, {x['assists']} assists, {x['steals']} steals, {x['blocks']} blocks and {x['turnovers']} turnovers in {x['minutes']} minutes"
lines=[
 'QCORE LABS QPIX™ NBA DAILY PERFORMANCE INDEX',
 '',
 'Wednesday, November 11, 2026',
 f"10 FINAL GAMES | {len(p)} PLAYERS EVALUATED | {j['coverage']['eligible_gt8']} LEADERBOARD-ELIGIBLE",
 'PROVISIONAL / SHADOW — NOT AN OFFICIALLY CERTIFIED QPIX RUN','',
 'NBA FINAL SCORES',''
]
for g in j['games']:lines.append(f"{name[g['away_alias']]} {g['away_points']} — {name[g['home_alias']]} {g['home_points']}")
lines.extend(['','WEMBANYAMA TAKES THE NIGHT — TWO-WAY DOMINANCE IN SAN ANTONIO’S WIN','',
 "Victor Wembanyama didn't need the game's highest scoring total to take the top spot. In San Antonio's 124–119 victory over Chicago, he finished with 32 points, nine rebounds, five blocks, two steals and a +29 differential across 32 minutes. Shooting 13-for-18 and giving the Spurs defensive resistance around the basket, he led all 223 players at 104.2 provisional RAW QPIX, with 105.7 QPIX-R.",
 '',
 'QPIX TOP 10 — PROVISIONAL RAW (QPIX-R SHOWN SEPARATELY)',''])
for i,x in enumerate(top,1):
 lines.append(f"{i}. {x['name']} ({x['team']}) — RAW {score(x)} | QPIX-R {rate(x)} | Q-OffR {x['qcore_q_offr']:.2f} | Q-DefR {x['qcore_q_defr']:.2f}")
lines.extend(['','THE PERFORMANCES BEHIND THE NUMBERS',''])
stories=[
 ('Nikola Jokic','NIKOLA JOKIC — DENVER'),
 ('Dylan Harper','DYLAN HARPER — SAN ANTONIO'),
 ('Alperen Sengun','ALPEREN SENGUN — HOUSTON'),
 ('Karl-Anthony Towns','KARL-ANTHONY TOWNS — NEW YORK'),
 ('Fred VanVleet','FRED VANVLEET — HOUSTON'),
 ('Neemias Queta','NEEMIAS QUETA — BOSTON')]
paragraphs={
 'Nikola Jokic':"Denver's 123–118 win over Memphis featured another orchestration from Jokic: 27 points, 11 rebounds and eight assists, with one steal, one block and just one turnover. He shot 10-for-16 and finished +5. That all-around line earned 97.7 RAW, second overall.",
 'Dylan Harper':"Harper filled the box score beside Wembanyama: 18 points, six rebounds, 10 assists, four steals and a block, without a single turnover in 36 minutes. His +19 differential helped San Antonio get past Chicago, and his 87.3 RAW ranked third.",
 'Alperen Sengun':"Sengun nearly delivered a triple-double as Houston defeated Golden State 115–108: 19 points, 13 rebounds, nine assists, one steal and a block. He shot 8-for-14 and finished +11. His 82.7 RAW reflected his production as both a scorer and facilitator.",
 'Karl-Anthony Towns':"The Knicks fell 115–107 to Cleveland, but Towns produced 21 points, 11 rebounds and eight assists on 7-for-11 shooting. Despite the loss, the production and efficiency put him sixth in the provisional index at 79.3 RAW. The score measures his individual night, not his team's result alone.",
 'Fred VanVleet':"VanVleet helped set Houston's winning tempo with 18 points, six assists, three steals and zero turnovers. He hit four three-pointers, shot 6-for-9 overall and finished +25 against the Warriors. His 77.9 RAW placed him eighth.",
 'Neemias Queta':"Queta posted 11 points, 13 rebounds, three assists, a steal and three blocks in Boston's 98–93 win at Toronto. His +27 differential and defensive presence earned him 72.7 RAW and a top-ten spot despite a modest scoring total."
}
for key,heading in stories:lines.extend([heading,'',paragraphs[key],''])
lines.extend(['QPIX BOTTOM 10 — PROVISIONAL RAW',''])
for i,x in enumerate(bottom,1):lines.append(f"{i}. {x['name']} ({x['team']}) — RAW {score(x)}")
lines.extend(['','THE OTHER END OF THE INDEX','',
 'Cameron Carr finished with no points on 0-for-3 shooting, two rebounds and two turnovers in 13 minutes for the Lakers. His -34.4 provisional RAW was the lowest qualifying score of the night.',
 'Gui Santos went scoreless in 12 minutes for Golden State, finishing with three rebounds, an assist, a block and four turnovers. Bub Carrington played 10 minutes without scoring or recording a rebound or assist. Those isolated games landed both near the bottom.',
 'The lower rankings also included Aaron Nesmith (two points on 1-for-6 shooting), Tari Eason (six points on 2-for-11) and Mikal Bridges (two points in 17 minutes). These are single-game statistical evaluations, not judgments about any player’s standing or long-term value.',
 '',
 'THE QPIX TAKEAWAY','',
 'Wembanyama’s 32 points were only part of his leading score: five blocks, two steals, efficient shooting and an enormous on-court differential mattered too. Jokic nearly posted a triple-double; Harper supplied ten assists and four steals; Queta controlled the glass and protected the rim. Meanwhile, a player can score efficiently in a loss and still rate highly.',
 'That is the point of QPIX: quantify total measurable game impact rather than reward the points column alone. The RAW score determines the rankings; QPIX-R is a companion, not a replacement. Q-OffR and Q-DefR are separately labeled experimental QCore estimates. QPIXM is being evaluated independently and is not part of this official RAW ordering.',
 '',
 'DATA QUALITY / PUBLICATION','',
 'Provisional shadow results only. All 10 final games and 223 participant records were reconciled to original ESPN box-score captures; both leaderboards require strictly more than eight minutes. The unchanged main-branch scoring functions were executed for all players, using 212 complete experimental QCore offensive/defensive estimate pairs, with 11 unavailable Q-OffR estimates. Independent provider individual ratings remain unavailable; player-level points in the paint, fast-break points and second-chance points are missing, so C6 is unverified and C11 is incomplete. Thirty-one engine starter/reserve classifications disagree with observed ESPN starters; the underlying engine has not been edited, and starter-corrected sensitivity scores are retained separately. These factors prohibit official certification.',
 '',
 'QCore Labs © 2026',
 'QPIX™ — Because the box score never tells the whole story.',''])
out=ROOT/f'docs/reports/{DATE}.provisional.md'
out.write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'wrote':str(out),'lines':len(lines),'audit':str(audit_path),'leaderboard':[[x['name'],x['raw_qpix_shadow']] for x in top]}))
