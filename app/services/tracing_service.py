from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any

from app.config import get_settings


def _is_tracing_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.LANGFUSE_ENABLED
        and settings.LANGFUSE_PUBLIC_KEY
        and settings.LANGFUSE_SECRET_KEY
    )


def _should_capture_images() -> bool:
    settings = get_settings()
    return bool(
        settings.LANGFUSE_CAPTURE_IMAGES
        and settings.LANGFUSE_PUBLIC_KEY
        and settings.LANGFUSE_SECRET_KEY
    )


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
    except Exception:
        return None

    settings = get_settings()
    kwargs: dict[str, Any] = {
        "public_key": settings.LANGFUSE_PUBLIC_KEY,
        "secret_key": settings.LANGFUSE_SECRET_KEY,
    }
    if settings.LANGFUSE_HOST:
        kwargs["host"] = settings.LANGFUSE_HOST
    try:
        return Langfuse(**kwargs)
    except Exception:
        return None


def _create_trace(client, *, name: str, input_payload: Any | None, metadata: dict[str, Any] | None):
    trace_factory = getattr(client, "trace", None)
    if trace_factory is None:
        trace_factory = getattr(client, "create_trace", None)
    if trace_factory is None:
        return None
    kwargs = {}
    if input_payload is not None:
        kwargs["input"] = _scrub_payload(
            input_payload,
            capture_images=_should_capture_images(),
        )
    if metadata is not None:
        kwargs["metadata"] = metadata
    try:
        return trace_factory(name=name, **kwargs)
    except Exception:
        return None


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


def _extract_trace_id(trace: Any) -> str | None:
    return getattr(trace, "id", None) or getattr(trace, "trace_id", None)


@dataclass
class TraceHandle:
    trace: Any
    trace_id: str | None
    span: Any | None = None
    client: Any | None = None

    def end(self, output: Any | None = None, error: Exception | None = None) -> None:
        if self.trace is None:
            return

        if error is not None:
            _call_if_available(self.trace, "score", status="error")
            _call_if_available(self.trace, "update", output=str(error))
        elif output is not None:
            _call_if_available(self.trace, "update", output=copy.deepcopy(output))

        if self.span is not None:
            if error is not None:
                _call_if_available(self.span, "update", status="error")
            _call_if_available(self.span, "end")
            _call_if_available(self.span, "flush")

        _call_if_available(self.trace, "end")
        _call_if_available(self.client, "flush")

    def __enter__(self) -> "TraceHandle":
        return self

    def __exit__(self, exc_type: type | None, exc: Exception | None, tb: Any) -> None:
        if exc is not None:
            self.end(error=exc)
        else:
            self.end()


def maybe_start_trace(
    *,
    name: str,
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
    span_name: str | None = None,
) -> TraceHandle:
    if not _is_tracing_enabled():
        return TraceHandle(trace=None, trace_id=None, span=None, client=None)

    client = _create_langfuse_client()
    if client is None:
        return TraceHandle(trace=None, trace_id=None, span=None, client=None)

    sanitized_input = _scrub_payload(input, capture_images=_should_capture_images())
    trace = _create_trace(
        client,
        name=name,
        input_payload=sanitized_input,
        metadata=metadata,
    )
    if trace is None:
        return TraceHandle(trace=None, trace_id=None, span=None, client=None)

    span = None
    if span_name is not None:
        span_factory = getattr(trace, "span", None) or getattr(trace, "create_span", None)
        if callable(span_factory):
            try:
                span = span_factory(name=span_name)
            except Exception:
                span = None
            _call_if_available(span, "update", input=copy.deepcopy(sanitized_input))

    return TraceHandle(
        trace=trace,
        trace_id=_extract_trace_id(trace),
        span=span,
        client=client,
    )


__all__ = ["TraceHandle", "maybe_start_trace"]
