# TerraPulse slope failure backend

This batch pipeline maps **post-event slope failure candidates** from NISAR L-band GUNW. It is designed for retrospective mapping after a second radar acquisition. Large changes may also come from snow, moving ice, rain, vegetation, shadows or other disturbances. A low model score or a missing pixel does not establish that a slope is stable.

## Rasuwa pilot

The August 26, 2026 rock–ice avalanche originated near 85.53°E, 28.29°N on Langtang Lirung. The pilot crop covers that source area. The independent study used pre/post optical imagery, including August 28 Cartosat-3 and Pléiades, to examine the collapse scar and distinguish it from the downstream flood. The paper documents the scar. Training needs a reviewed georeferenced boundary and explicit stable examples. [USGS event assessment](https://www.usgs.gov/programs/landslide-hazards/science/2026-nepal-debris-avalanche-and-flash-flood) · [Optical mapping study](https://doi.org/10.1007/s12524-026-02611-x)

| Role | ASF provisional granule | UTC acquisition dates |
| --- | --- | --- |
| Event | [G4296329930-ASF](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4296329930-ASF) | August 19–31, 2026 |
| Pre-event control | [G4287214426-ASF](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4287214426-ASF) | July 26–August 19, 2026 |

CMR confirms both footprints contain the crop. The pair shares the August 19 acquisition and matches track 98, frame 16, ascending pass, frequency A, HH and 40 MHz range bandwidth. The control spans 24 days and the event pair spans 12. This can confound coherence loss, particularly on ice. A closer post-event descending acquisition exists for August 16–28, but the available adjacent July 23–August 16 control has 40 MHz bandwidth versus the event's 20 MHz. The selected ascending stack holds bandwidth fixed at the cost of a later post-event image. Both products need valid-pixel coverage checks over the scar. [August 16–28 metadata](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4292286252-ASF) · [Descending control metadata](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4284904763-ASF)

## Features and QA

| Input | Use |
| --- | --- |
| `unwrappedInterferogram/HH/coherenceMagnitude` | Event and control coherence on the native ~80 m grid. Coherence is unitless and ranges from 0 to 1. Coherence loss is control minus event and ranges from −1 to 1. No minimum coherence gate is applied to these features because rapid failure can decorrelate a pixel. |
| `unwrappedInterferogram/HH/unwrappedPhase` and `connectedComponents` | Local phase gradient magnitude in rad/m in each pair. A center and all four neighbors must be valid, have coherence ≥0.25, and share one positive component ID. Component IDs and phase offsets are never compared between pairs. The gradient is an uncorrected disturbance feature and can contain atmospheric or unwrapping artifacts. |
| `unwrappedInterferogram/mask` and optional polarization `validDataMask` | Enforce valid reference and secondary coverage, exclude water and flagged RSLC anomalies, and preserve missing values. A separately supplied layover/shadow mask keeps pixels coded 1 on reprojection. GUNW validity flags do not by themselves resolve mountain radar visibility. |
| Independent pre-event DEM | Compute terrain slope in degrees after reprojecting a DEM in meters to the native radar grid. The DEM needs coverage of the crop plus one radar pixel in each direction. [Copernicus GLO-30](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) is one option. |
| Independently reviewed optical polygons | GeoJSON with `label` integer 1 for slope failure and 0 for reviewed stable terrain. Use local high-resolution pre/post optical imagery. Pixels outside explicitly assessed polygons remain unknown. Exclude downstream inundation, cloud, and ambiguous or unmapped terrain from the label layer. |

Input GUNW HDF5 contains the aligned radar measurements and metadata. GCOV provides calibrated backscatter for a future complementary analysis, GOFF provides amplitude-tracked offsets, and a COG is a raster storage format. This backend exports COGs for map publishing. [ASF GUNW guide and specification](https://nisar-docs.asf.alaska.edu/gunw/) · [ASF products overview](https://nisar-docs.asf.alaska.edu/products-overview/)

## Run on the hackathon Linux server

From `~/castor/machine learning`, use `/opt/spaceapps/bin/python` on the hackathon machine or install `requirements.txt` into a local Python virtual environment.

```bash
python=/opt/spaceapps/bin/python
"$python" -m unittest discover -s tests -v
"$python" landslide.py catalog nepal.json > nepal-cmr.json
```

The catalog command saves NASA CMR metadata only. An actual HDF5 header inspection on the hackathon server reached ASF and returned an Earthdata authentication challenge. The tests use synthetic HDF5 and GeoTIFF fixtures and a stub score instead of fitting a model. [Earthdata Login setup](https://nisar-docs.asf.alaska.edu/access-overview/)

Once Earthdata Login is set up on the server, set `EVENT_HDF5_URL` and `CONTROL_HDF5_URL` to the `event.hdf5` and `control.hdf5` fields in the catalog output. `inspect` reads scalar metadata, coordinate endpoints and dataset descriptors by HTTPS range requests up to 16 MiB per product. It refuses a full-body response.

```bash
"$python" landslide.py inspect "$EVENT_HDF5_URL" --earthdata > event-header.json
"$python" landslide.py inspect "$CONTROL_HDF5_URL" --earthdata > control-header.json
```

When ready to read crop pixels, `prepare` accepts already available local HDF5 paths or the ASF URLs with `--earthdata`. Remote preparation has a separate 128 MiB range budget per granule and also refuses full-file responses. Supply a documented radar visibility mask for the pilot before interpreting scores on these steep slopes. Use a separate output path for each run.

```bash
"$python" landslide.py prepare --pilot nepal.json --event "$EVENT_HDF5_URL" \
  --control "$CONTROL_HDF5_URL" --earthdata --dem dem.tif \
  --geometry-mask radar-visible.tif --labels reviewed.geojson \
  --label-source `URL and date of reviewed optical mapping` --output nepal-features.tif
```

When preparing unlabeled inference inputs, omit `--labels` and `--label-source`. For supervised training, supply a JSON array with a `stack`, `event`, `site` and `split` on each row. `stack` is relative to the manifest. Use whole events and sites across disjoint `train`, `validation`, and `test` partitions, with positive and negative labels in each. The loader also rejects shared acquisition times for the same track and pass, and shared granule IDs across splits. A single pilot is useful for visual inspection. A reliable estimate of generalization needs independently labeled events from additional sites.

```bash
"$python" landslide.py train splits.json slope-failure.joblib
"$python" landslide.py predict nepal-features.tif slope-failure.joblib nepal-candidates.tif
```

Training uses histogram gradient boosting, selects the binary threshold on validation F1 and reports test average precision, precision, recall and F1. Compare test average precision with the coherence-loss baseline and inspect missed scars and false positives in snow, water, shadow and stable slopes. Use only trusted model artifacts. The output COG contains a model score and a thresholded candidate mask with NaN for unobserved pixels. It retains granule IDs, acquisition times, grid and mask provenance. The model score has not been calibrated as a probability of landslide occurrence.

## CUDA tuning on Ubuntu

Use a team-local Python environment with the backend requirements and CUDA-enabled
XGBoost 3.2.0. It can reuse the hackathon Python environment's installed packages.

```bash
/opt/spaceapps/bin/python -m venv --system-site-packages "$HOME/castor-gpu-env"
python="$HOME/castor-gpu-env/bin/python"
"$python" -m pip install -r requirements.txt xgboost==3.2.0
"$python" landslide.py train splits.json slope-failure-gpu.joblib --gpu cuda:0 --trials 96 \
  > tuning-metrics.json 2> tuning-progress.log
```

The tuner checks that XGBoost actually trained on CUDA. It uses early stopping
and selects hyperparameters by validation average precision, then sets the
decision threshold on validation data and reports held-out test metrics.
The saved model runs inference on CPU. Each tuning run uses one GPU so it can
run on either L40. More trials help compare candidate settings, while additional
independently labeled sites are what establish whether performance generalizes.

The Rasuwa pilot can use the preliminary UNOSAT detachment polygon as an independent
positive reference. Keep its source attribution and assess its optical interpretation
before using it quantitatively. It supplies no stable class. The Copernicus GLO-30
tile at N28/E085 covers the pilot and supports a small remote crop. [UNOSAT product
4260](https://unosat.org/products/4260) · [Detachment geometry in the reconstruction
archive](https://github.com/hyoseokp/langtang-2026-cascade/blob/b5efb873006a3714b95cbb9c0b784c404df01f3f/data/source/unosat_4260/detachment_zone_utm45n.geojson) ·
[Copernicus DEM download layout](https://copernicus-dem-90m.s3.amazonaws.com/readme.html)

### Optical benchmark

The reproducible Landslide4Sense run trains on a fixed 120-chip subset, selects
a model on 48 validation chips, and evaluates once on 80 held-out test chips
from the published splits. It reads Sentinel-2 and ALOS-derived terrain bands
and writes a checkpoint for that schema. It can run while Earthdata access is
pending. [Dataset and labels](https://huggingface.co/datasets/ibm-nasa-geospatial/Landslide4sense)

```bash
"$python" l4s_benchmark.py "$HOME/castor-audit/l4s-reproduction"
```
