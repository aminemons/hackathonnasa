"""Optional generative replies for the map assistant.

Configuration is read only from the server environment. Model output can
propose a small set of map actions; every action is checked against the same
allowlist as the browser before it leaves this module.
"""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

try:
    from .chat_router import MAP_IDS, plan
except ImportError:
    from chat_router import MAP_IDS, plan

MAX_HISTORY = 8
MAX_REPLY = 1000
ALLOWED_TOOLS = {"forecast", "scar", "exposure", "nisar", "glof"}
ALLOWED_TABS = {"Dataset", "Time", "Legend", "Alarm"}
ALLOWED_PAGES = {"Map", "How", "Sources", "Alarm"}
ALLOWED_BASEMAPS = {"Satellite", "Streets", "Topographic"}
GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
DEFAULT_GATEWAY_MODEL = "nvidia/nemotron-3.5-lightning-free"

SYSTEM_PROMPT = """You are TerraPulse, a concise conversational guide for an Earth-observation map app.
Answer naturally and use earlier user/assistant turns to resolve follow-up questions.
Be honest about evidence and uncertainty. Never claim a validated warning, future landslide, earthquake prediction, exact forecast probability, casualty count, or site safety: observations and screening are not emergency warnings. The app has no live data tools for your answer; avoid claiming a current event is present. Explain general science plainly, and point users to the app's sources or tools when useful.

You may control the map only by returning one to three actions in the JSON response. Use actions only when the user asks to change the map or open a panel. Allowed actions:
- {"type":"open_tool","value":"forecast|scar|exposure|nisar|glof"}
- {"type":"layer","value":"quakes|faults|glac|eflood|fire|vol|plates|depth","enabled":true|false}
- {"type":"basemap","value":"Satellite|Streets|Topographic"}
- {"type":"zoom","lon":number,"lat":number,"zoom":number} (longitude -180..180, latitude -85..85, zoom 2..10)
- {"type":"period","days":1|7|30}
- {"type":"tab","value":"Dataset|Time|Legend|Alarm"}
- {"type":"page","value":"Map|How|Sources|Alarm"}
- {"type":"clear"}
Return exactly a JSON object with keys "reply" (string) and "actions" (array). Do not include markdown or additional keys. Never invent an action type or parameter."""


def validate_actions(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    valid = []
    layers = set(MAP_IDS.values())
    for action in value:
        if len(valid) == 3:
            break
        if not isinstance(action, dict):
            continue
        kind = action.get("type")
        target = action.get("value")
        target = target if isinstance(target, str) else None
        if kind == "open_tool" and target in ALLOWED_TOOLS:
            valid.append({"type": kind, "value": target})
        elif kind == "layer" and target in layers and type(action.get("enabled")) is bool:
            valid.append({"type": kind, "value": target, "enabled": action["enabled"]})
        elif kind == "basemap" and target in ALLOWED_BASEMAPS:
            valid.append({"type": kind, "value": target})
        elif kind == "zoom":
            lon, lat, zoom = (action.get("lon"), action.get("lat"), action.get("zoom"))
            if all(type(number) in (int, float) for number in (lon, lat, zoom)) and -180 <= lon <= 180 and -85 <= lat <= 85 and 2 <= zoom <= 10:
                valid.append({"type": kind, "lon": lon, "lat": lat, "zoom": zoom})
        elif kind == "period" and type(action.get("days")) is int and action["days"] in (1, 7, 30):
            valid.append({"type": kind, "days": action["days"]})
        elif kind == "tab" and target in ALLOWED_TABS:
            valid.append({"type": kind, "value": target})
        elif kind == "page" and target in ALLOWED_PAGES:
            valid.append({"type": kind, "value": target})
        elif kind == "clear":
            valid.append({"type": "clear"})
    return valid


def _history_messages(history) -> list[dict]:
    if not isinstance(history, list):
        return []
    result = []
    for item in history[-MAX_HISTORY:]:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            result.append({"role": item["role"], "content": content.strip()[:150]})
    return result


def is_configured(gateway_token: str | None = None) -> bool:
    if os.environ.get("TERRAPULSE_CHAT_API_URL", "").strip():
        return bool(os.environ.get("TERRAPULSE_CHAT_MODEL", "").strip())
    return bool(os.environ.get("AI_GATEWAY_API_KEY", "").strip()
                or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
                or (gateway_token and gateway_token.strip()))


def _model_reply(message: str, history, gateway_token: str | None = None) -> dict | None:
    custom_endpoint = os.environ.get("TERRAPULSE_CHAT_API_URL", "").strip()
    custom_model = os.environ.get("TERRAPULSE_CHAT_MODEL", "").strip()
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY", "").strip()
    gateway_token = gateway_token or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
    endpoint = custom_endpoint or GATEWAY_URL
    model = custom_model or DEFAULT_GATEWAY_MODEL
    try:
        is_gateway = not custom_endpoint or urlsplit(endpoint).hostname == "ai-gateway.vercel.sh"
    except ValueError:
        return None
    auth_token = os.environ.get("TERRAPULSE_CHAT_API_KEY", "").strip() if custom_endpoint else ""
    if not auth_token and is_gateway:
        auth_token = gateway_key or gateway_token
    if (custom_endpoint and not custom_model) or (not custom_endpoint and not (gateway_key or gateway_token)):
        return None
    # The configured URL is the complete OpenAI-compatible chat-completions URL.
    if not endpoint.startswith(("https://", "http://")):
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": message})
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 450,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = "Bearer " + auth_token
    try:
        request = Request(endpoint, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=7) as response:
            payload = json.loads(response.read(64 * 1024))
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return None
        reply = parsed.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            return None
        return {"reply": reply.strip()[:MAX_REPLY], "actions": validate_actions(parsed.get("actions")),
                "engine": "configured generative model", "model_is_generative": True}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError, IndexError):
        return None


def generate(message, history=None, gateway_token: str | None = None) -> dict:
    """Generate a conversational answer, keeping deterministic safety fallback."""
    if not isinstance(message, str) or not (1 <= len(message.strip()) <= 800):
        raise ValueError("Message must contain 1–800 characters.")
    prompt = message.strip()
    # Keep the trusted safety response in front of generative output.
    safe = plan(prompt)
    if safe.get("intent") == "safety" or (
        not safe.get("actions")
        and re.search(r"\b(?:safe|safety|dangerous|unsafe|casualties|death|evacuat\w*)\b", prompt.lower())
    ):
        return {**safe, "model_is_generative": False}
    result = _model_reply(prompt, history, gateway_token)
    if result is not None:
        # Established commands keep their known intent mapping. Generative
        # output can still answer naturally, but cannot silently change the
        # target of a supported map command.
        if safe.get("actions"):
            result["actions"] = safe["actions"]
        return result
    return plan(prompt)
