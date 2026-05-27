from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.services import embedding_service


class EmbeddingServiceContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_image_for_document_requests_valid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_path = Path(tmp_dir) / "sample.jpg"
            sample_path.write_bytes(b"fake image bytes")

            client = AsyncMock()
            client.embed_multimodal.return_value = [0.25] * embedding_service.EMBEDDING_DIMENSION

            embedding = await embedding_service.embed_image_for_document(
                image_path=sample_path,
                llm_client=client,
                model="google/gemini-embedding-2-preview",
            )

            self.assertEqual(len(embedding), embedding_service.EMBEDDING_DIMENSION)
            client.embed_multimodal.assert_awaited_once()
            _, kwargs = client.embed_multimodal.call_args
            self.assertEqual(kwargs["model"], "google/gemini-embedding-2-preview")
            self.assertEqual(kwargs["output_dimensionality"], embedding_service.EMBEDDING_DIMENSION)
            self.assertEqual(kwargs["task_type"], embedding_service.RETRIEVAL_DOCUMENT)
            self.assertEqual(kwargs["content"][1]["type"], "image_url")
            self.assertIn("data:image/jpeg;base64", kwargs["content"][1]["image_url"]["url"])

    async def test_embed_text_for_query_uses_retrieval_query_task_type(self) -> None:
        client = AsyncMock()
        client.embed_multimodal.return_value = [0.1] * embedding_service.EMBEDDING_DIMENSION

        embedding = await embedding_service.embed_text_for_query(
            query_text="rice and lentils",
            llm_client=client,
            model="google/gemini-embedding-2-preview",
        )

        self.assertEqual(len(embedding), embedding_service.EMBEDDING_DIMENSION)
        client.embed_multimodal.assert_awaited_once()
        kwargs = client.embed_multimodal.call_args.kwargs
        self.assertEqual(kwargs["model"], "google/gemini-embedding-2-preview")
        self.assertEqual(kwargs["output_dimensionality"], embedding_service.EMBEDDING_DIMENSION)
        self.assertEqual(kwargs["task_type"], embedding_service.RETRIEVAL_QUERY)
        self.assertEqual(kwargs["content"][0]["type"], "text")
        self.assertEqual(kwargs["content"][0]["text"], "rice and lentils")

    async def test_wrong_length_embedding_is_rejected_before_return(self) -> None:
        client = AsyncMock()
        client.embed_multimodal.return_value = [0.0, 0.1, 0.2]

        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_path = Path(tmp_dir) / "sample.jpg"
            sample_path.write_bytes(b"fake image bytes")

            with self.assertRaises(ValueError):
                await embedding_service.embed_image_for_document(
                    image_path=sample_path,
                    llm_client=client,
                    model="google/gemini-embedding-2-preview",
                )

            client.embed_multimodal.assert_awaited_once()

    def test_same_image_self_similarity_uses_99pct_gate(self) -> None:
        self.assertTrue(embedding_service.passes_same_image_gate([1.0, 0.0, 0.0], 1536 - 1, threshold=0.99))
        self.assertFalse(embedding_service.passes_same_image_gate([1.0, 0.0, 0.0], 0.98, threshold=0.99))

    def test_cross_modal_gate_fails_closed_on_reversed_or_tied_ranking(self) -> None:
        self.assertTrue(
            embedding_service.passes_cross_modal_gate(
                query_to_target=0.82,
                query_to_random=0.55,
                minimum_margin=0.001,
            )
        )
        self.assertFalse(
            embedding_service.passes_cross_modal_gate(
                query_to_target=0.55,
                query_to_random=0.82,
                minimum_margin=0.001,
            )
        )
        self.assertFalse(
            embedding_service.passes_cross_modal_gate(
                query_to_target=0.70,
                query_to_random=0.699,
                minimum_margin=0.01,
            )
        )

    def test_empty_corpus_is_a_valid_calibration_state(self) -> None:
        self.assertTrue(embedding_service.is_corpus_empty_ok(0))
        self.assertFalse(embedding_service.is_corpus_empty_ok(4))


if __name__ == "__main__":
    unittest.main()
