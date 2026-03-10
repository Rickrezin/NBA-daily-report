/**
 * QCore Labs — QPIX Daily NBA Report Generator
 * Runs every morning via GitHub Actions
 * - Fetches all last night's games from SportRadar NBA API
 * - Computes QPIX™ (QCore Advanced Player Performance Index)
 *   with proprietary Off/Def +/- split — unique to QCore Labs
 * - Calls Claude for AI analysis
 * - Sends rich HTML email via SendGrid
 * - Writes dashboard/index.html for GitHub Pages
 */

import Anthropic from "@anthropic-ai/sdk";
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
// The only player metric separating offensive and defensive +/-
// at the individual level. Patent Pending. QCore Labs © 2026.
function computeQPIX(p) {
  let score = 0;
  const notes = [];

  // Base weighted stats
  score += p.points * 1.0;
  score += p.rebounds * 1.2;
  score += p.assists * 1.5;
  score += p.steals * 3.0;
  score += p.blocks * 2.5;
  score -= p.turnovers * 2.0;

  // True Shooting bonus/penalty vs 55% baseline
  const ts = computeTS(p);
  const tsDelta = (ts - 55) * 0.3;
  score += tsDelta;
  if (ts >= 65) notes.push(`Elite efficiency (${ts.toFixed(1)}% TS)`);
  if (ts < 38 && p.fga > 5) { score -= 4; notes.push(`Poor efficiency (${ts.toFixed(1)}% TS)`); }

  // ── QPIX PROPRIETARY: Off/Def +/- Split ──────────────────────
  // Separates individual offensive and defensive rating contribution
  // No other public metric does this at the player level
  const offImpact = (p.offensive_rating - 110) / 10;
  const defImpact = (110 - p.defensive_rating) / 10;
  score += offImpact * 2;
  score += defImpact * 2;

  if (defImpact > 1.5) notes.push(`Strong defensive impact (Def±: ${p.defensive_rating?.toFixed(1)})`);
  if (offImpact > 2)  notes.push(`Dominant offensive presence (Off±: ${p.offensive_rating?.toFixed(1)})`);
  // ─────────────────────────────────────────────────────────────

  // Context bonuses
  if (p.second_chance_points > 0) {
    score += p.second_chance_points * 0.8;
    notes.push(`${p.second_chance_points} second-chance pts`);
  }
  if (p.fast_break_points > 0) {
    score += p.fast_break_points * 0.5;
    notes.push(`${p.fast_break_points} fast break pts`);
  }

  // Assist quality
  const astToRatio = p.turnovers > 0 ? p.assists / p.turnovers : p.assists;
  if (astToRatio >= 4 && p.assists >= 6) {
    score += 5;
    notes.push(`Elite playmaking ratio (${p.assists}/${p.turnovers} AST/TO)`);
  }

  // Raw +/-
  score += (p.plus_minus || 0) * 0.4;
  if (p.plus_minus >= 15) notes.push(`+${p.plus_minus} net differential`);

  // Defensive hold bonus
  if (p.defensive_rating < 98 && p.minutes >= 20) {
    score += 6;
    notes.push(`Held opponents under 98 DefRtg`);
  }

  // Multi-category bonuses
  const ddCats = [p.points >= 10, p.rebounds >= 10, p.assists >= 10].filter(Boolean).length;
  if (ddCats >= 3) { score += 12; notes.push("TRIPLE-DOUBLE"); }
  else if (ddCats >= 2) { score += 5; notes.push("Double-double"); }

  // Defensive stocks
  if ((p.steals + p.blocks) >= 4) {
    score += 4;
    notes.push(`${p.steals + p.blocks} combined stocks`);
  }

  return {
    score: Math.round(score * 10) / 10,
    notes,
    offPlusMinus: Math.round(offImpact * 10) / 10,
    defPlusMinus: Math.round(defImpact * 10) / 10,
    ts: Math.round(ts * 10) / 10
  };
}

