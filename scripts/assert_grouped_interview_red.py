from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


EXPECTED_FAILURES = {
    "tests.test_interview_flow": [
        "tests.test_interview_flow.InterviewProgressionTests.test_current_target_question_uses_locked_grouped_curry_detail_wording",
        "tests.test_interview_flow.InterviewPersistencePrepTests.test_prepare_interview_session_targets_unresolved_food_groups_before_quantity",
    ],
    "tests.test_match_flow": [
        "tests.test_match_flow.MatchWorkerTests.test_poll_and_match_routes_to_reasoning_when_any_segment_is_unresolved",
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
    parser = argparse.ArgumentParser(
        description="Assert that grouped interview RED tests fail for the expected pre-04.1 behavior."
    )
    parser.add_argument(
        "--expect",
        action="append",
        dest="modules",
        required=True,
        help="Unittest module expected to contain grouped interview RED failures.",
    )
    args = parser.parse_args()

    unknown = [module for module in args.modules if module not in EXPECTED_FAILURES]
    if unknown:
        print(f"Unknown expected modules: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    suite = unittest.TestSuite()
    for module in args.modules:
        for test_name in EXPECTED_FAILURES[module]:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(test_name))

    result = unittest.TestResult()
    suite.run(result)

    expected_failures = {
        test_id
        for module in args.modules
        for test_id in EXPECTED_FAILURES[module]
    }
    actual_failures = {_test_id(case) for case, _trace in result.failures}
    actual_errors = {_test_id(case) for case, _trace in result.errors}
    unexpected_failures = sorted(actual_failures - expected_failures)
    missing_failures = sorted(expected_failures - actual_failures)

    if result.unexpectedSuccesses:
        unexpected_successes = ", ".join(
            sorted(_test_id(case) for case in result.unexpectedSuccesses)
        )
        print(
            f"RED failed: expected missing grouped interview behavior unexpectedly passed: {unexpected_successes}",
            file=sys.stderr,
        )
        return 1

    if actual_errors:
        print(
            "RED failed: test run had unexpected errors:\n- "
            + "\n- ".join(sorted(actual_errors)),
            file=sys.stderr,
        )
        return 1

    if unexpected_failures:
        print(
            "RED failed: unrelated tests failed:\n- " + "\n- ".join(unexpected_failures),
            file=sys.stderr,
        )
        return 1

    if missing_failures:
        print(
            "RED failed: expected grouped interview contract failures did not occur:\n- "
            + "\n- ".join(missing_failures),
            file=sys.stderr,
        )
        return 1

    print("RED verified: grouped interview contract failures reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
