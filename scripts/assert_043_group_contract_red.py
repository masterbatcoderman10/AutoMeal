from __future__ import annotations

import sys
import unittest
from pathlib import Path

EXPECTED_FAILURES = {
    "tests.test_reasoning_contract": [
        "tests.test_reasoning_contract.ReasoningContractTests.test_grouped_reasoning_migrates_root_clarification_into_group_contract",
    ],
    "tests.test_reasoning_gate": [
        "tests.test_reasoning_gate.ReasoningGateTests.test_identity_clarification_actions_use_ranked_top_three_and_contract_owned_other",
        "tests.test_reasoning_gate.ReasoningGateTests.test_visual_only_high_confidence_requires_affirmation_but_learned_match_auto_confirms",
        "tests.test_reasoning_gate.ReasoningGateTests.test_source_origin_is_reasoning_owned_and_ordered_after_affirmation",
    ],
    "tests.test_reasoning_flow": [
        "tests.test_reasoning_flow.ReasoningFlowTests.test_run_reasoning_request_persists_group_owned_clarification_actions_before_telegram_mapping",
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
            "RED failed: expected Phase 04.3 contract gaps unexpectedly passed: "
            f"{unexpected_successes}",
            file=sys.stderr,
        )
        return 1

    if missing_failures:
        print(
            "RED failed: expected group-contract failures did not occur:\n- "
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

    print("RED verified: 04.3 per-group clarification contract failures reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
