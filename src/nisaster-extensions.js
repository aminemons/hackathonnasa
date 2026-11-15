import './nisaster-extensions.css';
import {initializeAlarmSystem} from './alarm-system.js';
import {loadCountriesLocal,loadPlateBoundariesLocal} from './geo-sources.js';

const TP = window.TerraPulseMap;
if (!TP?.map) throw new Error('NISASTER reference map did not initialize');

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = x => Number.isFinite(x) ? (x * 100).toFixed(1) + '%' : 'N/A';
const score = x => typeof x === 'number' && Number.isFinite(x) ? x.toFixed(4) : 'No data';
let activeLayer = null;
let lastExposure = null;
let lastScar = null;
let lastFocus = document.activeElement;

const overlay = document.createElement('div');
overlay.id = 'tp-overlay';
overlay.setAttribute('aria-hidden', 'true');
overlay.innerHTML = '<section id="tp-dialog" role="dialog" aria-modal="true" aria-labelledby="tp-title">' +
  '<header class="tp-head"><div><h2 id="tp-title"></h2><small id="tp-subtitle"></small></div>' +
  '<button type="button" id="tp-close">Close ×</button></header>' +
  '<div class="tp-body" id="tp-body"></div></section>';
document.body.appendChild(overlay);
$('#tp-close').onclick = close;
overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && overlay.classList.contains('on')) close();
});
function close() {
  overlay.classList.remove('on');
  overlay.setAttribute('aria-hidden', 'true');
  if (lastFocus && lastFocus.isConnected) lastFocus.focus();
}
function open(title, subtitle, html) {
  lastFocus = document.activeElement;
  $('#tp-title').textContent = title;
  $('#tp-subtitle').textContent = subtitle;
  $('#tp-body').innerHTML = html;
  overlay.classList.add('on');
  overlay.setAttribute('aria-hidden', 'false');
  $('#tp-close').focus();
}
function output(html) {
  const target = $('#tp-result');
  if (target) target.innerHTML = html;
}
function requestAbort(ms = 25000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ms);
  return {signal: controller.signal, finish: () => clearTimeout(timeout)};
}
async function getJSON(url, options = {}) {
  const timer = requestAbort();
  try {
    const response = await fetch(url, {...options, signal: timer.signal});
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Service returned an unexpected response');
    }
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'Service unavailable (' + response.status + ')');
    return body;
  } finally { timer.finish(); }
}
function center() {
  const c = TP.map.getCenter();
  return {lon: c.lng, lat: c.lat};
}
function inputCoords() {
  const lon = Number($('#tp-lon')?.value), lat = Number($('#tp-lat')?.value);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) throw new Error('Use valid latitude and longitude.');
  return {lon, lat};
}
function setMapCenter() {
  const c = center();
  if ($('#tp-lon')) $('#tp-lon').value = c.lon.toFixed(5);
  if ($('#tp-lat')) $('#tp-lat').value = c.lat.toFixed(5);
}
function controls(latMin = -60, latMax = 60) {
  const c = center();
  const lat = Math.max(latMin, Math.min(latMax, c.lat));
  return `<form id="tp-form" class="tp-controls">
    <label>Longitude<input id="tp-lon" type="number" step="any" min="-180" max="180" required value="${c.lon.toFixed(5)}"></label>
    <label>Latitude<input id="tp-lat" type="number" step="any" min="${latMin}" max="${latMax}" required value="${lat.toFixed(5)}"></label>
    <button type="button" class="tp-btn secondary" id="tp-use-center">Map center</button>
    <button type="submit" class="tp-btn" id="tp-submit">Analyze location</button>
  </form><div id="tp-result" aria-live="polite"></div>`;
}
function attachCoords(action) {
  $('#tp-use-center').onclick = setMapCenter;
  $('#tp-form').onsubmit = async e => {
    e.preventDefault();
    const button = $('#tp-submit');
    button.disabled = true;
    output('<div class="tp-output">Retrieving scientific data…</div>');
    try { await action(inputCoords()); }
    catch (error) {
      output(`<div class="tp-note" role="alert">${escape(error.message)}. No safety conclusion is possible when data are missing.</div>`);
    } finally { button.disabled = false; }
  };
}
function clearAnalysisLayer() {
  if (activeLayer) {
    TP.map.removeLayer(activeLayer);
    activeLayer = null;
  }
}
function toggleMapLayer(layer) {
  clearAnalysisLayer();
  activeLayer = layer.addTo(TP.map);
  TP.go('Map');
  close();
  setTimeout(() => TP.map.invalidateSize(), 100);
}
function showForecast() {
  open('Landslide hazard forecast', 'NASA LHASA · next-day rainfall-triggered hazard · ~1 km',
    '<p>Choose an area to retrieve NASA’s published Hazard Tomorrow raster. Its numbers are <strong>model hazard scores</strong>, not locally calibrated landslide probabilities.</p>' +
    controls() +
    '<div class="tp-note">The public feed does not expose the precise issue/validity time. Retrieval time must not be mistaken for forecast issuance.</div>');
  attachCoords(async ({lon,lat}) => {
    const r = await getJSON('/api/forecast?' + new URLSearchParams({lon,lat}));
    const image = String(r.preview_png ?? '');
    if (!image.startsWith('data:image/png;base64,')) throw new Error('NASA preview image was invalid');
    output(`<div class="tp-output">
      <div class="tp-stats"><div class="tp-stat"><b>${score(r.point_value)}</b><span>Cell model score</span></div>
      <div class="tp-stat"><b>${score(r.peak_value)}</b><span>Highest regional score</span></div>
      <div class="tp-stat"><b>${Number(r.valid_pixels||0).toLocaleString()}</b><span>Valid raster cells</span></div></div>
      <div style="display:flex;align-items:center;gap:15px;flex-wrap:wrap;margin-top:12px">
        <img alt="NASA LHASA hazard raster" width="144" height="144" style="image-rendering:pixelated;border:1px solid #dbe3f1" src="${image}">
        <div><p>Retrieved ${escape(r.retrieved_at)} UTC.<br>NASA issue and valid time are not provided here.</p>
        <button type="button" id="tp-forecast-map" class="tp-btn">Show hazard raster on map</button></div>
      </div></div>`);
    $('#tp-forecast-map').onclick = () => {
      if (!Array.isArray(r.bounds) || r.bounds.length !== 4) return;
      const b = r.bounds, bbox = [[b[1],b[0]],[b[3],b[2]]];
      toggleMapLayer(L.imageOverlay(r.preview_png, bbox, {opacity:.78,alt:'NASA LHASA forecast'}));
      TP.map.fitBounds(bbox, {maxZoom:9});
    };
  });
}
function drawTile(canvas, result, view) {
  const ctx = canvas.getContext('2d');
  const w = result.width, h = result.height;
  canvas.width = w; canvas.height = h;
  const image = ctx.createImageData(w,h);
  const labels = result.labels, rgb = result.rgb;
  for (let i=0;i<w*h;i++) {
    const value = result.scores[i], predicted = value !== null && value >= result.threshold;
    const truth = Array.isArray(labels) && labels[i] === 1;
    const j = i*4, k = i*3;
    let color = Array.isArray(rgb) ? [rgb[k],rgb[k+1],rgb[k+2]] : [91,108,120];
    if (view==='reference' && truth) color=[51,188,147];
    if (view==='prediction' && predicted) color=[245,161,55];
    if (view==='errors' && Array.isArray(labels)) {
      if (predicted&&truth) color=[35,185,131];
      else if (predicted&&!truth) color=[247,168,56];
      else if (!predicted&&truth) color=[233,70,83];
    }
    image.data[j]=color[0]??0;
    image.data[j+1]=color[1]??0;
    image.data[j+2]=color[2]??0;
    image.data[j+3]=value === null ? 85 : 255;
  }
  ctx.putImageData(image,0,0);
}
function displayScar(result) {
  lastScar = result;
  const evaluation = result.example_evaluation;
  const views = Array.isArray(result.labels) && Array.isArray(result.rgb)
    ? [['satellite','Satellite imagery'],['reference','Reference landslide mask'],['prediction','Model prediction'],['errors','Correct / false / missed']]
    : [['prediction','Predicted scar candidates']];
  output(`<div class="tp-output">
    <h3>${escape(result.id || 'Uploaded prepared satellite tile')}</h3>
    <div class="tp-four">${views.map(([key,label])=>
      `<figure><figcaption>${label}</figcaption><canvas data-tp-canvas="${key}" aria-label="${label}" role="img"></canvas></figure>`).join('')}</div>
    <p class="tp-error-key"><strong>Green</strong>: true scar pixel · <strong>Orange</strong>: false alarm · <strong>Red</strong>: missed scar</p>
    ${evaluation ? `<div class="tp-stats">
      <div class="tp-stat"><b>${pct(evaluation.f1)}</b><span>F1 · this one tile</span></div>
      <div class="tp-stat"><b>${pct(evaluation.precision)}</b><span>Precision · this tile</span></div>
      <div class="tp-stat"><b>${pct(evaluation.recall)}</b><span>Recall · this tile</span></div></div>
      <p>Correct scar pixels: ${evaluation.tp.toLocaleString()} · False alarms: ${evaluation.fp.toLocaleString()} · Missed: ${evaluation.fn.toLocaleString()}.</p>` : ''}
    <p><strong>Scar review priority:</strong> ${escape(result.screening?.review_priority || 'unavailable')}.
      Based on connected predicted pixels—not slope stability, damage, risk, or people.</p>
    <div class="tp-note">This identifies disturbed ground <strong>after</strong> a landslide. It does not predict a future landslide or how dangerous the area is.</div>
    ${result.candidate_location ? '<button id="tp-check-exposure" type="button" class="tp-btn" style="margin-top:12px">Inspect buildings near candidate</button>' : '<p>Benchmark chips have no verified geographic position; buildings cannot be inferred from this image.</p>'}
  </div>`);
  for (const [view] of views) drawTile($(`[data-tp-canvas="${view}"]`),result,view);
  if (result.candidate_location) $('#tp-check-exposure').onclick = () => {
    const p=result.candidate_location;
    showExposure({lon:p.lon,lat:p.lat},p.image_source);
  };
}
function showScar() {
  open('Detect landslide scars', 'Sentinel-2 + terrain · post-event U-Net · experimental',
    '<p>A scar is the ground disturbed <strong>after</strong> material slides down a slope. Compare the model against a labelled image, or upload a prepared 14-channel Landslide4Sense JSON tile.</p>' +
    '<div class="tp-stats"><div class="tp-stat"><b>66.2%</b><span>F1 · pooled 80-chip benchmark</span></div>' +
    '<div class="tp-stat"><b>66.9%</b><span>Benchmark precision</span></div>' +
    '<div class="tp-stat"><b>65.6%</b><span>Benchmark recall</span></div></div>' +
    '<div class="tp-controls"><button type="button" class="tp-btn" id="tp-run-example">Compare held-out example</button>' +
    '<label>Prepared JSON tile<input id="tp-tile-file" type="file" accept=".json,application/json"></label></div>' +
    '<div id="tp-result" aria-live="polite"></div>' +
    '<div class="tp-note">This optical model does not use NISAR inputs. It was evaluated on a limited benchmark subset; independent country-level validation is missing.</div>');
  $('#tp-run-example').onclick = async () => {
    $('#tp-run-example').disabled = true;
    output('<div class="tp-output">Running ONNX inference on the held-out example…</div>');
    try { displayScar(await getJSON('/api/landslide?example=1')); }
    catch(e) { output(`<div class="tp-note" role="alert">${escape(e.message)}</div>`); }
    finally { $('#tp-run-example').disabled = false; }
  };
  $('#tp-tile-file').onchange = async e => {
    const file=e.target.files[0]; if(!file)return;
    if(file.size>4_000_000) { output('<div class="tp-note">Maximum JSON file size is 4 MB.</div>');return; }
    output('<div class="tp-output">Evaluating uploaded 14-channel tile…</div>');
    try {
      const contents = await file.text();
      const result = await getJSON('/api/landslide',
        {method:'POST',headers:{'Content-Type':'application/json'},body:contents});
      displayScar(result);
    } catch(e) { output(`<div class="tp-note" role="alert">${escape(e.message)}</div>`); }
  };
}
function showExposure(coords=null, provenance='User-nominated location; not a verified scar') {
  open('Human exposure near a landslide', 'OpenStreetMap building footprints, roads and sensitive facilities',
    '<p>Check whether mapped assets are <strong>near a nominated landslide location</strong>. Proximity is an inspection priority; it is not a prediction of debris impact or whether any building is safe.</p>' +
    controls(-80,80).replace('</form>','<label>Radius<select id="tp-radius"><option value="250">250 m</option><option selected value="500">500 m</option><option value="600">600 m</option></select></label></form>')+
    `<div class="tp-note">Location source: ${escape(provenance)}. OpenStreetMap may be incomplete; no mapped buildings does not mean no people.</div>`);
  if(coords){$('#tp-lon').value=coords.lon.toFixed(6);$('#tp-lat').value=coords.lat.toFixed(6);}
  attachCoords(async ({lon,lat}) => {
    const radius_m=Number($('#tp-radius').value);
    const r=await getJSON('/api/exposure?'+new URLSearchParams({lon,lat,radius_m}));
    lastExposure=r;
    const c=r.counts||{}, near=r.nearest_m||{};
    output(`<div class="tp-output">
      <h3>Human exposure review: ${escape(r.human_exposure_review_priority)}</h3>
      <p>${escape(r.explanation)}</p>
      <div class="tp-stats">
        <div class="tp-stat"><b>${Number(c.buildings_within_150m||0)}</b><span>Buildings within 150 m</span></div>
        <div class="tp-stat"><b>${Number(c.roads_within_150m||0)}</b><span>Roads within 150 m</span></div>
        <div class="tp-stat"><b>${Number(c.sensitive_places_within_100m||0)}</b><span>Schools / clinics within 100 m</span></div>
      </div>
      <p>Nearest mapped building: ${Number.isFinite(near.buildings)?near.buildings+' m':'unknown'}.
      Source OSM timestamp: ${escape(r.osm_timestamp||'unknown')}.</p>
      <button class="tp-btn" id="tp-show-assets" type="button">Show buildings and roads on map</button>
      <div class="tp-note">This is <strong>NOT a danger rating</strong>. No downslope debris runout, occupancy or building vulnerability has been measured. An incomplete OSM map never establishes safety.</div>
      <div class="tp-links"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors · ODbL</a></div>
    </div>`);
    $('#tp-show-assets').onclick = () => {
      if (r.osm_geojson?.features) {
        const group=L.layerGroup();
        L.geoJSON(r.osm_geojson,{
          style: f => ({
            color:f.properties.kind==='buildings'?'#ffb02e':'#1450ab',
            weight:f.properties.kind==='buildings'?1.3:2.6,
            fillColor:'#ffb02e',fillOpacity:.4
          }),
          pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:5,color:'#ff6b35',weight:2}),
          onEachFeature:(f,l)=>l.bindPopup('OSM '+escape(f.properties.kind)+' · distance '+Number(f.properties.distance_m).toFixed(1)+' m')
        }).addTo(group);
        L.circleMarker([lat,lon],{color:'#d62828',radius:8,weight:2,fillColor:'#ff6b35',fillOpacity:.9})
          .bindPopup('Nominated review location, NOT confirmed landslide').addTo(group);
        toggleMapLayer(group);
        TP.map.setView([lat,lon],14);
        TP.toast('OSM assets shown: nearby is not automatically in the landslide path.');
      }
    };
  });
}
function showNISAR() {
  open('Real NISAR radar evidence', 'Himalayas · L-band GCOV · 30 October to 11 November 2026',
    '<p>Inspect <strong>real calibrated radar backscatter</strong> and its change. Both observations are <strong>after</strong> the August Rasuwa rock–ice avalanche; they do not detect that August event.</p>' +
    '<div class="tp-controls" id="tp-radar-buttons">' +
    ['before','after','change','candidates'].map(k=>
      `<button class="tp-btn secondary" type="button" data-radar="${k}">${k==='candidates'?'Change candidates':k[0].toUpperCase()+k.slice(1)}</button>`).join('') +
    '</div><img id="tp-radar-img" class="tp-radar-img" alt="Real NISAR GCOV measurement" src="/data/nisar-rasuwa/change.png">' +
    '<div class="tp-note">Significant radar changes are not proof of a landslide. This is independent radar evidence, not the input to the Sentinel-2 U-Net.</div>' +
    '<div class="tp-links"><a target="_blank" rel="noopener" href="https://cmr.earthdata.nasa.gov/search/concepts/G4405167589-ASF.umm_json">First granule</a><a target="_blank" rel="noopener" href="https://cmr.earthdata.nasa.gov/search/concepts/G4411492899-ASF.umm_json">Second granule</a></div>');
  $('#tp-radar-buttons').onclick = e => {
    const key=e.target.dataset.radar;
    if(['before','after','change','candidates'].includes(key)){
      $('#tp-radar-img').src='/data/nisar-rasuwa/'+key+'.png';
      $('#tp-radar-img').alt='Real NISAR '+key+' radar measurement, not verified landslide detection';
    }
  };
}
// Ishaq's historical GLOF evidence: React only supplies the research panel.
// The public map stays Meryem's original Leaflet map, never a second canvas.
let glofReady = null;
function showGlof(requestedSite = null) {
  if (!glofReady) {
    TP.toast('Loading the five-lake GLOF observatory…');
    glofReady = Promise.all([
      import('react'),
      import('react-dom/client'),
      import('./GlofPanel.jsx'),
    ]).then(([React, ReactDOM, view]) => {
      const host = document.createElement('div');
      host.id = 'tp-glof-root';
      document.body.appendChild(host);
      ReactDOM.flushSync
        ? ReactDOM.flushSync(() => ReactDOM.createRoot(host).render(React.createElement(view.default)))
        : ReactDOM.createRoot(host).render(React.createElement(view.default));
      return host;
    }).catch(error => {
      glofReady = null;
      throw error;
    });
  }
  glofReady.then(() => {
    // React 19 schedules the initial render; wait until dialog exists.
    let attempts = 0;
    const openPanel = () => {
      const dialog = document.getElementById('glof-monitor');
      if (dialog) {
        if (requestedSite && typeof requestedSite === 'string') {
          window.dispatchEvent(new CustomEvent('tp:glof-open', {detail:{site:requestedSite}}));
        }
        if(!dialog.open) dialog.showModal();
      }
      else if (!dialog && attempts++ < 15) requestAnimationFrame(openPanel);
      else if (!dialog) TP.toast('GLOF view did not mount. Refresh the app and try again.');
    };
    requestAnimationFrame(openPanel);
  }).catch(error => {
    TP.toast('Unable to load GLOF view: '+error.message);
  });
}
window.TerraPulseOpenGlof = showGlof;
window.TerraPulseGlofMap = (site, geometry, date) => {
  if (!TP.map || !site || !geometry || geometry.type !== 'FeatureCollection'
      || !Array.isArray(geometry.features)) return false;
  const source = L.geoJSON(geometry, {
    style: feature => {
      const kind = feature?.properties?.layer;
      const color = kind === 'glacial_lake' ? '#17b8d1'
        : kind === 'historical_lake_inventory' ? '#f5aa35'
        : '#8fa4b5';
      return {color, weight:2, fillColor:color, fillOpacity:0.32};
    },
    pointToLayer: (feature,latlng)=>L.circleMarker(latlng,{
      color:'#1150a2', radius:4, fillColor:'#17b8d1',fillOpacity:.8,
    }),
    onEachFeature: (feature, layer) => {
      const kind = String(feature?.properties?.layer || 'historical context');
      const dateValue = String(feature?.properties?.date || 'Date unavailable');
      const holder = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = kind.replaceAll('_',' ');
      holder.appendChild(title);
      const detail = document.createElement('p');
      detail.textContent = 'Source date: ' + dateValue;
      holder.appendChild(detail);
      layer.bindPopup(holder);
    },
  });
  toggleMapLayer(source);
  if (Array.isArray(site.lake_bbox) && site.lake_bbox.length===4) {
    const [west,south,east,north] = site.lake_bbox.map(Number);
    if ([west,south,east,north].every(Number.isFinite))
      TP.map.fitBounds([[south,west],[north,east]],{padding:[25,25],maxZoom:12});
  } else {
    TP.map.setView([site.lat,site.lon],11);
  }
  TP.toast('GLOF: '+site.name+' · radar date '+date+' · monitoring only, not a breach warning.');
  return true;
};
const tools={forecast:showForecast,scar:showScar,exposure:showExposure,nisar:showNISAR,glof:showGlof};
$('#ds').addEventListener('click',event=>{
  const button=event.target.closest('[data-tp-open]');
  if(button&&tools[button.dataset.tpOpen]){event.preventDefault();tools[button.dataset.tpOpen]();}
});

