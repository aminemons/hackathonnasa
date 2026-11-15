import React, { useEffect, useState } from 'react';

function count(value) {
  return Number.isInteger(value) ? value.toLocaleString() : 'Unavailable';
}
function distance(value) {
  return Number.isFinite(value) ? value.toFixed(0) + ' m' : 'Not mapped';
}
const descriptions = {
  urgent: 'Urgent field review',
  high: 'High review priority',
  medium: 'Medium review priority',
  low: 'Low review priority',
  no_mapped_assets: 'No relevant assets mapped',
};
const initial = {lon: '85.5300', lat: '28.2900', radius_m: '500'};

export default function ExposurePanel() {
  const [coords, setCoords] = useState(initial);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [locationSource, setLocationSource] = useState('manual');

  useEffect(() => {
    const handle = event => {
      const {lon, lat, image_source} = event.detail || {};
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      setCoords(current => ({...current, lon: lon.toFixed(6), lat: lat.toFixed(6)}));
      setLocationSource(image_source || 'user-supplied georeferenced scar candidate');
      setResult(null);
      setError('');
      const dialog = document.getElementById('exposure-panel');
      if (dialog && !dialog.open) dialog.showModal();
    };
    window.addEventListener('tp:scar-location', handle);
    return () => window.removeEventListener('tp:scar-location', handle);
  }, []);

  async function centerOnMap() {
    const { forecastMapCenter } = await import('./main.js');
    const position = forecastMapCenter();
    if (!position) {
      setError('Map position is unavailable. Enter a documented site manually.');
      return;
    }
    setCoords(old => ({...old, lon: position.lng.toFixed(5), lat: position.lat.toFixed(5)}));
    setLocationSource('manually selected map center (not a verified scar)');
  }

  async function showBuildingsOnMap() {
    if (!result) return;
    try {
      const { showExposureOnMap } = await import('./main.js');
      if (showExposureOnMap(result)) {
        document.getElementById('exposure-panel')?.close();
      } else {
        setError('The interactive map is unavailable; OSM counts remain visible.');
      }
    } catch {
      setError('Map rendering failed; the numeric exposure report remains available.');
    }
  }

  async function check(event) {
    event.preventDefault();
    setResult(null);
    setError('');
    setLoading(true);
    try {
      const query = new URLSearchParams(coords);
      const response = await fetch('/api/exposure?' + query, {
        signal: AbortSignal.timeout(22000),
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Exposure service returned an invalid response.');
      }
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Exposure data unavailable.');
      setResult(body);
    } catch (failure) {
      setError(failure.name === 'TimeoutError' ? 'OpenStreetMap query timed out; exposure is unknown.' : failure.message);
    } finally {
      setLoading(false);
    }
  }

  return <dialog id="exposure-panel" aria-labelledby="exposure-title">
    <div className="discovery-heading">
      <div>
        <h2 id="exposure-title">People and infrastructure nearby</h2>
        <p>OpenStreetMap · geographic exposure screening</p>
      </div>
      <form method="dialog"><button className="quiet" aria-label="Close exposure panel">×</button></form>
    </div>
    <p><strong>First locate a known or suspected landslide.</strong> This tool looks for
      mapped buildings, roads, and schools/medical facilities around that point.
      It does <strong>not</strong> predict where debris will travel or whether people are in danger.</p>
    <form className="exposure-form" onSubmit={check}>
      <label>Longitude <input type="number" step="any" min="-180" max="180" required
        value={coords.lon} onChange={event => setCoords({...coords, lon:event.target.value})}/></label>
      <label>Latitude <input type="number" step="any" min="-80" max="80" required
        value={coords.lat} onChange={event => setCoords({...coords, lat:event.target.value})}/></label>
      <label>Search radius
        <select value={coords.radius_m} onChange={event => setCoords({...coords, radius_m:event.target.value})}>
          <option value="250">250 m</option><option value="500">500 m</option>
          <option value="600">600 m</option>
        </select>
      </label>
      <button className="quiet" type="button" onClick={centerOnMap}>Use map center</button>
      <button className="quiet lab-primary" type="submit" disabled={loading}>Check mapped assets</button>
    </form>
    <p>Location provenance: <strong>{locationSource}</strong>. The selected location is not automatically verified as a landslide.</p>
    {loading && <p role="status">Comparing mapped building footprints and road lines…</p>}
    {error && <p role="alert">{error} A failed map query must not be interpreted as zero exposure.</p>}
    {result && <section className="exposure-results">
      <h3>{descriptions[result.human_exposure_review_priority] || 'Review required'}</h3>
      <p>{result.explanation}. This is a screening category, <strong>not a physical danger classification</strong>.</p>
      <div className="exposure-stat-grid">
        <div><strong>{count(result.counts.buildings_within_30m)}</strong><span>Mapped buildings within 30 m</span></div>
        <div><strong>{count(result.counts.buildings_within_150m)}</strong><span>Mapped buildings within 150 m</span></div>
        <div><strong>{count(result.counts.roads_within_150m)}</strong><span>Road segments within 150 m</span></div>
        <div><strong>{count(result.counts.sensitive_places_within_100m)}</strong><span>Schools / clinics within 100 m</span></div>
      </div>
      <p>Nearest mapped building: <strong>{distance(result.nearest_m.buildings)}</strong>.
        Nearest road: <strong>{distance(result.nearest_m.roads)}</strong>.
        Total mapped buildings in query area: <strong>{count(result.counts.buildings_within_search_radius)}</strong>.</p>
      <div className="lab-actions">
        <button className="quiet lab-primary" type="button" onClick={showBuildingsOnMap}>
          Show mapped buildings and roads on atlas
        </button>
        {result.map_features_truncated && <span>Map layer is truncated to 300 OSM elements; totals use all queried elements.</span>}
      </div>
      <p><strong>What this does not know:</strong> whether any asset is downslope,
        debris travel direction, local slope stability, number of occupants,
        building vulnerability, or incomplete OSM coverage.
        No buildings on the map does <strong>not</strong> mean nobody is at risk.</p>
      <p><strong>Source date:</strong> {result.osm_timestamp || 'Unknown'}.
        {' '}<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          © OpenStreetMap contributors · ODbL</a>.
        {' '}The queried point is user-selected, not automatically a verified scar.</p>
    </section>}
    <details>
      <summary>How review priority is computed</summary>
      <p>We calculate the shortest horizontal distance to mapped building polygons,
        road polylines and selected public facilities; we do not use polygon center
        alone. Urgent indicates a building within 30 m or a school/clinic within 100 m.
        High indicates other nearby mapped assets. Medium/low refer to more distant
        assets. These are explainable, unvalidated screening thresholds, not a
        casualty/severity algorithm.</p>
      <p>For a real risk estimate we must add the actual georeferenced scar boundary,
        DEM-derived downslope paths, runout uncertainty, population occupancy and
        local verification. The post-event U-Net uses Sentinel-2 plus terrain; its
        non-georeferenced example cannot be linked directly to OSM buildings.</p>
    </details>
  </dialog>;
}
