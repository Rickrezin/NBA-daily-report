// Read-only ESPN API probe for the November 2, 2026 NBA slate.
// Prints request status, game coverage, sample player fields, and QPIX field gaps.
// No changes to production reports, data, or scoring formulas.
const date = '20261102';
const base = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba';
async function read(url) {
  const start = Date.now();
  try {
    const res = await fetch(url, {headers: {'Accept':'application/json','User-Agent':'QCore-QPIX-DataAudit/1.0'}, signal: AbortSignal.timeout(20000)});
    const body = await res.text();
    console.log('REQUEST', JSON.stringify({url,status:res.status,ms:Date.now()-start,bytes:body.length,contentType:res.headers.get('content-type')}));
    if (!res.ok) return null;
    try { return JSON.parse(body); } catch(e) {console.log('JSON_PARSE_ERROR',e.message);return null;}
  } catch(e) {console.log('FETCH_ERROR', url, e.message);return null;}
}
const slate = await read(base+'/scoreboard?dates='+date+'&limit=100');
if (!slate) {process.exitCode=1;} else {
  const events = slate.events || [];
  const finals = events.filter(e => e.status?.type?.completed);
  console.log('SLATE',JSON.stringify({all:events.length,final:finals.length,ids:finals.map(e=>e.id),games:finals.map(e=>e.shortName)}));
  if(finals.length !== 15) process.exitCode=2;
  const target = finals.find(e=>e.shortName?.includes('DET') && e.shortName?.includes('CHA')) || finals[0];
  if (!target) process.exitCode=2;
  else {
    const summary = await read(base+'/summary?event='+encodeURIComponent(target.id));
    if (!summary) process.exitCode=1;
    else {
      const keys = Object.keys(summary);
      console.log('SUMMARY_KEYS',JSON.stringify(keys));
      const competitors = summary.boxscore?.players || [];
      console.log('BOXSCORE_TEAM_COUNT',competitors.length);
      for(const team of competitors) {
        console.log('TEAM',JSON.stringify({name:team.team?.displayName,statGroups:(team.statistics||[]).map(g=>({name:g.name,labels:g.labels,names:g.names,athletes:g.athletes?.length}))}));
        for(const group of (team.statistics||[])) {
          const one=group.athletes?.find(x=>x.athlete?.displayName==='Cade Cunningham') || group.athletes?.[0];
          if(one) {console.log('SAMPLE_PLAYER', JSON.stringify({name:one.athlete?.displayName,keys:Object.keys(one),statistics:one.stats,labels:group.labels,names:group.names,athleteKeys:Object.keys(one.athlete||{})}));break;}
        }
      }
      const text=JSON.stringify(summary).toLowerCase();
      const indicators=['offensiverating','defensiverating','pointsinpaint','pointssecondchance','pointsfastbreak','secondchancepoints','fastbreakpoints'];
      console.log('QPIX_ADVANCED_FIELD_SEARCH',JSON.stringify(Object.fromEntries(indicators.map(k=>[k,text.includes(k)]))));
      console.log('PBP',JSON.stringify({plays:summary.plays?.length||0,firstKeys:Object.keys(summary.plays?.[0]||{})}));
    }
  }
}

console.log('FULL_SLATE_AUDIT_BEGIN');
const slate2=await read(base+'/scoreboard?dates='+date+'&limit=100');
const finals2=(slate2?.events||[]).filter(e=>e.status?.type?.completed);
let playerCount=0, validGames=0, missingGames=[], advancedGames=0;
for (const e of finals2) {
 const s=await read(base+'/summary?event='+encodeURIComponent(e.id));
 if (!s || (s.boxscore?.players||[]).length!==2) {missingGames.push(e.id);continue;}
 validGames++;
 let count=0, missing=0, sample='';
 for(const team of s.boxscore.players) for(const grp of (team.statistics||[])) for(const p of(grp.athletes||[])){
  if(p.didNotPlay)continue;
  count++;
  if(!Array.isArray(p.stats)||p.stats.length<14)missing++;
  if(!sample)sample=p.athlete?.displayName||'';
 }
 playerCount+=count;
 const lower=JSON.stringify(s).toLowerCase();
 if(lower.includes('offensiverating')&&lower.includes('defensiverating'))advancedGames++;
 console.log('GAME_AUDIT',JSON.stringify({id:e.id,match:e.shortName,playerRows:count,badStatRows:missing,playEvents:s.plays?.length||0,example:sample}));
}
console.log('FULL_SLATE_AUDIT',JSON.stringify({finals:finals2.length,validGames,playerRows:playerCount,missingGames,advancedGames}));
if(validGames!==15||missingGames.length)process.exitCode=3;
