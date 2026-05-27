from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.services.vision_service import (
    _coerce_detect_decision,
    _coerce_segment_candidates,
    dedupe_overlapping_segments,
    normalize_segment_box,
    _normalize_payload,
    detect_food_photo,
    detect_prompt,
    detect_response_format,
    label_prompt,
    label_response_format,
    segment_food_photo_with_retry,
    SegmentDecision,
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

    def test_detect_prompt_converts_local_file_path_to_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "meal.jpg"
            image_path.write_bytes(b"jpeg-bytes")

            prompt = detect_prompt(str(image_path))

        image_url = prompt[0]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))

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

    def test_label_prompt_converts_local_file_path_to_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "crop.jpg"
            image_path.write_bytes(b"jpeg-bytes")

            prompt = label_prompt(str(image_path))

        image_url = prompt[0]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))

    def test_dedupe_overlapping_segments_keeps_higher_confidence_region(self) -> None:
        segments = [
            SegmentDecision(box_2d=[0.0, 0.0, 0.6, 0.6], label_hint="rice", confidence=0.40),
            SegmentDecision(box_2d=[0.05, 0.05, 0.65, 0.65], label_hint="rice", confidence=0.90),
            SegmentDecision(box_2d=[0.7, 0.7, 0.9, 0.9], label_hint="salad", confidence=0.50),
        ]

        deduped = dedupe_overlapping_segments(segments, threshold=0.5)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].confidence, 0.90)
        self.assertEqual(deduped[1].label_hint, "salad")


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

    async def test_label_food_segment_fails_closed_on_malformed_payload(self) -> None:
        from app.services.vision_service import label_food_segment

        client = AsyncMock()
        client.chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"name": "not-a-label"}),
                    },
                },
            ],
        }

        result = await label_food_segment(
            "https://example.test/crop.jpg",
            llm_client=client,
            model="google/gemini-3-flash-preview",
        )

        self.assertIsNone(result)

    async def test_segment_food_photo_retries_once_with_retry_model_after_invalid_primary_response(self) -> None:
        client = AsyncMock()
        client.chat_completion.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "segments": [
                                        {"box_2d": [100, 100, 600, 600], "confidence": 0.6},
                                        {"box_2d": [900, 900, 950, 950], "confidence": 0.9},
                                    ]
                                }
                            ),
                        },
                    },
                ],
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "segments": [
                                        {"box_2d": [100, 100, 600, 600], "confidence": 0.8},
                                    ]
                                }
                            ),
                        },
                    },
                ],
            },
        ]

        result = await segment_food_photo_with_retry(
            "https://example.test/meal.jpg",
            llm_client=client,
            model="google/gemini-3-flash-preview",
            retry_model="google/gemini-3.5-flash",
            max_segments=8,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].box_2d, [0.1, 0.1, 0.6, 0.6])
        self.assertEqual(client.chat_completion.await_args_list[0].kwargs["model"], "google/gemini-3-flash-preview")
        self.assertEqual(client.chat_completion.await_args_list[1].kwargs["model"], "google/gemini-3.5-flash")
