"""OpenStreetMap human-exposure screening for a nominated landslide site.

This module does NOT estimate slope failure, debris runout, casualties, damage,
or probability of future danger. OSM absence does not imply absence of people.
Distances are geodesic-scale local approximations for <= 600 m searches.
"""
from math import cos, radians, hypot, isfinite
from datetime import datetime, timezone

OSM_CREDIT = "© OpenStreetMap contributors (ODbL)"
OSM_LICENSE = "https://www.openstreetmap.org/copyright"
MAJOR_ROADS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "living_street", "service", "unclassified", "track",
}
FOOTPATHS = {"footway", "path", "pedestrian", "steps", "bridleway", "cycleway"}
CRITICAL_AMENITIES = {"hospital", "clinic", "school", "kindergarten", "fire_station"}


def validate(lon, lat, radius_m=500):
    try:
        lon, lat, radius_m = float(lon), float(lat), float(radius_m)
    except (TypeError, ValueError) as exc:
        raise ValueError("Longitude, latitude and radius must be numbers") from exc
    if not (isfinite(lon) and isfinite(lat) and isfinite(radius_m)):
        raise ValueError("Coordinates and search radius must be finite")
    if not (-180 <= lon <= 180 and -80 <= lat <= 80):
        raise ValueError("Longitude must be -180..180, latitude -80..80")
    if not (100 <= radius_m <= 600):
        raise ValueError("Search radius must be 100–600 meters")
    return lon, lat, radius_m


def _xy(lon, lat, center_lon, center_lat):
    # Tangent-plane distance approximation valid for deliberately small sites.
    return (
        (lon - center_lon) * 111320.0 * cos(radians(center_lat)),
        (lat - center_lat) * 111195.0,
    )


def _segment_distance(a, b):
    """Shortest distance from origin to the closed segment a--b."""
    vx, vy = b[0] - a[0], b[1] - a[1]
    denom = vx * vx + vy * vy
    if denom <= 1e-18:
        return hypot(a[0], a[1])
    t = max(0.0, min(1.0, -(a[0] * vx + a[1] * vy) / denom))
    return hypot(a[0] + t * vx, a[1] + t * vy)


def _inside_polygon(vertices):
    # Ray casting; only used for building footprints, not an impact/runout zone.
    inside = False
    x, y = 0.0, 0.0
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        if (a[1] > y) != (b[1] > y):
            intersection = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < intersection:
                inside = not inside
    return inside


def _element_distance(element, lon, lat):
    geometry = element.get("geometry", [])
    if not isinstance(geometry, list) or not geometry:
        # OSM nodes (e.g. an individual school) need no geometry array.
        if element.get("type") == "node" and "lon" in element and "lat" in element:
            geometry = [element]
        else:
            return None
    if len(geometry) > 15000:
        return None
    try:
        points = [
            _xy(float(p["lon"]), float(p["lat"]), lon, lat)
            for p in geometry
        ]
    except (TypeError, KeyError, ValueError):
        return None
    if not all(isfinite(x) and isfinite(y) for x, y in points):
        return None
    if len(points) == 1:
        return hypot(*points[0])
    tags = element.get("tags", {})
    if "building" in tags and len(points) >= 3 and _inside_polygon(points):
        return 0.0
    return min(_segment_distance(a, b) for a, b in zip(points, points[1:]))


