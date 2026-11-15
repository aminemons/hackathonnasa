import React from 'react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import LandslideLab from './LandslideLab.jsx';
import RadarExample from './RadarExample.jsx';
import ForecastPanel from './ForecastPanel.jsx';
import ExposurePanel from './ExposurePanel.jsx';
import './style.css';

function App() {
  return (
    <>
  <header className="topbar">
    <a className="identity" href="./">TerraPulse</a>
    <nav className="tabs" id="cases" aria-label="Select hazard"></nav>
    <a className="partner" href="https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/" target="_blank" rel="noopener"><img src="./data/space-apps.png" alt="NASA Space Apps Challenge" /></a>
  </header>
  <main className="workspace" aria-label="TerraPulse observation map">
    <aside id="browse-panel" className="observation-panel" aria-label="Observations">
      <div className="panel-top">
        <div id="record" className="record"></div>
        <div className="search-wrap"><label htmlFor="browse-filter" className="sr-only">Find observations by place</label><input id="browse-filter" type="search" placeholder="Find a place" autoComplete="off" /></div>
        <div id="regions" className="regions" aria-label="Regions"></div>
        <div id="map-controls" className="layers" aria-label="Map layers and filters"></div>
        <div id="evidence" className="evidence"></div>
      </div>
      <p id="browse-count" className="drawer-note" aria-live="polite"></p>
      <ul id="browse-results" className="observation-list"></ul>
      <nav id="browse-pages" aria-label="Observation pages"></nav>
    </aside>
    <div id="map-frame" className="map-frame">
      <div id="map" className="map" aria-label="Geographic observation map"></div>
      <div id="map-fallback" className="map-fallback" hidden></div>
      <div className="map-tools">
        <label className="control" id="basemap-control"><span className="sr-only">Base map</span><select id="basemap"><option value="satellite">Satellite</option><option value="atlas">Atlas</option></select></label>
        <button className="quiet" id="reset-map" type="button" aria-label="Reset map view" title="Reset map view">⌂</button>
        <button className="quiet forecast-entry" type="button" onClick={() => document.getElementById("forecast").showModal()}>Landslide forecast</button>
        <button className="quiet" type="button" onClick={() => document.getElementById("landslide-lab").showModal()}>Detect scars</button>
        <button className="quiet" type="button" onClick={() => document.getElementById("exposure-panel").showModal()}>Human exposure</button>
        <button className="quiet" id="find-radar" type="button">Find NISAR</button>
        <button className="quiet" id="ask-toggle" type="button" aria-expanded="false" aria-controls="ask-panel">Ask TerraPulse</button>
      </div>
      <div id="map-note" className="map-note" aria-live="polite"></div>
      <div id="legend" className="legend"></div>
      <span id="fallback-credit" className="map-credit" hidden>NASA Blue Marble</span>
      <section id="ask-panel" className="map-drawer" aria-label="Ask TerraPulse" hidden>
        <header><h2>Ask TerraPulse</h2><button className="quiet" type="button" data-dismiss="" aria-label="Close chat">×</button></header>
        <div id="ask-log" className="ask-log" role="log" aria-label="Conversation" aria-live="polite"></div>
        <div className="ask-prompts">
          <button className="quiet" type="button">Compare Guelma</button>
          <button className="quiet" type="button">Show M5+ earthquakes</button>
          <button className="quiet" type="button">Open Pine Island</button>
        </div>
        <form id="ask-form">
          <label className="sr-only" htmlFor="ask-query">Ask about the map</label>
          <input id="ask-query" placeholder="Ask about a place or layer" autoComplete="off" maxLength="240" required />
          <button className="quiet" type="submit">Send</button>
        </form>
      </section>
    </div>
  </main>
  <dialog id="discovery" aria-labelledby="discovery-title">
    <div className="discovery-heading"><h2 id="discovery-title">Find NISAR observations</h2><button className="quiet" type="button" data-close-discovery="" aria-label="Close">×</button></div>
    <p>Search a point anywhere on Earth. A catalog match shows coverage by footprint.</p>
    <form className="discovery-place">
      <label>City or place<input name="place" type="search" placeholder="e.g. Algiers, Algeria" minLength="2" required /></label>
      <button type="submit" className="quiet">Find place</button>
    </form>
    <div className="place-results" aria-live="polite"></div>
    <form id="radar-search">
      <label>Longitude<input name="lon" type="number" min="-180" max="180" step="any" required /></label>
      <label>Latitude<input name="lat" type="number" min="-90" max="90" step="any" required /></label>
      <label>From<input name="start" type="date" required /></label>
      <label>To<input name="end" type="date" required /></label>
      <button className="quiet" type="button" data-pick-location="">Pick on map</button>
      <button className="quiet" type="submit">Search NASA Earthdata</button>
    </form>
    <p role="status"></p>
    <button className="quiet" type="button" onClick={() => document.getElementById("radar-example").showModal()}>View Rasuwa radar comparison</button>
    <details className="landslide-inventory">
      <summary>Mapped landslides nearby</summary>
      <p>NASA COOLR inventories within about 25 km of this point and in the selected dates.</p>
      <button className="quiet" type="button" data-find-landslides="">Check inventory</button>
      <p role="status"></p>
      <button className="quiet" type="button" data-show-landslides="" hidden>Show mapped outlines</button>
      <a href="https://gpm.nasa.gov/applications/landslides/coolr" target="_blank" rel="noopener">About COOLR</a>
    </details>
    <ul aria-label="Matching observations"></ul>
  </dialog>
  <dialog id="reference" aria-label="Observation sources"><div id="reference-content"></div><form method="dialog"><button className="quiet" type="submit">Close</button></form></dialog>
  <LandslideLab />
  <ForecastPanel />
  <ExposurePanel />
  <RadarExample />
    </>
  );
}

const root = createRoot(document.getElementById('app'));
flushSync(() => root.render(<App />));
import('./main.js');
