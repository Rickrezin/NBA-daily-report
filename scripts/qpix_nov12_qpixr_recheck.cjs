#!/usr/bin/env node
// Run the unchanged checked-in C13 function with verified game-specific pregame FTA inputs.
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),date='2026-11-12';
const scorePath=path.join(root,'data','daily',date+'.provisional.json');
const auditPath=path.join(root,'data','historical','qpix_fta',date+'.json');
const source=fs.readFileSync(path.join(root,'generate-report.js'),'utf8');
const begin=source.indexOf('function computeC13_QPIXR(');
const end=source.indexOf('// ─── MAIN QPIX',begin);
if(begin<0||end<begin)throw new Error('Authoritative C13 source not found');
const compute=new Function('const qpixPhase = "regular";'+source.slice(begin,end)+';return computeC13_QPIXR;')();
const j=JSON.parse(fs.readFileSync(scorePath,'utf8'));
const archive=JSON.parse(fs.readFileSync(auditPath,'utf8'));
const before=[];
let updated=0,original=0;
for(const p of j.players){
 const entry=archive.players[String(p.player_id)];
 if(!entry)throw new Error('Missing identity '+p.player_id);
 p.qpix_r_legacy_shadow=p.qpix_r_shadow;
 p.referee_penalty_legacy=p.referee_penalty;
 p.referee_bonus_legacy=p.referee_bonus;
 if(entry.status==='ESPN_GAMELOG_VERIFIED' && entry.pregame_rolling20_fta!==null && entry.rolling20_games>0){
   const input={...p,rolling_20_fta:entry.pregame_rolling20_fta};
   const r=compute(input,p.raw_qpix_shadow);
   p.qpix_r_shadow=r.qpixR;
   p.referee_penalty=r.refPenalty;
   p.referee_bonus=r.refBonus;
   p.qpix_r_baseline={source:'ESPN_VERIFIED_PREGAME_ROLLING20',fta:entry.pregame_rolling20_fta,
                      prior_games:entry.previous_games,window_games:entry.rolling20_games};
   p.score_notes=(p.score_notes||[]).filter(n=>!n.startsWith('QPIX-R flag:'));
   if(r.qpixRFlag)p.score_notes.push('QPIX-R flag: '+r.qpixRFlag);
   p.quality={...p.quality,QPIXR:'ESPN_VERIFIED_PREGAME_ROLLING20_FTA'};
   updated++;
 }else{
   // Explicitly preserve prior companion as a legacy value, not a verified recalculation.
   p.qpix_r_baseline={source:'LEGACY_BASELINE_NOT_REVERIFIED',fta:null,
                      prior_games:entry.previous_games??null};
   p.quality={...p.quality,QPIXR:'LEGACY_BASELINE_UNVERIFIED'};
   original++;
 }
 if(p.raw_qpix_shadow!==p.raw_qpix_shadow || !Number.isFinite(p.raw_qpix_shadow))
   throw new Error('Bad RAW '+p.name);
 before.push({name:p.name,r:p.qpix_r_shadow});
}
j.qpix_r_recheck={date_et:date,engine:'UNCHANGED_CHECKED_IN_C13',
  baseline_source:'ESPN_PLAYER_2026_27_GAMELOG_PREGAME_20',
  count_verified:updated,count_legacy_unverified:original,
  audit_path:'data/historical/qpix_fta/'+date+'.json',
  quality:'PROVISIONAL_QPIXR_RECALIBRATED_SEASON_LOG_NOT_FULL_QPIX_CERTIFICATION'};
fs.writeFileSync(scorePath,JSON.stringify(j,null,2)+'\n');
console.log('QPIX_R_RECHECK',JSON.stringify({verified:updated,legacy:original,
 trae:j.players.find(x=>x.name==='Trae Young')&&{
 raw:j.players.find(x=>x.name==='Trae Young').raw_qpix_shadow,
 legacy:j.players.find(x=>x.name==='Trae Young').qpix_r_legacy_shadow,
 revised:j.players.find(x=>x.name==='Trae Young').qpix_r_shadow,
 baseline:j.players.find(x=>x.name==='Trae Young').qpix_r_baseline}}));
