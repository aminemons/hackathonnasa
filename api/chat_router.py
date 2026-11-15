"""Open-source TerraPulse chatbot planner for map controls and landslide science.

This graph is a deterministic LangGraph tool router, NOT a generative LLM.
No credentials, no paid APIs, no geolocation collection and no conversation
storage. Every returned action is an explicitly whitelisted UI operation.

An optional self-hosted LLM can be added later without changing the action
validation boundary. A safe map-science assistant benefits from predictable
actions more than unsupported free-form hazard claims.
"""
from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

try:
    from langgraph.graph import StateGraph, START, END
except ImportError:
    StateGraph = START = END = None

MAX_INPUT = 800

MAP_IDS = {
    "earthquake": "quakes", "earthquakes": "quakes", "quakes": "quakes",
    "fault": "faults", "faults": "faults",
    "glacier": "glac", "glaciers": "glac", "ice caps": "glac",
    "flood": "eflood", "floods": "eflood",
    "wildfire": "fire", "wildfires": "fire", "fire": "fire", "fires": "fire",
    "volcano": "vol", "volcanoes": "vol",
    "tectonic plate": "plates", "tectonic plates": "plates",
    "earthquake depth": "depth",
}
COUNTRIES = {
    "algeria": (2.7, 28.0, 5), "algiers": (3.05, 36.7, 8),
    "nepal": (84.1, 28.3, 6), "rasuwa": (85.53, 28.29, 10),
    "himalaya": (85.53, 28.29, 8), "himalayas": (85.53, 28.29, 8),
    "japan": (138.2, 36.2, 5), "tokyo": (139.7, 35.7, 9),
    "chile": (-70.66, -33.45, 5), "santiago": (-70.66, -33.45, 9),
    "italy": (12.5, 42.8, 6), "france": (2.2, 46.4, 6),
    "india": (79.1, 22.7, 5), "usa": (-98.0, 39.0, 4),
    "united states": (-98.0, 39.0, 4),
    "brazil": (-51.9, -14.2, 4),
    "antarctica": (0.0, -77.0, 3),
}
QUESTIONS = (
    ("difference between forecast and", "NASA LHASA forecasts rainfall-triggered hazard *before* a potential event. The U-Net identifies scar-like disturbed ground *after* an event. Neither by itself tells us who will be harmed."),
    ("what is a scar", "A landslide scar is visibly disturbed or exposed terrain left after slope material moves. Our optical U-Net maps likely scar pixels. It does not forecast when the slope will fail."),
    ("what are scars", "A scar is land already disturbed by a landslide. The Sentinel-2 U-Net maps potential post-event scars; it does not predict future collapse."),
    ("how accurate", "Our U-Net scored 66.2% F1 on a fixed 80-tile Landslide4Sense test subset. That is not worldwide performance or an estimate of risk to people."),
    ("what is nisar", "NISAR is a NASA-ISRO synthetic aperture radar mission. TerraPulse currently displays real radar backscatter changes; its optical landslide U-Net is not trained on NISAR."),
    ("how dangerous", "We cannot classify real-world safety from a satellite scar or building proximity alone. The exposure tool checks mapped nearby buildings, but true danger needs downslope runout, occupancy, ground conditions, and local expert verification."),
    ("is it safe", "A low score or missing OSM building does not establish safety. For an actual slope threat, use authoritative local emergency information and qualified geotechnical assessment."),
)


class State(TypedDict, total=False):
    message: str
    normalized: str
    actions: list[dict]
    reply: str
    intent: str


def normalize(message: str) -> str:
    compact = unicodedata.normalize("NFKC", message).strip().lower()
    compact = re.sub(r"\s+", " ", compact)
    return compact


