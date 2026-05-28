#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import traceback
import unittest


def _run(loader: unittest.TestLoader, name: str) -> str:
    try:
        suite = loader.loadTestsFromName(name)
    except Exception as exc:
        return f"load_error:{type(exc).__name__}: {exc}"
    if suite.countTestCases() == 0:
        return "no_tests"
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return "failed" if result.failures or result.errors else "passed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Red-phase assertion harness for /fix contracts.")
    parser.add_argument("--expect", action="append", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    unexpected: list[str] = []
    loader = unittest.TestLoader()
    for test_name in args.expect:
        status = _run(loader, test_name)
        if status == "failed":
            if args.verbose:
                print(f"PASS-RED EXPECTATION: {test_name} -> FAILED as expected")
            continue
        unexpected.append(f"{test_name}: {status}")
    if unexpected:
        for item in unexpected:
            print(f"UNEXPECTED RED RESULT: {item}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("HARNESS BROKEN:", type(exc).__name__, exc)
        traceback.print_exc()
        raise SystemExit(1)
