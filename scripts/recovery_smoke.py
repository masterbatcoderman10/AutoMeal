from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services import recovery_service


@dataclass(frozen=True)
class _SmokeSettings:
    STALE_TIMEOUT_MINUTES: int
    MAX_RECOVERY_ATTEMPTS: int
    TELEGRAM_CHAT_ID: str = "smoke"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or apply the production meal janitor recovery flow for a real meal."
    )
    parser.add_argument(
        "--meal-id",
        required=True,
        help="MealLog.id to inspect.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL override. Defaults to app settings.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=None,
        help="Override the janitor stale threshold for the smoke run.",
    )
    parser.add_argument(
        "--max-recoveries",
        type=int,
        default=None,
        help="Override the janitor recovery ceiling for the smoke run.",
    )
    parser.add_argument(
        "--at",
        default=None,
        help="Optional ISO timestamp to evaluate the janitor at instead of now.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run the production janitor once after inspecting the meal.",
    )
    return parser.parse_args()


def _resolve_database_url(args: argparse.Namespace) -> str:
    if args.database_url:
        return args.database_url
    settings = get_settings()
    return settings.DATABASE_URL


def _resolve_now(args: argparse.Namespace) -> datetime:
    if not args.at:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(args.at)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def _load_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    meal_id: str,
    current_time: datetime,
    stale_minutes: int,
    max_recoveries: int,
) -> dict[str, Any] | None:
    async with session_factory() as session:
        return await recovery_service.inspect_meal_recovery(
            session,
            meal_id,
            now=current_time,
            stale_minutes=stale_minutes,
            max_recoveries=max_recoveries,
        )


def _render_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    meal = snapshot["meal"]
    plan = snapshot["plan"]
    return {
        "meal_id": meal.id,
        "pre_recovery_stage": meal.processing_status.value,
        "last_stage_started_at": meal.last_stage_started_at.isoformat() if meal.last_stage_started_at else None,
        "recovery_attempt_count": meal.recovery_attempt_count,
        "inferred_resume_stage": plan.get("recovery_status"),
        "resume_basis": plan.get("resume_basis"),
        "action": plan.get("action"),
        "reason": plan.get("reason"),
        "notify_user": plan.get("notify_user", False),
    }


async def _main() -> int:
    args = _parse_args()
    current_time = _resolve_now(args)
    settings = get_settings()
    stale_minutes = int(args.stale_minutes or settings.STALE_TIMEOUT_MINUTES)
    max_recoveries = int(args.max_recoveries or settings.MAX_RECOVERY_ATTEMPTS)
    database_url = _resolve_database_url(args)

    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        before = await _load_snapshot(
            session_factory,
            meal_id=args.meal_id,
            current_time=current_time,
            stale_minutes=stale_minutes,
            max_recoveries=max_recoveries,
        )
        if before is None:
            print(json.dumps({"meal_id": args.meal_id, "error": "meal_not_found"}, indent=2))
            return 1

        report: dict[str, Any] = {
            "inspected_at": current_time.isoformat(),
            "before": _render_snapshot(before),
        }

        if args.apply:
            smoke_settings = _SmokeSettings(
                STALE_TIMEOUT_MINUTES=stale_minutes,
                MAX_RECOVERY_ATTEMPTS=max_recoveries,
            )
            processed = await recovery_service.run_meal_janitor(
                session_factory=session_factory,
                settings=smoke_settings,
                bot=None,
                now=current_time,
            )
            after = await _load_snapshot(
                session_factory,
                meal_id=args.meal_id,
                current_time=current_time,
                stale_minutes=stale_minutes,
                max_recoveries=max_recoveries,
            )
            report["janitor_run"] = {
                "processed_meal_ids": [item.get("meal_id") for item in processed],
                "matched_meal": next((item for item in processed if item.get("meal_id") == args.meal_id), None),
            }
            if after is not None:
                report["after"] = _render_snapshot(after)

        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
