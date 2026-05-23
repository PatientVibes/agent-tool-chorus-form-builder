"""Regression-lock on chorus_forms' customRules + includeList API.

Sub-project C v0.1 emits a JS body into customRules and a single jsFile
reference into includeList. This test verifies those slots exist in the
chorus_forms Classic XML pipeline and that the XML chain serializes them
into the expected XML elements.

DISCOVERY (2026-05-23) — API differs from initial assumption in the plan:

The initial design assumed custom_rules and include_list are fields on
CsdForm (the IR). They are NOT. CsdForm (chorus_forms/csd/models.py) has
no such fields. The slots live downstream on ScreenDefinitionModel:

  ScreenDefinitionModel.custom_rules: str          (alias "customRules")
  ScreenDefinitionModel.include_list: list[IncludeFile]  (alias "includeList")
  IncludeFile.js_file: str                          (alias "jsFile")

(chorus_forms/models/screen.py:48-64, xml_builder.py:425-435)

The correct emit pattern for sub-project C Task 5 is therefore:
  screen_model = csd_to_user_screen(form)          # adapter
  screen_model.screen_data.custom_rules = js_body  # inject JS
  screen_model.screen_data.include_list = [IncludeFile(js_file="awdForm.js")]
  envelope = build_user_screen(screen_model)        # XML

This replaces the (impossible) plan of setting form.custom_rules directly.
CsdForm does NOT need new fields — the injection happens at the
ScreenDefinitionModel level, after adapter conversion.

CASCADE IMPACT on downstream tasks:
  Task 5 emit.py must use screen_model.screen_data.custom_rules / .include_list,
  NOT form.custom_rules / form.include_list (those attributes don't exist).

If a future chorus_forms update changes the slot names or shape, this
test fails first and signals the design needs revision before downstream
emit work lands.
"""
from __future__ import annotations

import pytest

pytest.importorskip("chorus_forms", reason="chorus_forms required for these contract tests")

from lxml import etree


def _build_minimal_form_for_rules():
    """Hand-build a minimal CsdForm (no custom_rules field — see module docstring).

    Uses snake_case field names to match the sub-project A+B canary
    (tests/test_chorus_forms_assumption.py); chorus_forms' Pydantic models
    accept both snake_case and the camelCase aliases, but staying with
    snake_case across both canary files makes the codebase consistent.
    """
    from chorus_forms.csd.models import CsdForm, FormMeta, FormField
    return CsdForm(
        meta=FormMeta(
            file_name="RULESFRM",
            form_title="Rules Test Form",
            form_type="user_screen",
            num_pages=1,
        ),
        fields=[
            FormField(code="STAT", label="Status", control_type="text"),
        ],
    )


def _build_screen_model_with_rules():
    """Convert a CsdForm to a UserScreenModel and inject customRules + includeList.

    This is the actual pattern sub-project C Task 5 must follow:
      1. csd_to_user_screen produces a UserScreenModel with a ScreenDefinitionModel
      2. screen_model.screen_data is the ScreenDefinitionModel
      3. Set .custom_rules (str) and .include_list (list[IncludeFile]) on it
      4. build_user_screen serializes both into XML
    """
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.models.screen import IncludeFile

    form = _build_minimal_form_for_rules()
    screen_model = csd_to_user_screen(form)

    screen_model.screen_data.custom_rules = (
        "(function(awdForm){ /* hello */ })(window.awdForm);"
    )
    screen_model.screen_data.include_list = [IncludeFile(js_file="awdForm.js")]
    return screen_model


def test_screen_definition_model_exposes_custom_rules_and_include_list():
    """ScreenDefinitionModel has settable custom_rules + include_list slots.

    NOTE: these slots are on ScreenDefinitionModel, not on CsdForm.
    This is the API sub-project C Task 5 must target.
    """
    screen_model = _build_screen_model_with_rules()
    assert screen_model.screen_data.custom_rules.startswith("(function(awdForm)")
    assert len(screen_model.screen_data.include_list) == 1
    assert screen_model.screen_data.include_list[0].js_file == "awdForm.js"


def test_classic_xml_chain_emits_custom_rules_element():
    """When custom_rules is set on ScreenDefinitionModel, the emitted XML
    contains a non-empty <customRules> element with the JS body."""
    from chorus_forms.core.xml_builder import build_user_screen

    screen_model = _build_screen_model_with_rules()
    envelope = build_user_screen(screen_model)
    xml = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    xml_text = xml.decode("utf-8")

    assert "<customRules>" in xml_text, f"no <customRules> in: {xml_text[:500]}"
    assert "(function(awdForm)" in xml_text, "custom_rules content didn't reach XML"
    assert "</customRules>" in xml_text


def test_classic_xml_chain_emits_include_list_with_js_file():
    """When include_list has an IncludeFile entry, the emitted XML contains
    <includeList><jsFile>awdForm.js</jsFile></includeList>."""
    from chorus_forms.core.xml_builder import build_user_screen

    screen_model = _build_screen_model_with_rules()
    envelope = build_user_screen(screen_model)
    xml = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    xml_text = xml.decode("utf-8")

    assert "<includeList>" in xml_text, f"no <includeList> in: {xml_text[:500]}"
    assert "<jsFile>awdForm.js</jsFile>" in xml_text


def test_uxb_chain_isolated_from_rules_slots():
    """UXB chain does not see custom_rules / include_list because those slots
    live on ScreenDefinitionModel (the Classic-XML adapter output), NOT on
    CsdForm (the shared IR).

    Original plan intent (pre-API-correction): prove the UXB chain doesn't
    crash when CsdForm has rules slots populated.
    Post-correction intent (this test): prove UXB is structurally isolated —
    it consumes a CsdForm that NEVER carries rules data, so there's no path
    by which sub-project C's JS injection could affect UXB output. The
    'uxb_handlers_emitted: false' manifest field in v0.1 is therefore a
    spec-level documentation flag, not enforced by a contract test (because
    there's no observable behavior to test against).
    """
    import json
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model

    form = _build_minimal_form_for_rules()
    doc = csd_to_uxb(form)
    design = to_design_model(doc, form_type=form.meta.form_type)
    dumped = design.model_dump(exclude_none=True)
    # Round-trips through json.dumps without raising
    json.dumps(dumped)
