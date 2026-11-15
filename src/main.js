import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { observations } from './cases.js';
import { worldExplorer, globalFloodDate } from './world.js';
import { mountAssistant, normalize } from './assistant.js';
import { mountCatalog } from './catalog.js';
import { mountDiscovery } from './discovery.js';
import { drawImagery, imagery } from './imagery.js';
import { basemapStyle, addBasemap, setBasemap, addPlates, plateSource, projectWorld } from './basemap.js';

const asset = file => new URL(`${import.meta.env.BASE_URL}data/${file}`, location.origin).href;
const byId = id => document.getElementById(id);
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const getQuery = () => new URLSearchParams(location.search);
const hazards = ['Earthquakes','Floods','Glaciers'];
const selectedFromUrl = () => observations.find(item => item.id === getQuery().get('case')) ?? null;
const hazardFromUrl = () => hazards.find(item => item.toLowerCase() === getQuery().get('hazard')) ?? 'Earthquakes';
const modeFromUrl = item => item.modes.find(mode => mode.id === getQuery().get('layer'))?.id || item.modes[0].id;
let current = selectedFromUrl();
let hazard = current?.hazard ?? hazardFromUrl();
let mode = current ? modeFromUrl(current) : null;
let minMagnitude = 4;
let days = 7;
let plates = true;
let platesPromise;
let basemap = 'satellite';
let fallbackCenter;
let floodDate = globalFloodDate;
let floodTiles = false;
let imageryKey;
let imageryDate;
let map;
let maplibregl;
let popup;
let markers = [];
let overlay;
let mapReady = false;
let mapUnavailable = false;
let fallbackVersion = 0;
let quakePromise;
const grids = new Map();
let updateVersion = 0;
let focusedCase;
let choosingRadarPoint = false;
document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || !choosingRadarPoint) return;
  choosingRadarPoint = false;
  map.getCanvas().style.cursor = "";
  byId("map-note").textContent = "";
});
let fallbackSelection;

const regions = {
  Earthquakes: [['Algeria', 3, 36, 5], ['Japan', 138, 36, 5], ['California', -120, 36, 5], ['Chile', -71, -30, 5]],
  Floods: [['Algeria', 5, 36, 6], ['South Asia', 87, 25, 4], ['Southern Africa', 32, -23, 4]],
  Glaciers: [['Alps', 9, 46, 5], ['Himalaya', 83, 30, 5], ['Greenland', -41, 72, 4], ['Antarctica', -100, -75, 4]],
};
const world = worldExplorer({
  json, chooseCase:selectCase,
  onChange() {
    if (!current && !fallbackSelection) renderWorldCard();
  },
  inspect:showWorldPoint
});
function selectWorld(nextHazard) {
  if (hazard === nextHazard && !current) return;
  fallbackCenter = null;
  hazard = nextHazard;
  imageryKey = null;
  current = null;
  mode = null;
  fallbackSelection = null;
  setUrl(false);
  render();
}
function renderWorldCard() {
  const info = world.info(hazard,minMagnitude,floodDate,days);
  byId('record').innerHTML = `<h2 tabindex="-1" id="case-heading">${info.label}</h2><p class="time">${info.caption}</p>`;
  byId('evidence').innerHTML = `<div class="evidence-details"><h3 id="point-title" hidden></h3><p id="point-copy" aria-live="polite">${info.hint}</p></div><button type="button" class="quiet" data-sources>Sources</button>`;
}

function selectCase(id) {
  const found = observations.find(item => item.id === id);
  if (!found || found === current) return;
  current = found;
  fallbackSelection = null;
  hazard = current.hazard;
  mode = current.modes[0].id;
  setUrl(false);
  render();
}
byId('cases').addEventListener('click', event => {
  const button = event.target.closest('[data-hazard]');
  if (!button) return;
  selectWorld(button.dataset.hazard);
  byId('cases').querySelector('[aria-current=true]')?.focus({preventScroll:true});
});
window.addEventListener('popstate', () => {
  current = selectedFromUrl();
  hazard = current?.hazard ?? hazardFromUrl();
  mode = current ? modeFromUrl(current) : null;
  imageryKey = null;
  fallbackSelection = null;
  fallbackCenter = null;
  render();
});
function renderTabs() {
  byId('cases').innerHTML = hazards.map(item =>
    `<button class="tab" type="button" data-hazard="${item}" aria-current="${item===hazard}">${item}</button>`
  ).join('');
}
byId('map-controls').addEventListener('change', event => {
  if (event.target.id === 'magnitude') minMagnitude = Number(event.target.value);
  else if (event.target.id === 'quake-window') days = Number(event.target.value);
  else if (event.target.id === 'flood-date' && event.target.value) floodDate = event.target.value;
  else if (event.target.id === 'imagery-date' && event.target.value) imageryDate = event.target.value;
  else return;
  if (!current) {
    fallbackSelection = null;
    renderWorldCard();
    refreshCatalog();
    if (mapReady) updateMap();
    if (mapUnavailable) drawFallback();
    const layer = imagery[imageryKey];
    if (layer && mapReady && event.target.id === 'imagery-date') {
      byId('map-note').textContent = `${layer.title} · ${imageryDate}${imageryKey === 'radar' && map.getZoom() < 4 ? ' · visible from regional zoom' : ''}`;
    }
  }
});