def parse(state: State) -> dict:
    msg = normalize(state["message"])
    actions: list[dict] = []
    reply = ""
    intent = "explain"
    negative = bool(re.search(r"\b(hide|disable|remove|turn off|clear)\b", msg))
    # Questions must not accidentally toggle or open map layers.
    # The grounded science answer engine handles free-form questions.
    is_question=bool(re.match(r"^(what|why|how|when|where|explain|compare|tell me|is it|can you explain)\\b", msg))
    wants_action=bool(re.search(r"\\b(show|open|zoom|fly|go to|switch|turn on|turn off|hide|clear|display|inspect|check)\\b",msg))
    if is_question and not wants_action:
        return {"normalized":msg,"actions":[],
                "reply":"I can explain the evidence and distinguish observation, susceptibility, forecast and safety limitations.",
                "intent":"explain"}
    # First, scientific explanations take precedence over commands.
    for phrase, text in QUESTIONS:
        if phrase in msg:
            return {"normalized": msg, "actions": [], "reply": text, "intent": "explain"}
    if re.search(r"\b(urgent|risk|dangerous|unsafe|casualties|death|evacuat\w*)\b", msg):
        if not re.search(r"\b(show|check|open|inspect)\b", msg):
            return {"normalized": msg, "actions": [],
                    "reply": "I cannot tell if a site is safe or dangerous. Scar detection and OSM proximity are screening evidence, not a validated runout or life-safety forecast. For an immediate threat follow local emergency guidance.",
                    "intent": "safety"}
    if re.search(r"\b(help|what can you do|commands)\b", msg):
        return {"normalized": msg, "actions": [],
                "reply": "I can open NASA LHASA forecasts, compare post-event scar detections, inspect buildings/roads around a location, display NISAR observations, toggle map layers, select a basemap, open legend/time controls, or zoom to Nepal, Algeria, Japan, Chile and other supported places.",
                "intent": "help"}

    if re.search(r"\b(glof|glacial lake|outburst flood|lake outburst|monitor glacial lakes?)\b", msg):
        actions.append({"type":"open_tool", "value":"glof"})
        reply="Opening published historical glacial-lake monitoring: five lakes, 253 dated radar observations. It is not a breach forecast or emergency warning."
        intent="glof"
    elif re.search(r"\b(scars?|segmentation|unet|u-net|after landslide|detect landslide)\b", msg):
        actions.append({"type":"open_tool", "value":"scar"})
        reply="Opening post-event scar detection. It maps disturbed land after a landslide, not how dangerous the terrain is."
        intent="scar"
    elif re.search(r"\b(building|buildings|exposure|people|population|human impact|road|infrastructure|hospital|school)\b", msg):
        actions.append({"type":"open_tool", "value":"exposure"})
        reply="Opening OpenStreetMap human-exposure screening. This measures mapped nearby assets, not verified physical danger or casualties."
        intent="exposure"
    elif re.search(r"\b(forecast|tomorrow|lhasa|next.day|rainfall.triggered)\b",msg) and re.search(r"\b(landslide|slope|rain|forecast|lhasa)\b",msg):
        actions.append({"type":"open_tool", "value":"forecast"})
        reply="Opening NASA LHASA Hazard Tomorrow. Scores are not calibrated local landslide probabilities and exact issuance time is unavailable."
        intent="forecast"
    elif re.search(r"\b(nisar|sar|radar|backscatter|gunw|gcov|goff)\b",msg):
        actions.append({"type":"open_tool", "value":"nisar"})
        reply="Opening NISAR observations. Radar change is an observation, not a confirmed landslide or a forecast."
        intent="nisar"
    elif re.search(r"\b(landslide|landslides|slide events)\b",msg):
        actions.append({"type":"layer", "value":"slide","enabled":not negative})
        reply=("Showing" if not negative else "Hiding")+" currently open NASA EONET landslide reports, not the removed historical catalogue or a forecast."
        intent="layer"
    else:
        layer = None
        for keyword in sorted(MAP_IDS, key=len, reverse=True):
            if re.search(r"\b"+re.escape(keyword)+r"\b",msg):
                layer = MAP_IDS[keyword]
                break
        if layer:
            actions.append({"type":"layer","value":layer,"enabled":not negative})
            reply=("Showing" if not negative else "Hiding")+" the selected map layer."
            intent="layer"

    if re.search(r"\b(clear all|hide all|remove all|reset map)\b",msg):
        actions=[{"type":"clear"}]
        reply="Clearing the displayed dataset overlays."
        intent="clear"

    if re.search(r"\b(streets?|street map|road map)\b",msg) and not re.search(r"\b(near|building|exposure|people)\b",msg):
        actions.append({"type":"basemap","value":"Streets"})
        reply=reply or "Switching to streets basemap."
    elif re.search(r"\b(satellite|imagery)\b",msg) and not actions:
        actions.append({"type":"basemap","value":"Satellite"})
        reply="Switching to satellite basemap."
    elif re.search(r"\b(topographic|topo|terrain basemap)\b",msg):
        actions.append({"type":"basemap","value":"Topographic"})
        reply=reply or "Switching to the topographic basemap."

    match=re.search(r"\b(24\s*h|24 hours?|one day|today|7 days?|one week|30 days?|one month)\b",msg)
    if match:
        token=match.group(1)
        days=1 if "24" in token or "today" in token or token=="one day" else 7 if "7" in token or "week" in token else 30
        actions.append({"type":"period","days":days})
        reply=reply or f"Showing the {days}-day earthquake time window."

    if re.search(r"\b(legend|datasets?|time tab|alarm|sources)\b",msg) and re.search(r"\b(open|show|view|go to)\b",msg):
        if "legend" in msg: actions.append({"type":"tab","value":"Legend"})
        elif "time tab" in msg: actions.append({"type":"tab","value":"Time"})
        elif "dataset" in msg: actions.append({"type":"tab","value":"Dataset"})
        elif "alarm" in msg: actions.append({"type":"page","value":"Alarm"})
        elif "sources" in msg: actions.append({"type":"page","value":"Sources"})
        reply=reply or "Opening the requested interface section."

    for name in sorted(COUNTRIES,key=len,reverse=True):
        if re.search(r"\b"+re.escape(name)+r"\b",msg) and re.search(r"\b(zoom|fly|show|go to|near|in|map|rasuwa)\b",msg):
            lon,lat,zoom=COUNTRIES[name]
            actions.append({"type":"zoom","lon":lon,"lat":lat,"zoom":zoom})
            reply=(reply+" " if reply else "")+f"Centering the map approximately on {name.title()}."
            break

    if not actions:
        reply="I can control map layers and open the landslide tools, but I cannot verify an unsupported location or hazard claim. Try: 'forecast landslides', 'show scars', 'buildings near a landslide', 'show NISAR', 'show faults', or 'zoom to Nepal'."
    return {"normalized": msg, "actions":actions[:3],"reply":reply,"intent":intent}


