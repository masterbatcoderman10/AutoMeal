from __future__ import annotations

import argparse
import io
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assert that janitor RED tests fail only for the expected missing behavior."
    )
    parser.add_argument(
        "--expect",
        action="append",
        dest="expected_tests",
        required=True,
        help="Fully-qualified unittest name expected to fail in RED.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for test_name in args.expected_tests:
        suite.addTests(loader.loadTestsFromName(test_name))

    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output = stream.getvalue()
    sys.stdout.write(output)

    expected = sorted(args.expected_tests)
    if result.testsRun != len(expected):
        sys.stderr.write(
            f"Expected to run {len(expected)} tests, ran {result.testsRun} instead.\n"
        )
        return 1
    if result.errors:
        sys.stderr.write("RED harness saw unexpected import/runtime errors.\n")
        return 1
    failed = sorted(test.id() for test, _trace in result.failures)
    if failed != expected:
        sys.stderr.write(
            f"Expected assertion failures from {expected}, got {failed}.\n"
        )
        return 1
    if result.wasSuccessful():
        sys.stderr.write("RED harness passed unexpectedly; Phase 4 janitor behavior already exists.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
