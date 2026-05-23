"""emit.py tests — translator + chorus_forms builder wrapping + round-trip.

The translator + emitter wrap the verified-real chorus_forms API:
- FormField.control_type stays "combobox" (chorus_forms's adapter dispatch keys
  on "combobox"/"listbox"; "select" silently falls through to text-input).
- DictionaryInfo.domain_values entries use {"code", "expand"} keys, not
  {"value", "description"} — verified against adapter.py:267 + uxb/builder.py:268.
- Round-trip parsing uses chorus_forms.core.xml_parser.parse_xml_string (the
  emitted .csd is XML, not the legacy binary CSD format), returns a
  UserScreenModel whose field names live in pages[*].controls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chorus_forms", reason="chorus_forms required")

from chorus_form_builder._types import DomainValue
from chorus_form_builder.emit import (
    EmitError,
    _spec_field_to_form_field,
    emit,
)
from chorus_form_builder.spec import (
    BindingSpec,
    DomainValueSpec,
    FieldSpec,
    FormMetaSpec,
    FormSpec,
    OpenAPIDefaultsSpec,
)


def _form_spec_one_text_field() -> FormSpec:
    return FormSpec(
        form=FormMetaSpec(name="TESTFORM", title="Test"),
        openapi_defaults=OpenAPIDefaultsSpec(),
        fields=[
            FieldSpec(code="MEMO", label="Memo", control_type="text", length=60),
        ],
    )


def _form_spec_static_combo() -> FormSpec:
    return FormSpec(
        form=FormMetaSpec(name="STATCOMB", title="Static"),
        openapi_defaults=OpenAPIDefaultsSpec(),
        fields=[
            FieldSpec(
                code="STAT",
                label="Status",
                control_type="combobox",
                values=[
                    DomainValueSpec(value="A", description="Active"),
                    DomainValueSpec(value="I", description="Inactive"),
                ],
            ),
        ],
    )


def _collect_control_names(user_screen_model) -> set[str]:
    """Walk pages[*].controls recursively, collecting every control's name.

    UserScreenModel structure (verified in test_chorus_forms_assumption.py):
        screen_data.pages -> list[Page]
        Page.controls -> list[Control], some Controls have nested .controls
    """
    names: set[str] = set()

    def _walk(controls):
        for ctrl in controls:
            name = getattr(ctrl, "name", None)
            if name:
                names.add(name)
            children = getattr(ctrl, "controls", None) or []
            _walk(children)

    for page in user_screen_model.screen_data.pages:
        _walk(page.controls)
    return names


# --- translator unit tests ---

def test_translator_text_field():
    spec_field = FieldSpec(code="MEMO", label="Memo", control_type="text", length=60)
    ff = _spec_field_to_form_field(spec_field, resolved_domain=None)
    assert ff.code == "MEMO"
    assert ff.label == "Memo"
    assert ff.control_type == "text"
    # length lives on DictionaryInfo. The translator attaches a dictionary
    # when length OR domain_values is set.
    assert ff.dictionary is not None
    assert ff.dictionary.length == 60
    assert ff.dictionary.domain_values is None


def test_translator_combobox_with_resolved_binding():
    spec_field = FieldSpec(code="DCMB", label="Distro", control_type="combobox")
    resolved = [DomainValue(value="X", description="X-desc"), DomainValue(value="Y", description="Y-desc")]
    ff = _spec_field_to_form_field(spec_field, resolved_domain=resolved)
    # control_type stays "combobox" verbatim — chorus_forms's adapter dispatch
    # keys on "combobox"/"listbox", not "select".
    assert ff.control_type == "combobox"
    assert ff.dictionary is not None
    assert ff.dictionary.domain_values is not None
    assert len(ff.dictionary.domain_values) == 2
    # Domain values use {"code", "expand"} keys — verified against
    # chorus_forms/csd/adapter.py:267.
    assert ff.dictionary.domain_values[0]["code"] == "X"
    assert ff.dictionary.domain_values[0]["expand"] == "X-desc"


def test_translator_combobox_with_static_values_and_no_resolved():
    spec_field = FieldSpec(
        code="STAT",
        label="Status",
        control_type="combobox",
        values=[DomainValueSpec(value="A", description="Active")],
    )
    ff = _spec_field_to_form_field(spec_field, resolved_domain=None)
    assert ff.control_type == "combobox"
    assert ff.dictionary is not None
    assert len(ff.dictionary.domain_values) == 1
    assert ff.dictionary.domain_values[0]["code"] == "A"
    assert ff.dictionary.domain_values[0]["expand"] == "Active"


def test_translator_combobox_no_domain_at_all():
    """Combobox with neither binding nor values AND no length set — produces a
    FormField with dictionary=None. The DictionaryInfo attachment only fires
    when domain_source is non-empty OR length is set; this spec has neither.
    Direct FieldSpec construction is the path that hits this; load_spec allows
    it (the schema-level validator only blocks BOTH-set; see
    spec.py:_binding_xor_values)."""
    spec_field = FieldSpec(code="STAT", label="S", control_type="combobox")
    ff = _spec_field_to_form_field(spec_field, resolved_domain=None)
    assert ff.dictionary is None


# --- emit end-to-end ---

def test_emit_writes_three_files_for_text_only_form(tmp_path):
    spec = _form_spec_one_text_field()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    assert result.csd_path.is_file()
    assert result.uxb_path.is_file()
    assert result.manifest_path.is_file()
    assert result.csd_path.name == "TESTFORM.csd"
    assert result.uxb_path.name == "TESTFORM.uxb.json"
    assert result.manifest_path.name == "TESTFORM_manifest.json"


def test_emit_writes_non_empty_csd(tmp_path):
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    assert result.csd_path.stat().st_size > 0


def test_emit_uxb_json_is_valid_json(tmp_path):
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    data = json.loads(result.uxb_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_emit_round_trips_through_xml_parser(tmp_path):
    """Built .csd round-trips through chorus_forms.core.xml_parser.parse_xml_string;
    the static combo field's name shows up in the parsed control tree.

    NOTE: parse_xml_string takes a str (decoded XML), not raw bytes.
    """
    from chorus_forms.core.xml_parser import parse_xml_string

    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    parsed = parse_xml_string(result.csd_path.read_text(encoding="utf-8"))
    names = _collect_control_names(parsed)
    assert "STAT" in names, f"expected STAT in {names}"


def test_emit_uses_resolved_binding_over_static_values(tmp_path):
    """If a binding-bound combobox has resolved values, the XML carries those
    resolved values. We assert via substring on the emitted XML to avoid
    coupling to UserScreenModel's internal domain-value representation."""
    spec = FormSpec(
        form=FormMetaSpec(name="BNDFORM", title="Bound"),
        fields=[
            FieldSpec(
                code="DCMB",
                label="Distro",
                control_type="combobox",
                binding=BindingSpec(
                    openapi_spec="./oracle.json",
                    endpoint="/codes",
                    values_path="$.x",
                    value_field="value",
                ),
            ),
        ],
    )
    resolved = {"DCMB": [DomainValue(value="X-FROM-BINDING", description="From binding")]}
    result = emit(spec, resolved_bindings=resolved, output_dir=tmp_path)

    csd_text = result.csd_path.read_text(encoding="utf-8")
    # The resolved value flows through DictionaryInfo.domain_values into the
    # XML. Substring check avoids coupling to the exact element name.
    assert "X-FROM-BINDING" in csd_text, \
        f"expected resolved binding value 'X-FROM-BINDING' in emitted XML; got:\n{csd_text[:500]}"