byId('map-controls').addEventListener('click', event => {
  if (event.target.closest('[data-plates]')) {
    plates = !plates;
    render();
    byId('map-controls').querySelector('[data-plates]')?.focus();
    return;
  }
  if (event.target.closest('[data-world]')) {
    selectWorld(hazard);
    return;
  }
  if (event.target.closest('[data-flood-tiles]')) {
    floodTiles = !floodTiles;
    if (floodTiles) imageryKey = null;
    render();
    if (floodTiles && mapReady && map.getZoom() < 5) {
      byId('point-copy').textContent = 'Zoom in to see the VIIRS flood composite.';
    }
    byId('map-controls').querySelector('[data-flood-tiles]')?.focus();
    return;
  }
  const imageryButton = event.target.closest('[data-imagery]');
  if (imageryButton) {
    const key = imageryButton.dataset.imagery;
    setImagery(imageryKey === key ? null : key);
    byId('map-controls').querySelector(`[data-imagery="${key}"]`)?.focus();
    return;
  }
  const button = event.target.closest('[data-mode]');
  if (!button) return;
  openMode(button.dataset.mode);
  byId('map-controls').querySelector(`[data-mode="${mode}"]`)?.focus();
});
function openMode(nextMode) {
  if (nextMode === mode || !current?.modes.some(item => item.id === nextMode)) return;
  mode = nextMode;
  setUrl(true);
  render();
}

function setImagery(key) {
  imageryKey = key;
  imageryDate = imagery[key]?.latest;
  if (key) floodTiles = false;
  render();
}
byId('evidence').addEventListener('click', event => {
  if (!event.target.closest('[data-sources]')) return;
  const source = current ?? {...world.info(hazard,minMagnitude,floodDate,days),place:hazard};
  const layer = !current && imagery[imageryKey];
  const sources = [...source.sources];
  if (layer) sources.push(layer.source);
  if (!current && hazard === 'Earthquakes' && plates) sources.push(plateSource);
  byId('reference-content').innerHTML = `<h2>${source.place}</h2><p>${source.method}</p>${layer ? `<p class="imagery-note">${layer.title} · ${imageryDate}. ${layer.description}</p>` : ''}<ul>${
    sources.map(([label, url]) => `<li><a class="text-link" href="${url}" target="_blank" rel="noopener">${label}</a></li>`).join('')
  }</ul>`;
  byId('reference').showModal();
});

function setUrl(replace) {
  const url = new URL(location.href);
  url.searchParams.set('hazard',hazard.toLowerCase());
  if (current) {
    url.searchParams.set('case',current.id);
    url.searchParams.set('layer',mode);
  } else {
    url.searchParams.delete('case');
    url.searchParams.delete('layer');
  }
  history[replace ? 'replaceState' : 'pushState'](null,'',url);
}