function computeTS(p) {
  const denom = 2 * (p.fga + 0.44 * p.fta);
  return denom > 0 ? (p.points / denom) * 100 : 0;
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
        position: player.primary_position || "?",
        minutes: s.minutes || 0,
        points: s.points || 0,
        rebounds: s.rebounds || 0,
        offensive_rebounds: s.offensive_rebounds || 0,
        defensive_rebounds: s.defensive_rebounds || 0,
        assists: s.assists || 0,
        steals: s.steals || 0,
        blocks: s.blocks || 0,
        turnovers: s.turnovers || 0,
        fouls: s.personal_fouls || 0,
        fgm: s.field_goals_made || 0,
        fga: s.field_goals_att || 0,
        fg3m: s.three_points_made || 0,
        fg3a: s.three_points_att || 0,
        ftm: s.free_throws_made || 0,
        fta: s.free_throws_att || 0,
        plus_minus: s.plus_minus || 0,
        offensive_rating: s.offensive_rating || 110,
        defensive_rating: s.defensive_rating || 110,
        second_chance_points: s.second_chance_pts || 0,
        fast_break_points: s.fast_break_pts || 0,
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

// ─── AI ANALYSIS ──────────────────────────────────────────────────
async function getAIAnalysis(top10, dateLabel) {
  if (!process.env.ANTHROPIC_API_KEY) {
    return "AI analysis unavailable — set ANTHROPIC_API_KEY in GitHub secrets.";
  }

  const client = new Anthropic();
  const playerSummary = top10.slice(0, 5).map((p, i) =>
    `${i + 1}. ${p.name} (${p.team}): ${p.points}pts/${p.rebounds}reb/${p.assists}ast, TS%: ${p.ts.toFixed(1)}, Off±: ${p.offPlusMinus > 0 ? "+" : ""}${p.offPlusMinus}, Def±: ${p.defPlusMinus > 0 ? "+" : ""}${p.defPlusMinus}, QPIX: ${p.score}`
  ).join("\n");

  const msg = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 500,
    messages: [{
      role: "user",
      content: `You are an elite NBA analyst writing a sharp morning briefing for ${dateLabel}. Based on last night's top QPIX performers (QCore Labs' proprietary metric that uniquely separates offensive and defensive +/- at the individual player level), give a crisp 4-5 sentence analysis. Focus on: the best two-way performer, any standout efficiency story, a player who impacted winning that the box score undersells, and one bold take. Be specific and direct.\n\nTop 5 QPIX performers:\n${playerSummary}`
    }]
  });

  return msg.content[0].text;
}

