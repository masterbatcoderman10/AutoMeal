from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from app.services.vision_service import (
    _coerce_detect_decision,
    _coerce_segment_candidates,
    normalize_segment_box,
    _normalize_payload,
    detect_food_photo,
    detect_prompt,
    detect_response_format,
    label_prompt,
    label_response_format,
    segment_prompt,
    segment_response_format,
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


class SegmentPromptTests(unittest.TestCase):
    def test_segment_prompt_includes_grouping_and_garnish_rules(self) -> None:
        prompt = segment_prompt("https://example.test/meal.jpg")
        prompt_text = prompt[0]["content"][0]["text"].lower()
        self.assertIn("distinct visible food region", prompt_text)
        self.assertIn("clearly separate", prompt_text)
        self.assertIn("tiny garnish", prompt_text)
        self.assertIn("box_2d", prompt_text)

    def test_segment_response_format_is_strict_json_schema(self) -> None:
        schema = segment_response_format()
        self.assertEqual(schema["type"], "json_schema")
        json_schema = schema["json_schema"]["schema"]
        self.assertTrue(json_schema["additionalProperties"] is False)
        self.assertIn("segments", json_schema["required"])


class SegmentBoxTests(unittest.TestCase):
    def test_normalize_segment_box_divides_raw_1000_scale(self) -> None:
        normalized = normalize_segment_box([0, 250, 1000, 500])
        self.assertEqual(normalized, [0.0, 0.25, 1.0, 0.5])

    def test_reversed_coordinate_box_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_segment_box([900, 900, 100, 100])

    def test_out_of_range_segment_box_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_segment_box([900, 900, 1100, 1200])

    def test_tiny_segment_area_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_segment_box([0, 0, 80, 120])


class SegmentCandidateTests(unittest.TestCase):
    def test_coerce_segment_candidates_validates_whole_response(self) -> None:
        payload = {
            "segments": [
                {"box_2d": [100, 100, 500, 500], "label_hint": "bread"},
                {"box_2d": [900, 900, 950, 950]},
            ],
        }
        with self.assertRaises(ValueError):
            _coerce_segment_candidates(payload, max_segments=2)

    def test_segment_candidate_cap_is_applied(self) -> None:
        payload = {
            "segments": [
                {"box_2d": [0, 0, 200, 500]},
                {"box_2d": [200, 0, 400, 500]},
                {"box_2d": [400, 0, 600, 500]},
            ],
        }
        candidates = _coerce_segment_candidates(payload, max_segments=2)
        self.assertEqual(len(candidates), 2)

    def test_segment_label_prompt_includes_d_07_d_08_rules(self) -> None:
        prompt_text = label_prompt("https://example.test/crop.jpg")[0]["content"][0]["text"].lower()
        self.assertIn("dish-level labels", prompt_text)
        self.assertIn("ingredient-level", prompt_text)
        self.assertIn("tiny sauce", prompt_text)

    def test_segment_label_response_format_is_strict(self) -> None:
        schema = label_response_format()
        self.assertEqual(schema["type"], "json_schema")
        json_schema = schema["json_schema"]["schema"]
        self.assertTrue(json_schema["additionalProperties"] is False)
        self.assertIn("label", json_schema["required"])


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
