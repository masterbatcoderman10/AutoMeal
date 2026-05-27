from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from app.services.vision_service import (
    _coerce_detect_decision,
    _normalize_payload,
    detect_food_photo,
    detect_prompt,
    detect_response_format,
)


class DetectPromptTests(unittest.TestCase):
    def test_detect_prompt_includes_clutter_tolerance_rule(self) -> None:
        prompt = detect_prompt("https://example.test/meal.jpg")
        self.assertEqual(len(prompt), 1)
        self.assertEqual(prompt[0]["role"], "user")
        self.assertIsInstance(prompt[0]["content"], list)
        prompt_text = prompt[0]["content"][0]["text"].lower()
        self.assertIn("meal is clearly present anywhere in the frame", prompt_text)
        self.assertIn("utens", prompt_text)
        self.assertIn("continue", prompt_text)

    def test_detect_response_format_is_strict_json_schema(self) -> None:
        schema = detect_response_format()
        self.assertEqual(schema["type"], "json_schema")
        json_schema = schema["json_schema"]["schema"]
        self.assertTrue(json_schema["additionalProperties"] is False)
        self.assertIn("is_food", json_schema["required"])


class DetectPayloadTests(unittest.TestCase):
    def test_low_confidence_payload_skips(self) -> None:
        decision = _coerce_detect_decision({"is_food": True, "confidence": 0.3})
        self.assertEqual(decision["next_action"], "skip")
        self.assertFalse(decision["is_food"])

    def test_malformed_boolean_is_food_fails_closed_to_skip(self) -> None:
        decision = _coerce_detect_decision({"is_food": "true", "confidence": 0.95})
        self.assertEqual(decision["next_action"], "skip")
        self.assertFalse(decision["is_food"])
        self.assertEqual(decision["confidence"], 0.0)

    def test_missing_keys_fail_closed_to_skip(self) -> None:
        decision = _coerce_detect_decision({"confidence": 0.99})
        self.assertEqual(decision["next_action"], "skip")
        self.assertFalse(decision["is_food"])
        self.assertEqual(decision["confidence"], 0.0)

    def test_meal_present_with_clutter_continues_to_segment(self) -> None:
        decision = _coerce_detect_decision({"is_food": True, "confidence": 0.91})
        self.assertEqual(decision["is_food"], True)
        self.assertEqual(decision["next_action"], "segment")

    def test_normalize_payload_parses_json_content(self) -> None:
        parsed = _normalize_payload(json.dumps({"is_food": True, "confidence": 0.88}))
        self.assertEqual(parsed, {"is_food": True, "confidence": 0.88})


class DetectServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_detect_food_photo_uses_conservative_threshold(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"is_food": True, "confidence": 0.74}),
                    },
                },
            ],
        }

        result = await detect_food_photo(
            "https://example.test/meal.jpg",
            llm_client=client,
            model="google/gemma-4-31b-it",
            confidence_threshold=0.75,
        )

        self.assertEqual(result["next_action"], "skip")
        self.assertFalse(result["is_food"])

    async def test_detect_food_photo_accepts_clear_food_payload(self) -> None:
        client = AsyncMock()
        client.chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"is_food": True, "confidence": 0.95}),
                    },
                },
            ],
        }

        result = await detect_food_photo(
            "https://example.test/meal.jpg",
            llm_client=client,
            model="google/gemma-4-31b-it",
        )

        self.assertEqual(result["next_action"], "segment")
        self.assertTrue(result["is_food"])
        self.assertGreater(result["confidence"], 0.75)
        client.chat_completion.assert_awaited_once_with(
            model="google/gemma-4-31b-it",
            messages=detect_prompt("https://example.test/meal.jpg"),
            response_format=detect_response_format(),
        )
