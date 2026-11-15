import React, { useEffect, useRef, useState } from 'react';

const viewNames = {
  satellite: 'Satellite image',
  reference: 'Mapped landslide (ground truth)',
  predicted: 'Our U-Net prediction',
  errors: 'Correct / false / missed pixels',
};

function TileView({ result, view }) {
  const canvas = useRef(null);
  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const context = node.getContext('2d');
    const frame = context.createImageData(result.width, result.height);
    const labels = Array.isArray(result.labels) ? result.labels : null;
    for (let pixel = 0; pixel < result.width * result.height; pixel++) {
      const score = result.scores[pixel];
      const predicted = score !== null && score >= result.threshold;
      const label = labels ? labels[pixel] === 1 : false;
      const rgb = result.rgb
        ? result.rgb.slice(pixel * 3, pixel * 3 + 3)
        : [42, 58, 63];
      let color = rgb;
      if (view === 'reference' && label) color = [68, 212, 185];
      if (view === 'predicted' && predicted) color = [255, 181, 65];
      if (view === 'errors' && labels) {
        if (predicted && label) color = [58, 202, 155]; // true positive
        else if (predicted && !label) color = [255, 165, 54]; // false positive
        else if (!predicted && label) color = [242, 79, 87]; // false negative
      }
      frame.data.set([...color, score === null ? 70 : 255], pixel * 4);
    }
    context.putImageData(frame, 0, 0);
  }, [result, view]);

  return <figure className="scar-tile">
    <figcaption>{viewNames[view]}</figcaption>
    <canvas ref={canvas} width={result.width} height={result.height}
      role="img" aria-label={viewNames[view]} />
  </figure>;
}

const tierNames = {
  high: 'HIGH review priority',
  medium: 'MEDIUM review priority',
  low: 'LOW review priority',
  none_detected: 'No scar candidates detected',
  unavailable: 'Input insufficient to assess',
};

function percent(value) {
  return Number.isFinite(value) ? (100 * value).toFixed(1) + '%' : 'N/A';
}

export default function LandslideLab() {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const upload = useRef(null);

  async function run(file) {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      if (file && file.size > 4_000_000) throw new Error('The JSON tile must be 4 MB or smaller.');
      const response = await fetch(file ? '/api/landslide' : '/api/landslide?example=1',
        file ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: file } : undefined);
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('The scar detection API is unavailable.');
      }
      const answer = await response.json();
      if (!response.ok) throw new Error(answer.error || 'Inference failed.');
      setResult(answer);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  function uploadTile(event) {
    const file = event.currentTarget.files[0];
    if (file) run(file);
    event.currentTarget.value = '';
  }

  const screening = result?.screening;
  const evaluation = result?.example_evaluation;
  const views = result?.labels && result?.rgb
    ? ['satellite', 'reference', 'predicted', 'errors']
    : result?.rgb ? ['satellite', 'predicted'] : ['predicted'];

  return <dialog id="landslide-lab" aria-labelledby="landslide-title">
    <div className="discovery-heading">
      <div>
        <h2 id="landslide-title">Landslide scar detection</h2>
        <p>Post-event mapping · Sentinel-2 + terrain · experimental</p>
      </div>
      <form method="dialog"><button className="quiet" aria-label="Close scar detector">×</button></form>
    </div>
    <p>A <strong>landslide scar</strong> is the disturbed/exposed ground left <strong>after</strong>
      material slides down a slope. This U-Net maps possible scars in prepared satellite imagery.
      It does not predict when a slope will collapse.</p>
    <div className="lab-actions">
      <button className="quiet lab-primary" type="button" disabled={busy} onClick={() => run()}>
        Compare held-out example
      </button>
      <button className="quiet" type="button" disabled={busy} onClick={() => upload.current?.click()}>
        Upload prepared 14-band tile
      </button>
      <input type="file" ref={upload} accept=".json,application/json" onChange={uploadTile} hidden />
      <a href="/api/landslide" target="_blank" rel="noreferrer">Model evaluation</a>
    </div>
    {busy && <p role="status">Running the published ONNX model…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <div className="scar-results">
      <h3>{result.id || 'Uploaded satellite tile'}</h3>
      <div className="scar-comparison-grid">
        {views.map(view => <TileView key={view} result={result} view={view} />)}
      </div>
      {evaluation && <div className="scar-evaluation">
        <p><strong>This single test tile:</strong> F1 {percent(evaluation.f1)} ·
          Precision {percent(evaluation.precision)} · Recall {percent(evaluation.recall)} ·
          IoU {percent(evaluation.iou)}</p>
        <p>Correct scar pixels {evaluation.tp.toLocaleString()} ·
          False alarms {evaluation.fp.toLocaleString()} ·
          Missed scar pixels {evaluation.fn.toLocaleString()}</p>
        <p className="scar-key">Green: correctly detected · Orange: false alarm · Red: missed scar</p>
      </div>}
      <div className="scar-screening">
        <strong>Scar review priority: {tierNames[screening?.review_priority] || 'Not assessed'}</strong>
        <p>{screening?.reason} · {result.candidate_pixels.toLocaleString()} candidate pixels;
          {screening?.reviewable_regions ?? 0} connected regions with at least 6 pixels.</p>
        <p><strong>Not a danger rating.</strong> A large scar isn't automatically dangerous to people.
          High/medium/low here means how urgently to <em>review the image</em>, based only on
          candidate patch size. Actual danger needs terrain stability, runout, roads,
          buildings, people and weather.</p>
        <p>{result.input_quality?.incomplete_pixels?.toLocaleString() ?? '0'} of
          {' '}{(result.width * result.height).toLocaleString()} pixels have missing required input bands
          and were left unscored. Model scores are <strong>not calibrated hazard probabilities</strong>.</p>
      </div>
    </div>}
    <details>
      <summary>Model input and scientific limitations</summary>
      <p>Input is a prepared 128 × 128 (or smaller) raster with 12 Sentinel-2 channels
        B01–B12 and ALOS slope/elevation in Landslide4Sense channel order and units.
        A normal JPEG, a lone NISAR radar image, or an arbitrary RGB photograph
        cannot be scored by this model.</p>
      <p>The previously published test subset contains 80 Landslide4Sense chips.
        The existing release achieved 66.2% pooled pixel F1. Performance on new
        countries and rock–ice avalanches such as Rasuwa is unvalidated.</p>
    </details>
  </dialog>;
}
