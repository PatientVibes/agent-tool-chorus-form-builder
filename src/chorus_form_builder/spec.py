"""Form-spec YAML schema and loader.

Pydantic v2 models. YAML → FormSpec is a single load_spec(path) call.
Env-var interpolation happens at fetch time, not here — load_spec
preserves ${VAR} templates verbatim.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from chorus_form_builder._types import FormBuilderError


class SpecValidationError(FormBuilderError):
    """Spec YAML invalid — bad path, bad YAML, bad shape, bad regex, ..."""


class DomainValueSpec(BaseModel):
    """A static (value, description) pair embedded in the YAML."""
    model_config = ConfigDict(extra="forbid")
    value: str
    description: str = ""


class BindingSpec(BaseModel):
    """OpenAPI endpoint binding for a combobox field.

    v0.1 scope: GET only. The Fetcher Protocol exposes a single `.get()`
    method, so allowing other verbs here would silently downgrade them
    to GET at fetch time (with the manifest then lying about what really
    happened). Constraining method to "GET" makes the spec match the
    actual behavior; non-GET support is a v0.2+ extension that needs
    Fetcher.request(method, ...).
    """
    model_config = ConfigDict(extra="forbid")
    openapi_spec: str  # path relative to the YAML file
    endpoint: str
    method: Literal["GET"] = "GET"
    values_path: str  # JSONPath into response
    value_field: str
    description_field: str = ""  # if empty, no description column
    base_url_override: Optional[str] = None  # bypasses openapi_defaults.base_url
    timeout_seconds: float = 30.0


class FieldSpec(BaseModel):
    """One field on the form."""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., pattern=r"^[A-Z][A-Z0-9]{3}$")
    label: str
    control_type: Literal["combobox", "text"]
    required: bool = False
    length: Optional[int] = None  # meaningful for text
    binding: Optional[BindingSpec] = None
    values: Optional[list[DomainValueSpec]] = None  # static domain values

    # --- v0.2 rule attributes (sub-project C) ---
    visible_when: Optional[str] = None
    enabled_when: Optional[str] = None
    required_when: Optional[str] = None
    default_when: Optional[str] = None
    default_value: Optional[Union[str, int, float, bool]] = None

    # Pydantic v2 runs model_validator(mode="after") in declaration order.
    # The order below (binding-xor → default pairing → rule-parse) is
    # intentional: cheaper checks come first, and the rule-parse depends on
    # the procedures module loading cleanly. Don't reorder without thinking.
    @model_validator(mode="after")
    def _binding_xor_values(self) -> "FieldSpec":
        # Combobox forbids BOTH being set; the "neither set" case is allowed
        # by design — the emit translator handles it as an empty domain, and
        # constructing a FieldSpec directly (bypassing load_spec) is a
        # legitimate path for defensive tests in emit.py.
        if self.control_type == "combobox":
            if self.binding is not None and self.values is not None:
                raise ValueError(
                    f"field {self.code}: combobox must have exactly one of "
                    f"'binding' (dynamic) or 'values' (static); both are set"
                )
        return self

    @model_validator(mode="after")
    def _default_when_value_paired(self) -> "FieldSpec":
        """default_when and default_value must both be set or both absent.
        Set-without-pair on either side is a spec authoring error."""
        has_when = self.default_when is not None
        has_value = self.default_value is not None
        if has_when != has_value:
            raise ValueError(
                f"field {self.code}: default_when and default_value must be "
                f"set together (got default_when={self.default_when!r}, "
                f"default_value={self.default_value!r})"
            )
        return self

    @model_validator(mode="after")
    def _rule_strings_parse(self) -> "FieldSpec":
        """Parse each non-None rule string at load_spec time.

        Catches grammar errors before any downstream code touches the rule.
        Field-reference scope validation happens at the FormSpec level
        (later, when the full set of field codes is known).

        Import is deferred to avoid a spec <-> procedures circular import.
        """
        from chorus_form_builder.procedures import parse_rule_expr
        for kind, src in (
            ("visible_when", self.visible_when),
            ("enabled_when", self.enabled_when),
            ("required_when", self.required_when),
            ("default_when", self.default_when),
        ):
            if src is None:
                continue
            try:
                parse_rule_expr(src)
            except Exception as e:
                # Re-raise with field + kind context
                raise ValueError(
                    f"field {self.code}: {kind}: {e}"
                ) from e
        return self


class FormMetaSpec(BaseModel):
    """Form-level metadata."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., pattern=r"^[A-Z][A-Z0-9_]{0,7}$")
    title: str
    type: str = "user_screen"
    pages: int = 1


class OpenAPIDefaultsSpec(BaseModel):
    """Defaults applied to every binding unless overridden per-field."""
    model_config = ConfigDict(extra="forbid")
    base_url: Optional[str] = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0


class FormSpec(BaseModel):
    """Top-level form-spec YAML schema."""
    model_config = ConfigDict(extra="forbid")
    form: FormMetaSpec
    openapi_defaults: OpenAPIDefaultsSpec = Field(default_factory=OpenAPIDefaultsSpec)
    fields: list[FieldSpec]

    @field_validator("fields")
    @classmethod
    def _at_least_one_field(cls, v: list[FieldSpec]) -> list[FieldSpec]:
        if not v:
            raise ValueError("form must have at least one field")
        return v

    @field_validator("fields")
    @classmethod
    def _unique_field_codes(cls, v: list[FieldSpec]) -> list[FieldSpec]:
        codes = [f.code for f in v]
        if len(codes) != len(set(codes)):
            seen = set()
            dupes = []
            for c in codes:
                if c in seen:
                    dupes.append(c)
                seen.add(c)
            raise ValueError(f"duplicate field code(s): {sorted(set(dupes))}")
        return v

    @model_validator(mode="after")
    def _rule_field_refs_resolve(self) -> "FormSpec":
        """Every rule's field references must resolve to a field code in this
        form. Catches typos like 'XYZQ' instead of 'STAT'."""
        from chorus_form_builder.procedures import parse_rule_expr, validate_rule
        known_codes = {f.code for f in self.fields}
        for f in self.fields:
            for kind, src in (
                ("visible_when", f.visible_when),
                ("enabled_when", f.enabled_when),
                ("required_when", f.required_when),
                ("default_when", f.default_when),
            ):
                if src is None:
                    continue
                ast = parse_rule_expr(src)  # already validated to parse in FieldSpec
                try:
                    validate_rule(ast, known_codes)
                except Exception as e:
                    raise ValueError(
                        f"field {f.code}: {kind}: {e}"
                    ) from e
        return self


def load_spec(path: Path) -> FormSpec:
    """Parse a YAML file into a validated FormSpec.

    Raises SpecValidationError on:
    - File not found / unreadable
    - YAML parse failure
    - Pydantic validation failure (with friendly path-to-field messages)
    """
    if not path.is_file():
        raise SpecValidationError(f"spec file not found: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecValidationError(f"cannot read spec file {path}: {e}") from e
    try:
        raw_dict = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise SpecValidationError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(raw_dict, dict):
        raise SpecValidationError(
            f"spec file {path} must contain a YAML mapping at the top level, "
            f"got {type(raw_dict).__name__}"
        )
    try:
        return FormSpec(**raw_dict)
    except ValidationError as e:
        # Pretty-print the path-to-field for each error
        msg_parts = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            msg_parts.append(f"  {loc}: {err['msg']}")
        raise SpecValidationError(
            f"spec validation failed for {path}:\n" + "\n".join(msg_parts)
        ) from e
