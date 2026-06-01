from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

import httpx

from sqlalchemy import select, update
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.models import FoodItem, FoodVisual, MealLog, MealSegment, MealProcessingStatus  # noqa: E402
from app.services import embedding_service, interview_service, matching_service, reasoning_service  # noqa: E402
from app.services.image_service import HEIC_CONTENT_TYPES, compute_hash, save_segment_crop, transcode_to_jpeg  # noqa: E402
from app.services.llm_client import get_llm_client  # noqa: E402
from app.services.vision_service import (  # noqa: E402
    dedupe_overlapping_segments,
    detect_food_photo,
    segment_food_photo_with_retry,
    segment_debug_label,
)

EMBEDDING_MODEL = "google/gemini-embedding-2-preview"
EMBEDDING_TASK_MARGIN = 0.001
SMOKE_ID_MAX_LENGTH = 36
ALLOWED_CROP_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_UAT_TARGET_DATABASE = "mealttracker_043_harness"
DEFAULT_UAT_CHECKPOINT_DATABASE = "mealttracker_uat_with_meal_embeddings"
DEFAULT_UAT_API_BASE_URL = "http://127.0.0.1:18043"
DEFAULT_UAT_REPORT_DIR = PROJECT_ROOT / "uploads" / "reports" / "04.3"
DEFAULT_UAT_POSTGRES_CONTAINER = "mealttracker-postgres"
DEFAULT_UAT_POSTGRES_USER = "mealttracker"
DEFAULT_UAT_POLL_TIMEOUT_SECONDS = 180
DEFAULT_UAT_POLL_INTERVAL_SECONDS = 5.0
SENSITIVE_REPORT_KEYS = {
    "authorization",
    "x-ingest-secret",
    "ingest_secret",
    "openrouter_api_key",
    "langfuse_secret_key",
    "langfuse_public_key",
    "telegram_bot_token",
}
UAT_HARNESS_SCENARIOS = {
    "partial-match": {
        "sample_relative_path": "sample_images/IMG_4583.HEIC",
        "goal": "partial-match repeated-meal replay from the warm checkpoint",
    },
    "no-match": {
        "sample_relative_path": "sample_images/IMG_4641.HEIC",
        "goal": "no-match clarification replay from the warm checkpoint",
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wave 0 embedding contract smoke helper.")
    parser.add_argument(
        "--mode",
        choices=[
            "calibrate",
            "seed-demo",
            "unresolved-probe",
            "repeat-confirmation",
            "reasoning-probe",
            "grouped-uat",
            "uat-harness",
        ],
        required=True,
    )
    parser.add_argument(
        "--sample",
        help="Saved crop artifact for the smoke run (for example uploads/crops/seg-1.jpg)",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(UAT_HARNESS_SCENARIOS),
        default=None,
        help="Named 04.3 UAT harness scenario",
    )
    parser.add_argument(
        "--same-food-peer",
        default=None,
        help="Required for calibrate: a different saved crop artifact from a second photo of the same food",
    )
    parser.add_argument(
        "--random-food",
        default=None,
        help="Optional saved crop artifact for cross-modal sanity comparison",
    )
    parser.add_argument(
        "--second-sample",
        default=None,
        help="Optional second saved crop artifact for seeding a distinct demo FoodItem",
    )
    parser.add_argument(
        "--cross-modal-text",
        default="rice and lentils",
        help="Text query for cross-modal validation",
    )
    parser.add_argument(
        "--visual-corpus-size",
        type=int,
        default=0,
        help="How many existing FoodVisual rows are visible for calibration context",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL override for seed-demo and unresolved-probe modes",
    )
    parser.add_argument(
        "--target-database",
        default=DEFAULT_UAT_TARGET_DATABASE,
        help="Disposable Postgres database the 04.3 harness may reset/clone",
    )
    parser.add_argument(
        "--checkpoint-database",
        default=DEFAULT_UAT_CHECKPOINT_DATABASE,
        help="Warm checkpoint database used as the clone source for the 04.3 harness",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_UAT_API_BASE_URL,
        help="API base URL used by the 04.3 harness ingest replay",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_UAT_REPORT_DIR),
        help="Directory where 04.3 harness JSON reports are written",
    )
    parser.add_argument(
        "--postgres-container",
        default=DEFAULT_UAT_POSTGRES_CONTAINER,
        help="Postgres container name used for checkpoint clone and evidence queries",
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=int,
        default=DEFAULT_UAT_POLL_TIMEOUT_SECONDS,
        help="How long the live 04.3 harness waits for interview/completed state",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_UAT_POLL_INTERVAL_SECONDS,
        help="Polling interval for the live 04.3 harness",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit the 04.3 harness report and planned activation steps without touching Docker or the API",
    )
    args = parser.parse_args()
    if args.mode == "uat-harness":
        if not args.scenario:
            parser.error("--scenario is required when --mode uat-harness is selected")
    elif not args.sample:
        parser.error("--sample is required unless --mode uat-harness is selected")
    return args


def _load_raw_bytes(path: Path) -> bytes:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"sample image missing: {path}")
    return path.read_bytes()


def _resolve_crop_path(path_value: str | Path, *, flag_name: str) -> Path:
    crop_path = Path(path_value).expanduser().resolve()
    if not crop_path.exists() or not crop_path.is_file():
        raise FileNotFoundError(f"{flag_name} crop artifact missing: {crop_path}")

    if "crops" not in {part.lower() for part in crop_path.parts}:
        raise RuntimeError(
            f"{flag_name} must point to a saved crop artifact under a 'crops' directory; "
            f"whole-photo inputs like sample_images are not allowed: {crop_path}"
        )

    if crop_path.suffix.lower() not in ALLOWED_CROP_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_CROP_SUFFIXES))
        raise RuntimeError(
            f"{flag_name} must point to a durable crop image ({allowed}), got: {crop_path}"
        )

    return crop_path


