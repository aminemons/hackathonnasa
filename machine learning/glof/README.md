# GLOF scientific processing

This directory contains the actual Sentinel-1 water feature/inference code and
the three-indicator aggregation used by the integrated monitoring panel.
The trained model is `../../server_data/glof/model/water_model.json` relative
to this directory. The API serves published outputs; it does not retrain or
run geospatial processing inside a serverless request.

Install into a scientific Python environment:

```sh
python -m pip install -r "machine learning/glof/requirements.txt"
python "machine learning/glof/check_example.py"
```

The example is a real ESA Sentinel-1 RTC VV/VH crop for 7 October 2023 and
aligned Copernicus terrain at South Lhonak. Its manifest preserves source
granules and hashes. The check runs fresh CPU inference with the shipped
weights and compares lake area against the published run within one 20 m
pixel. It verifies reproducibility, not independently assessed accuracy.

For a full scientific artifacts directory, run from this directory:

```sh
python -m real_mvp.infer --root /path/to/artifacts --site south_lhonak
python -m real_mvp.simplified --root /path/to/artifacts
```

`infer` expects `water/water_model_card.json`, `water/models/water_model.json`
and `observed/<site>/manifest.json`, two-band VV/VH dB RTC GeoTIFFs on a
projected 20 m grid, and an exactly aligned `dem_lake.tif`. It preserves
unresolved lake components as null, not physical zero water. These weights
are not an L-band HH or ISRO S-band model.

`simplified` requires the earlier velocity reports/rasters, acquired GLIMS/JRC
subsets and, for South Lhonak elevation change, the repeat terrain crops.
Those larger analysis inputs remain in the source workspace and its
`output/evidence/simplified_mvp_run.tar.gz` reproducibility bundle. This Git
integration ships compact published results and one real inference example.

After execution, publish from the repository root:

```sh
python scripts/export_glof.py --artifacts /path/to/artifacts
```

This copies dated outputs and source lineage, model weights, 253 existing
per-epoch geometries, quality/reference checks and indicator imagery into the
web release. Review the changed release manifest before committing. A full
radar processing pass precedes aggregation/export; `infer` alone does not
refresh the three-indicator panel.

The water benchmark uses Sen1Floods11 independently supplied labels, with
11 held-out event-region folds. Local glacier/lake transfer remains limited;
see `docs/glof-monitoring.md`. GLIMS outlines are historical spatial candidates,
not verified hydrological connections. The repeat-terrain result covers only
5.2% of the selected South Lhonak glacier outline and is not lake water volume.
