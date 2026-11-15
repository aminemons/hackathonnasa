import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_provider


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


class ChatProviderTests(unittest.TestCase):
    def test_action_validation_drops_unknown_and_out_of_range_actions(self):
        actions = chat_provider.validate_actions([
            {"type": "open_tool", "value": "forecast", "url": "javascript:alert(1)"},
            {"type": "open_tool", "value": ["forecast"]},
            {"type": "zoom", "lon": 0, "lat": 90, "zoom": 6},
            {"type": "layer", "value": "quakes", "enabled": "yes"},
            {"type": "layer", "value": "quakes", "enabled": True},
            {"type": "execute", "value": "anything"},
        ])
        self.assertEqual(actions, [{"type": "open_tool", "value": "forecast"},
                                   {"type": "layer", "value": "quakes", "enabled": True}])

    @patch.dict("os.environ", {"TERRAPULSE_CHAT_API_URL": "https://model.example/v1/chat/completions",
                               "TERRAPULSE_CHAT_MODEL": "earth-chat", "TERRAPULSE_CHAT_API_KEY": "secret"})
    @patch.object(chat_provider, "urlopen")
    def test_model_uses_server_key_and_conversation_history(self, urlopen):
        urlopen.return_value = Response({"choices": [{"message": {"content": json.dumps({
            "reply": "It is a radar measurement.",
            "actions": [{"type": "open_tool", "value": "nisar"}, {"type": "open_tool", "value": "shell"}],
        })}}]})
        result = chat_provider.generate("What is it?", [{"role": "user", "content": "What does NISAR measure?"},
                                                         {"role": "assistant", "content": "Radar."}])
        self.assertTrue(result["model_is_generative"])
        self.assertEqual(result["actions"], [{"type": "open_tool", "value": "nisar"}])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], "earth-chat")
        self.assertEqual([item["role"] for item in sent["messages"][-3:]], ["user", "assistant", "user"])

    @patch.object(chat_provider, "_model_reply", return_value={"reply": "Opening a layer.",
                                                               "actions": [{"type": "open_tool", "value": "glof"}],
                                                               "model_is_generative": True})
    def test_deterministic_map_intent_overrides_model_action(self, _model_reply):
        result = chat_provider.generate("show faults")
        self.assertEqual(result["actions"], [{"type": "layer", "value": "faults", "enabled": True}])

    @patch.object(chat_provider, "_model_reply", return_value={"reply": "Radar measures backscatter.", "actions": []})
    def test_explanation_does_not_inherit_keyword_map_action(self, _model_reply):
        result = chat_provider.generate("How does radar measure change?")
        self.assertEqual(result["actions"], [])

    @patch.dict("os.environ", {"TERRAPULSE_CHAT_API_URL": "https://gpu.example/v1/chat/completions",
                               "TERRAPULSE_CHAT_MODEL": "local-model", "AI_GATEWAY_API_KEY": "gateway-only"}, clear=True)
    @patch.object(chat_provider, "urlopen")
    def test_gateway_credential_is_not_sent_to_custom_model(self, urlopen):
        urlopen.return_value = Response({"choices": [{"message": {"content": '{"reply":"Ready.","actions":[]}'}}]})
        chat_provider.generate("hello")
        request = urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))

    @patch.dict("os.environ", {"AI_GATEWAY_API_KEY": "gateway-key"}, clear=True)
    @patch.object(chat_provider, "urlopen")
    def test_zero_price_gateway_model_defaults_to_open_weight_slug(self, urlopen):
        urlopen.return_value = Response({"choices": [{"message": {"content": '{"reply":"Hello.","actions":[]}'}}]})
        result = chat_provider.generate("hello")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://ai-gateway.vercel.sh/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "nvidia/nemotron-3.5-lightning-free")
        self.assertTrue(result["model_is_generative"])

    @patch.dict("os.environ", {"TERRAPULSE_CHAT_API_URL": "https://model.example/v1/chat/completions",
                               "TERRAPULSE_CHAT_MODEL": "earth-chat"})
    @patch.object(chat_provider, "urlopen", side_effect=TimeoutError)
    def test_model_failure_uses_deterministic_fallback(self, _urlopen):
        result = chat_provider.generate("show faults")
        self.assertFalse(result["model_is_generative"])
        self.assertEqual(result["actions"], [{"type": "layer", "value": "faults", "enabled": True}])

    @patch.dict("os.environ", {"AI_GATEWAY_API_KEY": "gateway-key"}, clear=True)
    @patch.object(chat_provider, "urlopen")
    def test_non_object_model_output_uses_fallback(self, urlopen):
        urlopen.return_value = Response({"choices": [{"message": {"content": "[]"}}]})
        self.assertFalse(chat_provider.generate("hello")["model_is_generative"])

    @patch.object(chat_provider, "_model_reply")
    def test_safety_response_bypasses_model(self, model_reply):
        self.assertIn("does not establish safety", chat_provider.generate("Is it safe?")["reply"])
        result = chat_provider.generate("When will the next earthquake happen in Japan?")
        model_reply.assert_not_called()
        self.assertFalse(result["model_is_generative"])
        self.assertEqual(result["actions"], [])
        self.assertIn("cannot predict the exact time", result["reply"])


if __name__ == "__main__":
    unittest.main()
