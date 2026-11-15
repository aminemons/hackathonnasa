"""Reproducible, offline tests for OSM footprint/road proximity and API policy."""
import json
import math
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api import site_exposure
from api import exposure as exposure_api


def building(lon, lat, width=0.0001, ident=101):
    return {
        "type": "way", "id": ident, "tags": {"building": "yes"},
        "geometry": [
            {"lon": lon - width, "lat": lat - width},
            {"lon": lon + width, "lat": lat - width},
            {"lon": lon + width, "lat": lat + width},
            {"lon": lon - width, "lat": lat + width},
            {"lon": lon - width, "lat": lat - width},
        ],
    }


def road(lon, lat, ident=103):
    return {
        "type": "way", "id": ident, "tags": {"highway": "residential"},
        "geometry": [
            {"lon": lon - 0.001, "lat": lat},
            {"lon": lon + 0.001, "lat": lat},
        ],
    }


class ExposureTests(unittest.TestCase):
    def test_point_inside_footprint_is_zero_distance(self):
        result = site_exposure.screen_site([building(85.53, 28.29)], 85.53, 28.29)
        self.assertEqual(result["nearest_m"]["buildings"], 0)
        self.assertEqual(result["human_exposure_review_priority"], "urgent")
        self.assertEqual(result["danger_assessment"], "not_available")
        self.assertFalse(result["runout_direction_analyzed"])

    def test_line_distance_not_road_centroid(self):
        result = site_exposure.screen_site([road(85.53, 28.291)], 85.53, 28.29)
        self.assertGreater(result["nearest_m"]["roads"], 100)
        self.assertLess(result["nearest_m"]["roads"], 120)
        self.assertEqual(result["counts"]["roads_within_150m"], 1)

    def test_distant_building_remains_outside_radius(self):
        result = site_exposure.screen_site([building(85.54, 28.29)], 85.53, 28.29, 250)
        self.assertEqual(result["counts"]["buildings_within_search_radius"], 0)
        self.assertEqual(result["human_exposure_review_priority"], "no_mapped_assets")
        self.assertIn("NEVER", result["caution"])

    def test_school_is_sensitive_even_without_building_geometry(self):
        elements = [
            {"type": "node", "id": 42, "lon": 85.53, "lat": 28.2905,
             "tags": {"amenity": "school"}}
        ]
        result = site_exposure.screen_site(elements, 85.53, 28.29, 300)
        self.assertEqual(result["human_exposure_review_priority"], "urgent")
        self.assertEqual(result["counts"]["sensitive_places_within_100m"], 1)

    def test_invalid_coordinate_and_radius_fail_closed(self):
        for args in ((math.nan, 0, 500), (85, math.inf, 500), (85, 88, 500), (85, 28, 9999)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                site_exposure.validate(*args)

    def test_footpath_does_not_become_building_exposure(self):
        item = {
            "type": "way", "id": 30, "tags": {"highway": "path"},
            "geometry": [
                {"lon": 85.53, "lat": 28.29},
                {"lon": 85.5302, "lat": 28.29},
            ],
        }
        result = site_exposure.screen_site([item], 85.53, 28.29)
        self.assertEqual(result["counts"]["buildings_within_search_radius"], 0)
        self.assertEqual(result["counts"]["paths_within_search_radius"], 1)
        self.assertEqual(result["human_exposure_review_priority"], "low")

    def test_mocked_osm_fetch_and_cache(self):
        response = {
            "elements": [building(85.53, 28.29)],
            "osm3s": {"timestamp_osm_base": "2026-11-15T00:00:00Z"},
        }

        class FakeResponse:
            status = 200
            def __init__(self):
                self.body = BytesIO(json.dumps(response).encode())
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return self.body.read(limit)

        exposure_api._cache.clear()
        exposure_api._query_times.clear()
        exposure_api._retry_at.clear()
        with patch.object(exposure_api, "urlopen", return_value=FakeResponse()) as mocked:
            first = exposure_api.exposure(85.53, 28.29)
            second = exposure_api.exposure(85.53, 28.29)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(first["human_exposure_review_priority"], "urgent")
        self.assertEqual(second["osm_timestamp"], "2026-11-15T00:00:00Z")
        self.assertEqual(first["site_status"].split(";")[0], "User-nominated location")

    def test_overpass_query_is_bounded(self):
        query = exposure_api._query(85.53, 28.29, 500)
        self.assertIn('way["building"]', query)
        self.assertIn("out geom qt;", query)
        self.assertNotIn("node(around:999999", query)


if __name__ == "__main__":
    unittest.main()
