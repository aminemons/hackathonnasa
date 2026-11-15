# Human exposure near suspected landslide scars

This feature supplements the post-event Sentinel-2 scar detector with
OpenStreetMap (OSM) building and road context. It does NOT predict landslide
onset, debris runout, building damage, casualties or safety.

## Inputs
- One manually nominated location and radius 100-600 m, or a candidate
  centroid derived from user-supplied georeferenced WGS84 image bounds.
- An on-demand bounded OSM Overpass query for buildings, roads, paths, and
  selected critical amenities (clinics, schools, hospitals).
- The held-out Landslide4Sense example is not georeferenced. It cannot be
  placed onto OSM and receives NO exposure or danger classification.
- Uploaded 14-channel model tile may optionally supply geo_bounds as
  [west, south, east, north] and geo_source as an independent acquisition
  reference. The bounds are still user-supplied, unverified provenance.

## Method
We calculate the shortest distance from the nominated site point to
mapped building footprints (polygons) and roads (polylines), not the
distances between feature centroids. Local tangent-plane distances are
suitable only for the small bounded area and nonpolar latitudes.

Human-exposure REVIEW tiers:
- urgent: building polygon within 30 m or mapped sensitive facility within 100 m
- high: other building within 150 m, facility within 300 m, or major road within 30 m
- medium: other building/facility within search radius or major road within 150 m
- low: other mapped access roads or paths only
- no_mapped_assets: no features returned; NEVER interpreted as safe
- unavailable: OSM request failed or exceeded limits, no conclusion

These thresholds are **unvalidated human exposure screening**, not a
calibrated hazard severity or probability model. The distinct scar
screening tiers classify candidate-mask patch size only.

Public API: GET /api/exposure?lon=85.53&lat=28.29&radius_m=500

Only explicit user-initiated queries contact Overpass. Requests are bounded
by site size, runtime, response bytes and a best-effort local rate limit.
Responses are cached for up to 24 hours. This is a hackathon demonstration,
NOT a sustainable Overpass-backed production service. For production use,
regionally cached OSM extracts or a licensed infrastructure provider and
durable per-user rate limits. Missing OSM buildings does not imply that
no buildings, people or population are present.

Attribution required: © OpenStreetMap contributors (ODbL)
https://www.openstreetmap.org/copyright

## What future impact/danger models actually need
Use independently validated landslide initiation and runout polygons, a
DEM and downslope/flow-routing, event type and material volume, physical
runout uncertainty, population occupancy, road accessibility, building
vulnerability and ground-truth damage/outcome labels. Hold out entire
events/regions when evaluating. Neither building proximity nor optical
post-event scar segmentation proves a building will be hit.

The August 2026 Rasuwa rock-ice avalanche is distinct from rainfall-
triggered landslide forecasts delivered by NASA LHASA.
