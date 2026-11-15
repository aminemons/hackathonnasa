"""Normalized, source-attributed natural-hazard event observations.

TerraPulse is a research viewer, NOT a life-safety early-warning service.
USGS ComCat publishes earthquakes after the rupture. NASA EONET tracks
natural events; its open/closed status is NOT a severity or flood/ice warning.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import json

HAZARDS = {
    "eq": ("Earthquakes", "USGS ComCat"),
    "ls": ("Landslides", "NASA EONET"),
    "gl": ("Glacial lakes", "Published ESA Sentinel-1 / NASA ITS_LIVE study"),
    "fi": ("Wildfires", "NASA EONET"),
    "fl": ("Floods", "NASA EONET"),
}
CATEGORIES = {"ls": "landslides", "fi": "wildfires", "fl": "floods"}
GLOF_DATA = Path(__file__).resolve().parents[1] / "server_data" / "glof"
MAX_RESPONSE = 7_000_000


def _request(url):
    req = Request(url, headers={"User-Agent": "TerraPulse-public-research/1.0 (https://github.com/aminemons/hackathonnasa)", "Accept": "application/json"})
    with urlopen(req, timeout=13) as response:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("The upstream event feed exceeded the response limit")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Upstream service returned a non-object response")
    return data


def _point(geometry):
    if not isinstance(geometry, dict):
        return None, None
    if geometry.get("type") != "Point":
        # EONET may include polygons. Don't invent a 'landslide center'.
        return None, None
    point = geometry.get("coordinates")
    if not isinstance(point, list) or len(point) < 2:
        return None, None
    try:
        lon, lat = float(point[0]), float(point[1])
    except (ValueError, TypeError):
        return None, None
    if not (isfinite(lon) and isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return None, None
    return round(lon, 6), round(lat, 6)


def _valid_url(value, origin):
    return value if isinstance(value, str) and value.startswith(origin) else origin


def _usgs(min_mag, now, days=1):
    start = now - timedelta(hours=30 if days == 1 else days * 24)
    query = urlencode({
        "format": "geojson", "orderby": "time", "limit": "3000",
        "minmagnitude": str(min_mag),
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    data = _request("https://earthquake.usgs.gov/fdsnws/event/1/query?" + query)
    if not isinstance(data.get("features"), list):
        raise RuntimeError("USGS reported an invalid feature collection")
    events = []
    for item in data["features"]:
        if not isinstance(item, dict):
            continue
        p, g = item.get("properties", {}), item.get("geometry", {})
        if not isinstance(p, dict):
            continue
        try:
            tm = int(p.get("time"))
            mag = float(p.get("mag"))
        except (TypeError, ValueError):
            continue
        if not isfinite(mag) or mag < min_mag:
            continue
        lon, lat = _point(g)
        alert = str(p.get("alert") or "").lower()
        high = alert in ("red", "orange")
        notable = alert == "yellow" or p.get("tsunami") == 1 or (p.get("sig") or 0) >= 600
        level = "impact_report" if high else "notable" if notable else "observation"
        notes = [f"Magnitude {mag:.1f}"]
        if alert in ("yellow", "orange", "red"):
            notes.append("USGS PAGER " + alert)
        if p.get("tsunami") == 1:
            notes.append("USGS tsunami flag (not a confirmed warning)")
        events.append({
            "id": "usgs:" + str(item.get("id") or p.get("code") or tm),
            "title": f"M {mag:.1f} · {str(p.get('place') or 'Earthquake')[:180]}",
            "place": str(p.get("place") or "Unknown location")[:180],
            "magnitude": mag,
            "depth_km": (float(g.get("coordinates", [None,None,None])[2]) if isinstance(g, dict) and len(g.get("coordinates") or []) >= 3 and isinstance(g.get("coordinates")[2], (int,float)) and isfinite(float(g.get("coordinates")[2])) else None),
            "time": tm, "lon": lon, "lat": lat,
            "level": level, "notes": " · ".join(notes),
            "url": _valid_url(p.get("url"), "https://earthquake.usgs.gov/"),
        })
    return events


def _eonet(hazard):
    category = CATEGORIES[hazard]
    data = _request("https://eonet.gsfc.nasa.gov/api/v3/events?" +
                    urlencode({"status": "open", "category": category, "limit": 200}))
    if not isinstance(data.get("events"), list):
        raise RuntimeError("EONET reported an invalid event collection")
    events = []
    for item in data["events"]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        observations = item.get("geometry") or []
        g = observations[-1] if observations else {}
        when = (g.get("date") if isinstance(g, dict) else None)
        try:
            dt = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamp = round(dt.timestamp() * 1000)
        except (TypeError, ValueError):
            continue
        lon, lat = _point(g)
        events.append({
            "id": f"eonet:{hazard}:{item['id']}",
            "title": str(item.get("title") or "Reported natural event")[:180],
            "time": timestamp, "lon": lon, "lat": lat,
            "level": "observation",
            "notes": "NASA EONET reported event · not a hazard severity warning",
            "url": _valid_url(item.get("link"), "https://eonet.gsfc.nasa.gov/"),
        })
    return events



def _glacial_lake_observations():
    """Published historical measurements; never a live glacier breach alarm.

    A glacier velocity record, lake surface area, and GLOF rupture probability
    are different physical quantities. No risk classification is inferred.
    """
    with (GLOF_DATA / "catalog.json").open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    sites = catalog.get("sites")
    if not isinstance(sites, list) or not sites:
        raise RuntimeError("Published glacial lake study catalog is invalid")
    records = []
    for site in sites:
        sid = site.get("site_id")
        if not isinstance(sid, str) or not sid.replace("_", "").isalnum():
            raise RuntimeError("Invalid published glacial lake site identifier")
        with (GLOF_DATA / sid / "summary.json").open(encoding="utf-8") as handle:
            study = json.load(handle)
        lake_series = study.get("lake", {}).get("series", [])
        if not isinstance(lake_series, list) or not lake_series:
            raise RuntimeError("Published lake record is missing its dated observations")
        last = max(lake_series, key=lambda row: row["date"])
        date = last.get("date")
        if not isinstance(date, str):
            raise RuntimeError("Published lake observation date is missing")
        when = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        velocity = study.get("movement", {}).get("series", [])
        observed_speed = [
            row for row in velocity
            if isinstance(row, dict) and isinstance(row.get("median_m_yr"), (int, float))
            and isfinite(row["median_m_yr"]) and row["median_m_yr"] >= 0
        ]
        latest_speed = max(observed_speed, key=lambda row: row["year"]) if observed_speed else None
        notes = [f"Sentinel-1 lake observation: {date}", "Historical study; not a GLOF warning"]
        if latest_speed:
            notes.append(
                f"ITS_LIVE {latest_speed['year']} glacier speed: "
                f"{latest_speed['median_m_yr']:.1f} m/year"
            )
        lat, lon = site.get("lat"), site.get("lon")
        if not all(isinstance(x, (int, float)) and isfinite(x) for x in (lat, lon)):
            lat = lon = None
        records.append({
            "id": f"glof:{sid}:{date}",
            "title": f"{site.get('name', sid)} · historical lake observation",
            "time": round(when.timestamp() * 1000),
            "lat": lat, "lon": lon,
            "level": "observation",
            "notes": " · ".join(notes),
            "url": "/api/glof?site=" + quote(sid, safe=""),
        })
    return records


def collect(hazard, min_mag=5.0, days=1):
    if hazard not in HAZARDS:
        raise ValueError("Unknown hazard; use eq, ls, gl, fi, or fl")
    try:
        magnitude = float(min_mag)
    except (TypeError, ValueError) as exc:
        raise ValueError("Minimum magnitude must be numeric") from exc
    if not (isfinite(magnitude) and 2 <= magnitude <= 9):
        raise ValueError("Minimum magnitude must be in 2..9")
    if days not in (1, 7, 30):
        raise ValueError('Earthquake period must be 1, 7, or 30 days')
    now = datetime.now(timezone.utc)
    records = (_usgs(magnitude, now, days) if hazard == "eq" else
               _glacial_lake_observations() if hazard == "gl" else _eonet(hazard))
    records.sort(key=lambda event: event["time"], reverse=True)
    return {
        "hazard": hazard, "label": HAZARDS[hazard][0], "source": HAZARDS[hazard][1],
        "fetched_at": now.isoformat(), "status": "ok",
        "records": records,
        "monitor_kind": ("historical, non-operational glacial-lake evidence"
                         if hazard == "gl" else "catalogue observations, NOT real-time emergency warnings"),
        "operational_warning_ready": False,
        "disclaimer": (
            "Glacial lake records are dated historical evidence, NOT a live GLOF alarm."
            if hazard == "gl" else
            "Updates may arrive after the event. EONET open status is not severity. "
            "USGS PAGER describes possible earthquake impacts, not a prediction."
        ),
    }


class handler(BaseHTTPRequestHandler):
    def reply(self, body, status=200):
        raw = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=60, stale-while-revalidate=60" if status == 200 else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path.rstrip("/") != "/api/events":
            return self.reply({"error": "Unknown endpoint"}, 404)
        q = parse_qs(urlsplit(self.path).query)
        try:
            hazard = q.get("hazard", [""])[0]
            days = int(q.get("days", ["1"])[0])
            payload = collect(hazard, q.get("min_magnitude", ["5"])[0], days=days)
        except ValueError as exc:
            return self.reply({"error": str(exc)}, 400)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError, KeyError, TypeError):
            return self.reply({"status": "unavailable", "error": "Source feed could not be verified; do not interpret as zero events"}, 503)
        self.reply(payload)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8767), handler).serve_forever()
