import WorkflowReturn from './WorkflowReturn.jsx';
import React, { useState } from 'react';

const shades = ['#254871', '#307da8', '#66c8c0', '#f4ca60', '#ee803c', '#c63d41'];

function hazardScore(value) {
  return value === null || !Number.isFinite(value) ? 'No data' : Number(value).toFixed(4);
}

export default function ForecastPanel() {
  const [coords, setCoords] = useState({ lon: '3.05', lat: '36.70' });
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  async function fromMap() {
    const { forecastMapCenter } = await import('./main.js');
    const point = forecastMapCenter();
    if (point) setCoords({ lon: point.lng.toFixed(4), lat: point.lat.toFixed(4) });
    else setStatus('The interactive map is unavailable. Enter coordinates above.');
  }

  async function submit(event) {
    event.preventDefault();
    setResult(null);
    setStatus('');
    setBusy(true);
    try {
      const query = new URLSearchParams(coords);
      const response = await fetch('/api/forecast?' + query, { signal: AbortSignal.timeout(20000) });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The forecast service is temporarily unavailable.');
      const tile = await response.json();
      if (!response.ok) throw new Error(tile.error);
      setResult(tile);
    } catch (error) {
      setStatus(error.name === 'TimeoutError' ? 'The forecast feed took too long to respond.' : error.message);
    } finally {
      setBusy(false);
    }
  }

  async function onMap(event) {
    const dialog = event.currentTarget.closest('dialog');
    const { showForecastOnMap } = await import('./main.js');
    if (showForecastOnMap(result)) dialog.close();
    else setStatus('The interactive map is unavailable. The raster preview and download are available here.');
  }

  return <dialog id="forecast" aria-labelledby="forecast-title">
    <WorkflowReturn stage="01 / Rainfall-triggered hazard" />
    <div className="discovery-heading">
      <div><h2 id="forecast-title">Landslide forecast</h2><p>Rainfall-triggered hazard · NASA LHASA 2.1</p></div>
      <form method="dialog"><button className="quiet" aria-label="Close forecast">×</button></form>
    </div>
    <p>Search the NASA Hazard Tomorrow layer. It uses forecast rainfall to estimate regional hazard at about 1 km resolution, from 60°S to 60°N.</p>
    <form className="forecast-form" onSubmit={submit}>
      <label>Longitude<input type="number" value={coords.lon} min="-180" max="180" step="any" onChange={e => setCoords({...coords, lon:e.target.value})} required /></label>
      <label>Latitude<input type="number" value={coords.lat} min="-60" max="60" step="any" onChange={e => setCoords({...coords, lat:e.target.value})} required /></label>
      <button className="quiet" type="button" onClick={fromMap}>Use map center</button>
      <button className="quiet lab-primary" type="submit" disabled={busy}>Get forecast</button>
    </form>
    {busy && <p role="status">Loading the next-day raster…</p>}
    {status && <p role="alert">{status}</p>}
    {result && <div className="forecast-output">
      <div>
        <img src={result.preview_png} width="144" height="144" alt="Gridded NASA LHASA hazard values for the selected region" />
        <div className="forecast-scale" aria-label="Hazard score from lower to higher">
          {shades.map(shade => <span key={shade} style={{ background: shade }} />)}
        </div>
        <div className="forecast-scale-label"><span>Lower</span><span>Higher</span></div>
      </div>
      <div>
        <h3>NASA Hazard Tomorrow</h3>
        {result.valid_pixels ? <>
          <p>Selected cell hazard score <strong>{hazardScore(result.point_value)}</strong><br />Regional maximum score <strong>{hazardScore(result.peak_value)}</strong></p>
          <p>{result.valid_pixels.toLocaleString()} cells with data. Transparent cells have no data. These scores are not locally calibrated landslide probabilities.</p>
        </> : <p>NASA returned no valid cells in this area.</p>}
        <p>Retrieved <time dateTime={result.retrieved_at}>{new Date(result.retrieved_at).toISOString().slice(0, 16).replace('T', ' ')} UTC</time>. NASA does not expose the issue or validity time through this endpoint, so freshness for a specific day is unverified.</p>
        <div className="lab-actions">
          <button className="quiet" type="button" onClick={onMap} disabled={!result.valid_pixels}>Show on map</button>
          <a href={result.geotiff} target="_blank" rel="noreferrer">Source GeoTIFF</a>
        </div>
      </div>
    </div>}
    <p><a href="https://gis.earthdata.nasa.gov/portal/home/item.html?id=805b76ae2b1c48bf8a09d58f1fdd0e4f" target="_blank" rel="noreferrer">NASA product details</a></p>
  </dialog>;
}
