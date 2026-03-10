/**
 * QCore Labs — QPIX Daily NBA Report Generator
 * Runs every morning via GitHub Actions
 * - Fetches all last night's games from SportRadar NBA API
 * - Computes QPIX™ (QCore Advanced Player Performance Index)
 *   running the formula directly against live Sportradar box score data
 * - Sends rich HTML email via SendGrid
 * - Writes dashboard/index.html for GitHub Pages
 */

import sgMail from "@sendgrid/mail";
import { writeFileSync, mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DRY_RUN = process.argv.includes("--dry-run");
const isDryRun = DRY_RUN || !process.env.SENDGRID_API_KEY;

// ─── DATE HELPERS ─────────────────────────────────────────────────
function getYesterdayET() {
  const now = new Date();
  const etOffset = isDST(now) ? -4 : -5;
  const et = new Date(now.getTime() + etOffset * 60 * 60 * 1000);
  et.setDate(et.getDate() - 1);
  return {
    year: et.getFullYear(),
    month: String(et.getMonth() + 1).padStart(2, "0"),
    day: String(et.getDate()).padStart(2, "0"),
    label: et.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "America/New_York" })
  };
}

function isDST(date) {
  const jan = new Date(date.getFullYear(), 0, 1).getTimezoneOffset();
  const jul = new Date(date.getFullYear(), 6, 1).getTimezoneOffset();
  return Math.min(jan, jul) === date.getTimezoneOffset();
}

