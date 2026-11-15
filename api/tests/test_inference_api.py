"""Integration checks for released ONNX model and inference API."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api import landslide, forecast


class InferenceContractTests(unittest.TestCase):
    def test_actual_held_out_example_has_consistent_metrics(self):
        response = landslide.example_result()
        self.assertEqual(response["width"], 128)
        self.assertEqual(response["height"], 128)
        self.assertEqual(len(response["scores"]), 128 * 128)
        stats = response["example_evaluation"]
        self.assertEqual(stats["tp"] + stats["fp"] + stats["fn"] + stats["tn"],
                         stats["evaluated_pixels"])
        self.assertGreater(stats["evaluated_pixels"], 0)
        self.assertAlmostEqual(stats["f1"],
                               2 * stats["tp"] / max(1, 2 * stats["tp"] + stats["fp"] + stats["fn"]))
        self.assertEqual(response["screening"]["danger_assessment"], "not_available")
        self.assertIn(response["screening"]["review_priority"],
                      ("high", "medium", "low", "none_detected", "unavailable"))

    def test_any_missing_input_channel_remains_unscored(self):
        class DummySession:
            def run(self, *args, **kwargs):
                return [np.full((1, 1, 128, 128), 0.99, np.float32)]

        tile = np.ones((1, 2, 14), dtype=np.float32)
        tile[0, 0, 13] = np.nan
        with patch.object(landslide, "session", return_value=DummySession()):
            scores = landslide.predict(2, 1, tile)
        self.assertIsNone(scores[0])
        self.assertAlmostEqual(scores[1], 0.99, places=5)

    def test_model_card_does_not_claim_risk_forecast(self):
        card = landslide.model_card()
        self.assertEqual(card["task"], "post-event scar mapping")
        self.assertIs(card["model_scores_calibrated_as_hazard_probability"], False)
        self.assertEqual(card["chips"]["test"], 80)

    def test_invalid_forecast_coordinates_are_rejected_without_network(self):
        for lon, lat in ((float("nan"), 0), (0, float("inf")), (200, 10), (0, 90)):
            with self.subTest(lon=lon, lat=lat):
                with self.assertRaises(ValueError):
                    forecast.region(lon, lat)


if __name__ == "__main__":
    unittest.main()