// LangGraph-backed tool router. Only permit explicit safe actions in the browser.
const legalPanels=new Set(Object.keys(tools));
const legalTabs=new Set(['Dataset','Time','Legend','Alarm']);
const legalPages=new Set(['Map','How','Sources','Alarm']);
const legalBasemaps=new Set(['Satellite','Streets','Topographic']);
async function applyAction(action) {
  if(!action||typeof action!=='object')return;
  const kind=action.type, name=action.value;
  if(kind==='open_tool'&&legalPanels.has(name)){tools[name]();return;}
  if(kind==='basemap'&&legalBasemaps.has(name)){TP.setBase(name);return;}
  if(kind==='tab'&&legalTabs.has(name)){TP.openTab(name);return;}
  if(kind==='page'&&legalPages.has(name)){TP.go(name);return;}
  if(kind==='clear'){TP.clearAll();return;}
  if(kind==='layer'&&TP.DS.some(d=>d.id===name)) {
    await TP.setLayer(name,action.enabled===true);return;
  }
  if(kind==='zoom'&&Number.isFinite(action.lon)&&Number.isFinite(action.lat)
      &&Math.abs(action.lat)<=85&&Math.abs(action.lon)<=180) {
    TP.go('Map');TP.map.setView([action.lat,action.lon],Math.min(10,Math.max(2,action.zoom||6)));return;
  }
  if(kind==='period'&&[1,7,30].includes(action.days))TP.setPeriod(action.days);
}
function chatSay(message,user=false){
  const el=document.createElement('div');
  el.className='msg '+(user?'me':'bot');
  el.textContent=String(message??'');
  $('#log').appendChild(el);
  $('#log').scrollTop=$('#log').scrollHeight;
}
let chatInFlight=false;
window.tpAsk=async raw=>{
  const prompt=String(raw||'').trim().slice(0,800);
  if(!prompt||chatInFlight)return;
  chatInFlight=true;
  chatSay(prompt,true);
  try{
    const r=await getJSON('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:prompt})});
    for(const action of (Array.isArray(r.actions)?r.actions.slice(0,3):[])) await applyAction(action);
    chatSay(r.reply||'I could not find a matching map tool.');
  }catch(e){
    chatSay('The assistant service is temporarily unavailable. The Dataset sidebar and map controls remain usable. ('+e.message+')');
  }finally{chatInFlight=false;}
};

// Mounted after the core Leaflet map and DOM have loaded. No automatic browser
// notifications or permission requests are performed on page load.
initializeAlarmSystem(TP);
TP.loadCountries(loadCountriesLocal).catch(error=>
  TP.toast('Country hover boundaries unavailable: '+error.message));
// Local plates come from a versioned packaged source, not GitHub live requests.
window.TerraPulseGeo={loadPlateBoundariesLocal};

