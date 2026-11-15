"""Bounded, on-demand OSM exposure evidence for a manually nominated site.

Demonstration only: public Overpass is community capacity, not a production
backend. Never run this automatically per map move or for bulk locations.
"""
from collections import deque, OrderedDict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from math import cos, radians, hypot
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import json
import os
import time

try:
    from .site_exposure import screen_site, validate
except ImportError:
    from site_exposure import screen_site, validate

OVERPASS = os.environ.get("TP_OVERPASS_API_URL")
GLOBAL_PROVIDERS = (
    ("Private.coffee", "https://overpass.private.coffee/api/interpreter"),
    ("VK Maps", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
)
USER_AGENT = "TerraPulse-SpaceApps-research/1.1 (https://github.com/aminemons/hackathonnasa)"
MAX_BODY = 3_000_000
MAX_ELEMENTS = 10000
BUDGET_SECONDS = 16
ATTEMPT_SECONDS = 5
FRESH_SECONDS = 3600
MAX_CACHE_AGE_SECONDS = 86400
MAX_CACHE_ENTRIES = 128
_query_times = deque(maxlen=20)
_rate_lock = Lock()
_cache = OrderedDict()
_cache_lock = Lock()
_retry_at = {}


class SourceUnavailable(OSError):
    def __init__(self, attempts):
        super().__init__('No configured OSM provider answered with a complete result')
        self.attempts = attempts


@lru_cache(maxsize=1)
def coverage():
    path = Path(__file__).resolve().parents[1] / 'server_data/osm/provider_coverage.json'
    return json.loads(path.read_text())


def _inside(lon, lat, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > lat) != (b[1] > lat) and lon < (b[0]-a[0])*(lat-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def _ring_distance(lon, lat, ring):
    points = [((x-lon)*111320*cos(radians(lat)), (y-lat)*111195) for x,y in ring]
    distances = []
    for a,b in zip(points,points[1:]+points[:1]):
        vx,vy = b[0]-a[0],b[1]-a[1]
        denominator = vx*vx+vy*vy
        t = max(0,min(1,-(a[0]*vx+a[1]*vy)/denominator)) if denominator else 0
        distances.append(hypot(a[0]+t*vx,a[1]+t*vy))
    return min(distances, default=0)


def _covered(region, lon, lat, radius_m):
    # The whole buffered query square must fit inside the regional extract.
    # A conservative 2x-radius boundary distance also avoids partial edge data.
    margin = 2*(radius_m+20)
    rings = region['rings']
    outer = any(not r['hole'] and _inside(lon,lat,r['coordinates']) and
                _ring_distance(lon,lat,r['coordinates']) > margin for r in rings)
    hole = any(r['hole'] and (_inside(lon,lat,r['coordinates']) or
               _ring_distance(lon,lat,r['coordinates']) <= margin) for r in rings)
    return outer and not hole


def providers(lon, lat, radius_m):
    if OVERPASS:
        # A configured private/regional endpoint is exclusive, not silently
        # mixed with public services. Operators remain responsible for scope.
        parsed = urlsplit(OVERPASS)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Configured Overpass endpoint must use HTTPS without URL credentials')
        return [('Configured provider', OVERPASS, 'configured')]
    result = []
    for name, region in coverage().items():
        if _covered(region,lon,lat,radius_m):
            result.append((f'Dresel {name}',region['endpoint'],name))
    return result + [(name,url,'global') for name,url in GLOBAL_PROVIDERS]


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
        '[out:json][timeout:4][maxsize:67108864];('
        f'way["building"]({bounds});'
        f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
        f'residential|living_street|service|unclassified|track|'
        f'footway|path|pedestrian|steps|bridleway|cycleway)$"]({bounds});'
        f'node["amenity"~"^(hospital|clinic|school|kindergarten|fire_station)$"]({bounds});'
        f'way["amenity"~"^(hospital|clinic|school|kindergarten|fire_station)$"]({bounds});'
        ');out geom qt;'
    )


def _fetch(url, query, deadline):
    # GET permits upstream caching of these small read-only queries.
    request = Request(url + ('&' if '?' in url else '?') + urlencode({'data':query}),
                      headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
    timeout = min(ATTEMPT_SECONDS, deadline-time.monotonic())
    if timeout <= 0:
        raise TimeoutError('OSM request budget exhausted')
    with urlopen(request,timeout=timeout) as response:
        if response.status != 200:
            raise OSError('Non-successful OSM response')
        chunks, total = [], 0
        read = getattr(response,'read1',response.read)
        while total <= MAX_BODY:
            if time.monotonic() >= deadline:
                raise TimeoutError('OSM response exceeded request budget')
            chunk = read(min(65536,MAX_BODY+1-total))
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
        if total > MAX_BODY:
            raise OSError('OSM response too large')
    osm = json.loads(b''.join(chunks))
    if (not isinstance(osm,dict) or not isinstance(osm.get('elements'),list)
            or osm.get('remark') or len(osm['elements']) > MAX_ELEMENTS):
        raise OSError('Incomplete, invalid or oversized OSM result')
    timestamp = osm.get('osm3s',{}).get('timestamp_osm_base')
    if not isinstance(timestamp,str):
        raise OSError('OSM result has no source timestamp')
    return {'elements':osm['elements'],'osm_timestamp':timestamp}


def load_osm(lon, lat, radius_m):
    candidates = providers(lon,lat,radius_m)
    query = _query(lon,lat,radius_m)
    key = (round(lon, 5), round(lat, 5), int(radius_m))
    now = time.monotonic()
    with _cache_lock:
        item = _cache.get(key)
        if item and now-item[0] < FRESH_SECONDS:
            return {**item[1],'mode':'memory_cache','cache_age_seconds':round(now-item[0])}

    with _rate_lock:
        # Best-effort in-process protection; production deployments need
        # shared storage, quotas and a licensed/extracted OSM data backend.
        current = time.monotonic()
        while _query_times and current - _query_times[0] > 60:
            _query_times.popleft()
        if len(_query_times) >= 6:
            raise RuntimeError("The demo has reached its local OSM query limit; retry later")
        _query_times.append(current)

    attempts = []
    deadline = time.monotonic()+BUDGET_SECONDS
    for name,url,scope in candidates:
        with _rate_lock:
            cooling = _retry_at.get(url,0)>time.monotonic()
        if cooling:
            attempts.append({'provider':name,'status':'cooldown'}); continue
        if time.monotonic()>=deadline:
            break
        try:
            result = _fetch(url,query,deadline)
            result.update(provider=name,scope=scope,mode='upstream',cache_age_seconds=0,
                          retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            with _cache_lock:
                _cache[key] = (time.monotonic(),result)
                _cache.move_to_end(key)
                while len(_cache)>MAX_CACHE_ENTRIES:
                    _cache.popitem(last=False)
            return result
        except (OSError,ValueError,TimeoutError) as exc:
            status = 'rate_limited' if isinstance(exc,HTTPError) and exc.code in (429,406) else 'unavailable'
            attempts.append({'provider':name,'status':status})
            with _rate_lock:
                _retry_at[url] = time.monotonic()+60
            if status=='rate_limited':
                break  # Respect rate limits; do not retry through another host.
    with _cache_lock:
        if item and time.monotonic()-item[0] < MAX_CACHE_AGE_SECONDS:
            return {**item[1],'mode':'cached_fallback',
                    'cache_age_seconds':round(time.monotonic()-item[0]),'provider_attempts':attempts}
    raise SourceUnavailable(attempts)


def exposure(lon, lat, radius_m=500):
    lon, lat, radius_m = validate(lon, lat, radius_m)
    data = load_osm(lon, lat, radius_m)
    report = screen_site(data['elements'], lon, lat, radius_m, data['osm_timestamp'])
    report['availability'] = {k:v for k,v in data.items() if k not in ('elements','osm_timestamp')}
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
        if status == 503:
            self.send_header('Retry-After','60')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path not in ("/api/exposure", "/api/exposure/"):
            return handler.send_json(self,{"error": "Unknown endpoint"}, 404)
        query = parse_qs(url.query)
        try:
            lon, lat, radius = validate(
                query.get("lon", [None])[0],
                query.get("lat", [None])[0],
                query.get("radius_m", ["500"])[0],
            )
        except ValueError as exc:
            return handler.send_json(self,{"error": str(exc)}, 400)

        try:
            result = exposure(lon, lat, radius)
        except (OSError, HTTPError, URLError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return handler.send_json(self,{
                "status": "unavailable",
                "error": "No covering OSM provider returned a complete result. Try again later or nominate a different location.",
                "provider_attempts":getattr(exc,'attempts',[]),
                "retry_after_seconds":60,
            }, 503)
        cache = 'no-store' if result['availability']['mode']=='cached_fallback' else 'public, s-maxage=300'
        return handler.send_json(self,result,cache=cache)


if __name__ == "__main__":
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer(("127.0.0.1", 8766), handler).serve_forever()