def _ensure_distinct_rephoto_pair(sample_path: Path, peer_path: Path) -> None:
    if sample_path == peer_path:
        raise RuntimeError(
            "calibrate requires --same-food-peer to be a different crop artifact from --sample"
        )
    if _load_raw_bytes(sample_path) == _load_raw_bytes(peer_path):
        raise RuntimeError(
            "calibrate requires --same-food-peer to be a real re-photo crop, not a byte-identical copy"
        )


def _make_smoke_id(prefix: str, *, suffix_length: int = 12) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
    suffix = uuid.uuid4().hex[:suffix_length]
    prefix_budget = SMOKE_ID_MAX_LENGTH - suffix_length - 1
    if prefix_budget <= 0:
        raise RuntimeError("suffix length leaves no room for smoke ID prefix")
    trimmed = normalized[:prefix_budget].rstrip("-") or "smoke"
    return f"{trimmed}-{suffix}"


def _resolve_image_path(path_value: str | Path, *, flag_name: str) -> Path:
    image_path = Path(path_value).expanduser().resolve()
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"{flag_name} image missing: {image_path}")
    return image_path


def _resolve_uat_harness_scenario(name: str) -> dict[str, str]:
    scenario = UAT_HARNESS_SCENARIOS.get(name)
    if scenario is None:
        raise RuntimeError(f"unknown 04.3 harness scenario: {name}")
    return {
        "scenario": name,
        "sample": str((PROJECT_ROOT / scenario["sample_relative_path"]).resolve()),
        "goal": scenario["goal"],
    }


def _assert_safe_uat_target_database(
    target_database: str,
    *,
    checkpoint_database: str,
) -> str:
    normalized = str(target_database or "").strip()
    if not normalized:
        raise RuntimeError("target database is required for the 04.3 UAT harness")
    if normalized == "mealttracker":
        raise RuntimeError(
            "refusing to clone into the default 'mealttracker' database; select an explicit disposable target"
        )
    if normalized == checkpoint_database:
        raise RuntimeError(
            "refusing to clone over the warm checkpoint database; choose a separate disposable target"
        )
    if not normalized.startswith("mealttracker_"):
        raise RuntimeError(
            "refusing to clone into a database outside the disposable mealttracker_* namespace"
        )
    return normalized


def _sanitize_report_value(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for key, nested in value.items():
            if str(key).lower() in SENSITIVE_REPORT_KEYS:
                sanitized[str(key)] = "[redacted]"
                continue
            sanitized[str(key)] = _sanitize_report_value(nested)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_report_value(item) for item in value]
    return value


def _extract_trace_ids(*values: object) -> list[str]:
    found: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key).lower().replace("-", "_") == "trace_id":
                    text = str(nested or "").strip()
                    if text:
                        found.add(text)
                visit(nested)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                visit(item)

    for candidate in values:
        visit(candidate)
    return sorted(found)


def _current_prompt_from_interview_payload(interview: Mapping[str, Any] | None) -> str | None:
    if not isinstance(interview, Mapping):
        return None
    payload = interview.get("current_prompt_payload")
    if isinstance(payload, Mapping):
        current_question = payload.get("current_question")
        if isinstance(current_question, Mapping):
            prompt = current_question.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
    messages = interview.get("messages")
    if isinstance(messages, Sequence):
        for message in reversed(list(messages)):
            if not isinstance(message, Mapping):
                continue
            payload = message.get("payload")
            if not isinstance(payload, Mapping):
                continue
            prompt = payload.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
            if isinstance(prompt, Mapping):
                text = prompt.get("prompt")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return None


def _classify_uat_harness_outcome(
    meal: Mapping[str, Any] | None,
    interview: Mapping[str, Any] | None,
) -> str | None:
    meal_status = str((meal or {}).get("processing_status") or "").strip().upper()
    interview_payload = dict((interview or {}).get("current_prompt_payload") or {})
    interview_state = str((interview or {}).get("state_key") or "").strip().upper()
    roadmap_step = str(interview_payload.get("roadmap_step") or "").strip().upper()
    grounding_status = str(interview_payload.get("grounding_status") or "").strip().upper()

    if meal_status == MealProcessingStatus.COMPLETED.value:
        return "completed"
    if grounding_status == "RETRY_PENDING":
        return "retry-pending"
    if interview_state == "GROUNDING_PENDING" or roadmap_step == "GROUNDING_PENDING":
        return "grounding-pending"
    if meal_status == MealProcessingStatus.INTERVIEWING.value:
        return "interview"
    return None


def _summarize_uat_reasoning(reasoning_state: Mapping[str, Any] | None) -> str:
    if not isinstance(reasoning_state, Mapping):
        return "No reasoning state recorded."
    meal_reasoning = reasoning_state.get("meal_reasoning")
    if isinstance(meal_reasoning, Mapping):
        source = meal_reasoning
    else:
        source = reasoning_state
    trace_id = str(source.get("trace_id") or "").strip()
    rationale = str(source.get("decision_rationale") or "").strip() or "No reasoning rationale recorded."
    if trace_id:
        return f"trace_id={trace_id}; {rationale}"
    return rationale


