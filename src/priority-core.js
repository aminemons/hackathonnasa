/**
 * Transparent, NON-operational review triage.
 * Classification is deliberately not a safety alert or forecast probability.
 * Input classes must come from separately validated, timestamped hazard layers.
 */
export const PRIORITY_THRESHOLDS = Object.freeze({
  minExposureCoverage: 0.8, // fraction of assessed study footprint with valid OSM/population coverage
  criticalAssetsForUrgentReview: 1,
});
const nonnegative = x => Number.isInteger(x) && x >= 0;
export function classifyReviewPriority(input, cfg = PRIORITY_THRESHOLDS) {
  const unassessed = reason => ({priority:'not_assessed', reason,
    safety_warning:'Research review priority only; not an emergency alert.'});
  if(!input||!['low','moderate','high'].includes(input.hazardClass))
    return unassessed('No regionally validated hazard class');
  if(!['observed','modelled'].includes(input.hazardEvidence))
    return unassessed('Hazard evidence provenance is missing');
  if(!Number.isFinite(input.observedAt)||input.observedAt<0)
    return unassessed('Missing hazard observation timestamp');
  const e=input.exposure;
  if(!e||!Number.isFinite(e.coverageFraction)||
     e.coverageFraction<cfg.minExposureCoverage||e.coverageFraction>1||
     !nonnegative(e.criticalAssets)||!nonnegative(e.exposedPeople))
    return unassessed('Exposure data missing, incomplete, or not spatially verified');
  if(input.hazardClass==='low')return {priority:'low_review',reason:'Low hazard class with assessed exposure',
    operational:false};
  if(input.hazardClass==='moderate')return {priority:'moderate_review',reason:'Moderate hazard classification',
    operational:false};
  const exposed=e.criticalAssets>0||e.exposedPeople>0;
  if(!exposed)return {priority:'moderate_review',
    reason:'High hazard class but no exposure found within assessed coverage',operational:false};
  if(input.triggerObserved===true && e.criticalAssets>=cfg.criticalAssetsForUrgentReview &&
      input.triggerObservedAt && Number.isFinite(input.triggerObservedAt))
    return {priority:'urgent_review',reason:'High hazard, independent observed trigger and verified critical exposure',
      operational:false};
  return {priority:'high_review',reason:'High hazard class intersects assessed people or infrastructure',
    operational:false};
}
