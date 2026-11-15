/** Dated ITS_LIVE glacier *speed*, never simulated displacement or a surge forecast. */
let snapshot = null;
let interval = null;
const YEAR_MIN = 2000, YEAR_MAX = 2024;
const $ = selector => document.querySelector(selector);
const safe = s => String(s ?? '').replace(/[&<>"']/g,c=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[c]));

async function json(url) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),18000);
  try {
    const r=await fetch(url,{signal:controller.signal});
    if(!r.ok)throw Error('HTTP '+r.status);
    return await r.json();
  }finally{clearTimeout(timer);}
}

function yearSample(detail,year) {
  const rows=detail?.movement?.series||[];
  const found=rows.find(r=>r.year===year);
  return found && Number.isFinite(found.median_m_yr) && found.median_m_yr>=0
    ?found:null;
}
function popup(details,site,year) {
  const v=yearSample(details,year),name=safe(site.name);
  return `<strong>${name}</strong><br>
    <small>NASA ITS_LIVE annual glacier speed · ${year}</small><br>
    ${v?`<strong>${v.median_m_yr.toFixed(1)} m/year</strong>
      <br>Support pixels: ${Number(v.valid_glacier_pixels).toLocaleString()}`:
      '<em>No speed measurement for this year</em>'}
    <br><small>Historical scalar speed; direction and future motion not measured here.</small>
    <br><button type="button" class="tp-btn tp-glacier-open" data-glof-site="${safe(site.site_id)}">Open dated lake evidence</button>`;
}

function updateYear(year) {
  if(!snapshot)return;
  snapshot.year=year;
  for(const entry of snapshot.entries){
    const {site,detail,marker}=entry;
    const data=yearSample(detail,year);
    const speed=data?.median_m_yr;
    const available=Number.isFinite(speed);
    const radius=available?Math.min(17,Math.max(5,5+Math.sqrt(speed)*1.5)):5;
    marker.setRadius(radius).setStyle({
      color:available?'#0955ad':'#909fb1',
      fillColor:available?'#18a8d9':'#c6cbd4',
      fillOpacity:available?.8:.25,
    });
    marker.setPopupContent(popup(detail,site,year));
  }
  $('#tp-motion-year').textContent=String(year);
  $('#tp-motion-range').value=String(year);
  $('#tp-motion-status').textContent=
    snapshot.entries.filter(x=>yearSample(x.detail,year)).length+' of '+
    snapshot.entries.length+' monitored sites have a '+year+' velocity measurement. '+
    'Marker size encodes observed annual speed, not movement of coordinates.';
}
function stop() {
  if(interval){clearInterval(interval);interval=null;}
  const btn=$('#tp-motion-play');
  if(btn)btn.textContent='Play historical years';
}

function mountControls() {
  let host=$('#tp-motion-controls');
  if(host)return;
  host=document.createElement('div');
  host.id='tp-motion-controls';
  host.className='ts tp-motion-controls';
  host.dataset.t='motion';
  host.innerHTML=`<h4>Observed glacier motion</h4>
    <p>Historical annual surface speed (NASA ITS_LIVE) from glacier candidates
    near five studied lakes. These are <strong>not animations of physical flow</strong>,
    and data availability differs by site.</p>
    <div class="g">Observation year · <b id="tp-motion-year">2024</b></div>
    <input type="range" id="tp-motion-range" min="${YEAR_MIN}" max="${YEAR_MAX}" value="${YEAR_MAX}" step="1">
    <button type="button" class="btn tp-motion-play" id="tp-motion-play">Play historical years</button>
    <p id="tp-motion-status" aria-live="polite">Loading observed annual speed…</p>
    <p style="font-size:12px;color:#5f6f8c">Motion is visualized by marker size and time-series values only.
    There is no measured flow direction in this scalar summary dataset.</p>`;
  $('#tTime').appendChild(host);
  $('#tp-motion-range').oninput=e=>{
    stop();updateYear(Number(e.target.value));
  };
  $('#tp-motion-play').onclick=()=>{
    if(interval){stop();return;}
    $('#tp-motion-play').textContent='Pause timeline';
    interval=setInterval(()=>{
      if(!snapshot || !document.getElementById('c_motion')?.checked){stop();return;}
      updateYear(snapshot.year>=YEAR_MAX?YEAR_MIN:snapshot.year+1);
    },900);
  };
  const localTitle=$('#tFocus');
  if(localTitle && snapshot)host.classList.add('show');
}
document.addEventListener('click',e=>{
  const button=e.target.closest('button[data-glof-site]');
  if(!button)return;
  window.TerraPulseOpenGlof?.(button.dataset.glofSite);
});

export async function createMotionLayer() {
  const catalog=await json('/api/glof');
  if(!Array.isArray(catalog.sites)||catalog.sites.length<1)
    throw Error('Published glacial lake catalog is unavailable.');
  const details=await Promise.allSettled(catalog.sites.map(site=>
    json('/api/glof?site='+encodeURIComponent(site.site_id))));
  const group=L.layerGroup(),entries=[];
  for(let i=0;i<catalog.sites.length;i++){
    const site=catalog.sites[i],outcome=details[i];
    if(outcome.status!=='fulfilled')continue;
    const detail=outcome.value;
    const lat=Number(site.lat),lon=Number(site.lon);
    if(!Number.isFinite(lat)||!Number.isFinite(lon))continue;
    const mark=L.circleMarker([lat,lon],{
      radius:6,weight:2,color:'#0955ad',fillColor:'#18a8d9',
      fillOpacity:.8,
    }).addTo(group);
    entries.push({site,detail,marker:mark});
  }
  if(!entries.length)throw Error('All glacier motion source responses were unavailable.');
  stop();
  snapshot={entries,layer:group,year:YEAR_MAX};
  mountControls();
  updateYear(YEAR_MAX);
  group.on('remove',stop);
  // Show a regional, interpretable subset initially rather than all-site worldwide.
  const host=$('#tTime');
  if(host)host.dataset.motionReady='true';
  return group;
}

export function stopGlacierMotion() {stop();}
