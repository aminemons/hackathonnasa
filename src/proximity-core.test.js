import test from 'node:test';
import assert from 'node:assert/strict';
import {proximityReview,distanceKm} from './proximity-core.js';
const sample={counts:{},nearest_m:{buildings:149,roads:null,sensitive_places:null},osm_timestamp:'2026-11-15T00:00:00Z'};
test('proximity flags actual mapped distance, not a missing numeric value',()=>{
  assert.equal(proximityReview(sample).alert,true);
  assert.equal(proximityReview({...sample,nearest_m:{buildings:null}}).alert,false);
  assert.equal(proximityReview({...sample,nearest_m:{buildings:151}}).alert,false);
  assert.equal(proximityReview({...sample,nearest_m:{sensitive_places:100}}).alert,true);
  assert.equal(proximityReview({...sample,nearest_m:{roads:100}}).state,'access');
});
test('unavailable or undated asset query cannot establish exposure',()=>{
  assert.equal(proximityReview(null).state,'unknown');
  assert.equal(proximityReview({...sample,osm_timestamp:null}).alert,false);
});
test('watch distance handles the antimeridian and missing event locations',()=>{
  assert.ok(distanceKm({lat:0,lon:179.99},{lat:0,lon:-179.99})<3);
  assert.equal(distanceKm({lat:0,lon:0},{lat:null,lon:null}),Infinity);
});
