# OSM lookup availability repair

The original endpoint relied on one public Overpass host with a 14-second
socket timeout. The host timed out on even tiny status/ID queries, and the
deployed API returned 503. Increasing the query timeout cannot resolve an
unresponsive or overloaded provider.

## Public-provider routing

- Prefer Dresel's Europe or North America service **only** when the entire
  buffered query footprint fits its extract. The bundled Geofabrik `.poly`
  boundaries retain source URLs and SHA-256 in
  `server_data/osm/provider_coverage.json`.
- Else use the public global Private.coffee and VK Maps services. A Europe
  service is not used for Algeria; a North America service is not used for
  Himalayan sites or Peru. A successful empty response outside a provider's
  coverage must never become a zero-asset conclusion.
- `TP_OVERPASS_API_URL` still supports an operator-configured HTTPS endpoint.
  It is exclusive: requests are not silently sent to public fallback providers.
  Operators must ensure that endpoint covers their intended locations.

Regional services use daily Geofabrik extracts, so a live HTTP response is not
a claim of instantaneous OSM freshness. Every successful result includes the
OSM source timestamp plus provider, scope, retrieval time and cache mode.

The main `overpass-api.de` instance is no longer the application default. Its
current published guidance warns of overload and asks app operators to use
alternatives. No requests are redirected to the main OSM **editing** API.

References: [public instances and operator policies](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances),
[Europe boundary](https://download.geofabrik.de/europe.poly),
[North America boundary](https://download.geofabrik.de/north-america.poly).

## Bounded requests and caching

Small GET queries allow upstream caching. Each query declares four seconds and
64 MiB server memory; the client keeps the original 3 MB / 10,000-element
response caps. It rejects partial results with Overpass error remarks and
responses lacking a source timestamp.

Each attempt has a socket timeout up to five seconds, with a 16-second budget
for starting/reading attempts. A blocking socket operation can run to its
timeout after the budget expires, so this is not a hard real-time guarantee;
the Vercel function allows 25 seconds. No identical query is immediately retried
on the same host. Failed hosts cool down for 60 seconds; rate-limit responses
stop the request without hopping to another host. Unavailable API replies
include Retry-After and retain missing values.

Warm-process cache: reuse successful results for one hour; if providers fail,
a result under 24 hours old can be returned explicitly as `cached_fallback`.
Older data are rejected. The cache is bounded to 128 entries and is not durable
across cold serverless instances. CDN success caching is five minutes; fallback
responses are not cached by the CDN. These limits do not establish a shared
multi-instance quota or production service-level guarantee.

The UI labels cached data and retrieval time. It also explains when the map
preview is limited to 300 geometries while counts include the full returned
in-radius set. Exposure remains proximity screening, not runout or danger.

## Verification

On 15 November 2026, the actual exposure function retrieved:

- **Juneau:** 339 mapped buildings within 500 m, via the North America provider,
  about 4.2 seconds.
- **Paris:** 140 mapped buildings within 250 m, via the Europe provider,
  about 6.4 seconds.

Both responses retained source date `2026-11-14T21:20:41Z` and returned map
geometry. Full aggregate receipts are in `osm-live-verification.json`. These
are live source queries, not fixture-derived success claims; counts describe
OSM records, not independently verified physical exposure or people.

Offline tests cover regional/border exclusions, timeout failover, rate-limit
respect, partial/error responses, size caps, source timestamps, cache age and
request budgets, alongside the existing local HTTP/geometry tests. Frontend
builds pass; browser automation was unavailable for this follow-up, so live
verification is through the API rather than a new visual browser check.

Worldwide public-provider availability remains variable. Locations outside the
responding regional services can still return unavailable during global-provider
outages. No paid provider, account or synthetic asset fallback is introduced.

After deployment, recheck with one small nominated location:

```sh
curl 'https://hackathonnasa-sepia.vercel.app/api/exposure?lon=-134.419&lat=58.302&radius_m=500'
```
