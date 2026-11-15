"""Stateless, open-source LangGraph map assistant for Vercel.

No key, chat-history database, external generative AI endpoint or arbitrary
tool execution. The browser executes only whitelisted map controls.
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
import json

try:
    from .chat_router import plan
except ImportError:
    from chat_router import plan


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
        self.respond({
            "name":"TerraPulse open-source map assistant",
            "framework":"LangGraph StateGraph (deterministic intent and action routing)",
            "generative_llm_configured":False,
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
        if not (1 <= length <= 2048):
            return self.respond({"error":"Request too large; maximum 2048 bytes"},413)
        try:
            message=json.loads(self.rfile.read(length))
            if not isinstance(message,dict):
                raise ValueError("Expected JSON object")
            response=plan(message.get("message"))
        except (ValueError,TypeError,json.JSONDecodeError) as error:
            return self.respond({"error":str(error)},400)
        self.respond(response)
