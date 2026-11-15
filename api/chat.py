"""Stateless chat API with an optional server-side OpenAI-compatible model."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
import json
import os

try:
    from .chat_provider import generate, is_configured
except ImportError:
    from chat_provider import generate, is_configured


class handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path not in ("/api/chat","/api/chat/"):
            return self.respond({"error":"Endpoint not found"},404)
        configured=chat_configured(self)
        self.respond({
            "name":"TerraPulse assistant",
            "framework":"OpenAI-compatible server-side chat with deterministic fallback",
            "generative_llm_configured":configured,
            "stores_conversations":False,
            "tools":["NASA LHASA forecast panel","Landslide scar comparison",
                     "OSM human-exposure screen","NISAR evidence gallery",
                     "Whitelisted dataset layer toggles","Map and basemap navigation"],
            "limitations":"Does not issue emergency warnings or estimate casualties, future slope failure, or safety.",
        })

    def do_POST(self):
        if urlsplit(self.path).path not in ("/api/chat","/api/chat/"):
            return self.respond({"error":"Endpoint not found"},404)
        if self.headers.get_content_type()!="application/json":
            return self.respond({"error":"Use application/json"},415)
        try:
            length=int(self.headers.get("Content-Length","0"))
        except ValueError:
            return self.respond({"error":"Invalid request size"},400)
        if not (1 <= length <= 12288):
            return self.respond({"error":"Request too large; maximum 12288 bytes"},413)
        try:
            message=json.loads(self.rfile.read(length))
            if not isinstance(message,dict):
                raise ValueError("Expected JSON object")
            prompt=message.get("message")
            response=generate(prompt, message.get("history", []), request_gateway_token(self))
        except (ValueError,TypeError,json.JSONDecodeError) as error:
            return self.respond({"error":str(error)},400)
        self.respond(response)


def request_gateway_token(request):
    # Vercel injects this runtime-only header; do not trust similarly named
    # headers supplied to this endpoint outside a Vercel function.
    if os.environ.get("VERCEL") == "1":
        return request.headers.get("x-vercel-oidc-token")
    return None


def chat_configured(request):
    return is_configured(request_gateway_token(request))
