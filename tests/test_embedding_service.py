from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx

from app.services.llm_client import OpenRouterClient
from app.services import embedding_service


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeHTTPClient:
    def __init__(self, response: _FakeHTTPResponse) -> None:
        self.post = AsyncMock(return_value=response)

    async def aclose(self) -> None:
        return None


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

    def test_prepare_image_content_preserves_remote_url_inputs(self) -> None:
        content = embedding_service._prepare_image_content("https://example.com/crop.jpg")
        self.assertEqual(content[1]["image_url"]["url"], "https://example.com/crop.jpg")

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

    async def test_embed_with_retry_retries_transport_failures(self) -> None:
        client = AsyncMock()
        client.embed_multimodal.side_effect = [
            httpx.HTTPError("retryable transport error"),
            [0.42] * embedding_service.EMBEDDING_DIMENSION,
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_path = Path(tmp_dir) / "sample.jpg"
            sample_path.write_bytes(b"fake image bytes")

            embedding = await embedding_service.embed_image_for_document(
                image_path=sample_path,
                llm_client=client,
                model="google/gemini-embedding-2-preview",
            )

            self.assertEqual(len(embedding), embedding_service.EMBEDDING_DIMENSION)
            self.assertEqual(client.embed_multimodal.await_count, 2)

    async def test_embed_with_retry_fails_closed_on_validation_error(self) -> None:
        client = AsyncMock()
        client.embed_multimodal.side_effect = [ValueError("malformed response")]

        with tempfile.TemporaryDirectory() as tmp_dir:
            sample_path = Path(tmp_dir) / "sample.jpg"
            sample_path.write_bytes(b"fake image bytes")

            with self.assertRaises(ValueError):
                await embedding_service.embed_image_for_document(
                    image_path=sample_path,
                    llm_client=client,
                    model="google/gemini-embedding-2-preview",
                )

            self.assertEqual(client.embed_multimodal.await_count, 1)

    def test_same_image_self_similarity_uses_99pct_gate(self) -> None:
        self.assertTrue(embedding_service.passes_same_image_gate(similarity=0.995, threshold=0.99))
        self.assertFalse(embedding_service.passes_same_image_gate(similarity=0.98, threshold=0.99))

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


class OpenRouterClientContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_multimodal_rejects_wrong_length_vector(self) -> None:
        response = _FakeHTTPResponse(
            {
                "data": [
                    {
                        "embedding": [0.1, 0.2, 0.3],
                    },
                ],
            }
        )
        client = OpenRouterClient(api_key="test-key", base_url="https://openrouter.ai/api/v1")
        client._http = _FakeHTTPClient(response)  # type: ignore[assignment]

        with self.assertRaises(ValueError):
            await client.embed_multimodal(
                model="google/gemini-embedding-2-preview",
                content=[{"type": "text", "text": "hello"}],
                output_dimensionality=embedding_service.EMBEDDING_DIMENSION,
            )

        client._http.post.assert_awaited_once_with(  # type: ignore[attr-defined]
            "/embeddings",
            json={
                "model": "google/gemini-embedding-2-preview",
                "input": [{"content": [{"type": "text", "text": "hello"}]}],
                "dimensions": embedding_service.EMBEDDING_DIMENSION,
                "encoding_format": "float",
                "input_type": "search_document",
            },
        )

    async def test_embed_multimodal_rejects_missing_data_payload(self) -> None:
        response = _FakeHTTPResponse({})
        client = OpenRouterClient(api_key="test-key", base_url="https://openrouter.ai/api/v1")
        client._http = _FakeHTTPClient(response)  # type: ignore[assignment]

        with self.assertRaises(ValueError):
            await client.embed_multimodal(
                model="google/gemini-embedding-2-preview",
                content=[{"type": "text", "text": "hello"}],
            )

    async def test_embed_multimodal_maps_retrieval_query_to_openrouter_input_type(self) -> None:
        response = _FakeHTTPResponse(
            {
                "data": [
                    {
                        "embedding": [0.1] * embedding_service.EMBEDDING_DIMENSION,
                    },
                ],
            }
        )
        client = OpenRouterClient(api_key="test-key", base_url="https://openrouter.ai/api/v1")
        client._http = _FakeHTTPClient(response)  # type: ignore[assignment]

        embedding = await client.embed_multimodal(
            model="google/gemini-embedding-2-preview",
            content=[{"type": "text", "text": "rice and lentils"}],
            output_dimensionality=embedding_service.EMBEDDING_DIMENSION,
            task_type=embedding_service.RETRIEVAL_QUERY,
        )

        self.assertEqual(len(embedding), embedding_service.EMBEDDING_DIMENSION)
        client._http.post.assert_awaited_once_with(  # type: ignore[attr-defined]
            "/embeddings",
            json={
                "model": "google/gemini-embedding-2-preview",
                "input": [{"content": [{"type": "text", "text": "rice and lentils"}]}],
                "dimensions": embedding_service.EMBEDDING_DIMENSION,
                "encoding_format": "float",
                "input_type": "search_query",
            },
        )


if __name__ == "__main__":
    unittest.main()
