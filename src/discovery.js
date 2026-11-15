const cmr = 'https://cmr.earthdata.nasa.gov/search';
const collections = [
  ['GCOV', 'C3622241360-ASF', 'Validated'],
  ['GCOV', 'C2854338529-ASF', 'Provisional'],
  ['GUNW', 'C3622247503-ASF', 'Validated'],
  ['GUNW', 'C2854335566-ASF', 'Provisional'],
];

export async function discover(lon, lat, start, end, signal) {
  if (![lon, lat].every(Number.isFinite) || Math.abs(lon) > 180 || Math.abs(lat) > 90 ||
      !start || !end || start > end) throw new Error('Enter valid coordinates and dates.');
  const query = new URLSearchParams({
    point: [lon, lat].join(','), temporal: `${start}T00:00:00Z,${end}T23:59:59Z`,
    page_size: '100', sort_key: '-end_date',
  });
  for (const [, id] of collections) query.append('collection_concept_id[]', id);
  const response = await fetch(`${cmr}/granules.umm_json?${query}`, {signal});
  if (!response.ok) throw new Error('NASA Earthdata catalog could not be reached. Try again.');
  const {items, hits} = await response.json();
  const groups = new Map();
  for (const {meta, umm} of items) {
    const collection = collections.find(([, id]) => id === meta['collection-concept-id']);
    if (!collection) continue;
    const [product, , maturity] = collection;
    const attributes = Object.fromEntries((umm.AdditionalAttributes || []).map(item => [item.Name, item.Values[0]]));
    const times = (product === 'GUNW'
      ? [attributes.REFERENCE_ZERO_DOPPLER_START_TIME, attributes.SECONDARY_ZERO_DOPPLER_START_TIME]
      : [umm.TemporalExtent?.RangeDateTime?.BeginningDateTime]).filter(Boolean).sort();
    if (times.length !== (product === 'GUNW' ? 2 : 1)) continue;
    const id = meta['concept-id'];
    const date = times.at(-1).slice(0, 10);
    if (date < start || date > end) continue;
    const geometry = attributes.STACK_ID || [attributes.TRACK_NUMBER, attributes.FRAME_NUMBER,
      attributes.ASCENDING_DESCENDING, attributes.FREQUENCY_A_POLARIZATION,
      attributes.FREQUENCY_A_RANGE_BANDWIDTH].filter(Boolean).join("/");
    const key = [product, geometry || id, ...times.map(t => t.slice(0, 19))].join("/");
    const a = {
      id, product, maturity, date, dates: times.map(t => t.slice(0, 10)), version: attributes.PRODUCT_VERSION || '',
      track: attributes.TRACK_NUMBER, pass: attributes.ASCENDING_DESCENDING,
      polarization: attributes.FREQUENCY_A_POLARIZATION,
      source: `${cmr}/granules.umm_json?concept_id=${id}`,
    };
    const old = groups.get(key);
    if (!old || (old.maturity === a.maturity && a.version.localeCompare(old.version, undefined, {numeric:true}) > 0)
      || (old.maturity === 'Provisional' && a.maturity === 'Validated')) groups.set(key, a);
  }
  return {hits, observations: [...groups.values()].sort((a,b) => b.date.localeCompare(a.date))};
}

const inventory = 'https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/COOLR_Events_Polygons/FeatureServer/0/query';

async function mappedLandslides(lon, lat, start, end, signal) {
  if (![lon, lat].every(Number.isFinite) || !/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end) || start > end) {
    throw new Error('Enter valid coordinates and dates.');
  }
  const r = 25 / 111;
  const dy = r, dx = Math.min(180, r / Math.max(Math.cos(lat * Math.PI/180), .001));
  const nextDay = new Date(Date.parse(end) + 86400000).toISOString().slice(0,10);
  const query = new URLSearchParams({
    where: `event_date >= DATE '${start}' AND event_date < DATE '${nextDay}'`,
    geometry: [Math.max(-180,lon-dx), Math.max(-90,lat-dy), Math.min(180,lon+dx), Math.min(90,lat+dy)].join(','),
    geometryType:'esriGeometryEnvelope', inSR:'4326', outSR:'4326', returnGeometry:'true',
    outFields:'event_title,event_date,method', resultRecordCount:'200', f:'geojson',
  });
  const response = await fetch(`${inventory}?${query}`, {signal});
  if (!response.ok) throw new Error('NASA’s landslide inventory could not be reached.');
  const data = await response.json();
  if (!Array.isArray(data.features)) throw new Error('NASA’s landslide inventory returned an error.');
  return data;
}