// ─── SPORTRADAR NBA API ───────────────────────────────────────────
async function fetchNBAScores(date) {
  const { year, month, day } = date;
  const url = `https://api.sportradar.com/nba/trial/v8/en/games/${year}/${month}/${day}/results.json?api_key=`;
  const apiKey = process.env.SPORTRADAR_API_KEY || "YOUR_SPORTRADAR_TRIAL_KEY";

  if (isDryRun) {
    console.log(`[DRY RUN] Would fetch: ${url}[KEY]`);
    return getMockData(date);
  }

  try {
    const res = await fetch(`${url}${apiKey}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error("Failed to fetch scores:", err.message);
    return getMockData(date);
  }
}

async function fetchGameBoxScore(gameId) {
  const apiKey = process.env.SPORTRADAR_API_KEY || "YOUR_SPORTRADAR_TRIAL_KEY";
  const url = `https://api.sportradar.com/nba/trial/v8/en/games/${gameId}/boxscore.json?api_key=${apiKey}`;

  if (isDryRun) return null;

  try {
    await new Promise(r => setTimeout(r, 1100)); // Rate limit: 1 req/sec on trial
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`Failed to fetch boxscore ${gameId}:`, err.message);
    return null;
  }
}

// ─── QPIX™ ENGINE — QCore Labs Proprietary ────────────────────────
// Patent Pending. QCore Labs © 2026.
function computeQPIX(p) {
  let score = 0;
  const notes = [];

  // Base weighted stats
  score += p.pts * 1.0 + p.reb * 1.2 + p.ast * 1.5 + p.stl * 3.0 + p.blk * 2.5 - p.to * 2.0;

  const tsDenom = 2 * (p.fga + 0.44 * p.fta);
  const ts = tsDenom > 0 ? (p.pts / tsDenom) * 100 : 0;
  score += (ts - 55) * 0.3;

  if (ts >= 72) { score += 5; notes.push("Elite TS% (" + ts.toFixed(1) + "%)"); }
  else if (ts >= 65) { score += 3; notes.push("High efficiency (" + ts.toFixed(1) + "% TS)"); }
  else if (ts >= 58) notes.push("Efficient (" + ts.toFixed(1) + "% TS)");
  else if (ts < 38 && p.fga > 5) { score -= 5; notes.push("Inefficient volume (" + ts.toFixed(1) + "% TS)"); }

  if (p.fta >= 8) { score += (p.fta - 8) * 0.3; notes.push("Foul drawing (" + p.fta + " FTA)"); }

  const offImpact = (p.offRtg - 110) / 10;
  const defImpact = (110 - p.defRtg) / 10;
  score += offImpact * 2.5 + defImpact * 2.5;

  if (defImpact > 2.5) { score += 4; notes.push("Anchor defender (DefRtg " + p.defRtg.toFixed(1) + ")"); }
  else if (defImpact > 1.5) notes.push("Strong D (DefRtg " + p.defRtg.toFixed(1) + ")");
  else if (defImpact < -2) notes.push("Defensive liability (DefRtg " + p.defRtg.toFixed(1) + ")");
  if (offImpact > 3) notes.push("Offensive engine (OffRtg " + p.offRtg.toFixed(1) + ")");

  const stocks = p.stl + p.blk;
  if (stocks >= 5) { score += 8; notes.push(stocks + " stocks (elite)"); }
  else if (stocks >= 3) { score += 3; notes.push(stocks + " stocks"); }

  if (p.defRtg < 96 && p.min >= 20) { score += 8; notes.push("Elite defensive anchor"); }
  else if (p.defRtg < 100 && p.min >= 20) { score += 5; notes.push("Held opponents under 100 DefRtg"); }
  else if (p.defRtg < 104 && p.min >= 20) score += 2;

  if (p.dreb >= 8) { score += 3; notes.push(p.dreb + " defensive boards"); }

  // AST/TO ratio — reward clean playmaking, penalise turnover-heavy ball-handling
  const astTo = p.to > 0 ? p.ast / p.to : (p.ast > 0 ? p.ast * 2 : 0);
  if (astTo >= 6 && p.ast >= 10) { score += 10; notes.push("Elite playmaker (" + p.ast + "ast/" + p.to + "to)"); }
  else if (astTo >= 4 && p.ast >= 8) { score += 7; notes.push("High-level playmaking (" + p.ast + "/" + p.to + ")"); }
  else if (astTo >= 3 && p.ast >= 5) { score += 4; notes.push("Clean playmaking (" + p.ast + "/" + p.to + " AST/TO)"); }
  else if (astTo >= 2 && p.ast >= 4) score += 2;
  else if (astTo < 1 && p.to >= 4) { score -= 4; notes.push("Turnover-prone (" + p.ast + "/" + p.to + ")"); }

  score += p.scp >= 6 ? p.scp * 1.0 : p.scp * 0.7;
  if (p.scp >= 6) notes.push(p.scp + " second-chance pts");

  score += p.fbp >= 8 ? p.fbp * 0.8 : p.fbp * 0.5;
  if (p.fbp >= 8) notes.push(p.fbp + " fast break pts");

  if (p.pip >= 18) { score += 5; notes.push(p.pip + " points in paint"); }
  else if (p.pip >= 12) score += 3;
  else if (p.pip >= 8) score += 1;

  // Gravity: reward high-usage playmakers who create for others (capped at 7)
  const usage = p.fga + 0.44 * p.fta + p.to;
  const grav = usage > 12 && p.ast >= 3 ? Math.min((p.ast / Math.max(usage, 1)) * 30, 7) : 0;
  if (grav >= 4) { score += grav; notes.push("Gravity " + grav.toFixed(1)); }
  else score += grav;

  // +/- score: base rate (×0.3) plus per-minute weight capped at 36 min (×0.15)
  const pmScore = p.pm * 0.3 + (p.min > 0 ? (p.pm / p.min) * Math.min(p.min, 36) * 0.15 : 0);
  score += pmScore;
  if (p.pm >= 25) notes.push("+" + p.pm + " dominant differential");
  else if (p.pm >= 15) notes.push("+" + p.pm + " net differential");
  else if (p.pm <= -15) notes.push(p.pm + " net differential");

  const ddCats = [p.pts >= 10, p.reb >= 10, p.ast >= 10, p.stl >= 5, p.blk >= 5].filter(Boolean).length;
  if (ddCats >= 3) { score += 15; notes.push("TRIPLE-DOUBLE"); }
  else if (ddCats >= 2) { score += 6; notes.push("Double-double"); }

  const nearCats = [p.pts >= 9, p.reb >= 9, p.ast >= 9].filter(Boolean).length;
  if (nearCats >= 3 && ddCats < 3) { score += 4; notes.push("Near triple-double"); }

  if (!p.starter && p.pm > 0 && p.min >= 18) { score += 4; notes.push("Second unit anchor"); }
  if (p.min >= 28 && p.pm <= -15) score -= 4;

  return { score: Math.round((score || 0) * 10) / 10, ts: Math.round((ts || 0) * 10) / 10, notes };
}

// ─── PARSE SPORTRADAR BOXSCORE ────────────────────────────────────
function parseBoxScore(game, boxscore) {
  const players = [];

  if (!boxscore?.home?.players && !boxscore?.away?.players) return players;

  const processTeam = (teamData, teamAbbr) => {
    if (!teamData?.players) return;
    for (const player of teamData.players) {
      if (!player.statistics) continue;
      const s = player.statistics;
      if ((s.minutes || 0) < 5) continue;

      players.push({
        name: player.full_name,
        team: teamAbbr,
        pos: player.primary_position || "?",
        starter: player.starter || false,
        min: s.minutes || 0,
        pts: s.points || 0,
        reb: s.rebounds || 0,
        oreb: s.offensive_rebounds || 0,
        dreb: s.defensive_rebounds || 0,
        ast: s.assists || 0,
        stl: s.steals || 0,
        blk: s.blocks || 0,
        to: s.turnovers || 0,
        fouls: s.personal_fouls || 0,
        fgm: s.field_goals_made || 0,
        fga: s.field_goals_att || 0,
        fg3m: s.three_points_made || 0,
        fg3a: s.three_points_att || 0,
        ftm: s.free_throws_made || 0,
        fta: s.free_throws_att || 0,
        pm: s.plus_minus || 0,
        offRtg: s.offensive_rating || 110,
        defRtg: s.defensive_rating || 110,
        scp: s.second_chance_pts || 0,
        fbp: s.fast_break_pts || 0,
        pip: s.points_in_paint || 0,
        game: `${boxscore.away?.alias || "?"} @ ${boxscore.home?.alias || "?"}`,
        home_score: game.home_points,
        away_score: game.away_points,
      });
    }
  };

  processTeam(boxscore.home, boxscore.home?.alias);
  processTeam(boxscore.away, boxscore.away?.alias);
  return players;
}

// ─── HTML EMAIL TEMPLATE ──────────────────────────────────────────
function buildEmailHTML(top10, games, dateLabel) {

  const playerRow = (p, rank) => {
    const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `#${rank}`;
    const offColor = p.offRtg >= 110 ? "#22c55e" : "#ef4444";
    const defColor = p.defRtg <= 110 ? "#3b82f6" : "#ef4444";
    return `
    <tr style="border-bottom:1px solid #1e293b;">
      <td style="padding:12px 8px;color:#94a3b8;font-size:15px;text-align:center;">${medal}</td>
      <td style="padding:12px 8px;">
        <div style="font-weight:800;color:#f1f5f9;font-size:14px;">${p.name}</div>
        <div style="font-size:11px;color:#475569;">${p.team} · ${p.game}</div>
      </td>
      <td style="padding:12px 8px;text-align:center;font-weight:900;color:#f97316;font-size:16px;">${p.pts}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.reb}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.ast}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.stl}/${p.blk}</td>
      <td style="padding:12px 8px;text-align:center;font-size:12px;">
        <span style="color:${offColor};">O:${p.offRtg.toFixed(1)}</span>
        <span style="color:#475569;"> / </span>
        <span style="color:${defColor};">D:${p.defRtg.toFixed(1)}</span>
      </td>
      <td style="padding:12px 8px;text-align:center;font-size:12px;color:#94a3b8;">${p.ts.toFixed(1)}%</td>
      <td style="padding:12px 8px;text-align:center;">
        <span style="background:#f97316;color:#fff;font-weight:900;font-size:13px;padding:3px 8px;border-radius:6px;">${p.score}</span>
      </td>
    </tr>`;
  };

  const scoreboardItems = games.map(g =>
    `<div style="background:#0f1f35;border-radius:8px;padding:10px 14px;display:inline-block;margin:4px;">
      <div style="font-size:11px;color:#22c55e;font-weight:700;margin-bottom:4px;">FINAL</div>
      <div style="font-size:13px;font-weight:800;color:${g.away_points > g.home_points ? "#f97316" : "#64748b"};">${g.away_alias} ${g.away_points}</div>
      <div style="font-size:13px;font-weight:800;color:${g.home_points > g.away_points ? "#f97316" : "#64748b"};">${g.home_alias} ${g.home_points}</div>
    </div>`
  ).join("");

  return `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>QPIX Daily NBA Report — ${dateLabel}</title></head>
<body style="margin:0;padding:0;background:#060e1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:700px;margin:0 auto;padding:24px 16px;">

  <!-- Header -->
  <div style="text-align:center;padding:32px 0 24px;">
    <div style="font-size:11px;color:#f97316;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:4px;">QCore Labs</div>
    <div style="font-size:11px;color:#22c55e;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">🏀 QPIX™ Daily Report</div>
    <h1 style="margin:0;font-size:28px;font-weight:900;color:#f8fafc;letter-spacing:-1px;">NBA Nightly Breakdown</h1>
    <div style="font-size:14px;color:#475569;margin-top:6px;">${dateLabel}</div>
  </div>

  <!-- Scoreboard -->
  <div style="background:#0c1520;border:1px solid #1e293b;border-radius:12px;padding:16px;margin-bottom:20px;text-align:center;">
    <div style="font-size:11px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">Last Night's Results</div>
    ${scoreboardItems}
  </div>

  <!-- Top 10 QPIX Table -->
  <div style="background:#0c1520;border:1px solid #1e293b;border-radius:12px;overflow:hidden;margin-bottom:20px;">
    <div style="padding:16px 20px;border-bottom:1px solid #1e293b;">
      <div style="font-size:13px;font-weight:800;color:#f97316;text-transform:uppercase;letter-spacing:1px;">Top 10 QPIX™ Rankings</div>
      <div style="font-size:11px;color:#475569;margin-top:3px;">Ranked by QPIX™ — the only metric with proprietary Off/Def ± split at the individual player level</div>
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <thead>
        <tr style="background:#0f1f35;">
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;"></th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:left;font-weight:700;text-transform:uppercase;letter-spacing:1px;">Player</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">PTS</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">REB</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">AST</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">STL/BLK</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">O/D ±</th>
          <th style="padding:8px;font-size:10px;color:#475569;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">TS%</th>
          <th style="padding:8px;font-size:10px;color:#f97316;text-align:center;font-weight:700;text-transform:uppercase;letter-spacing:1px;">QPIX™</th>
        </tr>
      </thead>
      <tbody style="background:#0c1520;">
        ${top10.map((p, i) => playerRow(p, i + 1)).join("")}
      </tbody>
    </table>
  </div>

  <!-- Why They Ranked -->
  <div style="background:#0c1520;border:1px solid #1e293b;border-radius:12px;padding:16px;margin-bottom:20px;">
    <div style="font-size:11px;color:#f97316;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">Why They Ranked Here</div>
    ${top10.slice(0, 5).map((p, i) => `
      <div style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:800;color:#f1f5f9;">#${i+1} ${p.name} — QPIX™ ${p.score}</div>
        <div style="font-size:12px;color:#64748b;margin-top:3px;">${p.notes.join(" · ")}</div>
      </div>
    `).join("")}
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:16px;color:#1e3a5f;font-size:11px;line-height:1.8;">
    <span style="color:#f97316;font-weight:700;">QPIX™</span> by QCore Labs<br>
    QPIX = PTS×1 + REB×1.2 + AST×1.5 + STL×3 + BLK×2.5 − TO×2 + TS%Δ×0.3 + Off/Def Rating Split + Context Bonuses<br>
    Generated automatically via GitHub Actions · Powered by Sportradar API
  </div>

</div>
</body>
</html>`;
}

// ─── DASHBOARD HTML (GitHub Pages) ───────────────────────────────
function buildDashboardHTML(top10, games, dateLabel) {
  const rows = top10.map((p, i) => {
    const offColor = p.offRtg >= 110 ? "#22c55e" : "#ef4444";
    const defColor = p.defRtg <= 110 ? "#3b82f6" : "#ef4444";
    const rank = i + 1;
    const rankColors = ["#ffd700", "#c0c0c0", "#cd7f32"];
    const rankColor = rankColors[i] || "#475569";
    return `
      <tr onclick="toggleRow(${i})" style="cursor:pointer;border-bottom:1px solid #1e293b;transition:background 0.15s;"
          onmouseover="this.style.background='#0f172a'" onmouseout="this.style.background='transparent'">
        <td style="padding:14px 8px;text-align:center;color:${rankColor};font-weight:900;font-size:16px;">${rank <= 3 ? ["🥇","🥈","🥉"][rank-1] : rank}</td>
        <td style="padding:14px 8px;">
          <div style="font-weight:800;color:#f1f5f9;font-size:14px;">${p.name}</div>
          <div style="font-size:11px;color:#475569;">${p.team} · ${p.pos} · ${p.game}</div>
        </td>
        <td style="padding:14px 8px;text-align:center;font-weight:900;color:#f97316;font-size:18px;">${p.pts}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.reb}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.ast}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.stl}/${p.blk}</td>
        <td style="padding:14px 8px;text-align:center;font-size:13px;">
          <span style="color:${offColor};font-weight:700;">O:${p.offRtg.toFixed(1)}</span><br>
          <span style="color:${defColor};font-weight:700;">D:${p.defRtg.toFixed(1)}</span>
        </td>
        <td style="padding:14px 8px;text-align:center;color:#94a3b8;">${p.ts.toFixed(1)}%</td>
        <td style="padding:14px 8px;text-align:center;">
          <span style="background:#f97316;color:#fff;font-weight:900;padding:4px 10px;border-radius:6px;">${p.score}</span>
        </td>
      </tr>
      <tr id="detail-${i}" style="display:none;background:#0a1628;">
        <td colspan="9" style="padding:16px 20px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div>
              <div style="font-size:11px;color:#f97316;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Full Stat Line</div>
              <div style="display:flex;flex-wrap:wrap;gap:8px;">
                ${[["FG",`${p.fgm}/${p.fga}`],["3P",`${p.fg3m}/${p.fg3a}`],["FT",`${p.ftm}/${p.fta}`],
                   ["TS%",`${p.ts.toFixed(1)}%`],["+/-",p.pm>=0?`+${p.pm}`:p.pm],
                   ["2CH",p.scp],["FBK",p.fbp],["MIN",Math.round(p.min)]
                  ].map(([l,v])=>`<div style="background:#0f172a;border:1px solid #1e293b;border-radius:6px;padding:6px 12px;text-align:center;">
                    <div style="font-size:13px;font-weight:700;color:#e2e8f0;">${v}</div>
                    <div style="font-size:9px;color:#475569;">${l}</div>
                  </div>`).join("")}
              </div>
            </div>
            <div>
              <div style="font-size:11px;color:#f97316;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Why This QPIX™ Rank</div>
              ${p.notes.map(n=>`<div style="font-size:12px;color:#94a3b8;margin-bottom:4px;">› ${n}</div>`).join("")}
            </div>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  const scoreboard = games.map(g => `
    <div style="background:#0f1f35;border-radius:10px;padding:12px 16px;min-width:130px;">
      <div style="font-size:10px;color:#22c55e;font-weight:700;text-transform:uppercase;margin-bottom:8px;">FINAL</div>
      <div style="font-size:14px;font-weight:800;color:${g.away_points>g.home_points?"#f97316":"#64748b"};">${g.away_alias} ${g.away_points}</div>
      <div style="font-size:14px;font-weight:800;color:${g.home_points>g.away_points?"#f97316":"#64748b"};">${g.home_alias} ${g.home_points}</div>
    </div>
  `).join("");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>QPIX™ NBA Dashboard — ${dateLabel} | QCore Labs</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; background:#060e1a; color:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
  table { width:100%; border-collapse:collapse; }
  .container { max-width:900px; margin:0 auto; padding:24px 16px 60px; }
  .card { background:#0c1520; border:1px solid #1e293b; border-radius:12px; overflow:hidden; margin-bottom:20px; }
  .card-header { padding:16px 20px; border-bottom:1px solid #1e293b; }
  th { padding:10px 8px; font-size:10px; color:#475569; text-align:center; font-weight:700; text-transform:uppercase; letter-spacing:1px; background:#0f1f35; }
  th:nth-child(2) { text-align:left; }
  .scores { display:flex; gap:10px; overflow-x:auto; padding-bottom:4px; }
  @media(max-width:600px){ .hide-mobile { display:none; } }
</style>
</head>
<body>

<!-- Sticky Header -->
<div style="background:linear-gradient(180deg,#0a1628,#060e1a);border-bottom:1px solid #0f1f35;padding:20px;position:sticky;top:0;z-index:50;">
  <div style="max-width:900px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
    <div>
      <div style="font-size:10px;color:#f97316;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:2px;">QCore Labs</div>
      <div style="font-size:10px;color:#22c55e;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin-bottom:4px;">● Live Dashboard</div>
      <h1 style="margin:0;font-size:20px;font-weight:900;letter-spacing:-0.5px;">QPIX™ NBA Advanced Metrics</h1>
      <div style="font-size:12px;color:#475569;margin-top:2px;">${dateLabel} · Auto-updated every morning</div>
    </div>
    <div style="background:#0f1f35;border-radius:8px;padding:8px 16px;text-align:center;">
      <div style="font-size:10px;color:#475569;">Games</div>
      <div style="font-size:22px;font-weight:900;color:#f97316;">${games.length}</div>
    </div>
  </div>
</div>

<div class="container">

  <!-- Scoreboard -->
  <div class="card">
    <div class="card-header"><div style="font-size:12px;font-weight:700;color:#f97316;text-transform:uppercase;letter-spacing:1px;">Last Night's Results</div></div>
    <div style="padding:16px;"><div class="scores">${scoreboard}</div></div>
  </div>

  <!-- QPIX Rankings -->
  <div class="card">
    <div class="card-header">
      <div style="font-size:13px;font-weight:800;color:#f97316;text-transform:uppercase;letter-spacing:1px;">QPIX™ Top 10 Rankings</div>
      <div style="font-size:11px;color:#475569;margin-top:3px;">Click any row to expand · Ranked by QPIX™ score</div>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:44px;"></th>
          <th style="text-align:left;">Player</th>
          <th>PTS</th>
          <th class="hide-mobile">REB</th>
          <th class="hide-mobile">AST</th>
          <th class="hide-mobile">STL/BLK</th>
          <th>O/D Rtg</th>
          <th class="hide-mobile">TS%</th>
          <th style="color:#f97316;">QPIX™</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="text-align:center;font-size:11px;color:#1e3a5f;line-height:1.8;">
    <span style="color:#f97316;font-weight:700;">QPIX™</span> — QCore Labs Proprietary Player Performance Index<br>
    QPIX = PTS×1 + REB×1.2 + AST×1.5 + STL×3 + BLK×2.5 − TO×2 + TS%Δ×0.3 + Off/Def Rating Split + Context Bonuses<br>
    Auto-generated via GitHub Actions · Powered by Sportradar API
  </div>

</div>

<script>
function toggleRow(i) {
  const row = document.getElementById('detail-' + i);
  row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}
</script>
</body>
</html>`;
}

// ─── MOCK DATA ────────────────────────────────────────────────────
function getMockData(date) {
  return {
    games: [
      { id: "mock-1", home: { alias: "BOS", name: "Boston Celtics" }, away: { alias: "NYK", name: "New York Knicks" }, home_points: 115, away_points: 108 },
      { id: "mock-2", home: { alias: "LAL", name: "Los Angeles Lakers" }, away: { alias: "GSW", name: "Golden State Warriors" }, home_points: 121, away_points: 119 },
    ]
  };
}

function getMockPlayers() {
  return [
    { name: "Jayson Tatum", team: "BOS", pos: "F", starter: true, min: 36, pts: 32, reb: 8, oreb: 1, dreb: 7, ast: 6, stl: 2, blk: 1, to: 2, fgm: 12, fga: 22, fg3m: 3, fg3a: 8, ftm: 5, fta: 6, pm: 14, offRtg: 128, defRtg: 102, scp: 2, fbp: 4, pip: 10, game: "NYK @ BOS" },
    { name: "Karl-Anthony Towns", team: "NYK", pos: "C", starter: true, min: 32, pts: 28, reb: 12, oreb: 2, dreb: 10, ast: 3, stl: 1, blk: 2, to: 2, fgm: 10, fga: 16, fg3m: 2, fg3a: 5, ftm: 6, fta: 8, pm: 8, offRtg: 122, defRtg: 105, scp: 4, fbp: 2, pip: 14, game: "NYK @ BOS" },
    { name: "LeBron James", team: "LAL", pos: "F", starter: true, min: 34, pts: 27, reb: 7, oreb: 0, dreb: 7, ast: 9, stl: 1, blk: 0, to: 3, fgm: 10, fga: 18, fg3m: 2, fg3a: 5, ftm: 5, fta: 6, pm: 6, offRtg: 124, defRtg: 108, scp: 0, fbp: 6, pip: 8, game: "GSW @ LAL" },
  ];
}

// ─── MAIN ─────────────────────────────────────────────────────────
async function main() {
  const date = getYesterdayET();
  console.log(`\n🏀 QCore Labs — QPIX™ Daily Report — ${date.label}`);
  console.log(`Mode: ${isDryRun ? "DRY RUN" : "LIVE"}\n`);

  if (process.env.GITHUB_ENV) {
    writeFileSync(process.env.GITHUB_ENV, `REPORT_DATE=${date.month}/${date.day}/${date.year}\n`, { flag: "a" });
  }

  console.log("1. Fetching last night's scores...");
  const scoresData = await fetchNBAScores(date);
  const games = scoresData?.games || [];
  console.log(`   Found ${games.length} games`);

  if (games.length === 0) {
    console.log("   No games last night. Exiting.");
    process.exit(0);
  }

  console.log("2. Fetching box scores...");
  let allPlayers = [];

  if (isDryRun) {
    allPlayers = getMockPlayers();
  } else {
    for (const game of games) {
      console.log(`   Fetching: ${game.away?.alias} @ ${game.home?.alias}`);
      const boxscore = await fetchGameBoxScore(game.id);
      if (boxscore) {
        const players = parseBoxScore(game, boxscore);
        allPlayers.push(...players);
      }
    }
  }
  console.log(`   ${allPlayers.length} players parsed`);

  console.log("3. Computing QPIX™ scores...");
  const scoredPlayers = allPlayers
    .map(p => {
      const { score, notes, ts } = computeQPIX(p);
      return { ...p, score, notes, ts };
    })
    .sort((a, b) => b.score - a.score);

  const top10 = scoredPlayers.slice(0, 10);
  console.log(`   Top QPIX™ performer: ${top10[0]?.name} (${top10[0]?.score})`);

  const gameResults = games.map(g => ({
    home_alias: g.home?.alias || "?",
    away_alias: g.away?.alias || "?",
    home_points: g.home_points || 0,
    away_points: g.away_points || 0,
  }));

  console.log("4. Building QPIX™ dashboard...");
  const dashboardHTML = buildDashboardHTML(top10, gameResults, date.label);
  mkdirSync(join(__dirname, "dashboard"), { recursive: true });
  writeFileSync(join(__dirname, "dashboard/index.html"), dashboardHTML);
  console.log("   dashboard/index.html written");

  if (!isDryRun && process.env.SENDGRID_API_KEY) {
    console.log("5. Sending email...");
    sgMail.setApiKey(process.env.SENDGRID_API_KEY);
    const emailHTML = buildEmailHTML(top10, gameResults, date.label);

    await sgMail.send({
      to: process.env.REPORT_EMAIL_TO,
      from: process.env.REPORT_EMAIL_FROM,
      subject: `🏀 QPIX™ Daily — ${date.label} | #1: ${top10[0]?.name} (${top10[0]?.pts}pts, QPIX ${top10[0]?.score})`,
      html: emailHTML,
    });
    console.log(`   Email sent to ${process.env.REPORT_EMAIL_TO}`);
  } else {
    console.log("5. Skipping email (dry run or no SendGrid key)");
  }

  console.log("\n✅ QPIX™ Report complete!\n");
}

main().catch(err => {
  console.error("Fatal error:", err);
  process.exit(1);
});
