from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path


TARGET_MODULES = (
    "tests.test_reasoning_flow",
    "tests.test_interview_flow",
    "tests.test_bot_contract",
)
EXPECTED_FAILURES = {
    "tests.test_bot_contract.HandlerTests.test_meal_interview_text_fails_closed_after_turn_validation_error",
    "tests.test_bot_contract.HandlerTests.test_meal_interview_text_handles_continue_interview_turns",
    "tests.test_bot_contract.HandlerTests.test_meal_interview_text_handles_need_clarification_turns",
    "tests.test_bot_contract.HandlerTests.test_meal_interview_text_routes_ready_to_confirm_through_finalizer_with_approval_statuses",
    "tests.test_bot_contract.HandlerTests.test_start_meal_interview_turn_runs_llm_prompt_and_tracks_message_id",
    "tests.test_interview_flow.InterviewPersistencePrepTests.test_confirmation_items_from_state_preserve_explicit_approval_statuses",
}
REPO_ROOT = Path(__file__).resolve().parents[1]


class _FailureCollectingResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.failure_ids: set[str] = set()

    def addFailure(self, test, err):
        self.failure_ids.add(test.id())
        super().addFailure(test, err)


def main() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromNames(TARGET_MODULES)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream,
        verbosity=0,
        resultclass=_FailureCollectingResult,
    )
    result = runner.run(suite)
    output = stream.getvalue().strip()

    if result.errors:
        raise SystemExit(f"RED harness saw unexpected errors:\n{output}")
    if not result.failure_ids:
        raise SystemExit("RED harness expected live interview orchestration failures, but the suite passed.")
    if result.failure_ids != EXPECTED_FAILURES:
        expected = "\n".join(sorted(EXPECTED_FAILURES))
        actual = "\n".join(sorted(result.failure_ids))
        raise SystemExit(
            "RED harness saw the wrong failing tests.\n"
            f"Expected:\n{expected}\n\nActual:\n{actual}\n\n{output}"
        )

    print("RED harness passed: expected Phase 04.2 live interview failures are present.")
    if output:
        print(output)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - hard-fail path for harness integrity
        raise SystemExit(f"RED harness crashed: {exc}") from exc
