from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


EXPECTED_FAILURES = {
    "tests.test_reasoning_contract": [
        "tests.test_reasoning_contract.ReasoningContractTests.test_grouped_reasoning_contract_requires_food_groups",
    ],
    "tests.test_reasoning_gate": [
        "tests.test_reasoning_gate.ReasoningGateTests.test_group_gate_keeps_unrelated_foods_in_separate_races",
    ],
    "tests.test_reasoning_flow": [
        "tests.test_reasoning_flow.ReasoningFlowTests.test_persists_compact_group_snapshots_without_copying_meal_candidates",
    ],
    "tests.test_match_flow": [
        "tests.test_match_flow.GroupedAutoConfirmWriteTests.test_grouped_auto_confirm_collapses_to_one_final_write_item_per_food_group",
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
        description="Assert that grouped reasoning RED tests fail for the expected pre-04.1 reasons."
    )
    parser.add_argument(
        "--expect",
        action="append",
        dest="modules",
        required=True,
        help="Unittest module expected to contain one grouped RED failure.",
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
            f"RED failed: expected missing grouped behavior unexpectedly passed: {unexpected_successes}",
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
            "RED failed: expected grouped contract failures did not occur:\n- "
            + "\n- ".join(missing_failures),
            file=sys.stderr,
        )
        return 1

    print("RED verified: grouped reasoning contract failures reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
