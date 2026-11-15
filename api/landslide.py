"""Serve the validated Landslide4Sense segmentation model."""
from functools import lru_cache
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import isfinite
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import onnxruntime as ort

try:
    from .scar_assessment import assess
except ImportError:  # local development: python api/landslide.py
    from scar_assessment import assess

DATA = Path(__file__).resolve().parents[1] / "server_data"
TILE_SIZE = 128
MAX_BYTES = 4_000_000
BANDS = [f"B{band:02}" for band in range(1, 13)] + ["slope", "elevation"]


@lru_cache(maxsize=1)
def model_card():
    metrics = json.loads((DATA / "landslide_spatial_metrics.json").read_text(encoding="utf-8"))
    return {
        "model": "TerraPulse Sentinel-2 + Terrain U-Net ensemble",
        "model_version": "spatial-detector-2",
        "revision": metrics["revision"],
        "source": "https://huggingface.co/datasets/ibm-nasa-geospatial/Landslide4sense",
        "input": "12 Sentinel-2 bands and ALOS slope/elevation",
        "bands": BANDS,
        "threshold": metrics["validation"]["threshold"],
        "validation": metrics["validation"],
        "test": metrics["test"],
        "test_scope": "Repeated fixed Landslide4Sense benchmark on 80 chips",
        "chips": {name: len(ids) for name, ids in metrics["chip_ids"].items()},
        "task": "post-event scar mapping",
        "screening_definition": "Heuristic connected-candidate review priority; NOT physical danger or safety",
        "model_scores_calibrated_as_hazard_probability": False,
    }


@lru_cache(maxsize=1)
def session():
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(DATA / "landslide_spatial.onnx"), sess_options=options,
                                providers=["CPUExecutionProvider"])


def parse_tile(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object with width, height and rows.")
    width, height, rows = (payload.get(key) for key in ("width", "height", "rows"))
    if type(width) is not int or type(height) is not int or not (1 <= width <= TILE_SIZE and 1 <= height <= TILE_SIZE):
        raise ValueError("Width and height must be integers from 1 to 128.")
    if not isinstance(rows, list) or len(rows) != width * height:
        raise ValueError("Supply one row per pixel, ordered left to right and top to bottom.")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(BANDS):
            raise ValueError("Each pixel requires all 14 Landslide4Sense channels.")
        for value in row:
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or abs(value) > 3.4e38):
                raise ValueError("Band values must be finite float32 numbers or null.")
    tile = np.asarray(rows, dtype=np.float32).reshape(height, width, len(BANDS))
    return width, height, tile


def predict(width, height, tile):
    # The model needs all 12 optical and both terrain channels. Do not
    # silently score a partly missing pixel as if it were observed.
    valid = np.isfinite(tile).all(axis=2).reshape(-1)
    if not valid.any():
        return [None] * len(valid)
    pad = ((0, TILE_SIZE - height), (0, TILE_SIZE - width), (0, 0))
    inputs = np.ascontiguousarray(np.pad(tile, pad, mode="edge").transpose(2, 0, 1)[None])
    values = session().run(["scores"], {"tile": inputs})[0][0, 0, :height, :width].reshape(-1)
    return [float(value) if defined else None for value, defined in zip(values, valid)]


