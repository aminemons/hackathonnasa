# TerraPulse

## Reliability, science and low-compute deployment (November 2026)

TerraPulse's **primary NISAR research narrative** is earthquakes, landslides and glaciers.
Wildfire and flood layers remain useful supporting datasets; they are not part of
the three-hazard Alarm panel. Do not claim five operational predictions.

### How data reaches the user

```text
Visitor browser (HTTPS)
  |-- USGS direct public GeoJSON ----> normalized + timestamped earthquake reports
  |-- NASA EONET public JSON --------> normalized + timestamped landslide / fire / flood reports
  |-- NASA GIBS / ArcGIS tiles ------> third-party map tile CDN (provider latency varies)
  |-- Vercel static /data/* ---------> GLOF historical catalog, data, study geometry, images
  |-- browser session cache --------> feed TTL, shared pending requests, deduplicated reports
  `-- /api/... (on demand only) -----> ONNX scar inference, LHASA raster, exposure, assistant
```

- **Normal map browsing and alarm monitoring no longer need `/api/events`**.
  `src/hazard-feeds.js` calls public sources in the browser, with validation,
  timeout, same-tab request sharing and limited session cache.
  USGS is refreshed at most every 2 minutes, EONET at most every 10 minutes,
  and dated glacial studies are cached for 24 hours. TTL is **our fetch
  interval**, not a promise of provider freshness.
- Browser cross-origin requests require provider **CORS** support. A blocked or
  malformed feed is **unavailable**, never reported as zero events.
  If the public-source adapter fails to initialize completely, the original
  `/api/events` remains a rare compatibility fallback.
- **No WebSockets** for these provider catalogues: they are polled upstream
  and do not become more immediate from a persistent client connection.
  WebSockets would require connection management or a separate backend and
  could raise cost. A future server-sent stream is only justified if a real
  provider publishes an event stream and operational infrastructure exists.
- **Historical GLOF studies are static**, at `public/data/glof-study/`.
  The normal viewer no longer invokes Python six times per glacier click.
  Each study retains original dates, source IDs, units and limitations.
  Map geometry loads only when requested; CSV exports locally in the browser.
  Data are **not continuously updated**; new evidence requires a reviewed
  export/commit/deploy. Assets are cached by the CDN and browsers.
- **Model inference remains server-side**: `/api/landslide` loads a bundled
  ONNX model; `/api/forecast` fetches an upstream NASA LHASA raster.
  These are deliberately not run for every visitor automatically.
  OSM exposure requests should be bounded to an examined site, never
  whole-Earth queries. Do not embed FIRMS MAP_KEY, Earthdata credentials,
  or private GPU SSH credentials in client JavaScript.
- **Function/build quotas are separate**. Reducing invocations cannot lift
  a Vercel daily deployment limit. Check Vercel Usage and actual HTTP error
  before assuming which quota is exhausted. A hosted static page still uses
  CDN requests and data-transfer bandwidth.

### Method names and epistemic boundaries

| Hazard | Measured / available | Review or forecast role | Not established |
| --- | --- | --- | --- |
| Earthquakes | USGS event catalogue; dated radar displacement research | Post-event geophysical change | Earthquake occurrence prediction; seconds-ahead public warning |
| Landslides | EONET observations; LHASA hazard outlook; Landslide4Sense scars | Susceptibility + rain trigger + verified exposure | Operational event timing, local calibrated probability, evacuation alert |
| Glacial lakes | ITS_LIVE historical annual velocity; Sentinel-1 area | Dated change evidence for five lakes | Current flow vector at every map point, water-level forecast, GLOF breach probability |
| Fires | EONET catalogue; additional FIRMS source planned | Fuel/vegetation/dryness/wind research plan | Calibrated fire spread forecast |
| Floods | EONET, GIBS, example radar/water benchmark | Sentinel-1 delineation; GloFAS integration plan | Operational discharge forecast in this UI |

**Hazard layer × assessed exposure → research review priority** is a workflow,
not literally multiplication of two unitless uncalibrated scores. Separately
measured trigger evidence can raise review priority. `src/priority-core.js`
contains the visible, adjustable research-triage thresholds. Missing exposure,
coverage, hazard provenance or timestamp => **not assessed**, never 'safe'.
Even 'urgent review' is not an emergency warning or a 'catastrophic' forecast.
Never promote an unvalidated heuristic to an automatic browser notification.

**Landlside catalogue removal:** the deprecated Global Landslide Catalog is
not an interactive layer; historical cases may still support training with
independently defined labels and event-level holdouts. Regional lithology and
local precipitation intensity-duration threshold must be validated rather than
assumed globally. InSAR acceleration requires repeat phase/coherence/geometry
and dates; a single radar amplitude image is insufficient.

**Actual quality evidence:** the current Landslide4Sense U-Net record reports
test F1 about 0.662; the Sen1Floods11 water model reports event-split F1 about
0.739. Those are benchmark values, not a live event risk precision. Glacier
studies remain non-operational and largely dated to 2022–2024.
Test controls with `npm run test:reliability`, `npm run build`, Python
`python -m unittest discover -s api/tests -v`, and Chromium
`python scripts/smoke_browser.py` after starting the built preview.

### Next scientific work

1. Validate acquisition manifests for NISAR/ESA data (orbit, swath, polarization,
   UTC, incidence angle, masks, units, effective resolution).
2. Train on spatially **held-out events and countries**, compare baselines,
   calculate false positives, precision–recall and uncertainty; do not tune
   repeatedly on an inspected test set.
3. Review on the two-L40 GPU host using
   `bash scripts/train_landslide_gpu_detached.sh`; evaluate model promotion
   only after independent validation. The script never auto-replaces the model.
4. Add geography-bounded verified OSM and population overlap with freshness,
   missingness and downstream-flow assumptions explicitly recorded.
5. Add FIRMS fire and GloFAS discharge sources only with valid credentials,
   provider agreements, measurement units, source dates and benchmark tests;
   do not display placeholders as live predictions.


## Ishaq GLOF monitoring: dated real data, not breach forecasts

The Dataset sidebar now includes Glaciers & ice → Monitor GLOFs.
Five historical sites and 253 published radar epochs are served by
the Python endpoint GET /api/glof and displayed in the blue/white
NISASTER-style UI. Selected dated lake geometry is overlaid onto the
same Leaflet atlas. Missing data remain missing, never zero water.

- GET /api/glof : catalog
- GET /api/glof?site=south_lhonak : site time series and quality
- GET /api/glof?site=south_lhonak&view=geometry&date=2023-10-07 : dated polygons
- GET /api/glof?site=south_lhonak&view=csv : downloadable observations
- docs/glof-monitoring.md : measurements, sources, and limits
- machine learning/glof/check_example.py : independent offline inference check
- python -m api.local_server : local Python backend for all five API routes

The API serves offline precomputed scientific outputs; it does not
retrain the model during a website request. These observations are not
lake water level, breach probability, or operational emergency warnings.
## Interface: Meryem's NISASTER reference

The root `index.html` implements the supplied NISASTER/Leaflet interface,
retaining the **blue gradient header**, **white Dataset/Time/Legend/Alarm
sidebar**, **full map**, **base-map switcher**, and **floating chatbot**.
The TerraPulse hazard modules are extensions of that interface—not a separate
dark-themed UI.

In the **Landslides** dataset category, open:

- **NASA LHASA next-day forecast**: retrieves publicly available NASA hazard
  raster through `/api/forecast`. Scores are not locally calibrated probabilities.
- **Post-event scar detector**: existing Sentinel-2 + ALOS U-Net at
  `/api/landslide`, including held-out example, reference mask,
  TP/FP/FN visual comparison and 66.2% fixed benchmark subset F1.
- **Human exposure**: `/api/exposure` fetches nearby mapped OpenStreetMap
  building footprints, roads and sensitive facilities. Its review priority
  is not a physical danger/safety assessment.
- **NISAR radar evidence**: genuine 2026 Oct/Nov radar change product,
  explicitly NOT the August landslide's detection model.

The chatbot defines an **open-source LangGraph StateGraph** for deterministic
intent routing and a strict UI-tool allowlist. Vercel uses the equivalent
lightweight deterministic fallback (without installing LangGraph) because the
full dependency exceeded Vercel's Python serverless bundle limit. For an
actual LangGraph runtime on a self-hosted server, install
\`requirements-chat-langgraph.txt\`. It
does **not** use a generative language model or paid API. Map-science
answers are deliberately limited to verifiable descriptions and available
tools. This repository is open source under MIT (see LICENSE);
external OSM, NASA and map-tile/data usage remains subject to
their own attribution and licenses.

To develop locally: `npm ci && npm run dev`; the Vite proxy sends
`/api` to local Python when separately configured. Production uses
the Vercel Python serverless routes. Run
`python -m unittest discover -s api/tests -v` and `npm run build`.

## Human exposure screening (OpenStreetMap)

The **Human exposure** map control performs one user-triggered, bounded
OpenStreetMap query near a nominated landslide location. It measures geometric
distance to building footprints, roads and sensitive facilities and reports
**urgent/high/medium/low review priority**. It is **not** an earthquake,
landslide danger, casualty, safety, or runout prediction; a site with no OSM
buildings is not necessarily uninhabited.

The scar U-Net (post-event Sentinel-2 + terrain) remains a distinct model.
If a prepared inference JSON tile includes user-supplied `geo_bounds`
[west, south, east, north] in EPSG:4326 and a nonempty `geo_source`,
the model response includes the largest predicted scar component's approximate
geographic centroid. A user can explicitly inspect mapped buildings there.
The standard Landslide4Sense example has no trusted georeference and cannot
be matched to buildings automatically.

- Endpoint: `GET /api/exposure?lon=85.53&lat=28.29&radius_m=500`
- Unit-tested geometry distances to actual mapped polygons/road lines
- OSM data attribution: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
- See [human exposure data and limitations](docs/landslide-human-exposure.md).
- For public production scale, replace community Overpass queries with
  maintained cached regional OSM extracts or a licensed provider.

## Landslide scar screening and GPU follow-up

**What is a scar?** It is land visibly disturbed *after* a landslide. The
Sentinel-2 + terrain U-Net segments these post-event pixels; it is not a
forecast of where a future landslide will happen.

The **Detect scars** panel now shows the held-out satellite tile, independent
reference mask, model prediction, and true-positive/false-positive/
false-negative overlay at the same time. It reports metrics for that one tile
separately from the fixed 80-chip test benchmark.

The API's `screening.review_priority` is a **heuristic review queue**, *not*
danger to people or a calibrated risk probability. Its low/medium/high tiers
are assigned from connected candidate-pixel extent; no-candidate is not
a safe-land declaration. Real consequence/severity classification requires
independently assessed slope stability, event dynamics, runout, infrastructure
and population exposure, and dedicated labels.

The repo contains a reusable two-NVIDIA-L40 training script at
`scripts/train_landslide_gpu_detached.sh`. It stages up to 2,200 pinned
Landslide4Sense training chips (reusing any matching local chips), fits two
independent spatial models and evaluates the fixed benchmark. It exports an
ONNX candidate under `~/castor-audit/landslide-scar-gpu-v2/release/`, but
**does not automatically replace the deployed model**. Promotion uses only
validation AP, never test F1; the test set has already been inspected during
prior iterations and is not a new independent generalization test.

The October/November GCOV gallery is explicitly post-event radar monitoring,
not a detector of the August 26 Rasuwa rock-ice avalanche. NISAR-GUNW
preprocessing and reviewed terrain-failure labels are a separate research task.

An observation atlas for the 2026 NASA Space Apps Challenge, [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/).

## Run

Use Node 22.12 or later within the Node 22 release line.

```sh
npm ci
npm run dev
npm run build
```

Install the runtime dependencies with `python -m pip install -r requirements.txt` and run `python api/landslide.py` in a second terminal. Vite proxies `/api` to port 8765. On Vercel the React/Vite frontend and Python function share a domain.

Use **Landslide forecast** to request a 30-arcsecond tile from NASA LHASA’s rainfall-triggered **Hazard Tomorrow** feed. Enter coordinates or use the map center (60°S–60°N). The Python route `GET /api/forecast?lon=3.05&lat=36.70` returns a preview, source GeoTIFF link, and retrieval timestamp. The public GIS service exposes no forecast issuance or validity timestamps. NASA supplies the model and forecasts. TerraPulse retrieves and displays its output.

Use **Find NISAR** to search anywhere by coordinates, map point or place name. Catalog matches show NISAR acquisitions. The dialog also retrieves dated NASA COOLR inventory features and opens an illustrative NISAR GCOV comparison of Rasuwa. Existing flood, earthquake and glacier cases display sourced observations.

Use **Detect scars → Run held-out example** to run a real Landslide4Sense test chip. The service also accepts compatible prepared tiles.

- `GET /api/landslide` returns the model card, channel order and held-out metrics.
- `GET /api/landslide?example=1` scores the example and returns its RGB preview and reference labels.
- `POST /api/landslide` accepts JSON with integer `width` and `height` (1–128) and `rows` in row-major order. Each pixel requires 14 values in Landslide4Sense order and units. Use null for missing bands. An entirely missing pixel returns a null score.

Two residual U-Nets were trained on Linux on separate NVIDIA L40 GPUs. The ensemble and score threshold were selected on 48 validation chips before scoring 80 held-out chips. Average precision was 0.691 and F1 was 0.662. The Python backend runs the exported ONNX network on CPU. Tiles smaller than 128 × 128 are edge-padded for inference. The app requires prepared Sentinel-2 and terrain chips for custom inference. The worldwide map queries observations and existing inventories. The NISAR comparison shows backscatter change, with no field-validated hazard labels.

Training uses [Landslide4Sense](https://github.com/iarai/Landslide4Sense-2022). The `machine learning/l4s_stage.py` script takes the baseline metrics, an output data directory, and the training chip count. Run `l4s_spatial.py train --help` for CUDA training and `l4s_spatial.py select --help` for validation selection, held-out evaluation, and ONNX export. The model artifact and split IDs are stored in `server_data/`. The separate `stage_gfs_window.py` script extracts timestamped NOAA GFS 24-hour precipitation from an archived, specified run for future forecast evaluation.

## Published observations

- **Lower Limpopo, Mozambique.** Downloaded NASA GIBS Terra MODIS band 7/2/1 composites for 17 December 2025 and 25 January 2026. The app compares these optical observations and links to NASA's NISAR observations on 5 and 17 January 2026. The default flood layer displays NASA LANCE’s VIIRS three-day flood classification ending 25 January 2026. TerraPulse maps the published classes and exposes them on click.
- **Northern Venezuela.** Downloaded the numeric NASA JPL ARIA raster for NISAR's 13–25 June 2026 pair, reprojected and sampled it, and published the display raster and little-endian numeric grid. The grid conservatively suppresses the service's ambiguous zero fill. The two USGS event locations and the M7.5 ShakeMap contours provide separate earthquake context.
- **Pine Island Glacier.** Compare NASA GIBS NISAR radar observations from 3 and 15 October 2026. The case links to NASA’s ICESat-2 surface-height change visualization and the October NISAR GOFF record.

To rebuild the derived assets:

```sh
python -m pip install -r scripts/requirements.txt
python scripts/prepare_data.py
```

The repository includes the processed outputs for the cases. The [NASA Earthdata GIBS](https://www.earthdata.nasa.gov/data/projects/gibs), [NASA JPL ARIA](https://aria.jpl.nasa.gov/), [USGS](https://earthquake.usgs.gov/) and Natural Earth products retain their own terms and attribution. The NASA Space Apps logo identifies the event. This is a participant project.

The sourced hazard cases present dated observations. The landslide forecast uses the independent NASA LHASA feed documented above.

## Worldwide map

The three hazard tabs open worldwide catalogs. The default earthquake view shows magnitude 4.0+ in the seven days before the downloaded USGS snapshot. Switch to 1, 7, or 30 days, change the magnitude threshold, or toggle plate boundaries. Flood reports come from GDACS, with a separate dated NASA LANCE VIIRS satellite layer (visible after zooming in). Glacier points show the latest available annual mass balance and up to 12 recorded years from WGMS. These are monitored sites, and dates vary by site. Outlined markers open the detailed satellite cases.

Refresh the compact provider snapshots with `python scripts/prepare_world.py /path/to/DOI-WGMS-FoG-2026-02-10.zip`. The WGMS source is [Fluctuations of Glaciers Database, release 2026-02-10](https://doi.org/10.5904/wgms-fog-2026-02-10).

The sidebar lists observations in the selected hazard and lets readers filter them by place. **Ask TerraPulse** uses this same catalog and fixed map actions. Try “Compare Guelma”, “Earthquakes in Japan”, “Show M5+ earthquakes”, “Show rainfall” or “Open Pine Island”. The assistant runs in the browser and uses provider records and methods directly.

See [Data and models](docs/data-and-models.md) for collection IDs and units, the Guelma Earth Engine export workflow, and an evaluation plan for each hazard.

## NISAR radar comparisons

Guelma and Lake Réghaïa are searchable under Floods. Pine Island is under Glaciers. The date controls show georeferenced radar imagery and Compare swipes two NASA GIBS browse crops. Sources links the evaluated CMR records and local event or wetland references.

Recreate the imagery with `python scripts/prepare_radar_browse.py` after installing `scripts/requirements.txt`. This uses the [NASA GIBS NISAR Worldview layer](https://nisar-docs.asf.alaska.edu/worldview/). It is a daily visualization service that may mosaic acquisitions. The CMR records describe coverage and intended matching observation geometry, while the WebP images show what the service rendered for each date and crop. Numeric backscatter values require the calibrated GCOV arrays. We use NASA Worldview as a reference for dated comparison, and the [ASF NISAR Cookbook](https://github.com/ASFOpenSARlab/NISAR_Cookbook) as a reference for numeric extraction.

## Base map

NASA GIBS Blue Marble Shaded Relief and Bathymetry is the default basemap. The bundled Web Mercator overview mosaics the sixteen level-2 tiles, so the world opens without waiting on the satellite tile service. At regional zooms, the map requests finer NASA tiles. The browser fallback renders the same overview and observation locations. The optional [PB2002](https://github.com/fraxen/tectonicplates) plate boundaries by Peter Bird and Hugo Ahlenius / Nordpil are redistributed under [ODC-BY 1.0](https://opendatacommons.org/licenses/by/1-0/), with rounded coordinates and line segments split at the antimeridian.

### Further reliability and conversational improvements

- Same-origin EONET fallback uses a bounded official-category allowlist; archived
  reports are labeled as historical. Flood maps may show a dated GDACS bulletin
  snapshot when current EONET records are empty.
- GEM faults and Natural Earth glacier outlines are bundled locally.
  The GEM geometry is simplified for visualization, not engineering use.
- NASA GIBS imagery retries two older dates on tile errors. No-data regions
  may remain unavailable; this is not evidence a hazard is absent.
- The prominent **30 years · archive** control fetches historical USGS
  earthquakes year-by-year; this is distinct from live reports.
- The Sources page includes a user-run **Check data sources** table.
- Voice input uses browser SpeechRecognition when supported; spoken answers
  use SpeechSynthesis after explicit opt-in. No speech-service key is needed.
- For an optional real conversational LLM, add a Groq free-tier API key
  in Vercel Project Settings → Environment Variables as `GROQ_API_KEY`
  (optional model override `GROQ_MODEL`, default `llama-3.1-8b-instant`).
  Then redeploy. See https://console.groq.com/keys . Free quotas and
  provider limits are not guaranteed. Without a key, grounded scientific
  explanations and deterministic map actions remain functional.
