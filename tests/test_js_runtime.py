"""Layer-C integration tests — drive emitted customRules JS against the
awdForm shim using Node.

Each test case is a JS file in tests/js_runtime/test_cases/. Pytest
invokes `node tests/js_runtime/runner.js <test-case>` as a subprocess,
parses one JSON line per assertion, and surfaces any failures.

If `node` isn't on PATH, every test in this module skips with a clear
message — the Python suite still runs end-to-end.

DRIFT WARNING: the customRules template literals in each test case are
HAND-WRITTEN — they reproduce the shape that procedures.compile_rules
currently emits, but they are NOT regenerated from compile_rules at test
time. A future Task-3 codegen change that re-shapes the JS output (e.g.,
renamed shim methods, different event name conventions) would let these
integration tests keep passing on stale JS while real-world output drifts.
When updating compile_rules, also update each test case here so the
shapes stay aligned. (A complementary v0.2 follow-up could generate the
customRules string from compile_rules at test time to eliminate the
drift surface entirely.)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _REPO_ROOT / "tests" / "js_runtime" / "runner.js"
_CASES_DIR = _REPO_ROOT / "tests" / "js_runtime" / "test_cases"


def _require_node() -> str:
    """Return the path to a node executable, skipping the test if missing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; install Node 18+ to exercise Layer-C tests")
    return node


def _run_case(case_filename: str) -> list[dict]:
    """Invoke the Node runner against a single test-case file. Returns the
    list of parsed JSON-line assertions; pytest fails the test if any
    assertion's `ok` is False."""
    node = _require_node()
    case_path = _CASES_DIR / case_filename
    assert case_path.is_file(), f"missing test case: {case_path}"

    proc = subprocess.run(
        [node, str(_RUNNER), str(case_path)],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(_REPO_ROOT),
    )
    assertions = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            assertions.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(f"non-JSON output from runner: {line!r}\nstderr: {proc.stderr}")

    # Surface any failed assertion via pytest
    failed = [a for a in assertions if not a.get("ok", False)]
    if failed:
        pytest.fail(
            f"{len(failed)}/{len(assertions)} assertion(s) failed in {case_filename}:\n"
            + "\n".join(f"  - {a['name']}: {a.get('detail', '')}" for a in failed)
            + f"\nfull stderr: {proc.stderr}"
        )
    assert assertions, f"no assertions emitted by {case_filename}; stderr: {proc.stderr}"
    return assertions


def test_layer_c_shim_smoke():
    _run_case("shim_smoke.js")


def test_layer_c_visible_when():
    _run_case("visible_when.js")


def test_layer_c_enabled_when():
    _run_case("enabled_when.js")


def test_layer_c_required_when():
    _run_case("required_when.js")


def test_layer_c_default_when():
    _run_case("default_when.js")


def test_layer_c_multi_rule():
    _run_case("multi_rule.js")
