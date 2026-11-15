import test from 'node:test';
import assert from 'node:assert/strict';
import {HAZARDS,validateFeed,reconcile,sortedAlertHistory,isValidLocation,feedStatus} from './alarm-core.js';

const now=Date.now();
const sample={id:'usgs:test123',title:'M 5.4 · Test observation',time:now-60_000,
  lon:10,lat:20,level:'notable',url:'https://earthquake.usgs.gov/'};

test('all five hazard sources have explicit polling cadence',()=>{
  assert.deepEqual(HAZARDS.map(x=>x.id),['eq','ls','gl','fi','fl']);
  assert.equal(HAZARDS[0].minutes,2);
  assert.ok(HAZARDS.slice(1).every(x=>x.minutes===10));
});
test('source-validating feed rejects error masquerading as an empty list',()=>{
  assert.deepEqual(validateFeed({hazard:'eq',status:'ok',records:[]},'eq'),[]);
  assert.throws(()=>validateFeed({hazard:'eq',status:'unavailable',records:[]},'eq'));
  assert.throws(()=>validateFeed({hazard:'ls',status:'ok',records:[sample]},'eq'));
  assert.throws(()=>validateFeed({hazard:'eq',status:'ok',records:[{id:'x'}]},'eq'));
});
test('initial source retrieval never triggers a new-notification burst',()=>{
  const first=reconcile([], [sample],true);
  assert.deepEqual(first.fresh,[]);
  assert.deepEqual(first.seen,['usgs:test123']);
  const again=reconcile(first.seen,[sample],false);
  assert.equal(again.fresh.length,0);
  const second=reconcile(first.seen,[sample,{...sample,id:'usgs:next'}],false);
  assert.equal(second.fresh.length,1);
  assert.equal(second.fresh[0].id,'usgs:next');
});
test('history deduplicates per hazard and keeps source order by event time',()=>{
  const rows=sortedAlertHistory([
    {...sample,hazard:'eq'},
    {...sample,hazard:'eq'},
    {...sample,id:'eonet:fl:1',hazard:'fl',time:now-90_000},
  ]);
  assert.equal(rows.length,2);
  assert.equal(rows[0].hazard,'eq');
});
test('cannot fly map without finite measured coordinates',()=>{
  assert.equal(isValidLocation(sample),true);
  assert.equal(isValidLocation({...sample,lat:null}),false);
  assert.equal(isValidLocation({...sample,lon:Infinity}),false);
});
test('failure states must be visible and never presented as no reports',()=>{
  const label=feedStatus({on:true,error:'Source unavailable',busy:false});
  assert.match(label,/Unavailable/);
  assert.notEqual(label,'No events');
});