function render() {
  renderTabs();
  const selectedLayer = current?.modes.find(item => item.id === mode);
  const stillImage = Boolean(selectedLayer?.compare || (mapUnavailable && selectedLayer?.image));
  byId('basemap-control').hidden = stillImage;
  byId('reset-map').hidden = stillImage;
  byId('regions').innerHTML = current ? '' : regions[hazard].map(([name], index) =>
    `<button class="quiet" type="button" data-region="${index}">${name}</button>`).join('');
  refreshCatalog();
  if (!current) {
    renderWorldCard();
    const options = [2.5,4,5,6].map(value => `<option value="${value}"${value===minMagnitude?' selected':''}>M${value.toFixed(1)}+</option>`).join('');
    const periods = [1,7,30].map(value => `<option value="${value}"${value===days?' selected':''}>${value} ${value===1?'day':'days'}</option>`).join('');
    const controls = {
      Earthquakes:`<label class="control">Time <select id="quake-window">${periods}</select></label><label class="control">Magnitude <select id="magnitude">${options}</select></label><button type="button" data-plates aria-pressed="${plates}">Plate boundaries</button>`,
      Floods:`<button type="button" data-flood-tiles aria-pressed="${floodTiles}">VIIRS floodwater</button>${floodTiles?`<label class="control">Date <input id="flood-date" type="date" min="2025-04-01" max="${globalFloodDate}" value="${floodDate}"></label>`:''}`,
      Glaciers:'',
    };
    const imageryControls = ['radar', ...({ Floods:['rain'], Glaciers:['snow'] }[hazard] ?? [])]
      .map(key => `<button type="button" data-imagery="${key}" aria-pressed="${key === imageryKey}">${imagery[key].title}</button>`).join('');
    const layer = imagery[imageryKey];
    byId('map-controls').innerHTML = controls[hazard] + imageryControls + (layer
      ? `<label class="control">Date <input id="imagery-date" type="date" min="${layer.first}" max="${layer.latest}" value="${imageryDate}"></label>` : '');
    const legends = {
      Earthquakes:`<div class="key-list"><span><i style="--key:#f3cf74;border-radius:50%"></i> Earthquake / cluster</span><span>◎ Radar case</span>${plates?'<span><i class="line-key" style="--key:#ffc086"></i> Plate boundary</span>':''}</div>`,
      Floods:'<div class="key-list"><span><i style="--key:#65c5fa;border-radius:50%"></i> GDACS flood report</span>'
        + (floodTiles ? '<span><i style="--key:#fa1e24"></i> Flood <i style="--key:#32d2f5"></i> Surface water</span><span><i style="--key:#ffff00"></i> Recurring flood <i style="--key:#afafaf"></i> Insufficient data</span>' : '')
        + '<span>◎ Detailed flood case</span></div>',
      Glaciers:'<div class="key-list"><span><i style="--key:#f39678"></i> Latest annual loss</span><span><i style="--key:#93bef5"></i> Latest zero or gain</span><span>◎ Detailed ice imagery</span></div>',
    };
    byId('legend').innerHTML = legends[hazard];
    byId('map-note').textContent = layer ? `${layer.title} · ${imageryDate}${imageryKey === 'radar' ? ' · visible from regional zoom' : ''}` : '';
    renderOverlay();
    if (mapReady) updateMap();
    if (mapUnavailable) drawFallback();
    return;
  }
  const selected = current.modes.find(item => item.id === mode);
  byId('record').innerHTML = `<h2 tabindex="-1" id="case-heading">${current.place}</h2><p class="time">${selected.date ?? current.date}</p>`;
  byId('map-controls').innerHTML = '<button type="button" data-world>← Worldwide</button>' +
    (current.modes.length > 1 ? current.modes.map(item => `<button type="button" data-mode="${item.id}" aria-pressed="${item.id===mode}">${item.label}</button>`).join('') : '');
  byId('evidence').innerHTML = `<div class="evidence-details"><h3 id="point-title">${selected.label}</h3><p id="point-copy" aria-live="polite">${selected.hint ?? current.evidence}</p></div><button type="button" class="quiet" data-sources>Sources</button>`;
  const legends = {
    displacement: '<strong>Displacement · cm</strong><div class="gradient"></div><div class="legend-values"><span>−50</span><span>0</span><span>+50</span></div>',
    shaking: '<strong>Shaking · MMI</strong>',
    extent: '<div class="key-list"><span><i style="--key:#ff7957"></i> Flood detected</span><span><i style="--key:#57b9f0"></i> Surface water</span><span><i style="--key:#f0d15f"></i> Recurring flood</span><span><i style="--key:#a5abb2"></i> Insufficient data</span></div>',
  };
  byId('legend').innerHTML = legends[mode] ?? '';
  byId('map-note').textContent = '';
  renderOverlay();
  if (mapReady) updateMap();
  if (mapUnavailable) drawFallback();
}

