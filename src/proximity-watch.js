import {proximityReview,distanceKm} from './proximity-core.js';
import {fetchHazardFeed} from './hazard-feeds.js';

const esc=t=>String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=t=>t?new Date(t).toLocaleString():'Unknown';
const meters=n=>Number.isFinite(n)?n.toFixed(0)+' m':'Not mapped';

export function initializeProximityWatch(TP) {
  const root=document.createElement('section');
  root.className='proximity-watch';root.id='landslide-proximity';
  root.innerHTML=`<div class="section-meta">Landslide proximity</div>
    <h3>Is a landslide site close to people?</h3>
    <p>Check mapped buildings, roads, schools and clinics around a documented or suspected site. These are signs of human activity; occupancy and debris paths remain unknown.</p>
    <form id="proximity-form" class="proximity-form">
      <label>Site name<input id="proximity-name" type="text" maxlength="80" value="Nominated landslide site" required></label>
      <label>Latitude<input id="proximity-lat" type="number" min="-80" max="80" step="any" required placeholder="e.g. 28.29"></label>
      <label>Longitude<input id="proximity-lon" type="number" min="-180" max="180" step="any" required placeholder="e.g. 85.53"></label>
      <button class="btn tp-outline" id="proximity-center" type="button">Use map center</button>
      <button class="btn" id="proximity-check" type="submit">Check proximity</button>
    </form>
    <label class="r"><input type="checkbox" id="proximity-watch"> Watch new NASA EONET point reports within 5 km of this site</label>
    <p class="field-note">New qualifying reports show an on-page review alert. Use the notification and sound controls below for optional browser feedback. Watch checks every 10 minutes while this page is open. Only reports dated within 48 hours qualify. Regional polygons and historical archives cannot trigger this watch. Site coordinates stay in this session; a check sends the query point to the OSM provider.</p>
    <div id="proximity-status" role="status" aria-live="polite">Choose a site to begin</div>
    <div id="proximity-result" aria-live="polite"></div>`;
  document.querySelector('#aGlobal').before(root);
  const $=s=>root.querySelector(s);
  let busy=false,seen=new Set(),baseline=false,generation=0;
  const coords=()=>{
    const lat=$('#proximity-lat').value,lon=$('#proximity-lon').value;
    if(!lat.trim()||!lon.trim())throw Error('Enter the latitude and longitude of a documented or suspected landslide');
    const site={lat:Number(lat),lon:Number(lon)};
    if(!Number.isFinite(site.lat)||!Number.isFinite(site.lon)||Math.abs(site.lat)>80||Math.abs(site.lon)>180)throw Error('Use valid coordinates between 80°S and 80°N');
    return site;
  };
  $('#proximity-center').onclick=()=>{
    const c=TP.map.getCenter();$('#proximity-lat').value=c.lat.toFixed(5);$('#proximity-lon').value=c.lng.toFixed(5);
  };
  async function inspect(site,provenance='Manually nominated site · landslide not automatically verified') {
    const requestGeneration=generation,siteName=$('#proximity-name').value;
    const query=new URLSearchParams({...site,radius_m:500});
    const response=await fetch('/api/exposure?'+query,{signal:AbortSignal.timeout(24000)});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'OSM source unavailable');
    if(requestGeneration!==generation)return null;
    const review=proximityReview(result),n=result.nearest_m;
    $('#proximity-result').innerHTML=`<article class="proximity-result ${review.alert?'needs-review':''}">
      <div class="section-meta">${review.alert?'Proximity review alert':'Screening result'}</div>
      <h4>${esc(review.title)}</h4><p>${esc(siteName)} · ${site.lat.toFixed(5)}, ${site.lon.toFixed(5)}</p>
      <dl><div><dt>Nearest mapped building</dt><dd>${meters(n.buildings)}</dd></div><div><dt>Nearest school / clinic</dt><dd>${meters(n.sensitive_places)}</dd></div><div><dt>Nearest road</dt><dd>${meters(n.roads)}</dd></div></dl>
      <p>${esc(provenance)}</p><p class="field-note">OSM source: ${esc(date(result.osm_timestamp))} · ${esc(result.availability?.mode||'provider response')} · checked ${esc(date(Date.now()))}. Buildings within 150 m or schools/clinics within 100 m trigger human-activity review; roads within 150 m trigger access review. These are experimental screening thresholds.</p>
      <p><strong>People present: unknown. Debris impact: unknown.</strong> Missing assets cannot establish safety. <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors · ODbL</a></p>
    </article>`;
    return review;
  }
  $('#proximity-form').onsubmit=async e=>{
    e.preventDefault();if(busy)return;generation++;busy=true;$('#proximity-check').disabled=true;
    $('#proximity-result').innerHTML='';$('#proximity-status').textContent='Checking mapped assets within 500 m…';
    try{const review=await inspect(coords());$('#proximity-status').textContent=review?'Proximity check complete':'Site changed · run a new check'}
    catch(e){$('#proximity-status').textContent='Exposure unknown · '+(e.name==='TimeoutError'?'OSM request timed out':e.message)}
    finally{busy=false;$('#proximity-check').disabled=false}
  };
  async function tick() {
    if(!$('#proximity-watch').checked||busy||document.hidden)return;
    busy=true;
    try {
      const site=coords();$('#proximity-status').textContent='Checking current NASA landslide reports…';
      const feed=await fetchHazardFeed({hazard:'ls'});
      if(feed.status!=='ok'||feed.archive_only)throw Error('Current report feed unavailable');
      const recent=feed.records.filter(r=>Date.now()-r.time<=48*3600000&&r.time<=Date.now()&&distanceKm(site,r)<=5);
      const fresh=recent.filter(r=>!seen.has(r.id));
      const wasBaseline=baseline;baseline=true;
      if(!wasBaseline)recent.forEach(r=>seen.add(r.id));
      $('#proximity-status').textContent=`Checked ${date(Date.now())} · ${recent.length} recent point reports within 5 km${wasBaseline?'':' · baseline established'}`;
      // Initial reports establish the baseline; use the manual check for existing sites.
      if(!wasBaseline)return;
      // Bound external queries; retry a source failure on the next poll.
      for(const event of fresh.slice(0,3)) {
        const review=await inspect(event,'NASA EONET report: '+event.title+' · '+date(event.time));
        seen.add(event.id);
        if(review?.alert){TP.toast('New landslide report close to mapped human activity · review the Alarm panel');window.TerraPulseAlarm?.notifyProximityReview?.(event)}
      }
    }catch(e){$('#proximity-status').textContent='Watch unavailable · '+e.message}
    finally{busy=false}
  }
  $('#proximity-watch').onchange=()=>{baseline=false;seen.clear();if($('#proximity-watch').checked)tick();else $('#proximity-status').textContent='Report watch off'};
  for(const id of ['#proximity-lat','#proximity-lon'])$(id).onchange=()=>{generation++;baseline=false;seen.clear();$('#proximity-watch').checked=false;$('#proximity-result').innerHTML='';$('#proximity-status').textContent='Site changed · run a new check'};
  window.addEventListener('tp:proximity-site',event=>{
    const site=event.detail;
    if(![site?.lat,site?.lon].every(Number.isFinite)||Math.abs(site.lat)>80||Math.abs(site.lon)>180)return;
    generation++;baseline=false;seen.clear();$('#proximity-watch').checked=false;
    $('#proximity-lat').value=site.lat.toFixed(6);$('#proximity-lon').value=site.lon.toFixed(6);
    $('#proximity-name').value=String(site.name||'Nominated landslide site').slice(0,80);
    $('#proximity-result').innerHTML='';$('#proximity-status').textContent='Site copied from exposure screening · check proximity to create a review receipt';
  });
  setInterval(tick,600000);document.addEventListener('visibilitychange',tick);
}
