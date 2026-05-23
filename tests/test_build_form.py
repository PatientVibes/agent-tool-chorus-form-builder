"""build_form integration tests — orchestrates spec + binding + emit."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("chorus_forms", reason="chorus_forms required")

from chorus_form_builder import (
    BindingError,
    EmitResult,
    FormBuilderError,
    SpecValidationError,
    build_form,
)
from chorus_form_builder.binding import GoldenFetcher, NoFetchFetcher, Response


def _write_form(tmp_path: Path, content: str, name: str = "form.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def test_build_form_static_combo_no_fetcher_needed(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: STATCOMB
          title: Static Combo
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    out_dir = tmp_path / "out"
    result = build_form(spec_path, out_dir, fetcher=NoFetchFetcher())
    assert isinstance(result, EmitResult)
    assert result.csd_path.is_file()
    assert result.csd_path.name == "STATCOMB.csd"


def test_build_form_with_binding_uses_fetcher(tmp_path):
    (tmp_path / "oracle.json").write_text(json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {"/codes": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }), encoding="utf-8")
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: Bound Form
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: Distro
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /codes
              values_path: $.items[*]
              value_field: value
              description_field: description
    """)
    out_dir = tmp_path / "out"
    fetcher = GoldenFetcher({
        ("GET", "https://example.com/api/codes"): Response(
            200,
            {"items": [{"value": "X", "description": "X-desc"}, {"value": "Y", "description": "Y-desc"}]},
        )
    })
    result = build_form(spec_path, out_dir, fetcher=fetcher)
    assert result.csd_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bindings"][0]["value_count"] == 2


def test_build_form_propagates_spec_validation_error(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: lowercase
          title: T
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError):
        build_form(spec_path, tmp_path / "out", fetcher=NoFetchFetcher())


def test_build_form_propagates_binding_error(tmp_path):
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
    with pytest.raises(BindingError):
        build_form(spec_path, tmp_path / "out", fetcher=GoldenFetcher({}))


def test_build_form_default_fetcher_is_httpx(tmp_path):
    """If no fetcher is passed and the spec has no bindings, build_form
    succeeds (HttpxFetcher is never used for a binding-less form)."""
    spec_path = _write_form(tmp_path, """
        form:
          name: TXTONLY
          title: T
        fields:
          - {code: MEMO, label: M, control_type: text, length: 60}
    """)
    result = build_form(spec_path, tmp_path / "out")  # no fetcher kwarg
    assert result.csd_path.is_file()


def test_form_builder_error_catches_all_subclasses(tmp_path):
    """FormBuilderError is the common base — catch one to catch all.

    Verified via issubclass for all three subclasses + via pytest.raises
    catching each error class through the base on a triggering path.
    """
    # Class-level: all three subclass FormBuilderError.
    from chorus_form_builder import BindingError, EmitError, SpecValidationError
    assert issubclass(SpecValidationError, FormBuilderError)
    assert issubclass(BindingError, FormBuilderError)
    assert issubclass(EmitError, FormBuilderError)

    # Runtime: a spec-error path raises something catchable as FormBuilderError.
    bad_spec = _write_form(tmp_path, """
        form:
          name: lowercase
          title: T
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(FormBuilderError):
        build_form(bad_spec, tmp_path / "out", fetcher=NoFetchFetcher())

    # Runtime: a binding-error path also raises something catchable as FormBuilderError.
    binding_spec = _write_form(tmp_path, """
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
    """, name="binding_form.yaml")
    with pytest.raises(FormBuilderError):
        build_form(binding_spec, tmp_path / "out2", fetcher=NoFetchFetcher())
