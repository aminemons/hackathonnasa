/** Pure, tested catalogue-monitoring logic. No safety-critical predictions. */
export const HAZARDS = Object.freeze([
  {id:'eq',name:'Earthquakes',icon:'🌍',minutes:2,source:'USGS ComCat',kind:'reported'},
  {id:'ls',name:'Landslides',icon:'⛰️',minutes:10,source:'NASA EONET',kind:'reported'},
  {id:'gl',name:'Glacial lakes',icon:'🧊',minutes:1440,
    source:'Historical ESA Sentinel-1 / NASA ITS_LIVE study',kind:'historical'},
]);

export function validateEvent(record) {
  if (!record || typeof record.id !== 'string' || record.id.length > 150 ||
      typeof record.title !== 'string' || !Number.isFinite(record.time) ||
      record.time < 0 || record.time > Date.now() + 86400000) return false;
  return record.level === 'observation' || record.level === 'notable' ||
         record.level === 'impact_report';
}
export function validateFeed(feed, hazard) {
  if (!feed || feed.status !== 'ok' || feed.hazard !== hazard ||
      !Array.isArray(feed.records) || feed.records.length > 400 ||
      feed.records.some(r => !validateEvent(r))) {
    throw new Error('Upstream feed did not pass source and record validation');
  }
  return feed.records;
}
export function reconcile(previousSeen, records, initial = false) {
  const seen = new Set(previousSeen || []);
  const fresh = [];
  for (const record of records) {
    if (seen.has(record.id)) continue;
    seen.add(record.id);
    if (!initial) fresh.push(record);
  }
  // Bound storage to prevent indefinite browser cache growth.
  return {seen:[...seen].slice(-800), fresh};
}
export function sortedAlertHistory(alerts, max=120) {
  const byId = new Map();
  for (const a of alerts) {
    if (!a || !validateEvent(a) || !HAZARDS.some(h => h.id === a.hazard)) continue;
    const key=a.hazard + '/' + a.id;
    if (!byId.has(key) || a.time > byId.get(key).time) byId.set(key,a);
  }
  return [...byId.values()].sort((a,b)=>b.time-a.time).slice(0,max);
}
export function feedStatus(state) {
  if (!state?.on) return 'Off';
  if (state.error) return 'Unavailable · '+state.error;
  if (state.busy) return 'Checking source…';
  if (!state.lastSuccess) return 'Waiting for first feed';
  return 'Checked '+new Date(state.lastSuccess).toLocaleTimeString() +
    ' · '+(state.latestCount||0)+' reported';
}
export function isValidLocation(x) {
  return Number.isFinite(x?.lat) && Number.isFinite(x?.lon) &&
    x.lat >= -90 && x.lat <= 90 && x.lon >= -180 && x.lon <= 180;
}
