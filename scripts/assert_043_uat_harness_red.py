from __future__ import annotations

import sys
import unittest
from pathlib import Path

EXPECTED_FAILURES = {
    "tests.test_embed_match_smoke.SmokeUatHarnessContractTests.test_uat_harness_named_scenarios_map_to_phase_regression_samples",
    "tests.test_embed_match_smoke.SmokeUatHarnessContractTests.test_uat_harness_rejects_default_database_for_destructive_clone",
    "tests.test_embed_match_smoke.SmokeUatHarnessContractTests.test_uat_harness_report_contains_required_audit_sections",
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
    for test_id in sorted(EXPECTED_FAILURES):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(test_id))

    result = unittest.TestResult()
    suite.run(result)

    actual_failures = {_test_id(case) for case, _trace in result.failures}
    actual_errors = {_test_id(case) for case, _trace in result.errors}

    missing_failures = sorted(EXPECTED_FAILURES - actual_failures)
    unexpected_failures = sorted(actual_failures - EXPECTED_FAILURES)
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
            f"RED failed: expected missing 04.3 UAT harness behavior unexpectedly passed: {unexpected_successes}",
            file=sys.stderr,
        )
        return 1

    if missing_failures:
        print(
            "RED failed: expected 04.3 harness contract failures did not occur:\n- "
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

    print("RED verified: 04.3 harness gap is reproduced exactly.")
    for test_id in sorted(actual_failures):
        print(f"- {test_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
