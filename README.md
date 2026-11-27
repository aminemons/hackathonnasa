# TerraPulse

TerraPulse is a map-first Earth observation atlas for exploring natural hazards. It brings satellite imagery, event catalogues, dated scientific observations and model results into one interface so readers can check what was observed, when it was recorded and what the evidence supports.

**[Open the live TerraPulse demo](https://terrapulse-nasa-submission.vercel.app)**

> TerraPulse is a research demonstration. The location-based NASA LHASA forecast and OpenStreetMap infrastructure screening are temporarily unavailable. Please leave private locations out of those tools. TerraPulse does not issue official warnings.

## What you can do in the live demo

| Feature | What it shows |
| --- | --- |
| Hazard atlas | Explore the Equal Earth overview and drill down to the regional Leaflet map. Use layer and time controls to inspect earthquakes, landslides, glaciers, wildfires and floods. |
| Satellite evidence | Compare dated NISAR radar browse imagery for Guelma, Lake Réghaïa and Pine Island Glacier. Explore sourced case studies such as the Lower Limpopo flood and Northern Venezuela earthquake. |
| Glacial lake evidence | Explore five historical glacial lake outburst flood (GLOF) study sites, including South Lhonak. Compare 253 dated radar acquisitions and their quality flags, view dated lake outlines and export measurements as CSV. |
| Landslide scar inference | Run the held-out Landslide4Sense example or score a compatible prepared tile. Compare the predicted post-event scar with the reference mask when one is available. |
| Ask TerraPulse | Ask about the atlas or its evidence. A server-side Google Gemini integration handles conversational replies. Supported map actions use a deterministic router. |
| Alarm | Opt in to catalogue checks or a site watch for nearby reported landslides. Browser-only simulated proximity alerts use fictional observations and are labelled **Simulated**. OSM-based infrastructure checks are disabled in the live demo. |

Live catalogues and satellite overlays depend on provider coverage and availability. Dated archives can still be explored when a live feed is unavailable. The Sources view identifies providers, observation dates, retrieval times and verification status where available.

## Scientific methods and limits

- **Event reports and imagery.** The atlas uses USGS earthquake reports, NASA EONET event metadata, archived GDACS flood bulletins and NASA GIBS imagery. NISAR browse mosaics support visual comparisons. Quantitative backscatter needs calibrated source data. See [data and models](docs/data-and-models.md).
- **Glacial lakes.** The historical studies preserve acquisition dates, area measurements, threshold sensitivity, geometry and quality flags. Missing measurements stay blank. Lake area and outlines alone cannot establish water level, breach probability or downstream impact. See the [GLOF methods and API](docs/glof-monitoring.md).
- **Landslide scars.** A U-Net trained on Landslide4Sense uses prepared Sentinel-2 and terrain inputs. The bundled ONNX model runs on the server. Its F1 of 0.723 was measured on the previously evaluated 80-chip test subset. It measures benchmark segmentation performance and cannot establish event likelihood or site safety. See the [model and training notes](machine%20learning/README.md) and [infrastructure screening methods](docs/landslide-human-exposure.md).

The atlas distinguishes catalogue reports, satellite observations, model outputs and simulations. Use official agencies for emergency guidance.

## Technology

The frontend uses HTML, CSS and JavaScript served by Vite. Leaflet renders the regional map, D3-Geo draws the Equal Earth overview, and React powers the glacial lake viewer. Python serves the scientific and chat APIs, with ONNX Runtime for scar inference and Google Gemini for conversational generation. Vercel hosts the live demo and same-origin Python functions. A Flask/Gunicorn container is documented for [portable hosting](docs/portable-hosting.md).

## Run locally

Use **Node.js 22.12 or later within the Node 22 line**, npm and **Python 3.12**. The deployed Phase 4D build is `f2bb732d87b921cb58081ed49187fb132ff2e670`. This repository's `main` branch predates that snapshot, so the local interface and feature availability can differ from the live demo.

```sh
git clone https://github.com/aminemons/hackathonnasa.git
cd hackathonnasa
npm ci

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m api.local_server
```

In a second terminal at the repository root, run `npm run dev` and open the local URL printed by Vite. The development proxy forwards `/api` to `http://127.0.0.1:8765`.

```sh
npm run test:reliability
npm run test:glof
npm run build
python -m unittest discover -s api/tests -v
```

### Configuration

| Variable | Where it applies |
| --- | --- |
| `GEMINI_API_KEY` | Optional server-side Gemini credential. Set it in the Python process or hosting secret store. Local setup needs no key for the atlas or deterministic chat replies. |
| `GEMINI_MODEL` | Optional server-side model override. The default is `gemini-3.5-flash-lite`. |
| `TERRAPULSE_API_PORT` | Optional local Python port, default `8765`. |
| `TERRAPULSE_API_URL` | Optional Vite proxy target. Set it when changing the local API address. |
| `TP_DISABLE_LOCATION_APIS` | Server-side maintenance switch used on the deployed Phase 4D build. Production sets it to `1`. |

Keep real credentials out of Git and browser code. To enable Gemini locally, set `GEMINI_API_KEY` in the environment of the Python server before starting it.

## Repository guide

| Path | Contents |
| --- | --- |
| `index.html`, `src/` | Map workspace, data feeds, Alarm, and the GLOF viewer |
| `api/`, `deployment/` | Python handlers, local server and portable gateway |
| `public/data/`, `server_data/` | Published observations, geometry, scientific evidence and model artifacts |
| `machine learning/`, `scripts/` | Reproducible research workflows, model training and data preparation |
| `docs/` | Data provenance, scientific methods and hosting notes |

## Credits and license

TerraPulse is a participant project for the [2026 NASA Space Apps Challenge](https://science.nasa.gov/universe/nasa-welcomes-all-ages-experience-levels-for-space-apps-challenge/), for the *Dancing with the SARs* challenge. Thanks to [the project contributors](https://github.com/aminemons/hackathonnasa/graphs/contributors), including Amine (aminemons) and Ishaq Kolla (Ishaq-ML). The atlas draws on Meryem's NISASTER interface reference, and Ishaq contributed the glacial lake monitoring work.

Scientific and map credits include [NASA Earthdata GIBS](https://nasa-gibs.github.io/gibs-api-docs/), [NASA JPL ARIA](https://science.jpl.nasa.gov/projects/ARIA/), NASA/ASF NISAR, NASA EONET and LANCE, [USGS](https://earthquake.usgs.gov/), GDACS, WGMS, GEM, Natural Earth, and Esri, Maxar (Vantor) and Earthstar Geographics. [Landslide4Sense](https://github.com/iarai/Landslide4Sense-2022) provides the scar model benchmark. [PB2002 plate boundaries](https://github.com/fraxen/tectonicplates) credit Peter Bird and Hugo Ahlenius / Nordpil under [ODC-BY 1.0](https://opendatacommons.org/licenses/by/1-0/). [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) retain attribution under ODbL.

Project code is [MIT licensed](LICENSE). External imagery, maps and datasets retain their respective licenses and terms.

The [original submission notes](https://github.com/aminemons/hackathonnasa/blob/1d795d09efb7f0bb833fab0422d1607cb5291452/README.md) record earlier case-study dates, benchmarks and data preparation commands.
