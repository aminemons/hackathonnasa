import React from 'react';

const stages = [
  {
    id: 'forecast',
    number: '01',
    label: 'Before an event',
    title: 'Rainfall-triggered hazard',
    source: 'NASA LHASA · ~1 km grid',
    description: 'Explore the latest retrieved next-day hazard layer for a location.',
    caveat: 'NASA scores are not calibrated local probabilities; forecast validity time is unavailable.',
    action: 'Explore forecast',
  },
  {
    id: 'landslide-lab',
    number: '02',
    label: 'After an event',
    title: 'Find landslide scars',
    source: 'Sentinel-2 + terrain · U-Net',
    description: 'Compare the predicted disturbed ground with mapped reference scars.',
    caveat: '66.2% F1 on the fixed Landslide4Sense test subset; not a future-failure prediction.',
    action: 'Compare detection',
  },
  {
    id: 'exposure-panel',
    number: '03',
    label: 'Potential human exposure',
    title: 'Inspect nearby assets',
    source: 'OpenStreetMap · mapped geometry',
    description: 'Check building footprints, roads and sensitive facilities around a nominated site.',
    caveat: 'Proximity is a review priority, not a validated damage or personal-safety estimate.',
    action: 'Inspect buildings',
  },
];

function openDialog(id) {
  const hub = document.getElementById('landslide-workspace');
  const target = document.getElementById(id);
  if (!target) return;
  hub?.close();
  if (!target.open) target.showModal();
}

export default function LandslideWorkspace() {
  return <dialog id="landslide-workspace" aria-labelledby="landslide-workspace-title">
    <div className="discovery-heading landslide-workspace-heading">
      <div>
        <p className="landslide-eyebrow">TerraPulse / Landslide analysis</p>
        <h2 id="landslide-workspace-title">From hazard to human exposure</h2>
        <p className="landslide-workspace-lead">One workflow, three different scientific questions. Each result has its own evidence and limits.</p>
      </div>
      <form method="dialog"><button className="quiet landslide-workspace-close" type="submit" aria-label="Close landslide analysis">×</button></form>
    </div>

    <div className="landslide-stage-grid">
      {stages.map(stage => <section key={stage.id} className="landslide-stage">
        <header className="landslide-stage-top">
          <span className="landslide-step">{stage.number}</span>
          <span className="landslide-stage-label">{stage.label}</span>
        </header>
        <h3>{stage.title}</h3>
        <p className="landslide-source">{stage.source}</p>
        <p className="landslide-stage-description">{stage.description}</p>
        <div className="landslide-stage-footer">
          <p>{stage.caveat}</p>
          <button className="quiet landslide-stage-action" type="button"
            onClick={() => openDialog(stage.id)}>{stage.action}<span aria-hidden="true">↗</span></button>
        </div>
      </section>)}
    </div>

    <section className="landslide-hub-radar">
      <div>
        <p className="landslide-eyebrow">Separate radar evidence</p>
        <h3>NISAR backscatter monitoring</h3>
        <p>Compare two October–November 2026 observations. Both were captured after the August Rasuwa avalanche; this is not an avalanche-detection result.</p>
      </div>
      <button className="quiet" type="button" onClick={() => openDialog('radar-example')}>Inspect NISAR observations</button>
    </section>

    <footer className="landslide-workspace-footer">
      <span>Forecast hazard ≠ detected scar ≠ exposed people.</span>
      <span>No output here certifies a site as safe or unsafe.</span>
    </footer>
  </dialog>;
}
