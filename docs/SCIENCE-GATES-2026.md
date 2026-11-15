# TerraPulse scientific evidence gates — November 15, 2026

## Project contract

NASA Space Apps **Dancing with the SARs** asks for an interactive application that uses **NISAR** radar data to track and visualize **surface change**. It does not require predicting earthquakes or chaining three disasters. Our defensible promise: measure the change, identify the exact source, compare to independent observations and disclose uncertainty.

**First priority:** finish one scientifically trustworthy, quantitative NISAR before/after case inside the existing TerraPulse app. All extra hazards remain secondary until equally supported.

## What the completed November 14 logs establish

- Sen1Floods11 XGBoost V2: standard test P 0.8000, R 0.7455, F1 0.7718, IoU 0.6284; Bolivia geographical holdout P 0.8799, R 0.5556, F1 0.6811, IoU 0.5165. The 252/89/90 split is chip-level, NOT event-held-out; Bolivia has 15 chips. This model uses Sentinel-1, not NISAR.
- Validated NISAR GCOV HHHH (NASA Harmony), October 30 versus November 11, near 28.29 N, 85.53 E: before/after science GeoTIFFs were downloaded; a generated radar difference raster contained 504,081 reportedly valid pixels. Self-supervised CUDA XGBoost regressor used 180k training samples and a spatial 40k heldout set. Heldout MAE was 1.278 dB vs 1.343 dB baseline (~4.85% reduction). This evaluates **radiometric prediction**, not **flood/GLOF accuracy**.
- NISAR numeric pixels have not been independently verified through this chat. Run the new QA script on the server.

## Run the independent science audit from Windows

Requirements: Git, Node 22.12 or later, PowerShell 5.1, SSH and SCP; ability to authenticate to the team's Linux server.

    git clone --branch science-audit-2026-11-15 https://github.com/aminemons/hackathonnasa.git
    cd hackathonnasa
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_science_audit.ps1

The script builds the original website, sends only the QA script to Linux, recalculates F1/IoU/precision/recall from actual confusion counts, checks that the before/after/change NISAR GeoTIFFs have exactly matching CRS/shape/transform, and recomputes the physical dB change from positive linear powers. It downloads QA JSONs into audit-results. It **does not retrain** or modify the original datasets. Missing inputs are reported, not invented. Credentials are prompted by SSH and never saved into the repository.

A numeric PASS approves grid/algebra checks only; it is NOT independent hazard validation.

## Evidence-first pipeline

1. **Discovery:** NASA CMR granule IDs, dates in UTC, NISAR maturity, exact product, track/frame/orbit/polarization, acquisition time and region. CMR footprint matches are candidates, not verified pixel matches.
2. **Download:** acquire matched science arrays from NASA ASF/Harmony; archive original source names, variables, hashes, software/processing release and provenance.
3. **SAR quality control:** inspect coordinate reference, pixel transforms, NoData, quality masks, valid overlap, positive linear diagonal covariance power, and radiometric terrain correction. For GCOV HHHH **linear power**, the log ratio is 10 log10(P_after/P_before) dB. Do not use 20 log10 for power and do not log data already in dB.
4. **Control surfaces:** stable background regions, matched incidence geometry/polarization and season, topographic layover/shadow and calibration/registration. Separate negative controls and noise distributions.
5. **Flood track:** derive surface-water extent, exclude/label permanent water and water masked by vegetation, estimate newly inundated surface only when matched pre-event imagery exists. Confirm against independent flood masks/polygons, not merely a GDACS point. Our Sen1Floods11 V2 is a baseline trained on Sentinel-1; transfer to L-band NISAR is NOT validated.
6. **Earthquake track:** USGS event context + NASA ARIA/GUNW signed LOS deformation, unwrapped phase/coherence/connected components/reference location, comparison with GNSS where available. Event occurrence forecasting is outside the scope.
7. **Glacier/GLOF track:** GOFF pixel offsets and acquisition interval plus look geometry for glacier velocity, ICESat-2/ITS_LIVE independent comparison, lake boundary observations and documented flooding for a confirmed GLOF. Glacier speed is not mass balance; lake growth is not proof of outburst.
8. **Landslide track:** independent post-event landslide outlines or InSAR-validated slope motion plus rainfall/seismic triggers; evaluate event-level spatial holdouts and susceptibility separately from observed displacement. Avoid radar-shadow/layover false detections.
9. **Baseline and ML:** show threshold/change model and physical uncertainty before training another model; train spatial ML only with independent labels, clear holdouts, and improvement over baseline. 2 L40 GPUs are useful for paired ablations or multi-seed spatial segmentation, not decorative GPU utilization.
10. **Evaluation:** per-event IoU/recall/precision, false positives and area bias for water; GNSS LOS residual/uncertainty for seismic; ITS_LIVE/height-change error for glacier; polygon IoU or inventory recall for landslides. Include negative-control sites and missing-data areas. Track threshold chosen on validation only.
11. **Publish:** versioned COGs and numeric arrays, exact source record and times, confidence/uncertainty, QA JSON and citation attribution. UI must distinguish OBSERVED, CANDIDATE, MODELLED, and INDEPENDENTLY VALIDATED.
12. **Demo and submission:** One NISAR before/after case with source-specific pixel inspection and a clear uncertainty example, two honest secondary hazard pathways, model metrics and reproducibility link. Submit before official deadline.