def test_emit_creates_output_dir_if_missing(tmp_path):
    spec = _form_spec_one_text_field()
    missing_dir = tmp_path / "deep" / "nested" / "dir"
    result = emit(spec, resolved_bindings={}, output_dir=missing_dir)
    assert missing_dir.is_dir()
    assert result.csd_path.is_file()


# --- sub-project C: emit pipeline integration ---

from chorus_form_builder.spec import DomainValueSpec  # already imported but explicit for clarity


def _form_spec_with_visibility_rule() -> FormSpec:
    return FormSpec(
        form=FormMetaSpec(name="RULEFORM", title="Rule Form"),
        openapi_defaults=OpenAPIDefaultsSpec(),
        fields=[
            FieldSpec(code="STAT", label="Status", control_type="combobox",
                      values=[DomainValueSpec(value="A", description="Active"),
                              DomainValueSpec(value="R", description="Rejected")]),
            FieldSpec(code="MEMO", label="Memo", control_type="text", length=60,
                      visible_when='STAT == "R"'),
        ],
    )


def test_emit_rule_free_form_emits_no_custom_rules(tmp_path):
    """A form with no rules: emitted .csd has empty/no <customRules>, no jsFile
    in <includeList>, and no awdForm.js next to the .csd."""
    spec = _form_spec_static_combo()  # the existing rule-free fixture
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    xml = result.csd_path.read_text(encoding="utf-8")
    assert "<jsFile>awdForm.js</jsFile>" not in xml
    assert not (tmp_path / "awdForm.js").exists(), "shim should not be copied for rule-free forms"


def test_emit_rule_bearing_form_attaches_js_and_include(tmp_path):
    spec = _form_spec_with_visibility_rule()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    xml = result.csd_path.read_text(encoding="utf-8")
    assert "<customRules>" in xml
    assert "(function(awdForm)" in xml
    assert 'awdForm.on(&quot;field-change:STAT&quot;, applyAll);' in xml or \
           'awdForm.on("field-change:STAT", applyAll);' in xml
    assert "<jsFile>awdForm.js</jsFile>" in xml
    assert (tmp_path / "awdForm.js").is_file()
    # And the shipped shim should be the same as the package-data file
    shim_src = Path(__file__).resolve().parent.parent / "src" / "chorus_form_builder" / "runtime" / "awdForm.js"
    assert (tmp_path / "awdForm.js").read_bytes() == shim_src.read_bytes()


def test_emit_manifest_includes_new_fields(tmp_path):
    spec = _form_spec_with_visibility_rule()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    # New fields all present
    assert manifest["uxb_handlers_emitted"] is False
    assert manifest["runtime_validated"] is False
    assert manifest["shim_version"] == "0.1.0"
    assert isinstance(manifest["rules"], list)
    assert any(r["field_code"] == "MEMO" and r["kind"] == "visible_when" for r in manifest["rules"])


def test_emit_manifest_empty_rules_when_no_rules(tmp_path):
    """Rule-free form -> rules: [] in manifest; uxb_handlers_emitted still false."""
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rules"] == []
    assert manifest["uxb_handlers_emitted"] is False
    assert manifest["runtime_validated"] is False
