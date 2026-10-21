/** QPIX familiarity reporting, informational only. No effect on RAW QPIX or QPIX-R. */
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
const DATA_DIR = join(process.cwd(), "data");
function readJson(name, fallback) {
  const path = join(DATA_DIR, name);
  if (!existsSync(path)) return fallback;
  return JSON.parse(readFileSync(path, "utf8"));
}
function safeRecord(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
function valueOrNull(value) { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function buildContext(p, opponents, arenas) {
  const opponent = p.team === p.home_alias ? p.away_alias : p.home_alias;
  const playerKey = p.player_id || p.name;
  const opponentHistory = safeRecord(safeRecord(opponents.player_opponents)[playerKey])[opponent] || null;
  const arenaId = p.arena_id || null; // Source does not currently provide verified arena IDs.
  const arenaHistory = arenaId ? (safeRecord(safeRecord(arenas.player_arenas)[playerKey])[arenaId] || null) : null;
  return {
    opponent,
    arena_id: arenaId,
    opponent_familiarity: opponentHistory ? {
      games: valueOrNull(opponentHistory.games), avg_qpix: valueOrNull(opponentHistory.avg_qpix),
      last_meeting: opponentHistory.last_meeting || null, source: opponentHistory.source || null
    } : null,
    arena_familiarity: arenaHistory ? {
      games: valueOrNull(arenaHistory.games), avg_qpix: valueOrNull(arenaHistory.avg_qpix),
      source: arenaHistory.source || null
    } : null
  };
}
export function writeFamiliarityReport(players, games, reportDate) {
  const opponents = readJson("opponent_familiarity.json", {player_opponents:{}});
  const arenas = readJson("arena_familiarity.json", {player_arenas:{}});
  const records = players.map(p => ({
    player: p.name, player_id: p.player_id || null, team: p.team,
    game: p.game, raw_qpix: p.score, qpix_r: p.qpixR,
    ...buildContext(p, opponents, arenas)
  }));
  const report = {
    schema_version: 1, report_date_et: reportDate, season: opponents.season || arenas.season || null,
    source: "QPIX daily player scores + optional verified familiarity datasets",
    note: "Familiarity is descriptive only. Null means unknown, not zero. Arena IDs must be verified; no venue inferred from home team.",
    games: games.map(g => ({home: g.home_alias, away: g.away_alias})),
    players: records
  };
  const outDir = join(process.cwd(), "dashboard");
  mkdirSync(outDir, {recursive:true});
  writeFileSync(join(outDir, "familiarity.json"), JSON.stringify(report,null,2) + "\n");
  return report;
}