// ─── HTML EMAIL TEMPLATE ──────────────────────────────────────────
function buildEmailHTML(top10, games, aiAnalysis, dateLabel) {

  const playerRow = (p, rank) => {
    const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `#${rank}`;
    const offColor = p.offPlusMinus >= 0 ? "#22c55e" : "#ef4444";
    const defColor = p.defPlusMinus >= 0 ? "#3b82f6" : "#ef4444";
    return `
    <tr style="border-bottom:1px solid #1e293b;">
      <td style="padding:12px 8px;color:#94a3b8;font-size:15px;text-align:center;">${medal}</td>
      <td style="padding:12px 8px;">
        <div style="font-weight:800;color:#f1f5f9;font-size:14px;">${p.name}</div>
        <div style="font-size:11px;color:#475569;">${p.team} · ${p.game}</div>
      </td>
      <td style="padding:12px 8px;text-align:center;font-weight:900;color:#f97316;font-size:16px;">${p.points}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.rebounds}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.assists}</td>
      <td style="padding:12px 8px;text-align:center;color:#e2e8f0;">${p.steals}/${p.blocks}</td>
      <td style="padding:12px 8px;text-align:center;font-size:12px;">
        <span style="color:${offColor};">O:${p.offPlusMinus > 0 ? "+" : ""}${p.offPlusMinus}</span>
        <span style="color:#475569;"> / </span>
        <span style="color:${defColor};">D:${p.defPlusMinus > 0 ? "+" : ""}${p.defPlusMinus}</span>
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

  <!-- AI Analysis -->
  <div style="background:linear-gradient(135deg,#0c1a2e,#0f1f35);border:1px solid #1d4ed8;border-radius:12px;padding:20px;margin-bottom:20px;">
    <div style="font-size:11px;color:#3b82f6;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;">🤖 QCore AI Analyst</div>
    <p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.8;font-style:italic;">"${aiAnalysis}"</p>
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
    QPIX = PTS×1 + REB×1.2 + AST×1.5 + STL×3 + BLK×2.5 − TO×2 + TS%Δ×0.3 + Proprietary Off/Def ± Split + Context Bonuses<br>
    The only player metric separating offensive and defensive impact at the individual level.<br>
    Generated automatically via GitHub Actions · QCore AI Analysis
  </div>

</div>
</body>
</html>`;
}

// ─── DASHBOARD HTML (GitHub Pages) ───────────────────────────────
function buildDashboardHTML(top10, games, aiAnalysis, dateLabel) {
  const rows = top10.map((p, i) => {
    const offColor = p.offPlusMinus >= 0 ? "#22c55e" : "#ef4444";
    const defColor = p.defPlusMinus >= 0 ? "#3b82f6" : "#ef4444";
    const rank = i + 1;
    const rankColors = ["#ffd700", "#c0c0c0", "#cd7f32"];
    const rankColor = rankColors[i] || "#475569";
    return `
      <tr onclick="toggleRow(${i})" style="cursor:pointer;border-bottom:1px solid #1e293b;transition:background 0.15s;"
          onmouseover="this.style.background='#0f172a'" onmouseout="this.style.background='transparent'">
        <td style="padding:14px 8px;text-align:center;color:${rankColor};font-weight:900;font-size:16px;">${rank <= 3 ? ["🥇","🥈","🥉"][rank-1] : rank}</td>
        <td style="padding:14px 8px;">
          <div style="font-weight:800;color:#f1f5f9;font-size:14px;">${p.name}</div>
          <div style="font-size:11px;color:#475569;">${p.team} · ${p.position} · ${p.game}</div>
        </td>
        <td style="padding:14px 8px;text-align:center;font-weight:900;color:#f97316;font-size:18px;">${p.points}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.rebounds}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.assists}</td>
        <td style="padding:14px 8px;text-align:center;color:#e2e8f0;">${p.steals}/${p.blocks}</td>
        <td style="padding:14px 8px;text-align:center;font-size:13px;">
          <span style="color:${offColor};font-weight:700;">O:${p.offPlusMinus>=0?"+":""}${p.offPlusMinus}</span><br>
          <span style="color:${defColor};font-weight:700;">D:${p.defPlusMinus>=0?"+":""}${p.defPlusMinus}</span>
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
                   ["TS%",`${p.ts.toFixed(1)}%`],["+/-",p.plus_minus>=0?`+${p.plus_minus}`:p.plus_minus],
                   ["2CH",p.second_chance_points],["FBK",p.fast_break_points],["MIN",Math.round(p.minutes)]
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

  <!-- AI Analysis -->
  <div style="background:linear-gradient(135deg,#0c1a2e,#0f1f35);border:1px solid #1d4ed8;border-radius:12px;padding:20px;margin-bottom:20px;">
    <div style="font-size:11px;color:#3b82f6;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;">🤖 QCore AI Analyst</div>
    <p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.8;font-style:italic;">"${aiAnalysis}"</p>
  </div>

  <!-- QPIX Rankings -->
  <div class="card">
    <div class="card-header">
      <div style="font-size:13px;font-weight:800;color:#f97316;text-transform:uppercase;letter-spacing:1px;">QPIX™ Top 10 Rankings</div>
      <div style="font-size:11px;color:#475569;margin-top:3px;">Click any row to expand · The only metric with proprietary Off/Def ± split at the individual player level</div>
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
          <th>O/D ±</th>
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
    QPIX = PTS×1 + REB×1.2 + AST×1.5 + STL×3 + BLK×2.5 − TO×2 + TS%Δ×0.3 + Off/Def ± Split + Context Bonuses<br>
    The only metric separating offensive and defensive impact at the individual player level.<br>
    Auto-generated via GitHub Actions · Powered by Sportradar API + QCore AI
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
    { name: "Jayson Tatum", team: "BOS", position: "F", minutes: 36, points: 32, rebounds: 8, assists: 6, steals: 2, blocks: 1, turnovers: 2, fgm: 12, fga: 22, fg3m: 3, fg3a: 8, ftm: 5, fta: 6, offensive_rebounds: 1, defensive_rebounds: 7, plus_minus: 14, offensive_rating: 128, defensive_rating: 102, second_chance_points: 2, fast_break_points: 4, game: "NYK @ BOS" },
    { name: "Karl-Anthony Towns", team: "NYK", position: "C", minutes: 32, points: 28, rebounds: 12, assists: 3, steals: 1, blocks: 2, turnovers: 2, fgm: 10, fga: 16, fg3m: 2, fg3a: 5, ftm: 6, fta: 8, offensive_rebounds: 2, defensive_rebounds: 10, plus_minus: 8, offensive_rating: 122, defensive_rating: 105, second_chance_points: 4, fast_break_points: 2, game: "NYK @ BOS" },
    { name: "LeBron James", team: "LAL", position: "F", minutes: 34, points: 27, rebounds: 7, assists: 9, steals: 1, blocks: 0, turnovers: 3, fgm: 10, fga: 18, fg3m: 2, fg3a: 5, ftm: 5, fta: 6, offensive_rebounds: 0, defensive_rebounds: 7, plus_minus: 6, offensive_rating: 124, defensive_rating: 108, second_chance_points: 0, fast_break_points: 6, game: "GSW @ LAL" },
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
      const { score, notes, offPlusMinus, defPlusMinus, ts } = computeQPIX(p);
      return { ...p, score, notes, offPlusMinus, defPlusMinus, ts };
    })
    .sort((a, b) => b.score - a.score);

  const top10 = scoredPlayers.slice(0, 10);
  console.log(`   Top QPIX™ performer: ${top10[0]?.name} (${top10[0]?.score})`);

  console.log("4. Getting QCore AI analysis...");
  const aiAnalysis = await getAIAnalysis(top10, date.label);
  console.log(`   Done.`);

  const gameResults = games.map(g => ({
    home_alias: g.home?.alias || "?",
    away_alias: g.away?.alias || "?",
    home_points: g.home_points || 0,
    away_points: g.away_points || 0,
  }));

  console.log("5. Building QPIX™ dashboard...");
  const dashboardHTML = buildDashboardHTML(top10, gameResults, aiAnalysis, date.label);
  mkdirSync(join(__dirname, "dashboard"), { recursive: true });
  writeFileSync(join(__dirname, "dashboard/index.html"), dashboardHTML);
  console.log("   dashboard/index.html written");

  if (!isDryRun && process.env.SENDGRID_API_KEY) {
    console.log("6. Sending email...");
    sgMail.setApiKey(process.env.SENDGRID_API_KEY);
    const emailHTML = buildEmailHTML(top10, gameResults, aiAnalysis, date.label);

    await sgMail.send({
      to: process.env.REPORT_EMAIL_TO,
      from: process.env.REPORT_EMAIL_FROM,
      subject: `🏀 QPIX™ Daily — ${date.label} | #1: ${top10[0]?.name} (${top10[0]?.points}pts, QPIX ${top10[0]?.score})`,
      html: emailHTML,
    });
    console.log(`   Email sent to ${process.env.REPORT_EMAIL_TO}`);
  } else {
    console.log("6. Skipping email (dry run or no SendGrid key)");
  }

  console.log("\n✅ QPIX™ Report complete!\n");
}

main().catch(err => {
  console.error("Fatal error:", err);
  process.exit(1);
});
