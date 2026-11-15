"""Offline unit tests for source-attributed monitoring, including no-warning semantics."""
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api import events


class SourceMonitorTests(unittest.TestCase):
    @patch.object(events, "_request")
    def test_usgs_impact_information_is_not_a_future_prediction(self, request):
        request.return_value = {"features": [{
            "id": "m123",
            "geometry": {"type": "Point", "coordinates": [80.0, 28.0, 8.4]},
            "properties": {
                "time": 1794700000000, "mag": 5.4, "place": "Nepal",
                "alert": "orange", "tsunami": 0, "sig": 700,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/m123",
            },
        }]}
        out = events.collect("eq", 5, days=7)
        self.assertEqual(out["records"][0]["level"], "impact_report")
        self.assertEqual(out["records"][0]["magnitude"], 5.4)
        self.assertEqual(out["records"][0]["depth_km"], 8.4)
        self.assertIn("NOT real-time emergency warnings", out["monitor_kind"])
        self.assertIn("PAGER", out["disclaimer"])
        self.assertEqual(len(request.call_args_list), 1)
        self.assertIn("limit=3000", request.call_args.args[0])

    @patch.object(events, "_request")
    def test_eonet_empty_is_valid_but_not_a_warning(self, request):
        request.return_value = {"events": []}
        for hazard in ("ls", "fi", "fl"):
            with self.subTest(hazard=hazard):
                result = events.collect(hazard)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["records"], [])

    @patch.object(events, "_request")
    def test_eonet_polygon_retained_without_invented_center(self, request):
        request.return_value = {"events": [{
            "id": "EONET_123", "title": "Observed ice event",
            "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_123",
            "geometry": [{
                "date": "2026-11-14T08:00:00Z",
                "type": "Polygon",
                "coordinates": [[[2,3],[4,5],[2,3]]],
            }],
        }]}
        result = events.collect("ls")["records"][0]
        self.assertIsNone(result["lat"])
        self.assertIsNone(result["lon"])
        self.assertEqual(result["level"], "observation")

    def test_glacial_lake_monitor_references_dated_studies_not_eonet_ice(self):
        with patch.object(events, "_request") as request:
            result = events.collect("gl")
        request.assert_not_called()
        self.assertEqual(result["label"], "Glacial lakes")
        self.assertEqual(result["monitor_kind"], "historical, non-operational glacial-lake evidence")
        self.assertFalse(result["operational_warning_ready"])
        self.assertEqual(len(result["records"]), 5)
        self.assertTrue(all(item["id"].startswith("glof:") for item in result["records"]))
        self.assertTrue(all("not a GLOF warning" in item["notes"] for item in result["records"]))
        self.assertTrue(all(item["time"] < 1767225600000 for item in result["records"]))

    @patch.object(events, "_request")
    def test_malformed_eonet_response_is_unavailable_not_zero(self, request):
        request.return_value = {"unrelated": []}
        with self.assertRaises(RuntimeError):
            events.collect("ls")

    def test_finite_inputs_and_known_periods_required(self):
        for value in ("NaN", "Infinity", "a", 0, 99):
            with self.subTest(value=value), self.assertRaises(ValueError):
                events.collect("eq", value)
        with self.assertRaises(ValueError):
            events.collect("eq", 5, days=6)
        with self.assertRaises(ValueError):
            events.collect("unknown")

    @patch.object(events, "_request")
    def test_malicious_upstream_link_is_replaced_with_official_source(self, request):
        request.return_value = {"events": [{
            "id": "EVENT", "title": "Flood", "link": "javascript:alert(1)",
            "geometry": [{"date": "2026-11-14T08:00:00Z",
                          "type": "Point", "coordinates": [3.05,36.7]}],
        }]}
        result = events.collect("ls")["records"][0]
        self.assertEqual(result["url"], "https://eonet.gsfc.nasa.gov/")
        self.assertEqual(result["lat"], 36.7)


if __name__ == "__main__":
    unittest.main()