## Causality: two conditional branches, not a fabricated universal chain

- Glacier movement and climatic conditions can affect lake formation and stability; a suitable trigger and a breached natural dam can cause a GLOF; downstream floods can erode slopes and contribute to landslides.
- Earthquake shaking can trigger slope failures, rockfalls or disruption of a glacial/natural dam; a flood requires water storage and a breach. Rainfall can independently cause floods and slope failures.

To attribute a particular event, establish geographic proximity, temporal ordering, plausible physics, measured exposure, independent event confirmation and alternatives. If any are missing, call it an **associated hazard**, not a demonstrated cause.

## Deliverables by teammate

- **Amine — integration/ML:** run QA, archive model/data checksums, publish one vetted NISAR science-data map with disclosure; integrate repository branch after checks pass.
- **Mohamed Idriss — ML evaluation:** test/valid/Bolivia confusion and error maps, event-held-out split audit, calibration, baselines and multiple seeds.
- **Ishak — SAR pipeline:** granule/product metadata, validated HH pair, quality/geometry masks, acquisition matching and sensor physical interpretation.
- **Meryem — geophysics:** validate all claims on earthquake, glacial movement, flood/GLOF and landslide causality; veto unsupported links.
- **Snds — UX:** meaningful date/source/units controls, validated observation legend, before/after slider, failed-coverage and uncertainty display.
- **Ghollem and remaining teammates — QA/demo:** trace citations, cross-browser tests, failure-mode cases and concise narrated live case.

## Stop conditions

- No trustworthy unit/CRS/polarization? Do not publish quantitative change.
- No independent ground truth? No flood/GLOF/landslide detection accuracy claim.
- Only scene footprints? No claimed observed surface change.
- Only Sentinel-1 layers? Do not claim a NISAR-native feature.
- No event-specific observations? Do not claim a causal cascade.
- Wrong labels, area units or period? Fix before redesign.
- Exported SSH credentials are present in the team chat. Rotate the shared server password and never commit it to source control.

## Source URLs

NASA challenge: https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/
NASA NISAR releases: https://nisar-docs.asf.alaska.edu/data-availability/availability-overview/
NASA GCOV: https://nisar-docs.asf.alaska.edu/gcov/
NASA GUNW: https://nisar-docs.asf.alaska.edu/gunw/
NASA GOFF: https://nisar-docs.asf.alaska.edu/goff/
NASA CMR: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
Sen1Floods11: https://github.com/cloudtostreet/Sen1Floods11
USGS catalog: https://earthquake.usgs.gov/data/comcat/
ITS_LIVE: https://its-live.jpl.nasa.gov/
