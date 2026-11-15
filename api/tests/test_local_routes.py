"""Integrated HTTP route tests adapted from Ishaq's GLOF connection repair.

These tests use the real local dispatcher and exercise response contracts.
Only the external provider / LLM calls are mocked; routing, serialization,
geo screening and safety semantics are not mocked.
"""
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api import chat_provider, exposure, local_server


class LocalRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), local_server.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        with urlopen(self.url + path, timeout=12) as response:
            self.assertEqual(response.headers.get_content_type(), "application/json")
            return json.load(response)

    def post(self, path, body):
        req = Request(self.url + path, data=body,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=12) as response:
            return json.load(response)

    def test_glof_and_scar_card_routes(self):
        self.assertEqual(len(self.get("/api/glof")["sites"]), 5)
        summary = self.get("/api/glof?site=south_lhonak")
        self.assertEqual(summary["site"]["site_id"], "south_lhonak")
        card = self.get("/api/landslide")
        self.assertEqual(card["task"], "post-event scar mapping")
        self.assertFalse(card["model_scores_calibrated_as_hazard_probability"])

    def test_chat_post_act_and_speak_contracted(self):
        capabilities = self.get("/api/chat/")
        self.assertIn("speechSynthesis", capabilities["speech"])
        with patch.object(chat_provider, "_model_reply", return_value=None):
            body = json.dumps({"message": "Open GLOF monitoring"}).encode()
            reply = self.post("/api/chat", body)
        self.assertEqual(reply["actions"][0], {"type": "open_tool", "value": "glof"})
        self.assertIn("breach forecast", reply["reply"])
        self.assertFalse(reply["model_is_generative"])

    def test_chat_rejects_bad_json(self):
        req = Request(self.url + "/api/chat", data=b"{",
                      headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(req, timeout=12)
        self.assertEqual(error.exception.code, 400)
        self.assertIn("error", json.load(error.exception))

    def test_exposure_runs_geometry_with_fixture_source(self):
        school = {"type": "node", "id": 1, "lon": 85.53, "lat": 28.29,
                  "tags": {"amenity": "school"}}
        with patch.object(exposure, "load_osm",
                          return_value=([school], "2026-11-15T00:00:00Z")):
            result = self.get("/api/exposure?lon=85.53&lat=28.29&radius_m=500")
        self.assertEqual(result["counts"]["sensitive_places_within_100m"], 1)
        self.assertEqual(result["osm_geojson"]["features"][0]["geometry"]["type"], "Point")
        self.assertEqual(result["danger_assessment"], "not_available")

    def test_exposure_provider_failure_is_not_zero_assets(self):
        with patch.object(exposure, "load_osm", side_effect=OSError("offline")):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + "/api/exposure?lon=85.53&lat=28.29", timeout=12)
        self.assertEqual(error.exception.code, 503)
        body = json.load(error.exception)
        self.assertEqual(body["status"], "unavailable")
        self.assertNotIn("counts", body)

    def test_invalid_coordinates_and_unmapped_route(self):
        for path, expected in [
            ("/api/forecast?lon=nan&lat=0", 400),
            ("/api/exposure?lon=nan&lat=0", 400),
            ("/api/not-real", 404),
        ]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(self.url + path, timeout=12)
                self.assertEqual(caught.exception.code, expected)
                self.assertIn("error", json.load(caught.exception))


if __name__ == "__main__":
    unittest.main()
