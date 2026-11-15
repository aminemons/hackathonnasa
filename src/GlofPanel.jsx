import React, { useEffect, useMemo, useState } from 'react';
import { feature } from 'topojson-client';
import { equalEarth, worldPath, initialEpoch, lakeSegments } from './glofMath.js';
import './glof.css';

const api = query => '/api/glof?' + new URLSearchParams(query);
const number = (value, places = 2) => Number.isFinite(value) ? value.toLocaleString('en', {maximumFractionDigits: places, minimumFractionDigits: places}) : 'Unavailable';
async function get(query, signal) {
  const response = await fetch(api(query), { signal });
  if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The GLOF API is unavailable. Start the Python backend for local development.');
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The monitoring evidence could not load.');
  return result;
}

function WorldMap({countries, sites, selected, onSelect}) {
  const paths = useMemo(() => countries.map(f => <path key={f.id} d={worldPath(f)} />), [countries]);
  return <div className="glof-world">
    <svg viewBox="0 0 600 310" role="img" aria-label="Equal Earth map of the five GLOF study lakes">
      <g className="glof-land">{paths}</g>
      {sites.map(site => { const [x,y] = equalEarth([site.lon,site.lat]); return <g key={site.site_id}>
        <circle cx={x} cy={y} r={selected === site.site_id ? 7 : 4} className={selected === site.site_id ? 'selected' : ''} />
        {selected === site.site_id && <text x={x > 360 ? x-10 : x+10} y={y-10} textAnchor={x>360?'end':'start'}>{site.name.replace(' (Mendenhall Glacier)','')}</text>}
      </g>; })}
    </svg>
    <div className="glof-lakes">{sites.map(site => <button key={site.site_id} className="quiet" type="button" aria-pressed={selected === site.site_id} onClick={() => onSelect(site.site_id)}>{site.name.replace(' (Mendenhall Glacier)','')}</button>)}</div>
    <p className="glof-caption">Equal Earth · equal-area projection · Natural Earth context</p>
  </div>;
}

function Signal({index, title, value, unit, dates, grade, children}) {
  return <article className="glof-signal">
    <span className="glof-kicker">{index} / {title}</span>
    <strong>{value} {value !== 'Unavailable' && <small>{unit}</small>}</strong>
    <p>{dates}</p>
    <span className="glof-grade">Evidence: {grade}</span>
    <p>{children}</p>
  </article>;
}

