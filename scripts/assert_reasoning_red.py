#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import sys
import traceback
import unittest


def _as_text(name: str) -> str:
    return str(name)


def _run_target(loader: unittest.TestLoader, test_name: str) -> str:
    try:
        suite = loader.loadTestsFromName(test_name)
    except Exception as exc:
        return f"import_or_load_failure:{type(exc).__name__}: {exc}"

    if suite.countTestCases() == 0:
        return "no_tests_loaded"

    output = io.StringIO()
    runner = unittest.TextTestRunner(stream=output, verbosity=0)
    result = runner.run(suite)
    if result.failures or result.errors:
        return "failed"

    if result.wasSuccessful():
        return "passed"

    return f"unexpected_result:{type(result).__name__}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Red-phase assertion harness for reasoning contracts.")
    parser.add_argument(
        "--expect",
        action="append",
        required=True,
        help=(
            "Fully-qualified unittest test name expected to fail under the current implementation. "
            "Repeat for each contract assertion."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-test status details before exit code.")
    args = parser.parse_args()

    loader = unittest.TestLoader()
    expected_failing = list(args.expect)
    unexpected_passes: list[str] = []
    import_errors: list[str] = []
    unexpected_load_or_runtime: list[str] = []

    for test_name in expected_failing:
        status = _run_target(loader, test_name)
        if status == "failed":
            if args.verbose:
                print(f"PASS-RED EXPECTATION: {test_name} -> FAILED as expected")
            continue
        if status == "passed":
            unexpected_passes.append(test_name)
            continue
        if status.startswith("import_or_load_failure"):
            import_errors.append(f"{test_name}: {status}")
            continue
        if status == "no_tests_loaded":
            import_errors.append(f"{test_name}: no tests loaded")
            continue
        unexpected_load_or_runtime.append(f"{test_name}: {status}")

    if unexpected_passes or import_errors or unexpected_load_or_runtime:
        for message in import_errors:
            print(f"IMPORT/LOAD ERROR: {message}")
        for message in unexpected_load_or_runtime:
            print(f"RUNTIME/LOAD ERROR: {message}")
        for message in unexpected_passes:
            print(f"UNEXPECTED PASS: {message}")
        return 1

    if args.verbose:
        print(
            "All expected contracts failed as intended; red-harness contract guard satisfied."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("HARNESS BROKEN:", _as_text(type(exc).__name__), _as_text(exc))
        traceback.print_exc()
        raise SystemExit(1)