export function mountDiscovery({selectMapPoint, showRadar, showLandslides}) {
  const dialog = document.getElementById('discovery');
  const form = dialog.querySelector('#radar-search');
  const placeForm = dialog.querySelector('.discovery-place');
  const placeResults = dialog.querySelector('.place-results');
  const close = dialog.querySelector('[data-close-discovery]');
  const results = dialog.querySelector('ul');
  const status = dialog.querySelector(':scope > [role=status]');
  const landslideStatus = dialog.querySelector('.landslide-inventory [role=status]');
  const showInventory = dialog.querySelector('[data-show-landslides]');
  let landslideRequest;
  let outlines;
  let outlinePoint;

  const resetInventory = () => {
    landslideRequest?.abort();
    showInventory.hidden = true;
    outlines = null;
    landslideStatus.textContent = '';
  };
  form.addEventListener('input', resetInventory);
  showInventory.onclick = () => {
    if (!outlines) return;
    if (showLandslides(outlinePoint, outlines)) dialog.close();
    else landslideStatus.textContent = 'The interactive map is unavailable.';
  };
  dialog.querySelector('[data-find-landslides]').onclick = async () => {
    if (!form.reportValidity()) return;
    resetInventory();
    const controller = landslideRequest = new AbortController();
    const coords = [form.elements.lon.valueAsNumber, form.elements.lat.valueAsNumber];
    landslideStatus.textContent = 'Checking the landslide inventory…';
    try {
      const data = await mappedLandslides(...coords,form.elements.start.value,form.elements.end.value,
        AbortSignal.any([controller.signal,AbortSignal.timeout(16000)]));
      if (controller.signal.aborted) return;
      outlinePoint = coords;
      outlines = data;
      showInventory.hidden = !data.features.length;
      landslideStatus.textContent = data.features.length
        ? (data.features.length === 200 ? 'First 200' : data.features.length) + ' mapped features. These outlines come from NASA COOLR.'
        : 'No dated inventory polygons returned. This area may have incomplete records.';
    } catch (error) {
      if (!controller.signal.aborted) landslideStatus.textContent = error.name === 'TimeoutError'
        ? 'The landslide inventory took too long to respond.' : error.message;
    }
  };
  const choose = dialog.querySelector('[data-pick-location]');
  let request;
  let placeRequest;


  const setLocation = (lon, lat) => {
    form.elements.lon.value = lon.toFixed(5);
    form.elements.lat.value = lat.toFixed(5);
  };
  const open = (lon, lat) => {
    setLocation(lon, lat);
    resetInventory();
    results.replaceChildren();
    placeResults.replaceChildren();
    status.textContent = "";
    if (!dialog.open) dialog.showModal();
  };
  const today = new Date();
  form.elements.end.value = today.toISOString().slice(0,10);
  today.setUTCDate(today.getUTCDate() - 60);
  form.elements.start.value = today.toISOString().slice(0,10);
  close.onclick = () => dialog.close();
  choose.onclick = () => { if (selectMapPoint()) dialog.close(); else status.textContent = "Map selection is unavailable. Enter coordinates to search."; };
  dialog.addEventListener('close', () => { request?.abort(); placeRequest?.abort(); landslideRequest?.abort(); });

  placeForm.onsubmit = async event => {
    event.preventDefault();
    placeRequest?.abort();
    const controller = placeRequest = new AbortController();
    placeResults.textContent = 'Looking up places…';
    const name = placeForm.elements.place.value.trim();
    const query = new URLSearchParams({name,count:'6',language:'en'});
    try {
      const response = await fetch('https://geocoding-api.open-meteo.com/v1/search?' + query,
        {signal:AbortSignal.any([controller.signal,AbortSignal.timeout(10000)])});
      if (!response.ok) throw new Error('Place lookup failed');
      const {results: places = []} = await response.json();
      if (controller.signal.aborted) return;
      placeResults.textContent = places.length ? '' : 'No places found. Try a nearby city or enter coordinates.';
      for (const place of places) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quiet';
        button.textContent = [...new Set([place.name,place.admin1,place.country].filter(Boolean))].join(', ');
        button.onclick = () => {
          setLocation(place.longitude,place.latitude);
          resetInventory();
          placeResults.textContent = button.textContent;
          form.requestSubmit();
        };
        placeResults.append(button);
      }
    } catch {
      if (!controller.signal.aborted) placeResults.textContent = 'Place lookup is unavailable. Enter coordinates to search.';
    }
  };

  form.onsubmit = async event => {
    event.preventDefault();
    request?.abort();
    const controller = request = new AbortController();
    const searchedPoint = [form.elements.lon.valueAsNumber, form.elements.lat.valueAsNumber];
    setLocation(...searchedPoint);
    status.textContent = 'Searching NASA Earthdata…';
    results.replaceChildren();
    try {
      const {observations, hits} = await discover(...searchedPoint, form.elements.start.value,
        form.elements.end.value, AbortSignal.any([controller.signal, AbortSignal.timeout(18000)]));
      if (controller.signal.aborted) return;
      status.textContent = observations.length
        ? `${observations.length} observations listed${hits > 100 ? ' from the latest 100 catalog records. Narrow the dates for more detail.' : '.'}`
        : 'No matching NISAR observations in this result window. Try a different location or date range.';
      for (const observation of observations) {
        const row = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = `${observation.product === 'GCOV' ? 'Radar backscatter' : 'Interferogram pair'} · ${observation.dates.join(' to ')}`;
        const detail = document.createElement('p');
        detail.textContent = [
          observation.maturity, observation.pass?.toLowerCase(), observation.track && `track ${observation.track}`,
          observation.polarization, observation.product === 'GUNW' && 'Catalog coverage only',
        ].filter(Boolean).join(' · ');
        const source = document.createElement('a');
        source.href = observation.source;
        source.textContent = 'Earthdata record';
        source.target = '_blank';
        source.rel = 'noopener';
        row.append(title,detail,source);
        if (observation.product === 'GCOV') {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'quiet';
          button.textContent = 'Show daily radar';
          button.onclick = () => { if (showRadar(searchedPoint, observation.date)) dialog.close(); else status.textContent = "The interactive map is unavailable. Use the Earthdata record to inspect this observation."; };
          row.append(button);
        }
        results.append(row);
      }
    } catch (error) {
      if (!controller.signal.aborted) status.textContent = error.name === 'TimeoutError'
        ? 'NASA Earthdata took too long to respond. Try again.' : error.message || 'The search failed.';
    }
  };
  return open;
}
