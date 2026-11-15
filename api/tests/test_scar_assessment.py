"""Regression tests for honest, post-event scar screening. No GPU needed."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scar_assessment import assess


class ScarAssessmentTests(unittest.TestCase):
    def test_no_candidate_does_not_claim_safe(self):
        result = assess([0.1] * 256, 16, 16, 0.9)
        self.assertEqual(result["review_priority"], "none_detected")
        self.assertEqual(result["danger_assessment"], "not_available")
        self.assertIn("not danger", result["warning"].lower())

    def test_missing_data_unavailable(self):
        result = assess([None] * 64, 8, 8, 0.8)
        self.assertEqual(result["review_priority"], "unavailable")
        self.assertEqual(result["valid_pixels"], 0)

    def test_medium_connected_candidate(self):
        grid = [0.1] * (16 * 16)
        for r in range(5):
            for c in range(6):
                grid[r * 16 + c] = 0.98
        result = assess(grid, 16, 16, 0.95)
        self.assertEqual(result["review_priority"], "medium")
        self.assertEqual(result["largest_reviewable_region_pixels"], 30)
        self.assertEqual(result["regions"][0]["bbox_pixels"], [0, 0, 6, 5])

    def test_high_connected_candidate(self):
        grid = [0.95] * (16 * 16)
        result = assess(grid, 16, 16, 0.9)
        self.assertEqual(result["review_priority"], "high")
        self.assertEqual(result["candidate_pixels"], 256)

    def test_isolated_false_alarms_remain_low_priority(self):
        grid = [0.01] * (16 * 16)
        for r in (0, 5, 10, 15):
            grid[r * 16] = 0.99
        result = assess(grid, 16, 16, 0.9)
        self.assertEqual(result["review_priority"], "low")
        self.assertEqual(result["reviewable_regions"], 0)

    def test_invalid_shapes_and_threshold_rejected(self):
        with self.assertRaises(ValueError):
            assess([0.2], 2, 2, 0.5)
        with self.assertRaises(ValueError):
            assess([0.2], 1, 1, math.nan)


if __name__ == "__main__":
    unittest.main()
