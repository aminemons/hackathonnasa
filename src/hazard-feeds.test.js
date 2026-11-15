import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeUSGS,normalizeEONET,fetchHazardFeed} from './hazard-feeds.js';
import {readFileSync} from 'node:fs';
const archive=JSON.parse(readFileSync(new URL('../public/data/landslides-eonet-archive.json',import.meta.url)));
test('USGS maps only real observations with a measured timestamp',()=>{
  const result=normalizeUSGS({features:[{
    id:'a',geometry:{type:'Point',coordinates:[1,2,8]},
    properties:{mag:5.4,time:Date.now()-10000,place:'Algeria',
      url:'https://earthquake.usgs.gov/earthquakes/eventpage/a',alert:'yellow'}
  }]},5);
  assert.equal(result.length,1);assert.equal(result[0].depth_km,8);
  assert.equal(result[0].level,'notable');assert.equal(result[0].lat,2);
});
test('malformed upstream responses fail instead of becoming zero events',()=>{
  assert.throws(()=>normalizeUSGS({foo:1}),/schema/);
  assert.throws(()=>normalizeEONET({foo:1},'ls'),/schema/);
});
test('NASA polygons retain observations without invented coordinates',()=>{
  const rows=normalizeEONET({events:[{
    id:'1',title:'Reported slide',
    geometry:[{type:'Polygon',date:new Date().toISOString(),coordinates:[]}]
  }]},'ls');
  assert.equal(rows.length,1);assert.equal(rows[0].lat,null);
  assert.equal(rows[0].level,'observation');
});
test('invalid hazard and out of bounds magnitude never issue network requests',async()=>{
  await assert.rejects(fetchHazardFeed({hazard:'none'}),/Unsupported/);
  await assert.rejects(fetchHazardFeed({hazard:'eq',min_magnitude:100}),/Invalid/);
});
test('empty recent landslide scope falls back to dated real reports, preserving source polygons',async t=>{
  const module=await import('./hazard-feeds.js?test=archive');
  t.mock.method(globalThis,'fetch',async url=>new Response(JSON.stringify(
    String(url).includes('landslides-eonet-archive.json')?archive:{events:[]}),
    {headers:{'content-type':'application/json'}}));
  const result=await module.fetchHazardFeed({hazard:'ls',include_recent:true});
  assert.equal(result.records.length,17);
  assert.equal(result.archive_only,true);
  assert.equal(result.search_scope,'historical_eonet_archive');
  assert.equal(result.observation_start,'2015-03-23');
  assert.equal(result.observation_end,'2020-03-23');
  const polygons=result.records.filter(r=>r.geometry);
  assert.equal(polygons.length,12);
  assert.ok(polygons.every(r=>r.lat===null&&r.lon===null));
  assert.ok(result.records.every(r=>r.notes.includes('not a currently active incident')));
});
test('current landslide monitoring never substitutes an old archived incident',async t=>{
  const module=await import('./hazard-feeds.js?test=current-only');
  const calls=[];
  t.mock.method(globalThis,'fetch',async url=>{
    calls.push(String(url));
    return new Response(JSON.stringify({events:[]}),{headers:{'content-type':'application/json'}});
  });
  const result=await module.fetchHazardFeed({hazard:'ls'});
  assert.deepEqual(result.records,[]);
  assert.equal(result.search_scope,'currently_open');
  assert.equal(result.archive_only,undefined);
  assert.equal(calls.length,1);
});
test('browser source failure still permits explicitly labelled archive viewing',async t=>{
  const module=await import('./hazard-feeds.js?test=archive-outage');
  t.mock.method(globalThis,'fetch',async url=>{
    if(!String(url).includes('landslides-eonet-archive.json'))throw Error('Source unavailable');
    return new Response(JSON.stringify(archive),{headers:{'content-type':'application/json'}});
  });
  const result=await module.fetchHazardFeed({hazard:'ls',include_recent:true});
  assert.equal(result.records.length,17);
  assert.equal(result.archive_only,true);
});
test('a stale empty v1 session cache cannot hide the repaired archive',async t=>{
  const keys=[];
  const previous=Object.getOwnPropertyDescriptor(globalThis,'sessionStorage');
  Object.defineProperty(globalThis,'sessionStorage',{configurable:true,value:{getItem(key){
    keys.push(key);
    return key.startsWith('tp-public-feed-v1:')?JSON.stringify({until:Date.now()+600000,data:{status:'ok',records:[]}}):null;
  },setItem(){}}});
  t.after(()=>{if(previous)Object.defineProperty(globalThis,'sessionStorage',previous);else delete globalThis.sessionStorage;});
  const module=await import('./hazard-feeds.js?test=session-version');
  t.mock.method(globalThis,'fetch',async url=>new Response(JSON.stringify(
    String(url).includes('landslides-eonet-archive.json')?archive:{events:[]}),
    {headers:{'content-type':'application/json'}}));
  assert.equal((await module.fetchHazardFeed({hazard:'ls',include_recent:true})).records.length,17);
  assert.ok(keys.every(k=>k.startsWith('tp-public-feed-v2:')));
});