export default function GlofPanel() {
  const [catalog, setCatalog] = useState(null);
  const [countries, setCountries] = useState([]);
  const [sid, setSid] = useState('south_lhonak');
  const [published, setPublished] = useState(null);
  const [expert, setExpert] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [error, setError] = useState('');
  const [mapError, setMapError] = useState('');
  const [mapping, setMapping] = useState(false);
  const [retry, setRetry] = useState(0);
  const [validation, setValidation] = useState(null);
  const summary = published?.site.site_id === sid ? published : null;
  const series = summary?.lake.series || [];
  const row = series[epoch];
  const chart = lakeSegments(series);

  useEffect(() => {
    const controller = new AbortController();
    get({}, controller.signal).then(data => {
      setCatalog(data);
      const linked = new URLSearchParams(location.search).get('glof');
      if (linked) {
        if (data.sites.some(s => s.site_id === linked)) setSid(linked);
        document.getElementById('glof-monitor').showModal();
      }
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    fetch(`${import.meta.env.BASE_URL}data/world.json`, {signal:controller.signal}).then(r => r.json())
      .then(topology => setCountries(feature(topology, topology.objects.countries).features)).catch(() => {});
    get({view:'validation'}, controller.signal).then(setValidation).catch(() => {});
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!catalog) return;
    const controller = new AbortController();
    setPublished(null); setError(''); setMapError('');
    get({site:sid}, controller.signal).then(data => {
      setPublished(data); setEpoch(initialEpoch(data));
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [sid, catalog, retry]);

  function select(id) {
    if (mapping) return;
    setSid(id);
    const url = new URL(location.href); url.searchParams.set('glof', id);
    history.replaceState(null, '', url);
  }
  function close() {
    const url = new URL(location.href); url.searchParams.delete('glof');
    history.replaceState(null, '', url);
  }
  async function onMap() {
    setMapping(true); setMapError('');
    try {
      const geometry = await get({site:sid, view:'geometry', date:row.date}, AbortSignal.timeout(15000));
      // Prefer the public NISASTER Leaflet map; keep the legacy MapLibre
      // pathway only for the old React build. Do not import old app on click.
      const show = window.TerraPulseGlofMap || (await import('./main.js')).showGlofOnMap;
      if (show(summary.site, geometry, row.date)) document.getElementById('glof-monitor').close();
      else setMapError('The interactive map is unavailable. The Equal Earth study map and downloads remain available.');
    } catch (e) { setMapError(e.message); }
    finally { setMapping(false); }
  }

  return <dialog id="glof-monitor" aria-labelledby="glof-title" onClose={close}>
    <header className="glof-heading">
      <div><span className="glof-kicker">GLACIAL LAKE OBSERVATORY</span><h2 id="glof-title">Read the lake and its glacier together</h2><p>Historical monitoring · event probability not assessed</p></div>
      <form method="dialog"><button className="quiet" aria-label="Close GLOF monitoring">×</button></form>
    </header>
    <div className="glof-toolbar">
      <label>Study lake<select aria-label="GLOF study lake" value={sid} disabled={mapping || !catalog} onChange={e => select(e.target.value)}>
        {(catalog?.sites || [{site_id:'south_lhonak',name:'South Lhonak Lake'}]).map(s => <option value={s.site_id} key={s.site_id}>{s.name}</option>)}
      </select></label>
      <div className="glof-modes" role="group" aria-label="GLOF display mode">
        <button className="quiet" aria-pressed={!expert} onClick={() => setExpert(false)}>Normal</button>
        <button className="quiet" aria-pressed={expert} onClick={() => setExpert(true)}>Expert</button>
      </div>
    </div>
    {error ? <div role="alert"><p>{error}</p><button className="quiet" onClick={() => setRetry(r=>r+1)}>Retry GLOF evidence</button></div> : !summary ? <p role="status">Loading the published monitoring run…</p> : <>
      <div className="glof-intro">
        <WorldMap countries={countries} sites={catalog.sites} selected={sid} onSelect={select} />
        <section className="glof-story">
          <span className="glof-grade">Combined evidence: {summary.confidence}</span>
          <h3>{summary.site.name}</h3><p>{summary.site.country}</p>
          {sid === 'south_lhonak' ? <p>The 4 October 2023 outburst is bracketed by radar acquisitions on 25 September and 7 October. Their mapped-area decrease is a historical reconstruction with a 12-day gap.</p> : <p>Follow the dated radar observations alongside annual glacier movement where available. Seasonal ice, snow and classification errors can change the mapped open water.</p>}
          <p>Each indicator has its own dates and coverage. Changes identify questions for expert review.</p>
          <p className="glof-limit">Water level, lake water volume and breach probability are unavailable. No operational warning is issued.</p>
        </section>
      </div>
      <div className="glof-signals">
        <Signal index="01" title="EXPERIMENTAL LAKE AREA" value={number(row?.lake_area_km2,3)} unit="km²" dates={row?.date} grade={summary.lake.confidence}>ESA Sentinel-1 · radar-mapped open-water component. {row?.area_estimate_status !== 'mapped_component' && 'The lake outline is unresolved in this observation.'}</Signal>
        <Signal index="02" title="GLACIER MOVEMENT" value={number(summary.movement.value_m_yr,1)} unit="m/yr" dates={summary.movement.latest_year ? `${summary.movement.latest_year} annual estimate` : 'No usable velocity coverage'} grade={summary.movement.confidence}>NASA ITS_LIVE · median within the mapped glacier candidate and downloaded grid.</Signal>
        <Signal index="03" title="ICE SURFACE CHANGE" value={number(summary.elevation.mean_dh_m)} unit="m" dates={summary.elevation.start_date ? `${summary.elevation.start_date} → ${summary.elevation.end_date}` : 'No matched repeat terrain'} grade={summary.elevation.confidence}>{summary.elevation.observed_glacier_footprint_km2 ? `Research repeat terrain · ${number(summary.elevation.observed_glacier_footprint_km2)} km² footprint · ${number(summary.elevation.fraction_of_full_historical_glacier_observed*100,1)}% of historical outline.` : 'Repeat elevation measurements are unavailable for this site.'}</Signal>
      </div>
      <section className="glof-timeline" aria-label="GLOF lake-area timeline">
        <div className="glof-row"><h3>Replay the observed lake</h3><span>{series.length} radar epochs · {series[0]?.date} – {series.at(-1)?.date}</span></div>
        <svg viewBox="0 0 600 110" role="img" aria-label="Experimental lake area over time; gaps indicate unresolved observations">
          {chart.segments.map((points,i) => <g key={i}><polyline points={points.map(p=>p.join(',')).join(' ')} />{points.map(([x,y],j)=><circle key={j} cx={x} cy={y} r="2" />)}</g>)}
        </svg>
        <label className="glof-epoch">Radar observation <input aria-label="GLOF radar epoch" type="range" min="0" max={Math.max(0,series.length-1)} value={epoch} disabled={mapping} onChange={e=>setEpoch(Number(e.target.value))} /><time>{row?.date}</time></label>
        <p className="glof-caption">Missing observations remain gaps. Glacier movement and elevation cards keep their own dates as you replay the lake.</p>
        {row && !row.accepted && <p className="glof-limit">This acquisition is flagged by quality control. The raw estimate is retained for review.</p>}
        <div className="glof-actions"><button className="quiet lab-primary" onClick={onMap} disabled={mapping || !row}>{mapping ? 'Loading lake geometry…' : 'Show this epoch on map'}</button><a href={api({site:sid,view:'csv'})}>Download area CSV</a><a href={api({site:sid})} target="_blank" rel="noreferrer">Evidence JSON ↗</a></div>
        {mapError && <p role="alert">{mapError}</p>}
      </section>
      {!!summary.lake.independent_monthly_water.length && <section className="glof-note"><h3>Independent monthly water observations · JRC</h3><p>{summary.lake.independent_monthly_water.map(r => `${r.month}: ${number(r.mapped_connected_water_area_km2,3)} km²`).join(' · ')}</p><p>October 2023 may combine observations before and after the outburst. Monthly optical water and individual radar dates are separate estimates.</p></section>}
      {expert && <section className="glof-expert" aria-label="GLOF expert evidence">
        <h3>Evidence, coverage and validation</h3>
        <p>{summary.lake.confidence_basis}</p>
        {validation && <p>General water benchmark: IoU {number(validation.metrics.ml.iou*100,1)}% · F1 {number(validation.metrics.ml.f1,3)} on {validation.chips} chips across {validation.events} held-out event regions. This benchmark evaluates water mapping. It does not establish GLOF warning skill.</p>}
        <div className="glof-table-wrap"><table><caption>Lake-specific reference checks</caption><thead><tr><th>SAR date</th><th>IoU</th><th>Recall</th><th>Scope</th></tr></thead><tbody>{summary.lake.independent_checks.map(check => <tr key={check.sar_date}><td>{check.sar_date}</td><td>{number(check.iou,3)}</td><td>{number(check.recall,3)}</td><td>{check.scope ? 'Raw pixel classifier' : 'Final connected lake mask'}</td></tr>)}</tbody></table></div>
        <p>These are automatic optical references on nearby dates. Cloud, snow and ambiguous shorelines are excluded. Manual shoreline validation remains pending.</p>
        <p>Selected-epoch sensitivity range: {row?.lake_area_sensitivity_km2?.map(v=>number(v,3)).join('–') || 'Unavailable'} km². Threshold sensitivity is not a calibrated confidence interval.</p>
        <p>{summary.glacier_attribution}</p>
        {summary.movement.reason && <p>{summary.movement.reason}</p>}
        {summary.movement.quality_note && <p>{summary.movement.quality_note}</p>}
        {summary.elevation.start_date && <p>Partial surface-volume change: {number(summary.elevation.partial_surface_volume_change_m3/1e6,3)} million m³ over the {number(summary.elevation.observed_glacier_footprint_km2)} km² footprint. Stable-ground scatter (NMAD): {number(summary.elevation.stable_ground_nmad_m)} m; this is not a volume-error interval. No glacier-wide extrapolation or conversion to lake water volume.</p>}
        <div className="glof-maps">{[['velocity','Annual glacier-candidate movement and history'],['elevation','Partial glacier surface change on common valid terrain']].map(([key,alt]) => summary.assets[key] && <figure key={key}><img src={summary.assets[key]} alt={alt} /><figcaption>{alt}</figcaption></figure>)}</div>
        {summary.assets.surface_change && <a href={summary.assets.surface_change} download>Download partial surface-change GeoTIFF</a>}
        <h3>Source attribution</h3>
        <div className="glof-sources">{summary.sources.filter((s,i,all)=>all.findIndex(t=>t.provider===s.provider&&t.product===s.product)===i).map((s,i)=><article key={i}><strong>{s.provider}</strong><p>{s.product}</p><span className="glof-grade">{s.status}</span>{s.url && <a href={s.url} target="_blank" rel="noreferrer">Source ↗</a>}</article>)}</div>
      </section>}
    </>}
  </dialog>;
}
