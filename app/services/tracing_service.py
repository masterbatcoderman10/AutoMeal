from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any

from app.config import get_settings


def _should_capture_images() -> bool:
    settings = get_settings()
    return bool(settings.LANGFUSE_CAPTURE_IMAGES)


def _scrub_payload(value: Any, *, capture_images: bool) -> Any:
    if capture_images:
        return copy.deepcopy(value)
    if isinstance(value, list):
        return [_scrub_payload(item, capture_images=capture_images) for item in value]
    if not isinstance(value, dict):
        return value

    scrubbed: dict[str, Any] = {}
    for key, item in value.items():
        if key == "image_url":
            if isinstance(item, dict) and item.get("url"):
                scrubbed[key] = {"url": "[redacted image reference]"}
                continue
        scrubbed[key] = _scrub_payload(item, capture_images=capture_images)
    return scrubbed


def _create_langfuse_client():
    try:
        from langfuse import Langfuse
    except Exception as exc:
        raise RuntimeError("Langfuse SDK is required for MealTracker LLM calls") from exc

    settings = get_settings()
    kwargs: dict[str, Any] = {
        "public_key": settings.LANGFUSE_PUBLIC_KEY,
        "secret_key": settings.LANGFUSE_SECRET_KEY,
        "base_url": settings.LANGFUSE_BASE_URL,
        "environment": settings.LANGFUSE_TRACING_ENVIRONMENT,
    }
    try:
        return Langfuse(**kwargs)
    except Exception as exc:
        raise RuntimeError("Langfuse client initialization failed") from exc


def validate_langfuse_required() -> None:
    client = _create_langfuse_client()
    try:
        is_valid = client.auth_check()
    except Exception as exc:
        raise RuntimeError("Langfuse auth check failed") from exc
    if not is_valid:
        raise RuntimeError("Langfuse credentials were rejected")
    _call_if_available(client, "flush")


def _call_if_available(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, method_name, None)
    if callable(method):
        try:
            return method(*args, **kwargs)
        except TypeError:
            if args:
                return None
            if len(kwargs) == 1:
                try:
                    return method(next(iter(kwargs.values())))
                except Exception:
                    return None
            return None
        except Exception:
            return None
    return None


@dataclass
class TraceHandle:
    trace: Any
    trace_id: str | None
    span: Any | None = None
    client: Any | None = None
    context_manager: Any | None = None
    ended: bool = False

    def end(self, output: Any | None = None, error: Exception | None = None) -> None:
        if self.ended:
            return
        self.ended = True
        if self.trace is None:
            return

        if error is not None:
            _call_if_available(self.trace, "score", status="error")
            _call_if_available(self.trace, "update", level="ERROR", status_message=str(error))
        elif output is not None:
            _call_if_available(self.trace, "update", output=copy.deepcopy(output))

        if self.span is not None and self.span is not self.trace:
            if error is not None:
                _call_if_available(self.span, "update", status="error")
            _call_if_available(self.span, "end")
            _call_if_available(self.span, "flush")

        _call_if_available(self.trace, "end")
        _call_if_available(self.client, "flush")

    def __enter__(self) -> "TraceHandle":
        if self.context_manager is not None:
            self.trace = self.context_manager.__enter__()
            self.span = self.trace
            if self.client is not None:
                self.trace_id = _call_if_available(self.client, "get_current_trace_id") or self.trace_id
        return self

    def __exit__(self, exc_type: type | None, exc: Exception | None, tb: Any) -> None:
        if exc is not None:
            self.end(error=exc)
        else:
            self.end()
        if self.context_manager is not None:
            self.context_manager.__exit__(exc_type, exc, tb)


def maybe_start_trace(
    *,
    name: str,
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
    span_name: str | None = None,
) -> TraceHandle:
    client = _create_langfuse_client()
    sanitized_input = _scrub_payload(input, capture_images=_should_capture_images())
    context_manager = client.start_as_current_observation(
        name=span_name or name,
        as_type="span",
        input=sanitized_input,
        metadata=metadata,
        end_on_exit=False,
    )
    return TraceHandle(
        trace=None,
        trace_id=None,
        span=None,
        client=client,
        context_manager=context_manager,
    )


__all__ = ["TraceHandle", "maybe_start_trace", "validate_langfuse_required"]
