from __future__ import annotations

import sys
import unittest
from pathlib import Path

EXPECTED_FAILURES = {
    "tests.test_reasoning_contract": [
        "tests.test_reasoning_contract.ReasoningContractTests.test_reasoning_response_format_contains_strict_clarification_schema",
    ],
    "tests.test_reasoning_gate": [
        "tests.test_reasoning_gate.ReasoningGateTests.test_gate_emits_deterministic_clarification_batch_for_interview_groups",
        "tests.test_reasoning_gate.ReasoningGateTests.test_source_origin_question_only_for_ambiguous_material_foods",
    ],
    "tests.test_reasoning_flow": [
        "tests.test_reasoning_flow.ReasoningFlowTests.test_run_reasoning_request_adds_deterministic_clarification_schema_for_reviewable_groups",
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
    for module, test_names in EXPECTED_FAILURES.items():
        for name in test_names:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))

    result = unittest.TestResult()
    suite.run(result)

    expected_failures = {
        test_id
        for module in EXPECTED_FAILURES
        for test_id in EXPECTED_FAILURES[module]
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
            f"RED failed: expected missing grouped behavior unexpectedly passed: {unexpected_successes}",
            file=sys.stderr,
        )
        return 1

    if missing_failures:
        print(
            "RED failed: expected grouped contract failures did not occur:\n- "
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

    print("RED verified: 04.3 clarification contract failures reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
