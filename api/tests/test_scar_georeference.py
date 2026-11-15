"""Regression tests: georeference only voluntarily provided and never trusted."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api import landslide


class GeoreferenceTests(unittest.TestCase):
    def sample(self):
        return {"width": 4, "height": 4, "rows": [[1.0] * 14 for _ in range(16)]}

    def evaluate(self, payload):
        with patch.object(landslide, "predict", return_value=[0.99] * 16), patch.object(
            landslide, "model_card",
            return_value={"threshold": 0.9, "revision": "test", "model_version": "test"},
        ):
            return landslide.result(payload)

    def test_benchmark_tile_is_not_geolocated(self):
        result = self.evaluate(self.sample())
        self.assertIsNone(result["candidate_location"])

    def test_wgs84_tile_converts_pixel_centroid(self):
        payload = self.sample()
        payload["geo_bounds"] = [85.52, 28.28, 85.54, 28.30]
        payload["geo_source"] = "EPSG:4326 scene manifest on validation fixture"
        result = self.evaluate(payload)
        point = result["candidate_location"]
        self.assertAlmostEqual(point["lon"], 85.53, places=5)
        self.assertAlmostEqual(point["lat"], 28.29, places=5)
        self.assertEqual(point["status"], "unverified_user_supplied_georeference")
        self.assertEqual(point["region_pixels"], 16)

    def test_missing_georef_provenance_rejected(self):
        payload = self.sample()
        payload["geo_bounds"] = [85.52, 28.28, 85.54, 28.30]
        with self.assertRaisesRegex(ValueError, "geo_source"):
            self.evaluate(payload)

    def test_too_large_georeferenced_tile_rejected(self):
        payload = self.sample()
        payload["geo_bounds"] = [80, 20, 90, 30]
        payload["geo_source"] = "Source beyond admissible tile size"
        with self.assertRaisesRegex(ValueError, "small valid"):
            self.evaluate(payload)


if __name__ == "__main__":
    unittest.main()
