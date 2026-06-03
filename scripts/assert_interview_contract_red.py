from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path


TARGET_MODULES = (
    "tests.test_reasoning_flow",
    "tests.test_interview_schema",
    "tests.test_interview_flow",
)
EXPECTED_FAILURES = {
    "tests.test_interview_schema.InterviewConfigContractTests.test_settings_expose_explicit_interview_models",
    "tests.test_interview_schema.InterviewSchemaContractTests.test_confirmation_item_requires_approval_status",
    "tests.test_interview_schema.InterviewSchemaContractTests.test_schema_module_exposes_strict_contract_and_response_format",
    "tests.test_interview_schema.InterviewTurnManagerContractTests.test_invalid_ready_to_confirm_fails_closed_without_mutating_state",
    "tests.test_interview_schema.InterviewTurnManagerContractTests.test_single_repair_retry_recovers_malformed_first_pass",
    "tests.test_interview_flow.InterviewPersistencePrepTests.test_build_interview_turn_state_includes_unresolved_and_approval_groups",
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
        raise SystemExit("RED harness expected contract failures, but the suite passed.")
    if result.failure_ids != EXPECTED_FAILURES:
        expected = "\n".join(sorted(EXPECTED_FAILURES))
        actual = "\n".join(sorted(result.failure_ids))
        raise SystemExit(
            "RED harness saw the wrong failing tests.\n"
            f"Expected:\n{expected}\n\nActual:\n{actual}\n\n{output}"
        )

    print("RED harness passed: expected Phase 04.2 contract failures are present.")
    if output:
        print(output)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - hard-fail path for harness integrity
        raise SystemExit(f"RED harness crashed: {exc}") from exc