def result(payload):
    width, height, tile = parse_tile(payload)
    card = model_card()
    threshold = card["threshold"]
    scores = predict(width, height, tile)
    screening = assess(scores, width, height, threshold)
    # Only a supplied WGS84 georeference can link a predicted pixel to
    # OpenStreetMap. A generic Landslide4Sense benchmark chip has no geolocation.
    location = None
    if payload.get("geo_bounds") is not None:
        bounds = payload["geo_bounds"]
        source = payload.get("geo_source")
        if not (isinstance(bounds, list) and len(bounds) == 4
                and all(type(v) in (int, float) and isfinite(v) for v in bounds)):
            raise ValueError("geo_bounds must be [west, south, east, north] in EPSG:4326")
        west, south, east, north = map(float, bounds)
        if not (-180 <= west < east <= 180 and -80 <= south < north <= 80
                and east - west <= .2 and north - south <= .2):
            raise ValueError("geo_bounds must be a small valid geographic WGS84 tile")
        if not isinstance(source, str) or not (8 <= len(source.strip()) <= 300):
            raise ValueError("geo_source must name the independently georeferenced image source")
        if screening["regions"]:
            first = screening["regions"][0]
            col, row = first["centroid_pixel"]
            location = {
                "lon": west + (east - west) * col / width,
                "lat": north - (north - south) * row / height,
                "input_bounds": [west, south, east, north],
                "image_source": source.strip(),
                "region_pixels": first["pixels"],
                "status": "unverified_user_supplied_georeference",
                "warning": "Verify this georeference and scar candidate with source imagery; not a confirmed landslide."
            }
    return {
        "width": width, "height": height, "threshold": threshold, "scores": scores,
        "candidate_location": location,
        "candidate_pixels": screening["candidate_pixels"],
        "valid_pixels": screening["valid_pixels"],
        "input_quality": {
            "required_channels": BANDS,
            "incomplete_pixels": width * height - screening["valid_pixels"],
            "incomplete_pixels_are_unscored": True,
        },
        "screening": screening,
        "model_revision": card["revision"], "model_version": card["model_version"],
    }


@lru_cache(maxsize=1)
def example_result():
    with gzip.open(DATA / "landslide_example.json.gz", "rt", encoding="utf-8") as asset:
        tile = json.load(asset)
    response = result(tile) | {key: tile[key] for key in ("id", "rgb", "labels")}
    labels = tile["labels"]
    if len(labels) != response["width"] * response["height"] or any(y not in (0, 1) for y in labels):
        raise ValueError("Invalid trusted example labels")
    threshold = response["threshold"]
    # Per-tile evaluation, distinct from the fixed 80-chip benchmark result.
    actual = [(y, p >= threshold) for y, p in zip(labels, response["scores"]) if p is not None]
    tp = sum(y == 1 and pred for y, pred in actual)
    fp = sum(y == 0 and pred for y, pred in actual)
    fn = sum(y == 1 and not pred for y, pred in actual)
    tn = sum(y == 0 and not pred for y, pred in actual)
    response["example_evaluation"] = {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "evaluated_pixels": len(actual),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "iou": tp / (tp + fp + fn) if tp + fp + fn else 0.0,
    }
    return response


class handler(BaseHTTPRequestHandler):
    def send_json(self, body, status=200, cache="no-store"):
        content = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if urlsplit(self.path).path not in ("/api/landslide", "/api/landslide/"):
            self.send_json({"error": "Unknown endpoint"}, 404)
            return
        query = parse_qs(urlsplit(self.path).query)
        body = example_result() if query.get("example") == ["1"] else model_card()
        self.send_json(body, cache="public, max-age=300, s-maxage=3600")

    def do_POST(self):
        if urlsplit(self.path).path not in ("/api/landslide", "/api/landslide/"):
            self.send_json({"error": "Unknown endpoint"}, 404)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json({"error": "Use Content-Type application/json."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BYTES:
                self.send_json({"error": "JSON request must be between 1 byte and 4 MB."}, 413)
                return
            payload = json.loads(self.rfile.read(length))
            answer = result(payload)
        except (ValueError, OverflowError) as error:
            self.send_json({"error": str(error)}, 400)
            return
        self.send_json(answer)


if __name__ == "__main__":
    from forecast import handler as forecast_handler

    class LocalHandler(handler):
        def do_GET(self):
            if urlsplit(self.path).path == "/api/forecast":
                return forecast_handler.do_GET(self)
            return super().do_GET()

    ThreadingHTTPServer(("127.0.0.1", 8765), LocalHandler).serve_forever()