function renderOverlay() {
  overlay?.remove();
  overlay = null;
  if (!current) return;
  const selected = current.modes.find(item => item.id === mode);
  if (!selected?.compare && (!selected?.image || !mapUnavailable)) return;
  overlay = document.createElement('div');
  if (selected.compare) {
    const [first,second] = selected.compare;
    overlay.className = 'photo-compare';
    overlay.innerHTML = `<img alt="${escape(current.place)} · ${escape(first.label)}" src="${asset(first.image)}"><div class="second"><img alt="${escape(current.place)} · ${escape(second.label)}" src="${asset(second.image)}"></div><label class="swipe"><span>${escape(first.label)}</span><input type="range" min="0" max="100" value="50" aria-label="Compare ${escape(first.label)} with ${escape(second.label)}"><span>${escape(second.label)}</span></label>`;
    overlay.querySelector('input').addEventListener('input', event => overlay.style.setProperty('--divider', `${event.target.value}%`));
  } else {
    overlay.className = 'single-photo';
    overlay.innerHTML = `<img alt="${escape(current.title)}" src="${asset(selected.image)}">`;
    if (['displacement', 'extent'].includes(mode)) {
      overlay.classList.add('inspectable');
      overlay.addEventListener('click', inspectFallbackImage);
    }
  }
  byId('map-frame').insertBefore(overlay, byId('map-frame').querySelector('.map-tools'));
}

async function json(file) {
  const response = await fetch(asset(file));
  if (!response.ok) throw new Error(`Could not load ${file}`);
  return response.json();
}

const plateData = () => (platesPromise ||= json('plate-boundaries.json').catch(error => {
  platesPromise = null;
  throw error;
}));

function resetView() {
  fallbackCenter = null;
  if (!mapReady) { if (mapUnavailable) drawFallback(); return; }
  if (current) {
    map.fitBounds(current.bounds, { padding: 48, duration: 0, maxZoom: 11 });
    return;
  }
  const { clientWidth, clientHeight } = map.getContainer();
  const zoom = Math.log2(Math.max(180, Math.min(clientWidth - 40, clientHeight * 1.38)) / 512);
  map.jumpTo({ center: [0, 14], zoom });
}

byId('reset-map').addEventListener('click', resetView);
byId('basemap').addEventListener('change', event => {
  basemap = event.target.value;
  if (mapReady) setBasemap(map, basemap);
  else if (mapUnavailable) drawFallback();
});
byId('regions').addEventListener('click', event => {
  const button = event.target.closest('[data-region]');
  if (!button) return;
  const [, lon, lat, zoom] = regions[hazard][Number(button.dataset.region)];
  if (mapReady) map.easeTo({ center: [lon, lat], zoom, duration: 450 });
  else if (mapUnavailable) {
    fallbackCenter = { coords: [lon, lat], zoom };
    drawFallback();
  }
});

const openDiscovery = mountDiscovery({
  selectMapPoint() {
    if (!mapReady) return false;
    choosingRadarPoint = true;
    byId("map-note").textContent = "Click a location to search for NISAR observations.";
    map.getCanvas().style.cursor = "crosshair";
    return true;
  },
  showLandslides(coords, data) {
    if (!mapReady) return false;
    current = null;
    mode = null;
    focusedCase = "world";
    imageryKey = null;
    fallbackSelection = null;
    setUrl(false);
    map.jumpTo({center: coords, zoom: 9});
    render();
    const id = "coolr-outlines";
    map.addSource(id, {type:"geojson", data, attribution:"NASA COOLR"});
    map.addLayer({type:"line",id,source:id,paint:{"line-color":"#ffce78","line-width":2}});
    byId("map-note").textContent = "Mapped landslide outlines · NASA COOLR";
    return true;
  },
  showRadar(coords, date) {
    if (!mapReady) return false;
    current = null;
    mode = null;
    focusedCase = "world";
    fallbackSelection = null;
    imageryKey = "radar";
    imageryDate = date;
    setUrl(false);
    map.jumpTo({center: coords, zoom: 9});
    render();
    return true;
  },
});
byId("find-radar").onclick = () => {
  const center = mapReady ? map.getCenter() : {lng:0,lat:14};
  openDiscovery(center.lng, center.lat);
};

export function forecastMapCenter() {
  return mapReady ? map.getCenter().wrap() : null;
}

