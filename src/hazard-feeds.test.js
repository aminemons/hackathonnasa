import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeUSGS,normalizeEONET,fetchHazardFeed} from './hazard-feeds.js';
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
