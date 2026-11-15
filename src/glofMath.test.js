import test from 'node:test';
import assert from 'node:assert/strict';
import {equalEarth, worldPath, initialEpoch, lakeSegments} from './glofMath.js';

test('Unresolved water splits the plotted line instead of becoming zero', () => {
  const chart = lakeSegments([
    {date:'2023-01-01',lake_area_km2:1},
    {date:'2023-01-02',lake_area_km2:null},
    {date:'2023-02-01',lake_area_km2:0.5},
  ]);
  assert.equal(chart.segments.length, 2);
  assert.equal(chart.segments.flat().length, 2);
});
test('Timeline positions respect elapsed time between acquisitions', () => {
  const {segments} = lakeSegments([1,2,11].map(day=>({date:`2023-01-${String(day).padStart(2,'0')}`,lake_area_km2:1})));
  const [a,b,c] = segments[0].map(p=>p[0]);
  assert.ok(Math.abs((b-a)/(c-a)-.1)<1e-9);
});
test('Projection preserves hemispheres and has a finite polar extent', () => {
  assert.deepEqual(equalEarth([0,0]),[300,153]);
  assert.ok(equalEarth([90,30])[0]>300);
  assert.ok(equalEarth([-90,-30])[0]<300);
  for (const lat of [-90,90]) assert.ok(equalEarth([180,lat]).every(Number.isFinite));
});
test('South Lhonak opens on the documented post-event observation', () => {
  assert.equal(initialEpoch({site:{site_id:'south_lhonak'},lake:{series:[{date:'2023-09-25'},{date:'2023-10-07'},{date:'2024-12-24'}]}}),1);
});
test('A line crossing the antimeridian is split at the map edge', () => {
  const path = worldPath({type:'LineString',coordinates:[[179,0],[-179,0]]});
  assert.equal((path.match(/M/g)||[]).length,2);
});
