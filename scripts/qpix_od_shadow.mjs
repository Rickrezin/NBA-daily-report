// Archive-only experimental O/D evidence ledger. Never modifies production QPIX.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
export function reconstruct(cdn, pbp, advanced) {
  const g=cdn.game, teams=[g.homeTeam,g.awayTeam], ids=teams.map(t=>t.teamId);
  const other=t=>ids.find(x=>x!==t);
  const actions=pbp.game.actions;
  assert(actions.every((e,i)=>Number.isSafeInteger(e.orderNumber)&&(!i||e.orderNumber>actions[i-1].orderNumber)), 'Invalid orderNumber sequence');
  const players=new Map(), lineup=new Map(), counts=new Map(ids.map(t=>[t,0]));
  for(const t of teams){
    lineup.set(t.teamId,new Set(t.players.filter(p=>p.starter==='1').map(p=>p.personId)));
    for(const p of t.players)players.set(p.personId,{id:p.personId,name:p.name,team:t.teamId,seconds:0,points:0,assistedPoints:0,receivedAssistedPoints:0,turnovers:0,steals:0,blocks:0,defensiveRebounds:0,offensiveRebounds:0,onPoints:0,onAllowed:0,offPoss:0,defPoss:0,official:p.statistics});
  }
  const close=t=>{assert(counts.has(t));counts.set(t,counts.get(t)+1);for(const id of lineup.get(t))players.get(id).offPoss++;for(const id of lineup.get(other(t)))players.get(id).defPoss++;};
  let prev=0, home=0,away=0, open=null;
  const scoring=[];
  for(let i=0;i<actions.length;i++){
    const e=actions[i], m=/^PT(?:(\d+)M)?([\d.]+)S$/.exec(e.clock);assert(m,'Invalid clock');
    const elapsed=(e.period-1)*720+(e.period>4?-(e.period-4)*420:0)+720-(Number(m[1]||0)*60+Number(m[2]));
    assert(elapsed>=prev-1e-7,'Clock inversion');
    for(const p of players.values())if(lineup.get(p.team).has(p.id))p.seconds+=elapsed-prev;
    prev=elapsed;
    if(e.actionType==='substitution'){
      const set=lineup.get(e.teamId);assert(set);
      if(e.subType==='out')assert(set.delete(e.personId),'Invalid sub out');
      else {assert(e.subType==='in'&&!set.has(e.personId),'Invalid sub in');set.add(e.personId);}
      continue;
    }
    for(const t of ids)assert.equal(lineup.get(t).size,5,'Invalid lineup');
    const dh=Number(e.scoreHome)-home, da=Number(e.scoreAway)-away;
    home=Number(e.scoreHome);away=Number(e.scoreAway);
    assert(dh>=0&&da>=0&&!(dh&&da),'Unexpected score correction');
    if(dh||da){
      const t=dh?ids[0]:ids[1], points=dh||da, scorer=players.get(e.personId);
      assert(scorer&&scorer.team===t,'Missing scorer');
      scorer.points+=points;
      for(const id of lineup.get(t))players.get(id).onPoints+=points;
      for(const id of lineup.get(other(t)))players.get(id).onAllowed+=points;
      if(e.assistPersonId){const assister=players.get(e.assistPersonId);assert(assister&&assister.team===t);assister.assistedPoints+=points;scorer.receivedAssistedPoints+=points;}
      scoring.push({orderNumber:e.orderNumber,points,scorer:e.personId,assister:e.assistPersonId??null,tags:e.qualifiers??[]});
    }
    const p=players.get(e.personId);
    if(p){if(e.actionType==='turnover')p.turnovers++;if(e.actionType==='steal')p.steals++;if(e.actionType==='block')p.blocks++;if(e.actionType==='rebound'&&e.subType==='defensive')p.defensiveRebounds++;if(e.actionType==='rebound'&&e.subType==='offensive')p.offensiveRebounds++;}
    if(e.actionType==='period'&&e.subType==='start'){open=null;continue;}
    if(e.actionType==='period'&&e.subType==='end'){if(open)close(open);open=null;continue;}
    if(['2pt','3pt','heave','turnover','freethrow'].includes(e.actionType))open=e.teamId;
    let ending=null;
    if(e.isFieldGoal&&e.shotResult==='Made'){
      const next=actions.slice(i+1).find(x=>!['substitution','timeout','foul'].includes(x.actionType));
      if(!(next?.actionType==='freethrow'&&next.subType==='1 of 1'&&next.teamId===e.teamId&&next.clock===e.clock))ending=e.teamId;
    }
    if(e.actionType==='turnover')ending=e.teamId;
    if(e.actionType==='rebound'&&e.subType==='defensive')ending=other(e.teamId);
    if(e.actionType==='rebound'&&e.subType==='offensive')open=e.teamId;
    if(e.actionType==='freethrow'&&e.shotResult==='Made'&&/^(1 of 1|2 of 2|3 of 3)$/.test(e.subType))ending=e.teamId;
    if(ending){close(ending);open=null;}
  }
  assert.equal(home,g.homeTeam.score);assert.equal(away,g.awayTeam.score);
  const adv=advanced.boxScoreAdvanced;
  const teamAudit=teams.map(t=>({team:t.teamTricode,reconstructed:counts.get(t.teamId),official:[adv.homeTeam,adv.awayTeam].find(x=>x.teamId===t.teamId).statistics.possessions}));
  const rows=[...players.values()].filter(p=>p.seconds>0).map(p=>{
    const a=[adv.homeTeam,adv.awayTeam].flatMap(t=>t.players).find(x=>x.personId===p.id)?.statistics;
    const s=p.official, minutes=p.seconds/60;
    // No assumed individual weights: evidence only until calibrated.
    const {official,...evidence}=p;
    return {...evidence,minutes,pointsPerMinute:p.points/minutes,assistedPointsPerMinute:p.assistedPoints/minutes,official:{minutes:s.minutes,onPoints:s.plus,onAllowed:s.minus,possessions:a?.possessions,offensiveRating:a?.offensiveRating,defensiveRating:a?.defensiveRating},delta:{onPoints:p.onPoints-s.plus,onAllowed:p.onAllowed-s.minus,offPoss:p.offPoss-a?.possessions},Q_ORtg:null,Q_DRtg:null,Q_ORtg_M:null,Q_DRtg_M:null};
  });
  return {gameId:g.gameId,events:actions.length,teamAudit,rows,scoring,ratingsStatus:'unavailable_pending_reconciliation_and_weight_calibration'};
}
if(process.argv[1]&&path.basename(process.argv[1])==='qpix_od_shadow.mjs'){
  const [raw,gameId,out]=process.argv.slice(2);assert(raw&&gameId&&out,'Usage: node scripts/qpix_od_shadow.mjs RAW_DIR GAME_ID OUTPUT');
  const read=n=>JSON.parse(fs.readFileSync(path.join(raw,gameId+'-'+n+'.json'),'utf8'));
  const r=reconstruct(read('cdn'),read('pbp'),read('advanced'));
  for(const n of ['misc','tracking','defense','matchups','hustle']){
    const payload=read(n), box=Object.values(payload).find(x=>x?.homeTeam&&x?.awayTeam);
    assert(box&&box.gameId===gameId,'Invalid '+n);
    for(const p of r.rows){const row=[box.homeTeam,box.awayTeam].flatMap(t=>t.players).find(x=>x.personId===p.id);p.supporting??={};p.supporting[n]=row?.statistics??row?.matchups??null;}
  }
  fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,JSON.stringify(r,null,2)+'\n');
  console.log(JSON.stringify({gameId,teamAudit:r.teamAudit,players:r.rows.length,ratingsStatus:r.ratingsStatus}));
}
