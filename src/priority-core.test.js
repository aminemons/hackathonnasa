import test from 'node:test';
import assert from 'node:assert/strict';
import {classifyReviewPriority} from './priority-core.js';
const baseline={hazardClass:'high',hazardEvidence:'modelled',observedAt:Date.now()-60000,
  exposure:{coverageFraction:.95,criticalAssets:1,exposedPeople:20},
  triggerObserved:true,triggerObservedAt:Date.now()-120000};
test('missing layers never become low risk or a safety verdict',()=>{
  assert.equal(classifyReviewPriority({hazardClass:'high'}).priority,'not_assessed');
  assert.equal(classifyReviewPriority({...baseline,exposure:{...baseline.exposure,coverageFraction:.2}}).priority,'not_assessed');
});
test('urgent review needs high hazard, observed trigger, and assessed critical assets',()=>{
  assert.equal(classifyReviewPriority(baseline).priority,'urgent_review');
  assert.equal(classifyReviewPriority({...baseline,triggerObserved:null}).priority,'high_review');
  assert.equal(classifyReviewPriority({...baseline,exposure:{...baseline.exposure,criticalAssets:0}}).priority,'high_review');
});
test('review priority is not an operational alert',()=>{
  assert.equal(classifyReviewPriority(baseline).operational,false);
  assert.equal(classifyReviewPriority({...baseline,hazardClass:'low'}).priority,'low_review');
});
