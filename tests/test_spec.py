"""Spec parsing + Pydantic validation tests."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from chorus_form_builder.spec import (
    FormSpec,
    FieldSpec,
    BindingSpec,
    DomainValueSpec,
    OpenAPIDefaultsSpec,
    load_spec,
    SpecValidationError,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def test_minimal_form_with_one_text_field_loads(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: Test Form
        fields:
          - code: TFLD
            label: Test Field
            control_type: text
            length: 30
    """)
    spec = load_spec(p)
    assert spec.form.name == "TESTFORM"
    assert spec.form.title == "Test Form"
    assert spec.form.type == "user_screen"  # default
    assert spec.form.pages == 1              # default
    assert len(spec.fields) == 1
    assert spec.fields[0].code == "TFLD"
    assert spec.fields[0].control_type == "text"
    assert spec.fields[0].length == 30


def test_form_name_rejects_lowercase(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: testform
          title: Test
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "form.name" in str(exc.value)


def test_field_code_must_be_exactly_four_chars(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: TFL, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "code" in str(exc.value).lower()


def test_combobox_with_static_values(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    spec = load_spec(p)
    assert spec.fields[0].values is not None
    assert len(spec.fields[0].values) == 2
    assert spec.fields[0].values[0].value == "A"
    assert spec.fields[0].binding is None


def test_combobox_with_binding(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: Distro
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /codes
              values_path: $.codes[0].list
              value_field: value
              description_field: description
    """)
    spec = load_spec(p)
    assert spec.fields[0].binding is not None
    assert spec.fields[0].binding.endpoint == "/codes"
    assert spec.fields[0].binding.method == "GET"  # default
    assert spec.fields[0].values is None


def test_combobox_with_both_binding_and_values_rejected(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: STAT
            label: S
            control_type: combobox
            binding:
              openapi_spec: ./x.json
              endpoint: /x
              values_path: $.x
              value_field: v
              description_field: d
            values:
              - {value: A, description: Active}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    msg = str(exc.value).lower()
    assert "binding" in msg and "values" in msg


def test_env_var_interpolation_in_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_API_TOKEN", "secret-xyz")
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
          headers:
            Authorization: "${ORACLE_API_TOKEN}"
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
    """)
    spec = load_spec(p)
    # Interpolation happens at fetch time, not load time — at load time the
    # raw template is preserved. We verify the template survived parsing.
    assert spec.openapi_defaults.headers["Authorization"] == "${ORACLE_API_TOKEN}"


def test_load_spec_missing_file_raises_clear_error(tmp_path):
    p = tmp_path / "no-such-file.yaml"
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "no-such-file.yaml" in str(exc.value)


def test_load_spec_malformed_yaml_raises_clear_error(tmp_path):
    p = _write(tmp_path, "form.yaml", "form: : : :")
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "yaml" in str(exc.value).lower()
