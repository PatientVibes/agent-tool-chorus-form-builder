"""Golden tests — byte-exact .csd, structural .uxb.json + manifest.

If any of these fail, either the implementation drifted or the fixture
needs regenerating. To regenerate: delete the .csd / .uxb.json /
_manifest.json files in the relevant golden dir, then run this test
with REGENERATE_GOLDENS=1 in the env.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from chorus_form_builder import build_form
from chorus_form_builder.binding import GoldenFetcher, Response


GOLDENS_DIR = Path(__file__).parent / "goldens"

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _normalize_manifest(manifest: dict) -> dict:
    """Strip dynamic fields (timestamps) for stable comparison.

    `generator_version` is intentionally NOT stripped — a version bump is
    a deliberate, reviewable change and should require regenerating goldens
    so the diff stays visible in code review.
    """
    out = dict(manifest)
    out.pop("generated_at", None)
    for b in out.get("bindings", []):
        b.pop("fetched_at", None)
    return out


def _normalize_uxb(uxb: dict) -> dict:
    """Normalize .uxb.json for stable comparison.

    chorus_forms generates random UUIDs for elementId fields inside the
    embedded uxData JSON string on every call. We parse that string and
    replace each UUID with a stable positional placeholder so the structure
    test is deterministic without being sensitive to identity noise.
    """
    out = dict(uxb)
    if "uxData" in out and isinstance(out["uxData"], str):
        raw = out["uxData"]
        # Collect UUIDs in encounter order and replace each with its ordinal
        seen: dict[str, str] = {}
        def _sub(m: re.Match) -> str:
            uuid = m.group(0)
            if uuid not in seen:
                seen[uuid] = f"UUID_{len(seen)}"
            return seen[uuid]
        out["uxData"] = _UUID_RE.sub(_sub, raw)
    return out


def _load_canned_responses(golden_dir: Path) -> dict[tuple[str, str], Response]:
    """Build a GoldenFetcher canned-response map from a response.json in the
    golden dir. Shape: {"GET https://url": {...response body...}}.

    Missing response.json returns an empty map — fine for static-only goldens
    like `static_combo`. A bound-spec golden missing its response.json will
    not silently pass: GoldenFetcher raises BindingError naming the missing
    (method, url) key on the first lookup.
    """
    response_file = golden_dir / "response.json"
    if not response_file.is_file():
        return {}
    raw = json.loads(response_file.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], Response] = {}
    for key, body in raw.items():
        method, url = key.split(" ", 1)
        out[(method, url)] = Response(200, body)
    return out


def _run_golden(name: str, tmp_path: Path) -> None:
    """Run build_form against a golden dir's spec; compare outputs against
    the committed golden files."""
    golden_dir = GOLDENS_DIR / name
    spec_path = golden_dir / "form.yaml"
    canned = _load_canned_responses(golden_dir)
    fetcher = GoldenFetcher(canned)

    out_dir = tmp_path / "out"
    result = build_form(spec_path, out_dir, fetcher=fetcher)

    expected_csd = next(golden_dir.glob("*.csd"), None)
    expected_uxb = next(golden_dir.glob("*.uxb.json"), None)
    expected_manifest = next(golden_dir.glob("*_manifest.json"), None)

    if os.environ.get("REGENERATE_GOLDENS") == "1":
        if expected_csd is None:
            expected_csd = golden_dir / result.csd_path.name
        if expected_uxb is None:
            expected_uxb = golden_dir / result.uxb_path.name
        if expected_manifest is None:
            expected_manifest = golden_dir / result.manifest_path.name
        expected_csd.write_bytes(result.csd_path.read_bytes())
        expected_uxb.write_text(result.uxb_path.read_text(encoding="utf-8"), encoding="utf-8")
        expected_manifest.write_text(result.manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
        # Copy awdForm.js shim if present in output (rule-bearing forms only)
        generated_shim = result.csd_path.parent / "awdForm.js"
        if generated_shim.is_file():
            (golden_dir / "awdForm.js").write_bytes(generated_shim.read_bytes())
        pytest.skip(f"REGENERATE_GOLDENS=1 — regenerated {name} golden files")

    assert expected_csd is not None, f"no committed .csd golden in {golden_dir}"
    assert expected_uxb is not None, f"no committed .uxb.json golden in {golden_dir}"
    assert expected_manifest is not None, f"no committed _manifest.json golden in {golden_dir}"

    assert result.csd_path.read_bytes() == expected_csd.read_bytes(), \
        f"{name}: .csd bytes differ"

    actual_uxb = _normalize_uxb(json.loads(result.uxb_path.read_text(encoding="utf-8")))
    expected_uxb_data = _normalize_uxb(json.loads(expected_uxb.read_text(encoding="utf-8")))
    assert actual_uxb == expected_uxb_data, f"{name}: .uxb.json structure differs"

    actual_manifest = _normalize_manifest(json.loads(result.manifest_path.read_text(encoding="utf-8")))
    expected_manifest_data = _normalize_manifest(json.loads(expected_manifest.read_text(encoding="utf-8")))
    assert actual_manifest == expected_manifest_data, f"{name}: manifest differs"


def test_golden_static_combo(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("static_combo", tmp_path)


def test_golden_oracle_dcmb(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("oracle_dcmb", tmp_path)


def test_golden_text_plus_combo(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("text_plus_combo", tmp_path)


def test_golden_with_rules(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("with_rules", tmp_path)

    # Additionally: confirm the awdForm.js shim was emitted alongside the .csd
    out_dir = tmp_path / "out"
    assert (out_dir / "awdForm.js").is_file(), \
        f"with_rules golden should ship awdForm.js next to the .csd; out_dir={list(out_dir.iterdir())}"
    # And it should equal the committed shim
    golden_shim = (Path(__file__).resolve().parent / "goldens" / "with_rules" / "awdForm.js")
    assert golden_shim.is_file(), "with_rules golden dir is missing awdForm.js"
    assert (out_dir / "awdForm.js").read_bytes() == golden_shim.read_bytes()
