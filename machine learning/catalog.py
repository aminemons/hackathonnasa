"""Metadata-only verification against NASA's Common Metadata Repository."""

import re
from urllib.parse import urlsplit

import requests

from gunw import match_pilot

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"


def get_granule(concept_id):
    if not re.fullmatch(r"G[0-9]+-ASF", concept_id):
        raise ValueError(f"Invalid ASF granule concept ID: {concept_id}")
    response = requests.get(CMR, params={"concept_id": concept_id}, timeout=30)
    response.raise_for_status()
    items = response.json()["items"]
    if len(items) != 1 or items[0]["meta"]["concept-id"] != concept_id:
        raise ValueError(f"CMR did not resolve {concept_id}")
    meta, umm = items[0]["meta"], items[0]["umm"]
    attrs = {a["Name"]: a["Values"][0] for a in umm["AdditionalAttributes"]}
    if attrs.get("PRODUCT_TYPE") != "GUNW" or attrs.get("FREQUENCIES") != "A":
        raise ValueError(f"Expected frequency A GUNW for {concept_id}")
    urls = [entry["URL"] for entry in umm["RelatedUrls"]
            if urlsplit(entry["URL"]).hostname == "nisar.asf.earthdatacloud.nasa.gov"]
    data_url, = [url for url in urls if urlsplit(url).path.endswith(f'{meta["native-id"]}.h5')]
    return {
        "concept_id": concept_id, "collection_id": meta["collection-concept-id"],
        "native_id": meta["native-id"], "revision": meta["revision-id"], "cmr": response.url,
        "track": int(attrs["TRACK_NUMBER"]), "frame": int(attrs["FRAME_NUMBER"]),
        "pass": attrs["ASCENDING_DESCENDING"], "polarization": attrs["FREQUENCY_A_POLARIZATION"],
        "bandwidth_mhz": int(attrs["FREQUENCY_A_RANGE_BANDWIDTH"]),
        "version": attrs["PRODUCT_VERSION"],
        "reference": attrs["REFERENCE_ZERO_DOPPLER_START_TIME"],
        "secondary": attrs["SECONDARY_ZERO_DOPPLER_START_TIME"],
        "footprints": [[(p["Longitude"], p["Latitude"]) for p in poly["Boundary"]["Points"]]
                       for poly in umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"]],
        "hdf5": data_url,
        "sidecars": [url for url in urls if url.endswith((".h5.iso.xml", "_QA_SUMMARY.csv", "_QA_REPORT.pdf"))],
    }


def pilot_metadata(pilot):
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    event = get_granule(pilot["event_granule"])
    control = get_granule(pilot["control_granule"])
    baselines = match_pilot(pilot, event, control)
    for key in ("collection_id", "track", "frame", "pass", "polarization", "bandwidth_mhz"):
        if event[key] != control[key]:
            raise ValueError(f"Event and control differ in {key}")
    extent = box(*pilot["bbox"])
    for granule in (event, control):
        footprint = unary_union([Polygon(coordinates) for coordinates in granule["footprints"]])
        granule["covers_bbox"] = bool(footprint.covers(extent))
        if not granule["covers_bbox"]:
            raise ValueError(f'{granule["concept_id"]} does not cover the pilot bounding box')
    return {"pilot": pilot, "baseline_days": baselines, "event": event, "control": control}
