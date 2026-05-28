#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import traceback
import unittest


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
    parser = argparse.ArgumentParser(description="Red-phase assertion harness for interview contracts.")
    parser.add_argument("--expect", action="append", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    loader = unittest.TestLoader()
    unexpected_passes: list[str] = []
    load_errors: list[str] = []
    runtime_errors: list[str] = []

    for test_name in args.expect:
        status = _run_target(loader, test_name)
        if status == "failed":
            if args.verbose:
                print(f"PASS-RED EXPECTATION: {test_name} -> FAILED as expected")
            continue
        if status == "passed":
            unexpected_passes.append(test_name)
        elif status.startswith("import_or_load_failure") or status == "no_tests_loaded":
            load_errors.append(f"{test_name}: {status}")
        else:
            runtime_errors.append(f"{test_name}: {status}")

    if unexpected_passes or load_errors or runtime_errors:
        for message in load_errors:
            print(f"IMPORT/LOAD ERROR: {message}")
        for message in runtime_errors:
            print(f"RUNTIME/LOAD ERROR: {message}")
        for test_name in unexpected_passes:
            print(f"UNEXPECTED PASS: {test_name}")
        return 1

    if args.verbose:
        print("All expected interview contracts failed as intended.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("HARNESS BROKEN:", type(exc).__name__, exc)
        traceback.print_exc()
        raise SystemExit(1)
