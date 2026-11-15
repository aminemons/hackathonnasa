/** Explainable proximity review, never an occupancy or runout estimate. */
export function proximityReview(result) {
  if (!result || !result.counts || !result.nearest_m || !result.osm_timestamp) {
    return {state:'unknown', title:'Exposure unknown', alert:false};
  }
  const n=result.nearest_m;
  const valid=x=>typeof x==='number' && Number.isFinite(x) && x>=0;
  if ((valid(n.buildings)&&n.buildings<=150) ||
      (valid(n.sensitive_places)&&n.sensitive_places<=100)) {
    return {state:'review',title:'Landslide site close to mapped human activity',alert:true};
  }
  if (valid(n.roads)&&n.roads<=150) {
    return {state:'access',title:'Mapped access route nearby',alert:true};
  }
  return {state:'unconfirmed',title:'Nearby human activity not confirmed',alert:false};
}

export function distanceKm(a,b) {
  if (![a?.lat,a?.lon,b?.lat,b?.lon].every(Number.isFinite)) return Infinity;
  const rad=x=>x*Math.PI/180, dlat=rad(b.lat-a.lat),dlon=rad(b.lon-a.lon);
  const h=Math.sin(dlat/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(dlon/2)**2;
  return 6371*2*Math.asin(Math.sqrt(Math.min(1,h)));
}
