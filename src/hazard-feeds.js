/**
 * TerraPulse public-data adapter. Public USGS/EONET APIs and immutable glacial
 * study assets are read from the visitor's browser, not through paid Vercel
 * Python invocations. CORS errors are explicit and never become "zero events".
 * No key or restricted API URL is embedded in browser code.
 */
const TTL = {eq:120000, ls:600000, gl:86400000, fi:600000, fl:600000};
const EONET = {ls:'landslides',fi:'wildfires',fl:'floods'};
const inFlight = new Map();
const memory = new Map();
const SITE_ROOT = '/data/glof-study/';
const MAX_STORED = 800_000;

function maybePoint(geometry) {
  if(geometry?.type!=='Point'||!Array.isArray(geometry.coordinates))return [null,null];
  const [lon,lat] = geometry.coordinates;
  return Number.isFinite(lon)&&Number.isFinite(lat)&&Math.abs(lon)<=180&&Math.abs(lat)<=90
    ? [lon,lat] : [null,null];
}
function safeURL(value,origin) {
  try {
    const parsed = new URL(value);
    if(parsed.origin===new URL(origin).origin && parsed.protocol==='https:') return parsed.href;
  }catch {}
  return origin;
}
function finiteTime(value) {
  return Number.isFinite(value)&&value>0&&value<=Date.now()+86400000;
}
function sorted(records) {
  return records.sort((a,b)=>b.time-a.time).slice(0,300);
}
export function normalizeUSGS(data,minMagnitude=5) {
  if(!Array.isArray(data?.features))throw Error('USGS feed schema invalid');
  const rows=[];
  for(const feature of data.features) {
    const p=feature?.properties, t=Number(p?.time), m=Number(p?.mag);
    if(!finiteTime(t)||!Number.isFinite(m)||m<minMagnitude||!feature?.id)continue;
    const [lon,lat]=maybePoint(feature.geometry);
    const alert=String(p?.alert||'').toLowerCase();
    const level=['red','orange'].includes(alert)?'impact_report'
      :(alert==='yellow'||p?.tsunami===1||Number(p?.sig)>=600)?'notable':'observation';
    const detail=Array.isArray(feature.geometry?.coordinates)?feature.geometry.coordinates[2]:null;
    rows.push({
      id:'usgs:'+String(feature.id).slice(0,100),
      title:'M '+m.toFixed(1)+' · '+String(p.place||'Earthquake').slice(0,180),
      place:String(p.place||'Unknown location').slice(0,180), magnitude:m,
      depth_km:Number.isFinite(detail)?detail:null,
      time:t,lon,lat,level,notes:'Magnitude '+m.toFixed(1)+(alert?' · PAGER '+alert:''),
      url:safeURL(p?.url,'https://earthquake.usgs.gov/'),
    });
  }
  return sorted(rows);
}
export function normalizeEONET(data,hazard) {
  if(!Array.isArray(data?.events))throw Error('NASA EONET feed schema invalid');
  const rows=[];
  for(const event of data.events){
    if(!event?.id)continue;
    const observations=Array.isArray(event.geometry)?event.geometry:[];
    const latest=observations.at(-1);
    const t=Date.parse(latest?.date||'');
    if(!finiteTime(t))continue;
    const [lon,lat]=maybePoint(latest);
    rows.push({
      id:'eonet:'+hazard+':'+String(event.id).slice(0,100),
      title:String(event.title||'Natural event').slice(0,180),time:t,lon,lat,
      level:'observation',notes:'NASA EONET catalogue report, not danger severity',
      url:safeURL(event.link,'https://eonet.gsfc.nasa.gov/'),
    });
  }
  return sorted(rows);
}
function readSession(key) {
  try {
    const entry=JSON.parse(sessionStorage.getItem('tp-public-feed-v1:'+key)||'null');
    return entry&&Number.isFinite(entry.until)&&entry.until>Date.now()&&entry.data?.status==='ok' ? entry:null;
  }catch {return null;}
}
function putSession(key,data,ttl) {
  try {
    const payload=JSON.stringify({until:Date.now()+ttl,data});
    if(payload.length<=MAX_STORED)sessionStorage.setItem('tp-public-feed-v1:'+key,payload);
  }catch {}
}
async function json(url,timeout=17000) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try {
    const response=await fetch(url,{signal:controller.signal,cache:'default'});
    if(!response.ok)throw Error('HTTP '+response.status);
    if(!response.headers.get('content-type')?.toLowerCase().includes('json'))
      throw Error('Unexpected response type');
    return await response.json();
  }finally{clearTimeout(timer);}
}
async function direct(hazard,days,minMagnitude) {
  if(hazard==='gl') {
    const catalog=await json(SITE_ROOT+'catalog.json');
    if(!Array.isArray(catalog.sites)||!catalog.sites.length)
      throw Error('Static glacial-lake source invalid');
    const details=await Promise.all(catalog.sites.map(site=>{
      if(!/^[a-z0-9_]+$/.test(site.site_id))throw Error('Invalid glacial-lake ID');
      return json(SITE_ROOT+site.site_id+'/summary.json');
    }));
    const records=details.map((detail,i)=>{
      const site=catalog.sites[i];
      const rows=detail?.lake?.series;
      if(!Array.isArray(rows)||!rows.length)throw Error('Missing lake observations');
      const last=[...rows].sort((a,b)=>b.date.localeCompare(a.date))[0];
      const time=Date.parse(last.date+'T00:00:00Z');
      if(!finiteTime(time))throw Error('Invalid lake observation date');
      const speeds=(detail?.movement?.series||[]).filter(row=>Number.isFinite(row?.median_m_yr));
      const speed=speeds.sort((a,b)=>b.year-a.year)[0];
      return {
        id:'glof:'+site.site_id+':'+last.date,
        title:site.name+' · historical lake observation',
        time,lon:site.lon,lat:site.lat,level:'observation',
        notes:'Sentinel-1 '+last.date+' · '+(speed
          ?'ITS_LIVE '+speed.year+': '+speed.median_m_yr.toFixed(1)+' m/year · ':'')
          +'historical evidence, NOT a GLOF warning',
        url:SITE_ROOT+site.site_id+'/summary.json',
      };
    });
    return {hazard,source:'Published Sentinel-1 / NASA ITS_LIVE study',records:sorted(records),
      monitor_kind:'historical, non-operational glacial-lake evidence',
      operational_warning_ready:false};
  }
  if(hazard==='eq'){
    const suffix=days===1?'day':days===7?'week':'month';
    const url=minMagnitude>=4.5
      ?'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_'+suffix+'.geojson'
      :'https://earthquake.usgs.gov/fdsnws/event/1/query?'+new URLSearchParams({
        format:'geojson',orderby:'time',limit:'300',starttime:new Date(Date.now()-days*86400000).toISOString(),
        minmagnitude:String(minMagnitude)
      });
    const data=await json(url);
    return {hazard,source:'USGS ComCat',records:normalizeUSGS(data,minMagnitude),
      monitor_kind:'catalogue observations, NOT real-time emergency warnings'};
  }
  const category=EONET[hazard];
  if(!category)throw Error('Unknown hazard');
  const data=await json('https://eonet.gsfc.nasa.gov/api/v3/events?'+new URLSearchParams({
    status:'open',category,limit:'200'
  }));
  return {hazard,source:'NASA EONET',records:normalizeEONET(data,hazard),
    monitor_kind:'catalogue observations, not hazard or impact forecasts'};
}
/** @param {{hazard:string,days?:number,min_magnitude?:number}} input */
export async function fetchHazardFeed({hazard,days=1,min_magnitude=5}={}) {
  if(!(hazard in TTL))throw Error('Unsupported hazard');
  if(![1,7,30].includes(days))throw Error('Unsupported earthquake period');
  const mag=Number(min_magnitude);
  if(!Number.isFinite(mag)||mag<2||mag>9)throw Error('Invalid magnitude');
  const key=[hazard,days,mag].join(':');
  const local=memory.get(key);
  if(local&&Date.now()<local.until)return local.data;
  const cached=readSession(key);
  if(cached){memory.set(key,{data:cached.data,until:cached.until});return cached.data;}
  if(inFlight.has(key))return inFlight.get(key);
  const task=(async()=>{
    const batch=await direct(hazard,days,mag);
    const data={...batch,status:'ok',fetched_at:new Date().toISOString()};
    memory.set(key,{data,until:Date.now()+TTL[hazard]});
    putSession(key,data,TTL[hazard]);
    return data;
  })().finally(()=>inFlight.delete(key));
  inFlight.set(key,task);
  return task;
}