export function showForecastOnMap({ bounds, preview_png }) {
  if (!mapReady) return false;
  current = null;
  mode = null;
  focusedCase = "world";
  imageryKey = null;
  fallbackSelection = null;
  setUrl(false);
  render();
  const [west, south, east, north] = bounds;
  const id = "lhasa-forecast";
  map.addSource(id, {
    type: "image", url: preview_png,
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
  });
  map.addLayer({ id, type: "raster", source: id, paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 } });
  map.fitBounds([[west, south], [east, north]], { padding: 45, maxZoom: 10, duration: 0 });
  byId("map-note").textContent = "Next-day rainfall-triggered landslide hazard · NASA LHASA";
  byId("legend").innerHTML = '<strong>LHASA hazard score</strong><div class="hazard-gradient"></div><div class="legend-values"><span>Lower</span><span>Higher</span></div>';
  return true;
}

async function startMap() {
  try {
    maplibregl = await import('maplibre-gl');
    maplibregl.setWorkerUrl(workerUrl);
    map = new maplibregl.Map({
      container: 'map', style: basemapStyle, center: [0, 14], zoom: 1, attributionControl: false,
      renderWorldCopies: false, maxPitch: 0, minZoom: -2, maxZoom: 14, dragRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({showCompass:false}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({unit:'metric'}), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({compact:true}), 'bottom-right');
    map.on('click', event => {
      if (!choosingRadarPoint) return inspectPoint(event);
      choosingRadarPoint = false;
      map.getCanvas().style.cursor = '';
      byId('map-note').textContent = '';
      openDiscovery(event.lngLat.wrap().lng, event.lngLat.lat);
    });
    await new Promise(resolve => map.once('load', resolve));
  } catch {
    mapUnavailable = true;
    render();
    return;
  }
  addBasemap(map, asset('blue-marble.webp'));
  setBasemap(map, basemap);
  mapReady = true;
  map.on('moveend', () => {
    if (imageryKey === 'radar' && !current) {
      byId('map-note').textContent = `NISAR radar · ${imageryDate}${map.getZoom() < 4 ? ' · visible from regional zoom' : ''}`;
    }
  });
  updateMap();
}

function inspectFallbackImage(event) {
  const image = event.target.closest('img');
  if (!image?.naturalWidth) return;
  const rect = image.getBoundingClientRect();
  const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  const x = (event.clientX - rect.left - (rect.width - width) / 2) / width;
  const y = (event.clientY - rect.top - (rect.height - height) / 2) / height;
  if (x < 0 || y < 0 || x >= 1 || y >= 1) return;
  const [[w, s], [e, n]] = current.bounds;
  const mercator = lat => Math.asinh(Math.tan(lat * Math.PI / 180));
  const lat = Math.atan(Math.sinh((1 - y) * mercator(n) + y * mercator(s))) * 180 / Math.PI;
  inspectPoint({ lngLat: { lng: w + (e - w) * x, lat } });
}

function massBalanceChart(values) {
  const [first] = values[0];
  const [last] = values.at(-1);
  const left = 6;
  const right = 234;
  const top = 6;
  const bottom = 58;
  const high = Math.max(0, ...values.map(([, value]) => value));
  const low = Math.min(0, ...values.map(([, value]) => value));
  const x = year => first === last ? 120 : left + (year - first) * (right - left) / (last - first);
  const y = value => top + (high - value) * (bottom - top) / (high - low || 1);
  const baseline = y(0);
  const bars = values.map(([year, value]) => {
    const end = y(value);
    const label = `${year}: ${value > 0 ? '+' : ''}${value.toFixed(2)} m water equivalent`;
    return `<rect x="${x(year) - 3}" y="${Math.min(end, baseline)}" width="6" height="${Math.max(1, Math.abs(end - baseline))}" fill="${value < 0 ? '#f39678' : '#93bef5'}"><title>${label}</title></rect>`;
  });
  const block = document.createElement('figure');
  block.className = 'balance-chart';
  block.innerHTML = `<figcaption>Annual mass balance · m w.e.</figcaption><svg viewBox="0 0 240 65" aria-hidden="true"><line x1="0" x2="240" y1="${baseline}" y2="${baseline}" stroke="#a9bdba" stroke-opacity=".65"/>${bars.join('')}</svg><div class="chart-years"><span>${first}</span><span>${last === first ? '' : last}</span></div><details><summary>Annual values</summary><ul>${[...values].reverse().map(([year, value]) => `<li>${year} · ${value > 0 ? '+' : ''}${value.toFixed(2)}</li>`).join('')}</ul></details>`;
  return block;
}

function showFallbackDetail(item) {
  const title = byId('point-title');
  byId('evidence').querySelector('.balance-chart')?.remove();
  title.hidden = false;
  title.textContent = item.title;
  const description = byId('point-copy');
  description.textContent = item.description;
  for (const [label,url] of item.links) {
    const link = document.createElement('a');
    link.className = 'provider-link';
    link.textContent = label;
    link.href = url;
    description.append(link);
  }
  if (item.balances?.length) {
    byId('point-copy').after(massBalanceChart(item.balances));
  }
}

async function openEntry(entryHazard, id) {
  if (current || entryHazard !== hazard) selectWorld(entryHazard);
  if (mapReady) return world.open(entryHazard, id, map);
  await world.load(entryHazard);
  if (current || entryHazard !== hazard) return;
  const item = world.visibleItems(entryHazard, 0).find(row => row.id === id);
  if (item) {
    fallbackSelection = world.details(entryHazard, item);
    showFallbackDetail(fallbackSelection);
    if (mapUnavailable) { fallbackCenter = { coords: item.coords, zoom: 5 }; drawFallback(); }
  }
}

async function drawFallback() {
  const version = ++fallbackVersion;
  const panel = byId('map-fallback');
  panel.hidden = Boolean(current);
  byId('fallback-credit').hidden = Boolean(current);
  if (current) return;
  const selected = hazard;
  try {
    const showPlates = selected === 'Earthquakes' && plates;
    const [boundaries] = await Promise.all([
      showPlates ? plateData().catch(() => null) : null, world.load(selected),
    ]);
    if (version !== fallbackVersion || current) return;
    renderWorldCard();
    if (fallbackSelection) showFallbackDetail(fallbackSelection);
    const markers = world.visibleItems(selected, minMagnitude, days).map(item => {
      const [x,y] = projectWorld(item.coords);
      const color = selected === 'Glaciers' ? (item.balances.at(-1)[1] < 0 ? '#f39678' : '#93bef5')
        : selected === 'Floods' ? '#65c5fa' : '#f3cf74';
      const radius = fallbackCenter ? 1.6 : selected === 'Earthquakes' ? 3 : 4;
      return `<circle data-entry="${escape(item.id)}" cx="${x}" cy="${y}" r="${radius}" fill="${color}"><title>${escape(item.name)}</title></circle>`;
    }).join('');
    const samples = observations.filter(item => item.hazard === selected).map(item => {
      const [[w,s],[e,n]] = item.bounds;
      const [x,y] = projectWorld([(w+e)/2,(s+n)/2]);
      return `<circle data-case="${item.id}" cx="${x}" cy="${y}" r="${fallbackCenter ? 3 : 6}" fill="#171c23" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke"><title>${escape(item.place)} · radar case</title></circle>`;
    }).join('');
    const lines = boundaries?.coordinates.map(line => 'M' + line.map(point => projectWorld(point).join(',')).join('L')).join('') ?? '';
    let box = '0 75 1024 845';
    if (fallbackCenter) {
      const size = 1024 / 2 ** (fallbackCenter.zoom - 2);
      const [x, y] = projectWorld(fallbackCenter.coords).map(Number);
      const clamp = value => Math.max(0, Math.min(1024 - size, value - size / 2));
      box = `${clamp(x)} ${clamp(y)} ${size} ${size}`;
    }
    panel.innerHTML = `<svg viewBox="${box}" aria-label="${escape(selected)} world map"><image class="${basemap}" href="${asset('blue-marble.webp')}" width="1024" height="1024"/><path d="${lines}" fill="none" stroke="#ffc086" stroke-width="1.1" opacity=".84" vector-effect="non-scaling-stroke"/>${markers}${samples}</svg>`;
    if ((selected === 'Floods' && floodTiles) || imageryKey) {
      byId('map-note').textContent = 'Satellite overlays require WebGL. Dated case images remain available.';
    }
  } catch {
    if (version === fallbackVersion) panel.textContent = 'The observation catalog could not load.';
  }
}
byId('map-fallback').addEventListener('click',event=>{
  if (event.target.dataset.case) selectCase(event.target.dataset.case);
  if (event.target.dataset.entry) openEntry(hazard,event.target.dataset.entry).catch(() => {});
});

async function updateMap() {
  const version = ++updateVersion;
  popup?.remove();
  world.remove(map);
  markers.forEach(marker => marker.remove());
  markers = [];
  for (const id of ['scene','contours','regional-context','satellite-context','tectonic-plates','coolr-outlines','lhasa-forecast']) {
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }
  if (!current) {
    if (focusedCase !== 'world') {
      focusedCase = 'world';
      resetView();
    }
    if (hazard === 'Earthquakes' && plates) {
      plateData().then(data => { if (version === updateVersion) addPlates(map, data); }).catch(() => {
        if (version === updateVersion) byId('map-note').textContent = 'Plate boundaries could not load.';
      });
    }
    drawImagery(map, imagery[imageryKey], imageryDate);
    world.draw(map,hazard,minMagnitude,floodDate,observations.filter(entry=>entry.hazard===hazard),floodTiles,days)
      .catch(() => { if (version === updateVersion) byId('map-note').textContent='The observation catalog could not load.'; });
    return;
  }
  const [[w,s],[e,n]] = current.bounds;
  if (focusedCase !== current.id) {
    focusedCase = current.id;
    map.fitBounds(current.bounds,{padding:{top:70,right:24,bottom:100,left:24},duration:0,maxZoom:11});
  }
  if (mode === 'compare') return;
  const contexts = {
    'venezuela-earthquakes': ['ve', [-70, 8.1, -65, 12.65]],
    'mozambique-floods': ['mo', [31.75, -26.2, 34.95, -23.6]],
    'pine-island-glacier': ['pi', [-107, -76.35, -95, -73.6]],
  };
  const region = contexts[current.id];
  if (region) {
    const [context, [cw, cs, ce, cn]] = region;
    map.addSource('regional-context',{type:'image',url:asset(`context-${context}.webp`),coordinates:[[cw,cn],[ce,cn],[ce,cs],[cw,cs]]});
    map.addLayer({id:'regional-context',source:'regional-context',type:'raster',paint:{'raster-fade-duration':0, 'raster-opacity':.92}});
  }
  const selected = current.modes.find(item => item.id === mode);
  if (selected?.image) {
    map.addSource('scene',{type:'image',url:asset(selected.image),coordinates:[[w,n],[e,n],[e,s],[w,s]]});
    map.addLayer({id:'scene',source:'scene',type:'raster',paint:{'raster-fade-duration':0,'raster-opacity':mode==='displacement'?.84:1,'raster-resampling':['displacement','extent'].includes(mode)?'nearest':'linear'}});
  }
  for (const [lng,lat,label] of current.markers) {
    const element=document.createElement('div');
    element.className='place-marker';
    element.textContent=label;
    markers.push(new maplibregl.Marker({element,anchor:'left'}).setLngLat([lng,lat]).addTo(map));
  }
  if (current.hazard !== 'Earthquakes') return;
  try {
    if (mode === 'shaking') {
      const contours = await json('shaking.json');
      if (version !== updateVersion) return;
      map.addSource('contours',{type:'geojson',data:contours});
      map.addLayer({id:'contours',type:'line',source:'contours',paint:{'line-color':['coalesce',['get','color'],'#b46537'],'line-width':2.4}});
    }
    quakePromise ||= json('events.json').catch(error => {quakePromise=null; throw error});
    const data=await quakePromise;
    if (version !== updateVersion) return;
    for (const event of data.features) {
      const info=event.properties;
      const button=document.createElement('button');
      button.type='button';
      button.className='epicenter';
      button.title=`M${info.mag} · ${info.place}`;
      button.textContent=`M${info.mag}`;
      button.addEventListener('click', e=>{
        e.stopPropagation();
        const date=new Date(info.time).toISOString().replace('T',' ').slice(0,16);
        showPoint(event.geometry.coordinates.slice(0,2),`M${info.mag} earthquake`,`${info.place} · ${info.depth} km deep · ${date} UTC`);
      });
      markers.push(new maplibregl.Marker({element:button}).setLngLat(event.geometry.coordinates.slice(0,2)).addTo(map));
    }
  } catch (error) {
    if (version === updateVersion) byId('map-note').textContent='An observation layer could not be loaded.';
    console.error(error);
  }
}

function showPoint(coords,title,copy) {
  byId('point-title').textContent=title;
  byId('point-copy').textContent=copy;
  if (!mapReady) return;
  popup?.remove();
  popup=new maplibregl.Popup({offset:8,maxWidth:'240px'}).setLngLat(coords)
    .setHTML(`<strong>${escape(title)}</strong><p>${escape(copy)}</p>`).addTo(map);
}

function showWorldPoint(coords, item) {
  if (current) return;
  const title = byId('point-title');
  title.hidden = false;
  showPoint(coords,item.title,item.description);
  const content = document.createElement('div');
  const name = document.createElement('strong');
  name.textContent = item.title;
  const detail = document.createElement('p');
  detail.textContent = item.description;
  content.append(name, detail);
  if (item.balances?.length) content.append(massBalanceChart(item.balances));
  for (const [label, url] of item.links) {
    const link = document.createElement('a');
    link.textContent = label;
    link.className = 'provider-link';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    content.append(link);
  }
  popup.setDOMContent(content);
}

async function inspectPoint(event) {
  if (!current) return world.click(event);
  const version = updateVersion;
  const {lng,lat}=event.lngLat;
  const coords=[lng,lat];
  const [[w,s],[e,n]]=current.bounds;
  const point=`${lat.toFixed(3)}°, ${lng.toFixed(3)}°`;
  if (lng < w || lng > e || lat < s || lat > n) {
    showPoint(coords,'Outside the observation',point);
    return;
  }
  if (!['displacement','extent'].includes(mode)) {
    showPoint(coords,point,mode==='shaking'?'Use the epicenter markers and MMI contours to inspect this event.':'Satellite imagery at this location. Open Data & methods for the acquisition and source.');
    return;
  }
  try {
    const isFlood = mode === 'extent';
    const key = isFlood ? 'flood-extent' : 'displacement';
    if (!grids.has(key)) {
      const loadGrid = Promise.all([json(key + '.json'), fetch(asset(key + (isFlood ? '.u8' : '.f32'))).then(response => {
        if (!response.ok) throw new Error('Grid could not load');
        return response.arrayBuffer();
      })]).catch(error => { grids.delete(key); throw error; });
      grids.set(key, loadGrid);
    }
    const [grid,buffer] = await grids.get(key);
    if (version !== updateVersion) return;
    const rad=lat*Math.PI/180;
    const x=6378137*lng*Math.PI/180;
    const y=6378137*Math.asinh(Math.tan(rad));
    const [west,south,east,north]=grid.bounds;
    const col=Math.floor(grid.width*(x-west)/(east-west));
    const row=Math.floor(grid.height*(north-y)/(north-south));
    const index = row>=0 && row<grid.height && col>=0 && col<grid.width ? row*grid.width+col : -1;
    const view = new DataView(buffer);
    if (isFlood) {
      const classes = ['No visible flood class', 'Surface water', 'Recurring flood', 'Flood detected', 'Insufficient data'];
      showPoint(coords, classes[index < 0 ? 0 : view.getUint8(index)], point + ' · NASA VIIRS · 23–25 Jan 2026');
    } else {
      const value = index < 0 ? NaN : view.getFloat32(4*index,true);
      showPoint(coords, Number.isFinite(value) ? `${value>0?'+':''}${value.toFixed(1)} cm` : 'No valid radar measurement', point + ' · 13–25 June 2026');
    }
  } catch {
    if (version === updateVersion) showPoint(coords,'Measurement unavailable',point);
  }
}

const refreshCatalog = mountCatalog({
  byId, view: () => ({ hazard, minMagnitude, days, caseId: current?.id }), world, normalize,
  openCase: selectCase, openEntry, cases: observations,
});
mountAssistant({
  byId, view: () => ({ hazard, current, days }),
  tools: {
    load: world.load, find: (kind, query) => world.find(kind, query, normalize, days),
    details: world.details, openCase: selectCase, openMode, openEntry,
    info: kind => world.info(kind, minMagnitude, floodDate, days),
    openImagery(kind, key) {
      selectWorld(kind);
      setImagery(key);
    },
    openWorld(kind, magnitude, satellite) {
      if (magnitude) minMagnitude = magnitude;
      if (satellite) {
        floodTiles = true;
        imageryKey = null;
      }
      if (kind !== hazard || current) selectWorld(kind);
      else render();
    },
  },
});
const askToggle = byId('ask-toggle');
const askPanel = byId('ask-panel');
function toggleChat(open) {
  askPanel.hidden = !open;
  askToggle.setAttribute('aria-expanded', String(open));
  (open ? byId('ask-query') : askToggle).focus();
}
askToggle.addEventListener('click', () => toggleChat(askPanel.hidden));
askPanel.querySelector('[data-dismiss]').addEventListener('click', () => toggleChat(false));
askPanel.addEventListener('keydown', event => { if (event.key === 'Escape') toggleChat(false); });

render();
startMap();
