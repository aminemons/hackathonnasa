# Landslide report scope and historical fallback

On 15 November 2026, NASA EONET returned zero open landslide events and zero
events in a 365-day lookback. Removing the date restriction returned 17 real
reports dated 23 March 2015 through 23 March 2020. The map's existing
"current / archived" layer stopped at one year and therefore displayed no data.

The repaired layer still prefers current/recent reports. When that scope is
empty or unavailable, it can display a bundled, dated snapshot from the same
NASA catalogue. The snapshot includes its source URL, retrieval timestamp,
SHA-256 of the retrieved response, original event IDs, dates and geometry.
It is in `public/data/landslides-eonet-archive.json`.

Five reports supply point locations. Twelve supply polygons; those are shown
as NASA-reported event regions, not manufactured center points or mapped scar
boundaries. Sidebar, legend and popups identify the historical period and the
map fits the available archive's extent.

The browser session cache version changes so a previously cached empty result
does not hide the repair. A page reload loads the new bundle.

Current monitoring keeps its original scope: it does not substitute historical
events into the Alarm feed. `/api/events?hazard=ls` can legitimately return an
empty current catalogue. `/api/events?hazard=ls&include_recent=1` explicitly
permits the labelled historical fallback. A zero NASA catalogue count does not
establish that no landslides occurred worldwide.

Regression tests exercise empty recent results, source outages, current-only
monitoring, stale browser caches, the actual snapshot, and polygon retention.
The Chromium smoke test checks the visible date label and all 17 map features.

Sources:

- [EONET API scope and status documentation](https://eonet.gsfc.nasa.gov/docs/v3)
- [Original all-status landslide query](https://eonet.gsfc.nasa.gov/api/v3/events?category=landslides&status=all&limit=300)