def screen_site(elements, lon, lat, radius_m=500, osm_timestamp=None):
    """Count mapped assets by actual footprint/line distance, not centroid."""
    lon, lat, radius_m = validate(lon, lat, radius_m)
    if not isinstance(elements, list) or len(elements) > 10000:
        raise ValueError("Unexpected OSM element count")

    categories = {"buildings": [], "roads": [], "paths": [], "sensitive_places": []}
    map_features = []
    map_features_truncated = False
    skipped = 0
    for element in elements:
        if not isinstance(element, dict) or not isinstance(element.get("tags"), dict):
            skipped += 1
            continue
        tags = element["tags"]
        building = tags.get("building")
        highway = tags.get("highway")
        amenity = tags.get("amenity")
        kinds = []
        if building and building not in ("no", "demolished"):
            kinds.append("buildings")
        if highway in MAJOR_ROADS:
            kinds.append("roads")
        elif highway in FOOTPATHS:
            kinds.append("paths")
        if amenity in CRITICAL_AMENITIES:
            kinds.append("sensitive_places")
        if not kinds:
            continue
        distance = _element_distance(element, lon, lat)
        if distance is None:
            skipped += 1
            continue
        if distance > radius_m:
            continue
        for category in kinds:
            categories[category].append({
                "osm_type": element.get("type", ""),
                "osm_id": str(element.get("id", "")),
                "distance_m": round(distance, 1),
                "category": amenity if category == "sensitive_places" else
                    (highway if category in ("roads", "paths") else building),
            })
        # Display only a bounded, attributed subset. The response is NOT a
        # runout footprint: OSM features are the background asset inventory.
        if len(map_features) >= 300:
            map_features_truncated = True
            continue
        geom = element.get("geometry", [])
        coordinates = []
        if isinstance(geom, list) and len(geom) <= 1000:
            try:
                coordinates = [[float(pt["lon"]), float(pt["lat"])] for pt in geom]
            except (ValueError, TypeError, KeyError):
                coordinates = []
        if not coordinates and element.get("type") == "node":
            coordinates = [[float(element["lon"]), float(element["lat"])]]
        if not coordinates:
            continue
        if len(coordinates) == 1:
            geometry = {"type": "Point", "coordinates": coordinates[0]}
        elif "buildings" in kinds and len(coordinates) >= 3:
            ring = coordinates if coordinates[0] == coordinates[-1] else coordinates + coordinates[:1]
            geometry = {"type": "Polygon", "coordinates": [ring]}
        else:
            geometry = {"type": "LineString", "coordinates": coordinates}
        map_features.append({
            "type": "Feature",
            "id": f'{element.get("type", "")}/{element.get("id", "")}',
            "geometry": geometry,
            "properties": {
                "kind": "buildings" if "buildings" in kinds else
                    ("sensitive_places" if "sensitive_places" in kinds else kinds[0]),
                "distance_m": round(distance, 1)
            }
        })

    for collection in categories.values():
        collection.sort(key=lambda obj: obj["distance_m"])

    def count(category, meters):
        return sum(asset["distance_m"] <= meters for asset in categories[category])

    buildings_30 = count("buildings", 30)
    buildings_150 = count("buildings", 150)
    roads_30 = count("roads", 30)
    roads_150 = count("roads", 150)
    sensitive_100 = count("sensitive_places", 100)
    sensitive_300 = count("sensitive_places", 300)

    if buildings_30 or sensitive_100:
        review = "urgent"
        explanation = "Mapped buildings within 30 m or a sensitive facility within 100 m of the nominated point"
    elif buildings_150 or sensitive_300 or roads_30:
        review = "high"
        explanation = "Mapped buildings/facilities nearby or a mapped road within 30 m"
    elif categories["buildings"] or roads_150 or categories["sensitive_places"]:
        review = "medium"
        explanation = "Mapped human assets in the local search area"
    elif categories["roads"] or categories["paths"]:
        review = "low"
        explanation = "Only mapped access routes or paths nearby; human exposure is still possible"
    else:
        review = "no_mapped_assets"
        explanation = "No relevant features returned by OSM; mapping may be incomplete"

    nearest = {
        category: collection[0]["distance_m"] if collection else None
        for category, collection in categories.items()
    }

    return {
        "location": {"lon": lon, "lat": lat, "radius_m": radius_m},
        "data_source": "OpenStreetMap via a bounded Overpass API query",
        "osm_timestamp": osm_timestamp,
        "attribution": OSM_CREDIT,
        "license_url": OSM_LICENSE,
        "counts": {
            "buildings_within_30m": buildings_30,
            "buildings_within_150m": buildings_150,
            "buildings_within_search_radius": len(categories["buildings"]),
            "roads_within_30m": roads_30,
            "roads_within_150m": roads_150,
            "roads_within_search_radius": len(categories["roads"]),
            "paths_within_search_radius": len(categories["paths"]),
            "sensitive_places_within_100m": sensitive_100,
            "sensitive_places_within_search_radius": len(categories["sensitive_places"]),
        },
        "nearest_m": nearest,
        "sample_assets": {k: assets[:8] for k, assets in categories.items()},
        "osm_geojson": {"type": "FeatureCollection", "features": map_features},
        "map_features_truncated": map_features_truncated,
        "skipped_elements": skipped,
        "human_exposure_review_priority": review,
        "explanation": explanation,
        "danger_assessment": "not_available",
        "landslide_probability": None,
        "runout_direction_analyzed": False,
        "population_estimated": False,
        "verified_scar_boundary": False,
        "method": "Measured horizontal distance from nominated point to OSM building footprints and road linework; fixed expert-review thresholds, not a trained severity classifier",
        "caution": (
            "This point is user-selected and is not automatically a confirmed scar. "
            "Buildings near it are not necessarily downhill or in the debris path. "
            "A low/no-mapped-assets result NEVER means safe. Real danger requires "
            "landslide geometry, slope and runout simulation, hazard timing, "
            "asset occupancy and locally verified maps."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
