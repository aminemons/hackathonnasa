import unittest
from unittest.mock import patch
from api import chat
class TestChatScientific(unittest.TestCase):
    @patch.dict("os.environ",{"GROQ_API_KEY":""})
    def test_grounded_qa_without_api_key(self):
        out=chat.respond("What is SAR backscatter?")
        self.assertIn("polarization",out["reply"].lower())
        self.assertEqual(out["actions"],[])
        self.assertFalse(out["model_is_generative"])
        self.assertTrue(out["references"])
    @patch.dict("os.environ",{"GROQ_API_KEY":""})
    def test_action_still_whitelisted(self):
        out=chat.respond("Show landslides")
        self.assertEqual(out["actions"][0]["type"],"layer")
        self.assertIn("landslide",out["reply"].lower())
    @patch.dict("os.environ",{"GROQ_API_KEY":""})
    def test_glof_limitations(self):
        out=chat.respond("Explain GLOF and glacier speed")
        self.assertIn("breach",out["reply"].lower())
    def test_history_bounded(self):
        h=[{"role":"user","content":"x"*900} for _ in range(20)]
        self.assertEqual(len(chat.clean_history(h)),6)
        self.assertTrue(all(len(x["content"])<=500 for x in chat.clean_history(h)))
