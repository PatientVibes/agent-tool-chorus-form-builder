"""Form-spec YAML schema and loader.

Pydantic v2 models. YAML → FormSpec is a single load_spec(path) call.
Env-var interpolation happens at fetch time, not here — load_spec
preserves ${VAR} templates verbatim.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

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
    """OpenAPI endpoint binding for a combobox field."""
    model_config = ConfigDict(extra="forbid")
    openapi_spec: str  # path relative to the YAML file
    endpoint: str
    method: str = "GET"
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
