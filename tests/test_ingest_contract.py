import unittest
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ingest as ingest_router

ingest_module = import_module("app.routers.ingest")


async def fake_session():
    yield object()


class IngestAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(ingest_router)
        app.dependency_overrides[ingest_module.get_session] = fake_session
        self.client = TestClient(app)

    def test_missing_ingest_secret_returns_401(self) -> None:
        with patch.object(
            ingest_module,
            "get_settings",
            return_value=SimpleNamespace(INGEST_SECRET="expected-secret"),
        ):
            response = self.client.post(
                "/ingest/photo",
                files={"picture": ("meal.jpg", b"not-used", "image/jpeg")},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})

    def test_wrong_ingest_secret_returns_401(self) -> None:
        with patch.object(
            ingest_module,
            "get_settings",
            return_value=SimpleNamespace(INGEST_SECRET="expected-secret"),
        ):
            response = self.client.post(
                "/ingest/photo",
                headers={"X-Ingest-Secret": "wrong-secret"},
                files={"picture": ("meal.jpg", b"not-used", "image/jpeg")},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})
