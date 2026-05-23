"""Regression-lock on chorus_forms' builder API.

Verified against chorus_forms source 2026-05-23. The form-builder design
depends on:
1. Models importable from chorus_forms.csd.models (CsdForm, FormMeta, FormField)
2. CsdForm -> UserScreenModel via chorus_forms.csd.adapter.csd_to_user_screen
3. UserScreenModel -> etree._Element via chorus_forms.core.xml_builder.build_user_screen
4. etree -> bytes via lxml.etree.tostring
5. CsdForm -> UxbDocument via chorus_forms.uxb.builder.csd_to_uxb
6. UxbDocument -> UxbDesignModel via chorus_forms.uxb.builder.to_design_model
7. The XML round-trips through chorus_forms.core.xml_parser.parse_xml_string
   (NOTE: parse_csd_file reads BINARY .CSD files, not the XML produced by
   build_user_screen; xml_parser is the correct inverse of xml_builder.)

If any of these break, the form-builder design is wrong and needs revision.
This test lives in the repo permanently so future chorus_forms updates
that break the contract are caught immediately.

API NOTES verified 2026-05-23 (relevant to downstream emit.py in Task 4):
- control_type="select" is NOT recognised by the adapter or UXB builder
  dispatch tables; only "combobox" and "listbox" route to SelectControl /
  select-dropdown. "select" falls through to TextInputControl / text-input.
  emit.py must use control_type="combobox" (not "select") for dropdown fields.
- DictionaryInfo.domain_values keys used by the adapter are "code" / "expand"
  (not "value" / "description"). emit.py must produce {"code": ..., "expand": ...}
  dicts when writing domain_values.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("chorus_forms", reason="chorus_forms required for these contract tests")


def _build_minimal_form():
    """Construct a minimal CsdForm by hand — one combobox-style field with three
    static domain values.

    chorus_forms architecture notes (verified 2026-05-23):
    - FormField (not CsdField) is the field class.
    - FormField has NO direct domain_values attribute. Domain values live on
      DictionaryInfo and attach via FormField.dictionary.
    - DictionaryInfo.data_name is required; conventionally the same as field code.
    - DictionaryInfo.domain_values is Optional[list[dict]] — list of plain
      dicts. The adapter/UXB builder dispatch reads {"code": ..., "expand": ...}
      keys (matching what the chorus_forms parser produces from binary CSD).
    - control_type="combobox" is the value the adapter recognises for SelectControl.
      ("select" falls through to TextInputControl — see module docstring above.)
    - Models use populate_by_name=True, so both snake_case and camelCase aliases
      work at construction time.
    """
    from chorus_forms.csd.models import (
        CsdForm,
        FormMeta,
        FormField,
        DictionaryInfo,
    )
    return CsdForm(
        meta=FormMeta(
            fileName="TESTFORM",
            formTitle="Test Form",
            formType="user_screen",
            numPages=1,
        ),
        fields=[
            FormField(
                code="TFLD",
                label="Test Field",
                controlType="combobox",
                dictionary=DictionaryInfo(
                    dataName="TFLD",
                    domain_values=[
                        {"code": "A", "expand": "Alpha"},
                        {"code": "B", "expand": "Bravo"},
                        {"code": "C", "expand": "Charlie"},
                    ],
                ),
            ),
        ],
    )


def test_chorus_forms_models_import():
    """csd.models exposes CsdForm, FormMeta, FormField at the expected paths."""
    from chorus_forms.csd.models import CsdForm, FormMeta, FormField


def test_csd_to_user_screen_accepts_hand_constructed_form():
    """The adapter csd_to_user_screen takes a hand-built CsdForm and returns
    a UserScreenModel (Pydantic) — the input to the XML builder."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    form = _build_minimal_form()
    model = csd_to_user_screen(form)
    assert hasattr(model, "model_dump"), f"expected Pydantic model, got {type(model)}"


def test_build_user_screen_produces_xml_envelope():
    """build_user_screen takes the adapter output and returns an lxml element."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.core.xml_builder import build_user_screen
    from lxml import etree
    form = _build_minimal_form()
    model = csd_to_user_screen(form)
    envelope = build_user_screen(model)
    assert isinstance(envelope, etree._Element), f"expected etree._Element, got {type(envelope)}"


def test_xml_envelope_serializes_to_non_empty_bytes():
    """etree.tostring on the envelope produces deployable .csd bytes."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.core.xml_builder import build_user_screen
    from lxml import etree
    form = _build_minimal_form()
    envelope = build_user_screen(csd_to_user_screen(form))
    xml_bytes = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    assert isinstance(xml_bytes, bytes)
    assert len(xml_bytes) > 0
    assert xml_bytes.startswith(b"<?xml")


def test_csd_to_uxb_returns_document():
    """uxb.builder.csd_to_uxb takes a CsdForm and returns a UxbDocument."""
    from chorus_forms.uxb.builder import csd_to_uxb
    form = _build_minimal_form()
    doc = csd_to_uxb(form)
    assert hasattr(doc, "model_dump"), f"expected Pydantic model, got {type(doc)}"


def test_to_design_model_returns_serializable_pydantic():
    """to_design_model output exposes model_dump (Pydantic v2) for JSON serialization."""
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model
    form = _build_minimal_form()
    doc = csd_to_uxb(form)
    design = to_design_model(doc, form_type=form.meta.form_type)
    dumped = design.model_dump(exclude_none=True)
    assert isinstance(dumped, dict)
    json.dumps(dumped)


def test_xml_round_trips_through_xml_parser():
    """Built XML parses back via xml_parser with the field name present. Catches
    bugs where the builder produces output the XML parser refuses.

    NOTE: parse_csd_file (chorus_forms.csd.parser) reads BINARY .CSD files and
    cannot parse the XML output of build_user_screen. The correct round-trip is
    xml_builder -> xml_parser (chorus_forms.core.xml_parser.parse_xml_string).
    The returned model is a UserScreenModel; field names live in control.name
    across all pages, not in a CsdForm.fields list.
    """
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.core.xml_builder import build_user_screen
    from chorus_forms.core.xml_parser import parse_xml_string
    from lxml import etree

    form = _build_minimal_form()
    xml_bytes = etree.tostring(
        build_user_screen(csd_to_user_screen(form)),
        pretty_print=True, xml_declaration=True, encoding="UTF-8",
    )

    parsed = parse_xml_string(xml_bytes.decode("utf-8"))

    # Collect all control names from all pages (controls may be nested in groups)
    def _collect_names(controls):
        names = set()
        for ctrl in controls:
            if hasattr(ctrl, "name") and ctrl.name:
                names.add(ctrl.name)
            if hasattr(ctrl, "controls"):
                names.update(_collect_names(ctrl.controls))
        return names

    all_names = set()
    for page in parsed.screen_data.pages:
        all_names.update(_collect_names(page.controls))

    assert "TFLD" in all_names, f"expected TFLD in parsed control names, got {all_names}"
