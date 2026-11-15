"""Read and render NASA's published next-day LHASA hazard raster."""
from base64 import b64encode
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import json
from math import isfinite
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

NASA = "https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/LHASA_Hazard_Tomorrow/ImageServer"
SIZE = 144
SPAN = SIZE / 120
MAX_DOWNLOAD = 1_000_000
PALETTE = (
    (0.001, (37, 72, 113, 180)),
    (0.005, (48, 125, 168, 190)),
    (0.02, (102, 200, 192, 210)),
    (0.05, (244, 202, 96, 225)),
    (0.1, (238, 128, 60, 235)),
    (1.01, (198, 61, 65, 240)),
)


def region(lon, lat):
    if not (-180 <= lon <= 180 and -60 <= lat <= 60):
        raise ValueError("NASA LHASA covers longitudes −180° to 180° and latitudes −60° to 60°.")
    west = round(min(180 - SPAN, max(-180, lon - SPAN / 2)), 5)
    south = round(min(60 - SPAN, max(-60, lat - SPAN / 2)), 5)
    return [west, south, round(west + SPAN, 5), round(south + SPAN, 5)]


def nasa_raster(bounds):
    options = {
        "bbox": ",".join(map(str, bounds)), "bboxSR": "4326", "imageSR": "4326",
        "size": f"{SIZE},{SIZE}", "format": "tiff", "pixelType": "F32",
        "interpolation": "RSP_NearestNeighbor", "f": "image",
    }
    url = f"{NASA}/exportImage?{urlencode(options)}"
    request = Request(url, headers={"User-Agent": "TerraPulse-SpaceApps/1.0", "Accept": "image/tiff"})
    with urlopen(request, timeout=12) as response:
        data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD or response.headers.get_content_type() != "image/tiff":
            raise OSError("The upstream response was not a bounded GeoTIFF.")
    return url, data


def rgba(value):
    if not (isfinite(value) and 0 <= value <= 1):
        return 0, 0, 0, 0
    for upper, color in PALETTE:
        if value < upper:
            return color


def forecast(lon, lat):
    bounds = region(lon, lat)
    source, tiff = nasa_raster(bounds)
    with Image.open(BytesIO(tiff), formats=["TIFF"]) as hazard:
        if hazard.size != (SIZE, SIZE) or hazard.mode != "F":
            raise OSError("Unexpected NASA raster schema.")
        pixels = list(hazard.getdata())
    colors = [rgba(value) for value in pixels]
    valid = [value for value, color in zip(pixels, colors) if color[3]]
    west, south, east, north = bounds
    col = min(SIZE - 1, int((lon - west) / (east - west) * SIZE + 1e-8))
    row = min(SIZE - 1, int((north - lat) / (north - south) * SIZE + 1e-8))
    index = row * SIZE + col
    raster = Image.new("RGBA", (SIZE, SIZE))
    raster.putdata(colors)
    with BytesIO() as buffer:
        raster.save(buffer, "PNG", optimize=True)
        png = b64encode(buffer.getvalue()).decode("ascii")
    return {
        "model": "NASA LHASA 2.1",
        "product": "Hazard Tomorrow",
        "bounds": bounds,
        "resolution_arcseconds": 30,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "issued_at": None,
        "valid_from": None,
        "valid_to": None,
        "source": NASA,
        "geotiff": source,
        "valid_pixels": len(valid),
        "pixels": len(pixels),
        "point_value": pixels[index] if colors[index][3] else None,
        "peak_value": max(valid, default=None),
        "preview_png": "data:image/png;base64," + png,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)
        try:
            lon = float(query.get("lon", [""])[0])
            lat = float(query.get("lat", [""])[0])
            region(lon, lat)
        except ValueError:
            self.send_json({"error": "Enter longitude −180° to 180° and latitude −60° to 60°."}, 400)
            return
        try:
            body = forecast(lon, lat)
        except (OSError, UnidentifiedImageError):
            self.send_json({"error": "NASA’s forecast feed is temporarily unavailable."}, 502)
            return
        self.send_json(body, cache="public, s-maxage=600")

    def send_json(self, data, status=200, cache="no-store"):
        body = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)
