"""Local REST dispatcher for the same Vercel Python endpoint contracts.

Start locally: python -m api.local_server
Then: npm run dev   (Vite proxies /api to 127.0.0.1:8765).

Training and raster production are offline scientific jobs. The HTTP API
serves the published dated GLOF bundle, the saved ONNX scar model, NASA LHASA,
OpenStreetMap context and the deterministic chat tool router. No model
retraining or bulk satellite downloads occur per request.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
import os

try:
    from . import chat, exposure, forecast, glof, landslide, events, events
except ImportError:
    import chat, exposure, forecast, glof, landslide

GET = {
    "/api/landslide": landslide.handler.do_GET,
    "/api/forecast": forecast.handler.do_GET,
    "/api/exposure": exposure.handler.do_GET,
    "/api/chat": chat.handler.do_GET,
    "/api/glof": glof.handler.do_GET,
    "/api/events": events.handler.do_GET,
}
POST = {
    "/api/landslide": landslide.handler.do_POST,
    "/api/chat": chat.handler.do_POST,
}


class handler(BaseHTTPRequestHandler):
    # Existing handlers are intentionally delegated unchanged. Their
    # helpers are explicitly installed to avoid incompatible response code.
    send_json = landslide.handler.send_json
    respond = chat.handler.respond
    reply = events.handler.reply

    def do_GET(self):
        endpoint = urlsplit(self.path).path.rstrip("/")
        target = GET.get(endpoint)
        if target is None:
            return self.send_json({"error": "Unknown API route"}, 404)
        return target(self)

    def do_POST(self):
        endpoint = urlsplit(self.path).path.rstrip("/")
        target = POST.get(endpoint)
        if target is None:
            return self.send_json({"error": "Unsupported API method"}, 405)
        return target(self)


if __name__ == "__main__":
    port = int(os.environ.get("TERRAPULSE_API_PORT", "8765"))
    if not (1024 <= port <= 65535):
        raise ValueError("Set TERRAPULSE_API_PORT to a nonprivileged TCP port")
    print(f"[TerraPulse] Local API http://127.0.0.1:{port} serving routes:", ", ".join(GET), flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
