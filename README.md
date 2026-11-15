# TerraPulse

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
