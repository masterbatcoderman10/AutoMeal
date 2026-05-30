from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
REQUIREMENTS_FILE = REPO_ROOT / "requirements.txt"
TARGET_MODULES = (
    "tests.test_reasoning_flow",
    "tests.test_interview_flow",
    "tests.test_bot_contract",
)
IMPORT_PROBE = (
    "app.config",
    "app.services.interview_service",
    "app.services.reasoning_service",
    "bot.handlers",
)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _ensure_venv() -> None:
    if VENV_PYTHON.exists():
        return
    builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=True, upgrade=False)
    builder.create(VENV_DIR)


def _venv_has_required_imports() -> bool:
    if not VENV_PYTHON.exists():
        return False
    probe = (
        "import importlib\n"
        "for name in " + repr(IMPORT_PROBE) + ":\n"
        "    importlib.import_module(name)\n"
    )
    result = _run([str(VENV_PYTHON), "-c", probe], check=False)
    return result.returncode == 0


def _install_requirements() -> None:
    _run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])


def _assert_python_version() -> None:
    version_probe = _run(
        [
            str(VENV_PYTHON),
            "-c",
            "import json, sys; print(json.dumps({'major': sys.version_info.major, 'minor': sys.version_info.minor}))",
        ]
    )
    payload = json.loads(version_probe.stdout.strip() or "{}")
    if payload.get("major") != 3 or payload.get("minor") != 12:
        raise SystemExit(f"Expected .venv interpreter to be Python 3.12, got: {version_probe.stdout.strip()}")


def _run_preflight_suite() -> None:
    command = [
        str(VENV_PYTHON),
        "-m",
        "unittest",
        *TARGET_MODULES,
        "-q",
    ]
    result = _run(command, check=False)
    if result.returncode == 0:
        print("Preflight passed: targeted suites executed cleanly.")
        return

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if "ImportError" in output or "ModuleNotFoundError" in output:
        raise SystemExit(f"Preflight import/bootstrap failure:\n{output}")
    if "Ran 0 tests" in output:
        raise SystemExit(f"Preflight failed to execute targeted suites:\n{output}")
    if "ERROR:" in output or "\nERROR\n" in output or "FAILED (errors=" in output:
        raise SystemExit(f"Preflight encountered runtime errors:\n{output}")

    print("Preflight passed: targeted suites executed and only assertion failures remain.")
    if output:
        print(output)


def main() -> None:
    _ensure_venv()
    if not _venv_has_required_imports():
        _install_requirements()
    _assert_python_version()
    if not _venv_has_required_imports():
        raise SystemExit("Repo imports still fail after installing requirements into .venv.")
    _run_preflight_suite()


if __name__ == "__main__":
    main()
