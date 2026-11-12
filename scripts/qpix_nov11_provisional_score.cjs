// Exact-authority category execution, never a fork or rewrite of the scoring formulas.
// Only ESM imports and the main() side-effect entrypoint are excluded.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const ROOT=path.resolve(__dirname,'..');process.chdir(ROOT);
const raw=fs.readFileSync('generate-report.js','utf8');
const sha=crypto.createHash('sha1').update('blob '+Buffer.byteLength(raw)+'\0'+raw).digest('hex');
if(sha!=='390833f45ee5191092813647f0735f1598cfeab1')throw Error('Authorized main source SHA mismatch '+sha);
const pos=raw.indexOf('async function main()');
if(pos<0)throw Error('Missing scoring entrypoint boundary');
let source=raw.slice(0,pos).replace(/^import .*;\r?\n/gm,'').replace('const __dirname = dirname(fileURLToPath(import.meta.url));','const __dirname = process.cwd();');
source+='\nREPORT_SEASON_END=2027;globalThis.Q={computeQPIX,buildGameContext,computeC1,computeC2,computeC3,computeC4,computeC5,computeC6,computeC7,computeC8,computeC9,computeC10,computeC11,computeC12};\n';
const ctx=vm.createContext({console,process:{cwd:()=>ROOT,argv:[],env:{QPIX_PHASE:'regular'}},readFileSync:fs.readFileSync,join:path.join,dirname:path.dirname,Date,Math,Number,String,JSON,Object,Array,Set,Map,Promise});
vm.runInContext(source,ctx,{filename:'generate-report.js',timeout:10000});
const Q=ctx.Q,inp=JSON.parse(fs.readFileSync('data/nba_data.json')),games=inp.games,players=inp.players;
if(inp.date_et!=='2026-11-11'||games.length!==10||players.length!==223)throw Error('Wrong collection date or participant count');
const byGame=new Map();for(const p of players){if(!byGame.has(p.game_id))byGame.set(p.game_id,[]);byGame.get(p.game_id).push(p);}
const mismatch=[],res=players.map(p=>{
  const game=games.find(g=>g.game_id===p.game_id),ctxp=Q.buildGameContext(p,byGame.get(p.game_id),game);
  const bad=ctxp.isBenchPlayer===p.source_starter;
  if(bad)mismatch.push({name:p.name,team:p.team,player_id:p.player_id,observed_starter:p.source_starter,engine_bench:ctxp.isBenchPlayer,minutes:p.minutes});
  const x=Q.computeQPIX({...p},ctxp);
  const cat={C1:Q.computeC1(p),C2:Q.computeC2(p).score,C3:Q.computeC3(p).score,C4:Q.computeC4(p).score,C5:Q.computeC5(p).score,C6:Q.computeC6(p).score,C7:Q.computeC7(p),C8:Q.computeC8(p,ctxp).score,C9:Q.computeC9(p).score,C10:Q.computeC10(p),C11:Q.computeC11(p,ctxp),C12:Q.computeC12(p,ctxp).score};
  if(Math.round(Object.values(cat).reduce((a,b)=>a+b,0)*10)/10!==x.score)throw Error('Category checksum drift '+p.name);
  if(!Number.isFinite(x.score)||!Number.isFinite(x.qpixR))throw Error('Bad score '+p.name);
  const sensitivity=Q.computeQPIX({...p},{...ctxp,isBenchPlayer:!p.source_starter});
  return {...p,category_contributions:cat,raw_qpix_shadow:x.score,qpix_r_shadow:x.qpixR,qpix_sfa_shadow:x.qpixSFA,sfa_adjustment:x.sfaAdj,referee_penalty:x.refPenalty,referee_bonus:x.refBonus,ts:x.ts,score_notes:x.notes,context:ctxp,starter_context_mismatch:bad,qpix_with_verified_starter_context_sensitivity:sensitivity.score,qpix_m_minutes_shadow:p.minutes>0?+(x.score/p.minutes).toFixed(3):null,raw_rank_eligible:p.minutes>8};
}).sort((a,b)=>b.raw_qpix_shadow-a.raw_qpix_shadow||a.name.localeCompare(b.name));
const eligible=res.filter(p=>p.minutes>8),top=eligible.slice(0,10),bottom=eligible.slice().sort((a,b)=>a.raw_qpix_shadow-b.raw_qpix_shadow).slice(0,10);
const result={schema_version:2,date_et:'2026-11-11',status:'PROVISIONAL_SHADOW_EXPERIMENTAL_QCORE_C3_MISSING_C6_AND_C11_FASTBREAK',engine:{authoritative_file:'generate-report.js',git_blob_sha:sha,phase:'regular',season_end:2027,method:'unmodified_source_function_bodies_node_vm_without_main',formulas_modified:false},coverage:{final_games:games.length,participating_players:res.length,eligible_gt8:eligible.length,qcore_both:res.filter(p=>p.qcore_q_offr!==null&&p.qcore_q_defr!==null).length,observed_provider_individual_ratings:0,verified_C6_players:0,verified_fast_break_C11_players:0,starter_context_mismatches:mismatch.length},quality:{C3:'EXPERIMENTAL_QCORE_NOV05_NOT_PROVIDER_VERIFIED',C6:'UNAVAILABLE_NOT_OBSERVED_ZERO',C11:'PARTIALLY_SOURCED_FASTBREAK_MISSING',minutes:'ESPN_WHOLE_MINUTE_ROUNDING',starter:'OBSERVED_STARTER_BUT_UNMODIFIED_ENGINE_CONTEXT_HEURISTIC',QPIXM:'EXPERIMENTAL_SEPARATE_NOT_OFFICIAL'},source_input_sha256:inp.original_input_sha256,games,leaderboards:{top10:top.map(p=>p.player_id),bottom10:bottom.map(p=>p.player_id)},starter_context_mismatches:mismatch,players:res};
fs.mkdirSync('data/daily',{recursive:true});fs.writeFileSync('data/daily/2026-11-11.provisional.json',JSON.stringify(result,null,2)+'\n');
function quote(x){if(x===null||x===undefined)return '';let s=String(x);return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
const cols=['rank','name','team','player_id','game_id','minutes','source_starter','points','rebounds','assists','steals','blocks','turnovers','fgm','fga','fg3m','fg3a','ftm','fta','plus_minus','qcore_q_offr','qcore_q_defr','qcore_model_version','rating_source','raw_qpix_shadow','qpix_r_shadow','qpix_sfa_shadow','sfa_adjustment','qpix_m_minutes_shadow','qpix_with_verified_starter_context_sensitivity','starter_context_mismatch',...'C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12'.split(' '),'raw_rank_eligible','C6_quality','C11_quality','qcore_flags'];
const rows=[cols.join(',')];res.forEach((p,i)=>{const d={rank:i+1,...p,C6_quality:p.quality.C6,C11_quality:p.quality.C11,qcore_flags:p.qcore_flags.join('|'),...p.category_contributions};rows.push(cols.map(k=>quote(d[k])).join(','));});
fs.writeFileSync('data/daily/2026-11-11.provisional.csv',rows.join('\n')+'\n');
console.log(JSON.stringify({status:result.status,coverage:result.coverage,top10:top.map(p=>[p.name,p.raw_qpix_shadow,p.qpix_r_shadow]),bottom10:bottom.map(p=>[p.name,p.raw_qpix_shadow])}));
