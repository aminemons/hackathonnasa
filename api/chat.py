"""Stateless grounded assistant API with deterministic map actions."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
import json
import os

try:
    from .chat_provider import clean_history, is_configured, respond as build_response
except ImportError:
    from chat_provider import clean_history, is_configured, respond as build_response


def respond(message, history=None, gateway_token=None):
    """Compatibility helper used by the science tests and local dispatcher."""
    return build_response(message, history, gateway_token)


def request_gateway_token(request):
    # Vercel injects this runtime-only header. In local development, the
    # provider reads VERCEL_OIDC_TOKEN from the environment instead.
    if os.environ.get("VERCEL") == "1":
        return request.headers.get("x-vercel-oidc-token")
    return None


class handler(BaseHTTPRequestHandler):
    # Keep this helper as a method: api.local_server binds it to the unified
    # REST handler when it delegates this endpoint.
    def respond(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path.rstrip("/") != "/api/chat":
            return self.respond({"error": "Endpoint not found"}, 404)
        self.respond({
            "name": "TerraPulse conversational map assistant",
            "generative_llm_configured": is_configured(request_gateway_token(self)),
            "conversation_storage": "none",
            "speech": "Browser speechSynthesis + optional SpeechRecognition",
            "actions": "strict deterministic whitelist",
            "limitations": "Research information, not an official emergency warning.",
        })

    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/") != "/api/chat":
            return self.respond({"error": "Endpoint not found"}, 404)
        if self.headers.get_content_type() != "application/json":
            return self.respond({"error": "JSON request required"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond({"error": "Invalid request size"}, 400)
        if not 1 <= length <= 12288:
            return self.respond({"error": "Request must be 1–12288 bytes"}, 413)
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected request object")
            message = data.get("message")
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 800:
                raise ValueError("Enter 1–800 characters")
            result = respond(message, data.get("history", []), request_gateway_token(self))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.respond({"error": str(error)}, 400)
        self.respond(result)
