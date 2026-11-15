import test from 'node:test';
import assert from 'node:assert/strict';
import {readStudy} from './study-transport.js';
test('dated lake geometry accepts the GeoJSON media type used by the live host',async()=>{
  const original=globalThis.fetch;
  try {
    for(const mime of ['application/json; charset=utf-8','application/geo+json']){
      globalThis.fetch=async()=>new Response('{"type":"FeatureCollection","features":[]}',{headers:{'Content-Type':mime}});
      assert.equal((await readStudy('/context.geojson')).type,'FeatureCollection');
    }
    globalThis.fetch=async()=>new Response('<html>login</html>',{headers:{'Content-Type':'text/html'}});
    await assert.rejects(readStudy('/context.geojson'),/unavailable/);
    globalThis.fetch=async()=>new Response('{}',{status:503,headers:{'Content-Type':'application/json'}});
    await assert.rejects(readStudy('/context.geojson'),/503/);
  } finally {globalThis.fetch=original}
});
