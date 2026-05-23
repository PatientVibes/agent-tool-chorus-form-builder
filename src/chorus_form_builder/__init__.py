"""chorus-form-builder — generate Chorus forms from declarative YAML.

Public API:
    build_form(spec_path, output_dir, *, fetcher=None) -> EmitResult

Exceptions:
    FormBuilderError (base)
    SpecValidationError
    BindingError
    EmitError
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from chorus_form_builder._types import DomainValue, EmitResult, FormBuilderError
from chorus_form_builder.binding import BindingError, Fetcher, HttpxFetcher, NoFetchFetcher, resolve_binding
from chorus_form_builder.emit import EmitError, emit
from chorus_form_builder.spec import SpecValidationError, load_spec

__version__ = "0.1.0"


def build_form(
    spec_path: Path,
    output_dir: Path,
    *,
    fetcher: Optional[Fetcher] = None,
) -> EmitResult:
    """Generate a Chorus form from a YAML spec.

    Args:
        spec_path: Path to the form-spec YAML.
        output_dir: Directory to write {form_name}.csd, {form_name}.uxb.json,
                    {form_name}_manifest.json into. Created if missing.
        fetcher: Optional Fetcher implementation for OpenAPI binding
                 resolution. Defaults to HttpxFetcher (real HTTP).
                 Tests inject GoldenFetcher; CLI --no-fetch injects
                 NoFetchFetcher.

    Returns:
        EmitResult with the three written paths.

    Raises:
        SpecValidationError: spec YAML is invalid (bad path, bad YAML, bad shape)
        BindingError: OpenAPI fetch or JSONPath resolution failed
        EmitError: chorus_forms builder rejected the constructed form
    """
    if fetcher is None:
        fetcher = HttpxFetcher()

    spec = load_spec(spec_path)
    openapi_root = spec_path.parent

    resolved_bindings: dict[str, list[DomainValue]] = {}
    for field in spec.fields:
        if field.binding is not None:
            resolved_bindings[field.code] = resolve_binding(
                field.binding,
                openapi_root=openapi_root,
                defaults=spec.openapi_defaults,
                fetcher=fetcher,
            )

    return emit(spec, resolved_bindings=resolved_bindings, output_dir=output_dir)


__all__ = [
    "build_form",
    "DomainValue",
    "EmitResult",
    "FormBuilderError",
    "SpecValidationError",
    "BindingError",
    "EmitError",
    "Fetcher",
    "HttpxFetcher",
    "NoFetchFetcher",
]
