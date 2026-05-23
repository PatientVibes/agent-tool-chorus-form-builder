"""CsdForm assembly + chorus_forms builder calls + file writes.

Thin assembler — does not duplicate chorus_forms logic. The translator
function is the single seam between our FormSpec/FieldSpec and
chorus_forms' CsdForm/FormField shapes.

API notes (verified 2026-05-23 via test_chorus_forms_assumption.py):
- FormField.control_type takes "combobox" verbatim (not "select").
- DictionaryInfo.domain_values uses dicts with {"code", "expand"} keys.
- Models live at chorus_forms.csd.models.
"""
from __future__ import annotations

import json
from pathlib import Path

from chorus_form_builder._types import DomainValue, EmitResult, FormBuilderError
from chorus_form_builder.manifest import build_manifest
from chorus_form_builder.procedures import compile_rules
from chorus_form_builder.spec import FieldSpec, FormSpec


class EmitError(FormBuilderError):
    """chorus_forms builder rejected the constructed form, or file write failed."""


def _spec_field_to_form_field(spec_field: FieldSpec, resolved_domain: list[DomainValue] | None):
    """Translate a FieldSpec → chorus_forms.csd.models.FormField.

    Domain-value precedence:
        1. resolved_domain (from a binding fetch)
        2. spec_field.values (static — declared inline in YAML)
        3. [] (empty — defensive default for combobox with neither)

    Verified-real chorus_forms API:
    - control_type stays "combobox" verbatim (chorus_forms dispatch keys on
      "combobox"/"listbox"; "select" silently falls through to text-input).
    - Domain values use {"code", "expand"} keys (per adapter.py:267 +
      uxb/builder.py:268), not {"value", "description"}.
    - Length and domain_values both live on DictionaryInfo, attached via
      FormField.dictionary.
    """
    if resolved_domain is not None:
        domain_source = resolved_domain
    elif spec_field.values is not None:
        domain_source = [DomainValue(value=v.value, description=v.description) for v in spec_field.values]
    else:
        domain_source = []

    from chorus_forms.csd.models import FormField, DictionaryInfo

    dictionary = None
    if domain_source or spec_field.length is not None:
        dictionary = DictionaryInfo(
            data_name=spec_field.code,  # required; convention: same as field code
            length=spec_field.length,
            domain_values=[
                {"code": d.value, "expand": d.description}
                for d in domain_source
            ] if domain_source else None,
        )

    return FormField(
        code=spec_field.code,
        label=spec_field.label,
        control_type=spec_field.control_type,  # "combobox" or "text" verbatim
        required=spec_field.required,
        dictionary=dictionary,
    )


def emit(
    spec: FormSpec,
    resolved_bindings: dict[str, list[DomainValue]],
    output_dir: Path,
) -> EmitResult:
    """Assemble a chorus_forms CsdForm from the spec + resolved bindings,
    compile any procedure rules into customRules + includeList, drive the
    Classic XML and UXB JSON chains, write the three artifacts (and the
    awdForm.js shim alongside if any rules were emitted).

    Classic XML chain:
        CsdForm → csd_to_user_screen → UserScreenModel(.screen_data: ScreenDefinitionModel)
                                                       ^^ rules slots live here
                → build_user_screen   → lxml etree element
                → etree.tostring       → bytes (xml_declaration + UTF-8)

    UXB JSON chain:
        CsdForm → csd_to_uxb        → UxbDocument
                → to_design_model    → UxbDesignModel (Pydantic)
                → .model_dump(...)   → dict → json.dumps

    Sub-project C v0.1 API note (verified via Task 0 canary at
    tests/test_chorus_forms_rules_assumption.py): custom_rules and
    include_list are NOT on CsdForm. They live on ScreenDefinitionModel,
    one level downstream. We inject them between adapter and builder.
    """
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.csd.models import CsdForm, FormMeta
    from chorus_forms.core.xml_builder import build_user_screen
    from chorus_forms.models.screen import IncludeFile
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model
    from lxml import etree

    # ----- compile procedure rules (pure, no I/O) -----
    compiled = compile_rules(spec.fields)

    # ----- assemble the chorus_forms CsdForm (no rule slots — those live downstream) -----
    try:
        form = CsdForm(
            meta=FormMeta(
                file_name=spec.form.name,
                form_title=spec.form.title,
                form_type=spec.form.type,
                num_pages=spec.form.pages,
            ),
            fields=[
                _spec_field_to_form_field(f, resolved_bindings.get(f.code))
                for f in spec.fields
            ],
        )
    except Exception as e:
        raise EmitError(f"failed to construct chorus_forms.csd.models.CsdForm from spec: {e}") from e

    # ----- Classic XML chain — inject rules at ScreenDefinitionModel level -----
    try:
        user_screen_model = csd_to_user_screen(form)

        # Inject custom_rules + include_list AFTER adapter, BEFORE builder.
        # The plan's original "CsdForm(custom_rules=..., include_list=...)"
        # approach doesn't work — see Task 0 canary for the discovery.
        if compiled.custom_rules_js:
            user_screen_model.screen_data.custom_rules = compiled.custom_rules_js
        if compiled.include_list:
            user_screen_model.screen_data.include_list = [
                IncludeFile(js_file=entry["js_file"])
                for entry in compiled.include_list
            ]

        envelope = build_user_screen(user_screen_model)
        csd_bytes = etree.tostring(
            envelope,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
    except Exception as e:
        raise EmitError(f"Classic XML chain failed: {e}") from e

    # ----- UXB JSON chain (unchanged; UXB output is handler-less in v0.1) -----
    try:
        uxb_doc = csd_to_uxb(form)
        uxb_model = to_design_model(uxb_doc, form_type=form.meta.form_type)
        uxb_dict = uxb_model.model_dump(exclude_none=True)
    except Exception as e:
        raise EmitError(f"UXB JSON chain failed: {e}") from e

    output_dir.mkdir(parents=True, exist_ok=True)
    csd_path = output_dir / f"{spec.form.name}.csd"
    uxb_path = output_dir / f"{spec.form.name}.uxb.json"
    manifest_path = output_dir / f"{spec.form.name}_manifest.json"

    csd_path.write_bytes(csd_bytes)
    uxb_path.write_text(json.dumps(uxb_dict, indent=2), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            build_manifest(spec, resolved_bindings, rule_summary=compiled.rule_summary),
            indent=2,
        ),
        encoding="utf-8",
    )

    # ----- ship awdForm.js alongside the .csd ONLY when rules were emitted -----
    if compiled.custom_rules_js:
        shim_src = Path(__file__).resolve().parent / "runtime" / "awdForm.js"
        (output_dir / "awdForm.js").write_bytes(shim_src.read_bytes())

    return EmitResult(csd_path=csd_path, uxb_path=uxb_path, manifest_path=manifest_path)
