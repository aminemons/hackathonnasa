"""Audit browser-visible NASA GIBS product identifiers against official WMTS.

This is a release diagnostic, not a guarantee of image coverage at an
arbitrary date/place. A valid WMTS layer may have transparent/no-data tiles.
"""
from pathlib import Path
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET
import re

HTML=(Path(__file__).resolve().parents[1]/"index.html").read_text()
LAYERS=re.findall(r"load:gibs\('([^']+)',(\d+),'([^']+)'",HTML)
URL="https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities"
print("[GIBS] Checking",len(LAYERS),"curated satellite visualizations", flush=True)
with urlopen(Request(URL,headers={"User-Agent":"TerraPulse-research-health-check/1.0"}), timeout=30) as r:
    payload=r.read(18_000_000)
root=ET.fromstring(payload)
WMTS="{http://www.opengis.net/wmts/1.0}"
OWS="{http://www.opengis.net/ows/1.1}"
catalog={}
for layer in root.iter(WMTS+"Layer"):
    key=layer.find(OWS+"Identifier")
    if key is None or not key.text:continue
    identifiers={element.text for element in layer.findall(".//"+WMTS+"TileMatrixSet") if element.text}
    formats=[el.text for el in layer.findall(WMTS+"Format")]
    catalog[key.text]=(identifiers,formats)
fail=[]
for layer,level,ext in LAYERS:
    if layer not in catalog:
        msg=f"MISSING PRODUCT: {layer}"
        fail.append(msg);print("[GIBS]",msg,flush=True);continue
    sets,formats=catalog[layer]
    tiles=f"GoogleMapsCompatible_Level{level}"
    check=tiles in sets or any(tiles in (name or "") for name in sets)
    matches=any(("jpeg" if ext=="jpg" else ext) in (fmt or "") for fmt in formats)
    print(f"[GIBS] {layer}: level={level} supported={check} extension={ext} supported={matches}", flush=True)
    if not check:
        print("[GIBS] Supported matrices:",sorted(sets),flush=True)
        fail.append(f"Unsupported matrix {tiles} for {layer}")
    if not matches:
        print("[GIBS] Supported formats:",formats,flush=True)
        fail.append(f"Unsupported format {ext} for {layer}")
if fail:
    raise SystemExit("NASA GIBS availability configuration needs fixes: "+"; ".join(fail))
print("[GIBS] Product matrix/format configuration verified. Actual daily imagery can still be unavailable.",flush=True)