def finalize(state: State) -> dict:
    # Strict output allowlist prevents arbitrary code, URLs and instructions.
    types={"open_tool","layer","basemap","zoom","period","tab","page","clear"}
    return {
        "actions":[a for a in state.get("actions",[]) if a.get("type") in types][:3],
        "reply":state.get("reply","No matching map command found.")[:1000],
    }


if StateGraph:
    graph = StateGraph(State)
    graph.add_node("parse",parse)
    graph.add_node("finalize",finalize)
    graph.add_edge(START,"parse")
    graph.add_edge("parse","finalize")
    graph.add_edge("finalize",END)
    COMPILED = graph.compile()
else:
    COMPILED = None


def plan(message:str) -> dict:
    if not isinstance(message,str) or not (1 <= len(message.strip()) <= MAX_INPUT):
        raise ValueError("Message must contain 1–800 characters.")
    initial:State={"message":message}
    result=COMPILED.invoke(initial) if COMPILED else finalize(parse(initial))
    return {
        "reply":result["reply"],
        "actions":result["actions"],
        "engine":"LangGraph deterministic tool router" if COMPILED else "deterministic tool router (LangGraph not installed)",
        "model_is_generative":False,
        "sources":{
            "landslide_forecast":"NASA LHASA",
            "scar_detection":"Landslide4Sense Sentinel-2 and ALOS terrain U-Net",
            "human_exposure":"OpenStreetMap",
            "nisar":"NASA-ISRO NISAR real observations",
        }
    }
