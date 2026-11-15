"""Bounded, on-demand OSM exposure evidence for a manually nominated site.

Demonstration only: public Overpass is community capacity, not a production
backend. Never run this automatically per map move or for bulk locations.
"""
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from math import cos, radians
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import json
import logging
import os
import time

try:
    from .site_exposure import screen_site, validate
except ImportError:
    from site_exposure import screen_site, validate

OVERPASS = os.environ.get("TP_OVERPASS_API_URL", "https://overpass.private.coffee/api/interpreter")
USER_AGENT = "TerraPulse-SpaceApps-research/1.1 (https://github.com/aminemons/hackathonnasa)"
MAX_BODY = 3_000_000
MAX_ELEMENTS = 10000
_query_times = deque(maxlen=20)
_rate_lock = Lock()
_cache = {}
_cache_lock = Lock()


def _bbox(lon, lat, meters):
    dy = meters / 111195.0
    dx = meters / (111320.0 * cos(radians(lat)))
    if lon - dx < -180 or lon + dx > 180:
        raise ValueError("This longitude crosses the antimeridian; select a nearby point")
    return (lat - dy, lon - dx, lat + dy, lon + dx)


def _query(lon, lat, radius_m):
    # Query slightly more than the search circle, then use exact geometry
    # distances in site_exposure; never rely on centroid-only proximity.
    south, west, north, east = _bbox(lon, lat, radius_m + 20)
    bounds = ",".join(f"{coord:.6f}" for coord in (south, west, north, east))
    return (
        '[out:json][timeout:10];('
        f'way["building"]({bounds});'
        f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
        f'residential|living_street|service|unclassified|track|'
        f'footway|path|pedestrian|steps|bridleway|cycleway)$"]({bounds});'
        f'node["amenity"~"^(hospital|clinic|school|kindergarten|fire_station)$"]({bounds});'
        f'way["amenity"~"^(hospital|clinic|school|kindergarten|fire_station)$"]({bounds});'
        ');out geom qt;'
    )


def load_osm(lon, lat, radius_m):
    if not OVERPASS.startswith("https://"):
        raise ValueError("Overpass endpoint must use HTTPS")
    # Cache network results for 24 hours per exact nominated location on warm
    # instances. CDN also caches successful GET responses.
    key = (round(lon, 5), round(lat, 5), int(radius_m))
    now = time.monotonic()
    with _cache_lock:
        item = _cache.get(key)
        if item and item[0] > now:
            return item[1]

    with _rate_lock:
        # Best-effort in-process protection; production deployments need
        # shared storage, quotas and a licensed/extracted OSM data backend.
        current = time.monotonic()
        while _query_times and current - _query_times[0] > 60:
            _query_times.popleft()
        if len(_query_times) >= 6:
            raise RuntimeError("The demo has reached its local OSM query limit; retry later")
        _query_times.append(current)

    payload = urlencode({"data": _query(lon, lat, radius_m)}).encode()
    request = Request(
        OVERPASS,
        data=payload,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urlopen(request, timeout=14) as response:
        if response.status != 200:
            raise OSError(f"OSM data provider returned HTTP {response.status}")
        data = response.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        raise OSError("OSM response too large for the bounded site query")
    osm = json.loads(data)
    if not isinstance(osm, dict) or not isinstance(osm.get("elements"), list):
        raise OSError("OSM provider returned an unexpected response")
    if osm.get("remark"):
        raise OSError("OSM provider could not complete the query")
    if len(osm["elements"]) > MAX_ELEMENTS:
        raise OSError("OSM site has too many elements for this demo")
    result = (
        osm["elements"],
        osm.get("osm3s", {}).get("timestamp_osm_base"),
    )
    with _cache_lock:
        _cache[key] = (time.monotonic() + 24 * 3600, result)
    return result


def exposure(lon, lat, radius_m=500):
    lon, lat, radius_m = validate(lon, lat, radius_m)
    elements, osm_timestamp = load_osm(lon, lat, radius_m)
    report = screen_site(elements, lon, lat, radius_m, osm_timestamp)
    report["site_status"] = "User-nominated location; independently confirmed landslide outline not supplied"
    report["query_mode"] = "one small user-initiated site lookup; not automatic global monitoring"
    return report


class handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200, cache="no-store"):
        content = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path not in ("/api/exposure", "/api/exposure/"):
            return self.send_json({"error": "Unknown endpoint"}, 404)
        query = parse_qs(url.query)
        try:
            lon, lat, radius = validate(
                query.get("lon", [None])[0],
                query.get("lat", [None])[0],
                query.get("radius_m", ["500"])[0],
            )
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)

        try:
            result = exposure(lon, lat, radius)
        except (OSError, HTTPError, URLError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            # Diagnostics must never contain the user-selected coordinates.
            logging.warning("TerraPulse OSM lookup failed: %s HTTP=%s",
                            type(exc).__name__, getattr(exc, "code", "NA"))
            return self.send_json({
                "status": "unavailable",
                "error": "The OSM data service is busy or unreachable. No safety conclusion can be made.",
            }, 503)
        return self.send_json(result, cache="public, s-maxage=86400, stale-while-revalidate=86400")


if __name__ == "__main__":
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer(("127.0.0.1", 8766), handler).serve_forever()
