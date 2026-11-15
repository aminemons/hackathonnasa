"""Auditable science snippets for a usable assistant with no external LLM key."""
import re

KNOWLEDGE=[
 ("radar",r"\b(sar|radar|backscatter|polarization|vv|vh|hh|hv)\b",
  "Synthetic aperture radar sends microwave pulses and measures returned signals. VV and HH transmit/receive the same polarization; VH and HV are cross-polarized. Backscatter changes can reflect moisture, roughness, vegetation or geometry, not uniquely a hazard. For change detection compare incidence angle, orbit, polarization and acquisition time.",
  "ESA Sentinel-1 SAR User Guide","https://sentinels.copernicus.eu/web/sentinel/user-guides/sentinel-1-sar"),
 ("nisar",r"\b(nisar|l.band|s.band|insar|interferometr)\b",
  "NISAR is a NASA–ISRO radar mission. Repeat SAR scenes can reveal surface change; interferometry can estimate line-of-sight displacement where coherence persists, while offset tracking can help with fast glacier motion. Radar observations alone do not certify a landslide or predict an earthquake.",
  "NASA NISAR","https://nisar.jpl.nasa.gov/"),
 ("landslide",r"\b(landslides?|slope|scar|susceptib|lhasa|unet|u.net)\b",
  "Landslide susceptibility asks which slopes are predisposed to failure using slope, geology, land cover and past events. NASA LHASA supplies a rainfall-triggered hazard outlook. TerraPulse’s U-Net detects post-event scar-like pixels on Sentinel-2 and terrain data. These are different tasks; a scar mask is not a future failure probability.",
  "NASA Landslides","https://landslides.nasa.gov/"),
 ("flood",r"\b(floods?|inundat|glofas|hand|water.mapp|drainage)\b",
  "Flood mapping uses radar observations and a dry reference to identify possible open water, with terrain masks and validation to reduce false positives. GloFAS models river-discharge forecasts, a separate product that is not integrated as a verified forecast here. Historical EONET/GDACS events are observations, not predictions.",
  "Copernicus GloFAS","https://global-flood.emergency.copernicus.eu/"),
 ("glacier",r"\b(glaciers?|ice|glof|outburst|its.live|velocity|mass.balance)\b",
  "Glacier speed measures surface motion; lake surface area measures visible water; neither alone estimates breach probability. Our five-lake study uses dated Sentinel-1 radar acquisitions and historical NASA ITS_LIVE velocities through 2024. An animated year marker is not physical glacier displacement.",
  "NASA ITS_LIVE","https://its-live.jpl.nasa.gov/"),
 ("earthquake",r"\b(earthquakes?|shakealert|magnitude|tectonic|fault|seismic)\b",
  "Earthquake catalogues report events after rupture. Earthquake early-warning systems detect a rupture already underway and may warn before strong shaking reaches another place; they do not predict when earthquakes begin. NISAR can help study deformation where suitable radar pairs exist.",
  "USGS Earthquake Hazards","https://www.usgs.gov/programs/earthquake-hazards"),
 ("fire",r"\b(fires?|wildfires?|firms|viirs|ndvi|fuel)\b",
  "FIRMS distributes satellite thermal anomalies and active-fire detections. A thermal detection is not the same as a spreading-fire boundary. Vegetation fuel, dryness, slope and forecasts of wind could support a spread outlook, but TerraPulse has not validated such a forecast.",
  "NASA FIRMS","https://firms.modaps.eosdis.nasa.gov/"),
 ("exposure",r"\b(exposure|infrastructure|population|buildings?|roads?|rail|bridges?|dams?|priority|risk)\b",
  "Hazard and exposure are distinct. First identify a dated, validated hazard footprint; then measure overlap with people, OSM roads, buildings, power and downstream assets. Missing OSM data never means no assets. A research review priority is not a safety warning or evacuation order.",
  "OpenStreetMap","https://www.openstreetmap.org/"),
 ("time",r"\b(30 years?|historical|archive|timeline|days|last year)\b",
  "Use the Time tab’s ‘Last 30 years’ control to fetch USGS historical earthquakes year by year. Those records are different from the 24-hour, 7-day and 30-day recent earthquake feeds. NASA EONET history is queried separately and may not cover all 30 years.",
  "USGS ComCat","https://earthquake.usgs.gov/fdsnws/event/1/"),
 ("dataset",r"\b(unavailable|not loading|empty|no events?|offline|source|dataset|loading|status)\b",
  "A working feed can have zero currently open reports. To see landslides or floods, select the dated EONET reports; historical closed events are labeled separately and floods may use the archived GDACS snapshot. Satellite tiles can have geographic, date and projection coverage limits. An unavailable source does not imply zero hazard.",
  "NASA EONET API","https://eonet.gsfc.nasa.gov/docs/v3"),
 ("classification",r"\b(classif|forecast|probab|low risk|high risk|trigger|confidence|accuracy)\b",
  "TerraPulse separates source observations, model scores, hazard outlooks and exposure review. LHASA displays research-only score bands (low below 0.02, moderate 0.02 to below 0.10, elevated at or above 0.10); these thresholds are not calibrated local probability cutoffs. No precise earthquake time or GLOF breach probability is claimed.",
  "NASA LHASA ImageServer","https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/LHASA_Hazard_Tomorrow/ImageServer")
]
def select(message,history=None):
    q=message.casefold()
    if re.search(r"\b(it|that|those|this|they|its)\b",q) and history:
        last=next((x.get("content","") for x in reversed(history)
                   if x.get("role")=="user" and isinstance(x.get("content"),str)), "")
        q+=" "+last.casefold()[:250]
    candidates=[]
    for i,(slug,pattern,answer,name,url) in enumerate(KNOWLEDGE):
        match=re.search(pattern,q)
        if match:
            # Prefer specific terms to the generic risk or dataset catch-all.
            score=len(match.group(0))+ (5 if slug in ("radar","nisar","landslide","flood","glacier") else 0)
            candidates.append((score,-i,slug,answer,name,url))
    if not candidates:return None
    _,_,slug,answer,name,url=max(candidates)
    return {"topic":slug,"answer":answer,"references":[{"title":name,"url":url}]}
