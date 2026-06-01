from __future__ import annotations

import sys
import unittest
from pathlib import Path

EXPECTED_FAILURES = {
    "tests.test_interview_flow": [
        "tests.test_interview_flow.InterviewProgressionTests.test_current_target_question_uses_contract_owned_user_prompt_for_affirmation_action",
    ],
    "tests.test_bot_contract": [
        "tests.test_bot_contract.HandlerTests.test_interview_callback_no_affirmation_prompts_same_group_free_text_correction",
    ],
    "tests.test_match_flow": [
        "tests.test_match_flow.InterviewFinalizationWriteTests.test_best_effort_grounding_resolution_preserves_visual_learning_inputs",
        "tests.test_match_flow.MatchWorkerTests.test_post_interview_grounding_quota_failure_surfaces_blocker_and_degraded_save",
    ],
}

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _test_id(case: unittest.case.TestCase) -> str:
    try:
        return case.id()
    except Exception:
        return repr(case)


def main() -> int:
    suite = unittest.TestSuite()
    for test_names in EXPECTED_FAILURES.values():
        for name in test_names:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))

    result = unittest.TestResult()
    suite.run(result)

    expected_failures = {
        test_id
        for test_names in EXPECTED_FAILURES.values()
        for test_id in test_names
    }
    actual_failures = {_test_id(case) for case, _trace in result.failures}
    actual_errors = {_test_id(case) for case, _trace in result.errors}

    missing_failures = sorted(expected_failures - actual_failures)
    unexpected_failures = sorted(actual_failures - expected_failures)

    if actual_errors:
        print(
            "RED failed: test run had unexpected errors:\n- "
            + "\n- ".join(sorted(actual_errors)),
            file=sys.stderr,
        )
        return 1

    if result.unexpectedSuccesses:
        unexpected_successes = ", ".join(
            sorted(_test_id(case) for case in result.unexpectedSuccesses)
        )
        print(
            "RED failed: expected 04.3 interview/grounding runtime gaps unexpectedly passed: "
            f"{unexpected_successes}",
            file=sys.stderr,
        )
        return 1

    if missing_failures:
        print(
            "RED failed: expected interview/grounding failures did not occur:\n- "
            + "\n- ".join(missing_failures),
            file=sys.stderr,
        )
        return 1

    if unexpected_failures:
        print(
            "RED failed: unrelated failures changed from expectation:\n- "
            + "\n- ".join(unexpected_failures),
            file=sys.stderr,
        )
        return 1

    print("RED verified: 04.3 interview correction and grounding failures reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
