"""Portable WSGI host for the built atlas and the existing Python API contracts."""
from email.message import Message
from io import BytesIO
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from api.local_server import GET, POST, handler

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 4_000_000


class CapturedHandler(handler):
    """Run existing handlers in-process, retaining their status and headers."""

    def __init__(self, body):
        self.command = request.method
        self.path = request.path
        if request.query_string:
            self.path += "?" + request.query_string.decode("ascii")
        self.headers = Message()
        for key, value in request.headers:
            if key.lower() != "content-length":
                self.headers[key] = value
        self.headers["Content-Length"] = str(len(body))
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status = 200
        self.response_headers = []

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, key, value):
        self.response_headers.append((key, str(value)))

    def end_headers(self):
        pass


@app.route("/api/<path:endpoint>", methods=["GET", "POST"])
def api_route(endpoint):
    routes = POST if request.method == "POST" else GET
    key = "/api/" + endpoint.rstrip("/")
    target = routes.get(key)
    if target is None:
        status = 405 if key in GET or key in POST else 404
        return jsonify(error="Unsupported API method" if status == 405 else "Unknown API route"), status
    captured = CapturedHandler(request.get_data())
    target(captured)
    return Response(captured.wfile.getvalue(), status=captured.status,
                    headers=captured.response_headers)


@app.get("/healthz")
def health():
    ready = all(path.is_file() for path in [
        DIST / "index.html", ROOT / "server_data/landslide_spatial.onnx",
        ROOT / "server_data/glof/catalog.json",
        ROOT / "server_data/osm/provider_coverage.json",
    ])
    return jsonify(status="ready" if ready else "missing_assets"), 200 if ready else 503


@app.get("/")
def index():
    response = send_from_directory(DIST, "index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/<path:filename>")
def asset(filename):
    # send_from_directory enforces path containment; never expose repo files.
    response = send_from_directory(DIST, filename)
    if filename.startswith("assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif filename.startswith("data/glof-study/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.errorhandler(HTTPException)
def http_error(error):
    if request.path.startswith("/api/"):
        return jsonify(error=error.description), error.code
    return error


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
