import test from 'node:test';
import assert from 'node:assert/strict';
import {classifyLHASA} from './priority-core.js';
test('LHASA score bins are explicitly research-only',()=>{
 assert.equal(classifyLHASA(null).label,'not_assessed');
 assert.equal(classifyLHASA(0.001).label,'low');
 assert.equal(classifyLHASA(0.03).label,'moderate');
 assert.equal(classifyLHASA(0.4).label,'elevated');
 assert.equal(classifyLHASA(0.4).operational,false);
});