def _report_filename(*, scenario_name: str, meal_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return f"{scenario_name}-dry-run.json"
    suffix = meal_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{scenario_name}-{suffix}.json"


def _report_path_for_run(
    report_dir: str | Path,
    *,
    scenario_name: str,
    meal_id: str | None,
    dry_run: bool,
) -> Path:
    directory = Path(report_dir).expanduser()
    if not directory.is_absolute():
        directory = (PROJECT_ROOT / directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _report_filename(scenario_name=scenario_name, meal_id=meal_id, dry_run=dry_run)


def _write_report_json(report_path: Path, report: Mapping[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _build_uat_harness_report(
    *,
    scenario: Mapping[str, Any],
    target_database: str,
    checkpoint_database: str,
    api_base_url: str,
    report_path: Path,
    dry_run: bool,
    meal: Mapping[str, Any] | None,
    interview: Mapping[str, Any] | None,
    diary_entries: Sequence[Mapping[str, Any]],
    food_visuals: Sequence[Mapping[str, Any]],
    activation: Mapping[str, Any] | None = None,
    ingest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    meal_data = dict(meal or {})
    interview_data = dict(interview or {})
    reasoning_state = dict(meal_data.get("reasoning_state_json") or {})
    prompt_payload = dict(interview_data.get("current_prompt_payload") or {})
    trace_ids = _extract_trace_ids(
        reasoning_state,
        prompt_payload,
        interview_data.get("messages"),
        diary_entries,
        food_visuals,
    )
    return {
        "mode": "uat-harness",
        "status": "dry-run" if dry_run else "pass",
        "scenario": {
            "name": scenario.get("scenario"),
            "sample": scenario.get("sample"),
            "goal": scenario.get("goal"),
        },
        "database": {
            "target": target_database,
            "checkpoint": checkpoint_database,
            "protected_default": "mealttracker",
        },
        "api": {"base_url": api_base_url.rstrip("/")},
        "report_path": str(report_path),
        "meal": {
            "id": meal_data.get("meal_id") or meal_data.get("id"),
            "status": meal_data.get("processing_status"),
            "created_at": meal_data.get("created_at"),
            "reasoning_state_json": _sanitize_report_value(reasoning_state),
        },
        "reasoning": {
            "summary": _summarize_uat_reasoning(reasoning_state),
            "clarification_schema": _sanitize_report_value(reasoning_state.get("clarification_schema")),
            "answers_by_question_id": _sanitize_report_value(reasoning_state.get("answers_by_question_id")),
            "resolver_payload": _sanitize_report_value(reasoning_state.get("resolver_payload")),
        },
        "interview": {
            "session_id": interview_data.get("session_id") or interview_data.get("id"),
            "state_key": interview_data.get("state_key"),
            "current_prompt": _current_prompt_from_interview_payload(interview_data),
            "current_prompt_payload": _sanitize_report_value(prompt_payload),
            "messages": _sanitize_report_value(interview_data.get("messages") or []),
        },
        "diary_entries": _sanitize_report_value(list(diary_entries)),
        "food_visuals": _sanitize_report_value(list(food_visuals)),
        "grounding": {
            "roadmap_step": prompt_payload.get("roadmap_step") or interview_data.get("state_key"),
            "status": prompt_payload.get("grounding_status"),
            "handoff_pending": prompt_payload.get("grounding_handoff_pending"),
        },
        "traces": {"ids": trace_ids},
        "activation": _sanitize_report_value(dict(activation or {})),
        "ingest": _sanitize_report_value(dict(ingest or {})),
    }


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_subprocess(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"command failed ({' '.join(command)}): {stderr}")
    return completed.stdout.strip()


def _run_psql_json(*, database: str, sql: str, postgres_container: str) -> object:
    raw = _run_subprocess(
        [
            "docker",
            "exec",
            postgres_container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            DEFAULT_UAT_POSTGRES_USER,
            "-d",
            database,
            "-Atc",
            sql,
        ]
    )
    if not raw:
        return None
    return json.loads(raw)


def _clone_checkpoint_database(
    *,
    target_database: str,
    checkpoint_database: str,
    postgres_container: str,
) -> None:
    _run_subprocess(
        [
            "docker",
            "exec",
            postgres_container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            DEFAULT_UAT_POSTGRES_USER,
            "-d",
            "postgres",
            "-c",
            f"DROP DATABASE IF EXISTS {target_database} WITH (FORCE);",
        ]
    )
    _run_subprocess(
        [
            "docker",
            "exec",
            postgres_container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            DEFAULT_UAT_POSTGRES_USER,
            "-d",
            "postgres",
            "-c",
            f"CREATE DATABASE {target_database} TEMPLATE {checkpoint_database};",
        ]
    )


def _snapshot_uat_harness_state(
    *,
    meal_id: str,
    database: str,
    postgres_container: str,
) -> dict[str, Any]:
    meal = _run_psql_json(
        database=database,
        postgres_container=postgres_container,
        sql=(
            "SELECT COALESCE(row_to_json(t), 'null'::json)::text "
            "FROM ("
            "SELECT id AS meal_id, processing_status, reasoning_state_json, created_at "
            f"FROM meal_logs WHERE id = {_sql_literal(meal_id)} "
            "LIMIT 1"
            ") t;"
        ),
    )
    if not isinstance(meal, Mapping):
        return {"meal": None, "interview": None, "diary_entries": [], "food_visuals": [], "outcome": None}

    interview = _run_psql_json(
        database=database,
        postgres_container=postgres_container,
        sql=(
            "SELECT COALESCE(row_to_json(t), 'null'::json)::text "
            "FROM ("
            "SELECT id AS session_id, state_key, is_active, current_prompt_payload, last_bot_message_id, updated_at "
            f"FROM interview_sessions WHERE meal_log_id = {_sql_literal(meal_id)} "
            "ORDER BY updated_at DESC LIMIT 1"
            ") t;"
        ),
    )
    if isinstance(interview, Mapping) and interview.get("session_id"):
        messages = _run_psql_json(
            database=database,
            postgres_container=postgres_container,
            sql=(
                "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text "
                "FROM ("
                "SELECT role, payload, message_id, created_at "
                f"FROM interview_messages WHERE session_id = {_sql_literal(str(interview['session_id']))} "
                "ORDER BY created_at ASC"
                ") t;"
            ),
        )
        interview = dict(interview)
        interview["messages"] = list(messages or [])

    diary_entries = _run_psql_json(
        database=database,
        postgres_container=postgres_container,
        sql=(
            "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text "
            "FROM ("
            "SELECT id, food_item_id, segment_id, is_verified, quantity_display, created_at "
            f"FROM diary_entries WHERE meal_log_id = {_sql_literal(meal_id)} "
            "ORDER BY created_at ASC"
            ") t;"
        ),
    ) or []
    food_visuals = _run_psql_json(
        database=database,
        postgres_container=postgres_container,
        sql=(
            "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text "
            "FROM ("
            "SELECT fv.id, fv.food_item_id, fv.cropped_image_url, fv.is_invalidated, fv.created_at "
            "FROM food_visuals fv "
            "WHERE fv.food_item_id IN ("
            f"SELECT DISTINCT food_item_id FROM diary_entries WHERE meal_log_id = {_sql_literal(meal_id)}"
            ") "
            "ORDER BY fv.created_at DESC "
            "LIMIT 20"
            ") t;"
        ),
    ) or []

    return {
        "meal": dict(meal),
        "interview": dict(interview) if isinstance(interview, Mapping) else None,
        "diary_entries": [dict(item) for item in diary_entries if isinstance(item, Mapping)],
        "food_visuals": [dict(item) for item in food_visuals if isinstance(item, Mapping)],
        "outcome": _classify_uat_harness_outcome(
            dict(meal),
            dict(interview) if isinstance(interview, Mapping) else None,
        ),
    }


async def _post_uat_sample(
    *,
    sample_path: Path,
    api_base_url: str,
    ingest_secret: str,
) -> dict[str, Any]:
    content_type = mimetypes.guess_type(sample_path.name)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=60.0) as client:
        with sample_path.open("rb") as handle:
            response = await client.post(
                f"{api_base_url.rstrip('/')}/ingest/photo",
                headers={"X-Ingest-Secret": ingest_secret},
                files={"picture": (sample_path.name, handle, content_type)},
            )
        response.raise_for_status()
        payload = response.json()
    return {
        "http_status": response.status_code,
        "meal_log_id": payload.get("meal_log_id"),
        "deduplicated": payload.get("deduplicated"),
        "sample": str(sample_path),
    }


async def _run_uat_harness(args: argparse.Namespace) -> dict[str, Any]:
    scenario = _resolve_uat_harness_scenario(str(args.scenario))
    target_database = _assert_safe_uat_target_database(
        args.target_database,
        checkpoint_database=str(args.checkpoint_database),
    )
    report_path = _report_path_for_run(
        args.report_dir,
        scenario_name=str(scenario["scenario"]),
        meal_id=None,
        dry_run=bool(args.dry_run),
    )
    activation = {
        "clone_source": str(args.checkpoint_database),
        "target_database": target_database,
        "postgres_container": str(args.postgres_container),
        "compose_override": "docker-compose.uat-043-harness.yml",
        "api_base_url": str(args.api_base_url).rstrip("/"),
        "commands": [
            f"docker exec {args.postgres_container} psql -U {DEFAULT_UAT_POSTGRES_USER} -d postgres -c \"DROP DATABASE IF EXISTS {target_database} WITH (FORCE);\"",
            f"docker exec {args.postgres_container} psql -U {DEFAULT_UAT_POSTGRES_USER} -d postgres -c \"CREATE DATABASE {target_database} TEMPLATE {args.checkpoint_database};\"",
        ],
    }
    if args.dry_run:
        report = _build_uat_harness_report(
            scenario=scenario,
            target_database=target_database,
            checkpoint_database=str(args.checkpoint_database),
            api_base_url=str(args.api_base_url),
            report_path=report_path,
            dry_run=True,
            meal={"processing_status": "DRY_RUN", "reasoning_state_json": {}},
            interview={"state_key": "DRY_RUN", "current_prompt_payload": {}, "messages": []},
            diary_entries=[],
            food_visuals=[],
            activation=activation,
            ingest={"planned_sample": scenario["sample"]},
        )
        _write_report_json(report_path, report)
        return report

    sample_path = _resolve_image_path(scenario["sample"], flag_name=f"--scenario {args.scenario}")
    ingest_secret = str(os.environ.get("INGEST_SECRET") or "").strip()
    if not ingest_secret:
        raise RuntimeError("INGEST_SECRET is required for live uat-harness runs")

    _clone_checkpoint_database(
        target_database=target_database,
        checkpoint_database=str(args.checkpoint_database),
        postgres_container=str(args.postgres_container),
    )
    ingest = await _post_uat_sample(
        sample_path=sample_path,
        api_base_url=str(args.api_base_url),
        ingest_secret=ingest_secret,
    )
    meal_id = str(ingest.get("meal_log_id") or "").strip()
    if not meal_id:
        raise RuntimeError(f"ingest response missing meal_log_id: {ingest}")

    deadline = asyncio.get_running_loop().time() + max(5, int(args.poll_timeout_seconds))
    snapshot = {
        "meal": None,
        "interview": None,
        "diary_entries": [],
        "food_visuals": [],
        "outcome": None,
    }
    while asyncio.get_running_loop().time() < deadline:
        snapshot = _snapshot_uat_harness_state(
            meal_id=meal_id,
            database=target_database,
            postgres_container=str(args.postgres_container),
        )
        if snapshot["outcome"] is not None:
            break
        await asyncio.sleep(max(1.0, float(args.poll_interval_seconds)))

    if snapshot["meal"] is None:
        raise RuntimeError(
            f"meal {meal_id} never appeared in target database {target_database}; verify api/bot are using docker-compose.uat-043-harness.yml"
        )

    final_report_path = _report_path_for_run(
        args.report_dir,
        scenario_name=str(scenario["scenario"]),
        meal_id=meal_id,
        dry_run=False,
    )
    report = _build_uat_harness_report(
        scenario=scenario,
        target_database=target_database,
        checkpoint_database=str(args.checkpoint_database),
        api_base_url=str(args.api_base_url),
        report_path=final_report_path,
        dry_run=False,
        meal=snapshot["meal"],
        interview=snapshot["interview"],
        diary_entries=snapshot["diary_entries"],
        food_visuals=snapshot["food_visuals"],
        activation=activation,
        ingest=ingest,
    )
    report["status"] = snapshot["outcome"] or "timed-out"
    _write_report_json(final_report_path, report)
    return report


async def _run_reasoning_probe(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    sample_input = _resolve_image_path(args.sample, flag_name="--sample")
    settings = get_settings()
    database_url = _resolve_database_url(args)
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    meal = MealLog(
        id=_make_smoke_id("reasoning-meal"),
        image_url=str(sample_input),
        image_hash="reasoning-probe",
        processing_status=MealProcessingStatus.REASONING,
    )
    segment = MealSegment(
        id=_make_smoke_id("reasoning-segment"),
        meal_log_id=meal.id,
        label="reasoning probe sample",
        bounding_box=[0, 0, 1000, 1000],
        cropped_image_url=str(sample_input),
    )

    try:
        async with session_factory() as session:
            match_result = await matching_service.match_segment_against_visual_corpus(
                segment=segment,
                session=session,
                llm_client=llm_client,
                embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
            )
            matching_service.persist_match_candidate_snapshot(
                segment=segment,
                result=match_result,
            )
            reasoning_result, trace_metadata = await reasoning_service.run_reasoning_request(
                llm_client=llm_client,
                meal_id=meal.id,
                meal=meal,
                match_results=[(segment, match_result)],
                settings=settings,
            )
    finally:
        await engine.dispose()

    trace_metadata = trace_metadata or {}
    return {
        "mode": "reasoning-probe",
        "status": "pass",
        "sample": str(sample_input),
        "model": getattr(settings, "REASONING_MODEL", None),
        "meal_id": meal.id,
        "segment_id": segment.id,
        "action": reasoning_result.get("action"),
        "meal_state": reasoning_result.get("meal_state"),
        "gate_auto_confirmed": reasoning_result.get("meal_state") == "READY_TO_WRITE",
        "gate_reason": reasoning_result.get("gate_reason"),
        "decision_rationale": reasoning_result.get("decision_rationale"),
        "trace_id": reasoning_result.get("trace_id") or trace_metadata.get("trace_id"),
        "cached_tokens": trace_metadata.get("cached_tokens"),
        "match": {
            "is_match": match_result.is_match,
            "is_below_threshold": match_result.is_below_threshold,
            "similarity": match_result.similarity,
            "candidate_count": len(match_result.top_candidates),
            "snapshot": segment.match_candidates_json,
        },
        "top_3": reasoning_result.get("top_3", []),
    }


def _prepare_sample_working_copy(sample_path: Path, work_dir: Path) -> Path:
    mime_type, _ = mimetypes.guess_type(sample_path.name)
    raw_bytes = sample_path.read_bytes()
    if mime_type in HEIC_CONTENT_TYPES:
        working_path = work_dir / f"{sample_path.stem}.jpg"
        working_path.write_bytes(transcode_to_jpeg(raw_bytes, mime_type or "image/heic"))
        return working_path

    working_path = work_dir / sample_path.name
    working_path.write_bytes(raw_bytes)
    return working_path


def _food_groups_from_reasoning_state(reasoning_state: object) -> list[dict[str, Any]]:
    if not isinstance(reasoning_state, dict):
        return []
    direct_groups = reasoning_state.get("food_groups")
    if isinstance(direct_groups, list):
        return [dict(group) for group in direct_groups if isinstance(group, dict)]
    meal_reasoning = reasoning_state.get("meal_reasoning")
    if isinstance(meal_reasoning, dict):
        nested_groups = meal_reasoning.get("food_groups")
        if isinstance(nested_groups, list):
            return [dict(group) for group in nested_groups if isinstance(group, dict)]
    return []


async def _run_grouped_uat(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    sample_input = _resolve_image_path(args.sample, flag_name="--sample")
    settings = get_settings()
    engine = create_async_engine(_resolve_database_url(args), echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    try:
        with TemporaryDirectory(prefix="grouped-uat-") as tempdir:
            work_dir = Path(tempdir)
            uploads_dir = work_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            working_image = _prepare_sample_working_copy(sample_input, work_dir)

            detect_result = await detect_food_photo(
                str(working_image),
                llm_client=llm_client,
                model=settings.DETECT_MODEL,
            )
            if detect_result.get("next_action") != "segment":
                raise RuntimeError(
                    f"grouped UAT sample was not routed to segmentation: {detect_result}"
                )

            raw_segments = await segment_food_photo_with_retry(
                str(working_image),
                llm_client=llm_client,
                model=settings.SEGMENT_MODEL,
                retry_model=settings.SEGMENT_RETRY_MODEL,
                max_segments=settings.VISION_MAX_SEGMENTS,
            )
            segments = dedupe_overlapping_segments(raw_segments)
            if not segments:
                raise RuntimeError("grouped UAT produced no food segments")

            async with session_factory() as session:
                meal = MealLog(
                    id=_make_smoke_id("grouped-uat-meal"),
                    image_url=str(working_image),
                    image_hash=compute_hash(sample_input.read_bytes()),
                    processing_status=MealProcessingStatus.REASONING,
                )
                session.add(meal)
                await session.flush()

                segment_rows: list[MealSegment] = []
                for decision in segments:
                    segment_id = _make_smoke_id("grouped-segment")
                    crop_path = save_segment_crop(
                        source_image_path=working_image,
                        segment_id=segment_id,
                        normalized_box=decision.box_2d,
                        uploads_dir=uploads_dir,
                    )
                    segment_row = MealSegment(
                        id=segment_id,
                        meal_log_id=meal.id,
                        label=segment_debug_label(decision),
                        bounding_box=decision.box_2d,
                        cropped_image_url=str(crop_path),
                    )
                    session.add(segment_row)
                    segment_rows.append(segment_row)

                await session.flush()

                match_results: list[tuple[MealSegment, Any]] = []
                for segment_row in segment_rows:
                    match_result = await matching_service.match_segment_against_visual_corpus(
                        segment=segment_row,
                        session=session,
                        llm_client=llm_client,
                        embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                    )
                    matching_service.persist_match_candidate_snapshot(
                        segment=segment_row,
                        result=match_result,
                    )
                    match_results.append((segment_row, match_result))

                reasoning_result, trace_metadata = await reasoning_service.run_reasoning_request(
                    llm_client=llm_client,
                    meal_id=meal.id,
                    meal=meal,
                    match_results=match_results,
                    settings=settings,
                )
                finalization = await reasoning_service.finalize_meal_from_reasoning(
                    session=session,
                    meal=meal,
                    segments=segment_rows,
                    match_results=match_results,
                    reasoning_payload=reasoning_result,
                )

                food_groups = [
                    dict(group)
                    for group in list(finalization.get("food_groups", []))
                    if isinstance(group, dict)
                ] or _food_groups_from_reasoning_state(getattr(meal, "reasoning_state_json", None))
                unresolved_group_ids = [
                    str(group.get("group_id"))
                    for group in food_groups
                    if str(group.get("group_action") or group.get("action") or "").upper()
                    in {"INTERVIEW", "ASK_CHOICE", "ASK_QUANTITY"}
                    or str(group.get("group_state") or group.get("state") or "").upper()
                    in {"UNRESOLVED", "PENDING_INTERVIEW", "PENDING_CHOICE", "PARTIAL_RESOLVED_WAITING"}
                ]

                current_prompt = None
                interview_session_id = None
                if not finalization.get("finalized"):
                    interview = await interview_service.prepare_interview_session(
                        session=session,
                        meal=meal,
                        segments=segment_rows,
                        chat_id="grouped-uat",
                    )
                    interview_session_id = interview.id
                    await session.commit()
                    current_prompt = interview_service.current_target_question(
                        interview.current_prompt_payload or {}
                    ).get("prompt")

                grouped_summary = [
                    {
                        "group_id": group.get("group_id"),
                        "label": group.get("group_label") or group.get("label"),
                        "action": group.get("group_action") or group.get("action"),
                        "state": group.get("group_state") or group.get("state"),
                        "primary_segment_id": group.get("primary_segment_id"),
                        "segment_ids": group.get("segment_ids"),
                    }
                    for group in food_groups
                ]

                return {
                    "mode": "grouped-uat",
                    "status": "pass",
                    "sample": str(sample_input),
                    "meal_id": meal.id,
                    "interview_session_id": interview_session_id,
                    "processing_status": getattr(meal.processing_status, "value", meal.processing_status),
                    "segment_labels": [
                        {
                            "segment_id": segment.id,
                            "label": segment.label,
                            "crop_path": segment.cropped_image_url,
                        }
                        for segment in segment_rows
                    ],
                    "food_groups": grouped_summary,
                    "unresolved_group_ids": unresolved_group_ids,
                    "current_prompt": current_prompt,
                    "trace_id": reasoning_result.get("trace_id") or trace_metadata.get("trace_id"),
                    "trace_metadata": {
                        "trace_id": trace_metadata.get("trace_id"),
                        "cached_tokens": trace_metadata.get("cached_tokens"),
                        "meal_image_path": str(working_image),
                        "segment_crop_paths": [segment.cropped_image_url for segment in segment_rows],
                    },
                }
    finally:
        await engine.dispose()


def is_corpus_branch_valid(visual_count: int) -> bool:
    if visual_count < 0:
        raise RuntimeError("visual corpus size must be >= 0")
    return visual_count == 0 or visual_count > 0


def _resolve_database_url(args: argparse.Namespace) -> str:
    database_url = args.database_url
    if not database_url:
        settings = get_settings()
        database_url = settings.DATABASE_URL
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is empty. Set it in .env or pass --database-url for smoke modes that use Postgres."
        )
    return database_url


async def _run_calibrate(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    if args.visual_corpus_size < 0:
        raise RuntimeError("visual corpus size must be >= 0")

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    if not args.same_food_peer:
        raise RuntimeError(
            "calibrate requires --same-food-peer pointing to a different saved crop artifact"
        )
    peer_input = _resolve_crop_path(args.same_food_peer, flag_name="--same-food-peer")
    _ensure_distinct_rephoto_pair(sample_input, peer_input)
    random_input = (
        _resolve_crop_path(args.random_food, flag_name="--random-food")
        if args.random_food
        else None
    )

    sample_vector = await embedding_service.embed_image_for_document(
        image_path=sample_input,
        llm_client=llm_client,
        model=EMBEDDING_MODEL,
    )
    self_similarity = embedding_service.cosine_similarity(sample_vector, sample_vector)
    if not embedding_service.passes_same_image_gate(self_similarity):
        raise RuntimeError(
            f"same-image similarity {self_similarity:.6f} below 0.99"
        )

    same_food_vector = await embedding_service.embed_image_for_document(
        image_path=peer_input,
        llm_client=llm_client,
        model=EMBEDDING_MODEL,
    )
    same_food_similarity = embedding_service.cosine_similarity(sample_vector, same_food_vector)

    query_similarity = None
    random_similarity = None
    if args.cross_modal_text and random_input is not None:
        query_vector = await embedding_service.embed_text_for_query(
            query_text=args.cross_modal_text,
            llm_client=llm_client,
            model=EMBEDDING_MODEL,
        )
        random_vector = await embedding_service.embed_image_for_document(
            image_path=random_input,
            llm_client=llm_client,
            model=EMBEDDING_MODEL,
        )
        query_similarity = embedding_service.cosine_similarity(query_vector, sample_vector)
        random_similarity = embedding_service.cosine_similarity(query_vector, random_vector)
        if not embedding_service.passes_cross_modal_gate(
            query_to_target=query_similarity,
            query_to_random=random_similarity,
            minimum_margin=EMBEDDING_TASK_MARGIN,
        ):
            raise RuntimeError(
                "cross-modal query is not closer to same-food target than random food"
            )

    return {
        "mode": "calibrate",
        "status": "pass",
        "visual_corpus_size": args.visual_corpus_size,
        "visual_corpus_acceptable": is_corpus_branch_valid(args.visual_corpus_size),
        "sample": str(sample_input),
        "self_similarity": self_similarity,
        "same_food_peer": str(peer_input),
        "same_food_similarity": same_food_similarity,
        "cross_modal_text": args.cross_modal_text,
        "cross_modal_target_similarity": query_similarity,
        "cross_modal_random_similarity": random_similarity,
        "cross_modal_margin": (
            query_similarity - random_similarity
            if query_similarity is not None and random_similarity is not None
            else None
        ),
    }


async def _run_seed_demo(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    demo_items = [
        {
            "name": "Daal Chawal",
            "aliases": ["daal chawal", "rice and lentils"],
            "calories": 420.0,
            "protein_g": 16.0,
            "carbs_g": 68.0,
            "fat_g": 12.0,
            "source_type": "home",
            "image": args.sample,
            "is_verified": True,
        }
    ]
    if args.second_sample:
        demo_items.append(
            {
                "name": "Chicken Biryani",
                "aliases": ["chicken biryani"],
                "calories": 520.0,
                "protein_g": 28.0,
                "carbs_g": 58.0,
                "fat_g": 22.0,
                "source_type": "home",
                "image": args.second_sample,
                "is_verified": False,
            }
        )

    seeded = []
    try:
        async with session_factory() as session:
            for item in demo_items:
                existing_item = await session.scalar(
                    select(FoodItem).where(FoodItem.name == item["name"])
                )
                if existing_item is not None:
                    continue

                image_path = _resolve_crop_path(item["image"], flag_name="--sample")
                embedding = await embedding_service.embed_image_for_document(
                    image_path=image_path,
                    llm_client=llm_client,
                    model=EMBEDDING_MODEL,
                )

                food_item = FoodItem(
                    id=str(item["name"]).lower().replace(" ", "-"),
                    name=item["name"],
                    aliases=item["aliases"],
                    source_type=item["source_type"],
                    calories=item["calories"],
                    protein_g=item["protein_g"],
                    carbs_g=item["carbs_g"],
                    fat_g=item["fat_g"],
                    is_verified=item["is_verified"],
                )
                session.add(food_item)
                session.add(
                    FoodVisual(
                        id=f"{food_item.id}-visual",
                        food_item_id=food_item.id,
                        cropped_image_url=str(image_path),
                        embedding=embedding,
                        is_invalidated=False,
                    )
                )
                seeded.append(food_item.id)

            await session.commit()
    finally:
        await engine.dispose()

    return {
        "mode": "seed-demo",
        "status": "pass",
        "seeded_food_items": seeded,
    }


async def _run_unresolved_probe(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    probe_segment = MealSegment(
        id=str(uuid.uuid4()),
        meal_log_id="probe-meal",
        cropped_image_url=str(sample_input),
    )

    try:
        async with session_factory() as session:
            existing_visuals = await session.scalar(
                select(func.count())
                .select_from(FoodVisual)
                .where(FoodVisual.is_invalidated == False)  # noqa: E712
            )
            existing_visuals = int(existing_visuals or 0)

            if existing_visuals > 0:
                await session.execute(
                    update(FoodVisual)
                    .where(FoodVisual.is_invalidated == False)  # noqa: E712
                    .values(is_invalidated=True)
                )
                probe_food_item_id = _make_smoke_id("probe-unresolved-item")
                probe_item = FoodItem(
                    id=probe_food_item_id,
                    name="Probe Unresolved",
                    is_verified=False,
                )
                session.add(probe_item)
                probe_embedding = await matching_service.embed_segment_query_embedding(
                    segment=probe_segment,
                    llm_client=llm_client,
                    embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                )
                session.add(
                    FoodVisual(
                        id=_make_smoke_id("probe-unresolved-visual"),
                        food_item_id=probe_food_item_id,
                        cropped_image_url=str(sample_input),
                        embedding=[-value for value in probe_embedding],
                        is_invalidated=False,
                    )
                )
                await session.flush()

            result = await matching_service.match_segment_against_visual_corpus(
                segment=probe_segment,
                session=session,
                llm_client=llm_client,
                embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
            )

            return {
                "mode": "unresolved-probe",
                "status": "pass",
                "sample": str(sample_input),
                "probe_route": "empty-corpus" if existing_visuals == 0 else "below-threshold",
                "visual_count_before_probe": existing_visuals,
                "resolved": result.resolved,
                "is_below_threshold": result.is_below_threshold,
                "routed_state": "REASONING" if result.is_below_threshold else "COMPLETED",
                "similarity": result.similarity,
            }
    finally:
        await engine.dispose()


async def _run_repeat_confirmation(args: argparse.Namespace, llm_client) -> dict[str, Any]:
    engine = create_async_engine(
        _resolve_database_url(args),
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    sample_input = _resolve_crop_path(args.sample, flag_name="--sample")
    seed_food_id = "smoke-repeat-food"

    rounds = []
    try:
        async with session_factory() as session:
            seed_food = await session.get(FoodItem, seed_food_id)
            if seed_food is None:
                seed_embedding = await embedding_service.embed_image_for_document(
                    image_path=sample_input,
                    llm_client=llm_client,
                    model=EMBEDDING_MODEL,
                )
                seed_food = FoodItem(
                    id=seed_food_id,
                    name="Repeat Confirmed Food",
                    aliases=["repeat confirmed food", "repeat confirmation"],
                    source_type="home",
                    calories=360.0,
                    protein_g=14.0,
                    carbs_g=58.0,
                    fat_g=10.0,
                    is_verified=True,
                )
                session.add(seed_food)
                session.add(
                    FoodVisual(
                        id=f"{seed_food_id}-seed-visual",
                        food_item_id=seed_food.id,
                        cropped_image_url=str(sample_input),
                        embedding=seed_embedding,
                        is_invalidated=False,
                    )
                )
                await session.commit()

            seed_visual_count_before = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FoodVisual)
                    .where(FoodVisual.food_item_id == seed_food_id)
                )
                or 0
            )

            previous_visual_count = seed_visual_count_before
            for repeat_index in range(2):
                meal = MealLog(
                    id=_make_smoke_id(f"smoke-repeat-{repeat_index}"),
                    image_url=str(sample_input),
                    image_hash=f"repeat-{repeat_index}-{uuid.uuid4()}",
                )
                segment = MealSegment(
                    id=str(uuid.uuid4()),
                    meal_log_id=meal.id,
                    cropped_image_url=str(sample_input),
                )
                session.add(meal)
                session.add(segment)
                await session.flush()

                segment.embedding = await matching_service.embed_segment_query_embedding(
                    segment=segment,
                    llm_client=llm_client,
                    embedding_model=matching_service.MATCHING_EMBEDDING_MODEL,
                )
                match_result = await matching_service.match_segment_with_cached_embedding(
                    segment=segment,
                    session=session,
                )

                if not match_result.resolved:
                    raise RuntimeError("Repeat confirmation did not resolve a match")

                await matching_service.persist_successful_match_rows(
                    session=session,
                    meal=meal,
                    match_results=[(segment, match_result)],
                    llm_client=llm_client,
                )
                meal.processing_status = MealProcessingStatus.COMPLETED
                await session.commit()

                seed_food_visual_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(FoodVisual)
                        .where(FoodVisual.food_item_id == seed_food_id)
                    )
                    or 0
                )
                rounds.append(
                    {
                        "round": repeat_index + 1,
                        "meal_id": meal.id,
                        "seed_visual_count": seed_food_visual_count,
                        "visual_added": seed_food_visual_count > previous_visual_count,
                    }
                )
                previous_visual_count = seed_food_visual_count

            seed_visual_count_after = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FoodVisual)
                    .where(FoodVisual.food_item_id == seed_food_id)
                )
                or 0
            )

        return {
            "mode": "repeat-confirmation",
            "status": "pass",
            "sample": str(sample_input),
            "rounds": rounds,
            "seed_food_id": seed_food_id,
            "seed_visual_count_before": seed_visual_count_before,
            "seed_visual_count_after": seed_visual_count_after,
            "committed_before_notification": True,
            "database_commit_signal": "completed_before_any_notification",
        }
    finally:
        await engine.dispose()


async def main() -> int:
    args = _parse_args()
    client = None

    try:
        if args.mode == "uat-harness":
            report = await _run_uat_harness(args)
        else:
            client = get_llm_client()
        if args.mode == "calibrate":
            report = await _run_calibrate(args, client)
        elif args.mode == "seed-demo":
            report = await _run_seed_demo(args, client)
        elif args.mode == "repeat-confirmation":
            report = await _run_repeat_confirmation(args, client)
        elif args.mode == "reasoning-probe":
            report = await _run_reasoning_probe(args, client)
        elif args.mode == "grouped-uat":
            report = await _run_grouped_uat(args, client)
        elif args.mode == "uat-harness":
            report = report
        else:
            report = await _run_unresolved_probe(args, client)

        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"failed: {exc}")
        return 1
    finally:
        if client is not None:
            await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
