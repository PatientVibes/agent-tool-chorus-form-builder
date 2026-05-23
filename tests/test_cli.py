"""CLI tests — invokes chorus-form-build via subprocess, checks exit codes + files."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _write_form(tmp_path: Path, content: str, name: str = "form.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def _venv_python() -> str:
    """Resolve the venv's python — works on Windows where .venv/Scripts/
    differs from POSIX .venv/bin/."""
    repo_root = Path(__file__).resolve().parent.parent
    if sys.platform == "win32":
        return str(repo_root / ".venv" / "Scripts" / "python.exe")
    return str(repo_root / ".venv" / "bin" / "python")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Invoke the CLI module via `python -m chorus_form_builder.cli`."""
    return subprocess.run(
        [_venv_python(), "-m", "chorus_form_builder.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_static_combo_succeeds(tmp_path):
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: STATCOMB
          title: Static
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    out_dir = tmp_path / "out"
    proc = _run_cli("--spec", str(spec_path), "--output", str(out_dir), "--no-fetch")
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert (out_dir / "STATCOMB.csd").is_file()
    assert (out_dir / "STATCOMB.uxb.json").is_file()
    assert (out_dir / "STATCOMB_manifest.json").is_file()


def test_cli_spec_validation_failure_exit_1(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: lowercase
          title: T
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"))
    assert proc.returncode == 1
    assert "form.name" in proc.stderr or "form.name" in proc.stdout


def test_cli_binding_failure_exit_2(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: D
            control_type: combobox
            binding:
              openapi_spec: ./does-not-exist.json
              endpoint: /x
              values_path: $.x
              value_field: v
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    # --no-fetch would also error here, but the missing-file check fires first
    assert proc.returncode == 2


def test_cli_no_fetch_with_static_only_succeeds(tmp_path):
    """--no-fetch is fine when the spec has zero bindings."""
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: TXTONLY
          title: T
        fields:
          - {code: MEMO, label: M, control_type: text, length: 60}
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    assert proc.returncode == 0


def test_cli_no_fetch_with_binding_errors(tmp_path):
    """--no-fetch errors clearly if any binding is present."""
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: D
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /x
              values_path: $.x
              value_field: v
    """)
    (tmp_path / "oracle.json").write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "T", "version": "1"},
        "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }), encoding="utf-8")
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    assert proc.returncode == 2
    assert "--no-fetch" in (proc.stderr + proc.stdout)


def test_cli_missing_spec_path_exit_1(tmp_path):
    proc = _run_cli("--spec", str(tmp_path / "no-such.yaml"), "--output", str(tmp_path / "out"))
    assert proc.returncode == 1


def test_cli_help_exits_zero():
    proc = _run_cli("--help")
    assert proc.returncode == 0
    assert "chorus-form-build" in proc.stdout or "--spec" in proc.stdout
