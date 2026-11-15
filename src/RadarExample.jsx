import WorkflowReturn from './WorkflowReturn.jsx';
import React, { useState } from 'react';

const layers = [
  { file: 'before', label: 'Oct 30 radar', description: 'NISAR L-band radar backscatter on October 30, after the August avalanche' },
  { file: 'after', label: 'Nov 11 radar', description: 'NISAR L-band radar backscatter on November 11' },
  { file: 'change', label: 'Change', description: 'Red and blue radar backscatter changes between both dates' },
  { file: 'candidates', label: 'Candidate regions', description: 'Connected regions with unusually large radar residuals' },
];
const directory = '/data/nisar-rasuwa';

export default function RadarExample() {
  const [layer, setLayer] = useState(layers[2]);
  const candidates = layer.file === 'candidates';

  return <dialog id="radar-example" aria-labelledby="radar-example-title">
    <WorkflowReturn stage="NISAR / Separate monitoring evidence" />
    <div className="discovery-heading">
      <div><h2 id="radar-example-title">Himalayan post-event radar monitoring</h2><p>NISAR L-band GCOV · 30 Oct to 11 Nov 2026</p></div>
      <form method="dialog"><button className="quiet" aria-label="Close radar comparison">×</button></form>
    </div>
    <div className="lab-actions" aria-label="Radar layers">
      {layers.map(option => <button key={option.file} className="quiet" type="button" aria-pressed={layer === option} onClick={() => setLayer(option)}>{option.label}</button>)}
    </div>
    <div className="radar-scene">
      <img src={directory + '/' + (candidates ? 'after' : layer.file) + '.png'} alt={candidates ? '' : layer.description} loading="lazy" />
      {candidates && <img className="radar-scene-overlay" src={directory + '/candidates.png'} alt={layer.description} />}
    </div>
    <p><strong>Not the August 26 landslide detection result.</strong> Both GCOV scenes were captured after the Rasuwa rock–ice avalanche. Their differences show later backscatter change, not the avalanche onset, and do not prove a landslide.</p><p>92.6% shared valid-pixel coverage. A separate August NISAR GUNW study is needed to analyze the event itself, using independent mapped detachment boundaries and radar quality masks.</p>
    <div className="lab-actions">
      <a href="https://cmr.earthdata.nasa.gov/search/concepts/G4405167589-ASF.umm_json" target="_blank" rel="noreferrer">Oct 30 Earthdata record</a>
      <a href="https://cmr.earthdata.nasa.gov/search/concepts/G4411492899-ASF.umm_json" target="_blank" rel="noreferrer">Nov 11 Earthdata record</a>
    </div>
  </dialog>;
}
