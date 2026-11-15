"""Source-scoped tests for no-hallucination map tool assistant."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chat_router import plan


class ChatRouterTests(unittest.TestCase):
    def action(self,prompt):
        out=plan(prompt)
        self.assertLessEqual(len(out["actions"]),3)
        return out

    def test_landslide_forecast(self):
        actions=self.action("Forecast landslides tomorrow in Nepal")["actions"]
        self.assertEqual(actions[0],{"type":"open_tool","value":"forecast"})
        self.assertTrue(any(a.get("type")=="zoom" for a in actions))

    def test_scars_are_post_event(self):
        out=self.action("show scars")
        self.assertEqual(out["actions"][0]["value"],"scar")
        self.assertIn("after",out["reply"])

    def test_exposure_is_not_danger(self):
        out=self.action("Check buildings near the landslide")
        self.assertEqual(out["actions"][0]["value"],"exposure")
        self.assertIn("not",out["reply"])

    def test_unsafe_claim_not_predicted(self):
        out=self.action("Is it safe?")
        self.assertEqual(out["actions"],[])
        self.assertIn("safe",out["reply"])

    def test_exact_time_prediction_is_rejected_before_generic_question(self):
        out=self.action("When will the next earthquake happen in Japan?")
        self.assertEqual(out["actions"],[])
        self.assertIn("cannot predict the exact time",out["reply"])

    def test_validated_benchmark_score_is_current(self):
        out=self.action("How accurate is the landslide model?")
        self.assertIn("72.3% F1",out["reply"])

    def test_open_science_question_does_not_change_map_layer(self):
        out=self.action("How does radar backscatter work?")
        self.assertEqual(out["actions"],[])

    def test_glof_observatory_is_not_a_warning(self):
        out = self.action("Monitor GLOF at glacial lakes")
        self.assertEqual(out["actions"][0], {"type":"open_tool","value":"glof"})
        self.assertIn("not a breach forecast", out["reply"])

    def test_nisar_evidence(self):
        out=self.action("Show real NISAR data")
        self.assertEqual(out["actions"][0]["value"],"nisar")

    def test_basemap(self):
        self.assertIn({"type":"basemap","value":"Satellite"},self.action("satellite imagery")["actions"])

    def test_zoom_geographical(self):
        out=self.action("Zoom to Algeria")
        self.assertTrue(any(a.get("type")=="zoom" and a.get("lon")==2.7 for a in out["actions"]))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            plan("")
        with self.assertRaises(ValueError):
            plan("a"*900)

    def test_no_arbitrary_command(self):
        out=self.action("run rm -rf /")
        self.assertEqual(out["actions"],[])


if __name__=="__main__":
    unittest.main()
