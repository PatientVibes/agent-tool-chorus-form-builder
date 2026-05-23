"""Provenance manifest — JSON describing what produced an emitted form."""
from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any

from chorus_form_builder._types import DomainValue
from chorus_form_builder.spec import FormSpec

_GENERATOR_NAME = "chorus-form-builder"
_GENERATOR_VERSION = "0.1.0"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def build_manifest(spec: FormSpec, resolved_bindings: dict[str, list[DomainValue]]) -> dict[str, Any]:
    """Construct the provenance JSON shape."""
    bindings_records = []
    for field in spec.fields:
        if field.binding is None:
            continue
        domain_count = len(resolved_bindings.get(field.code, []))
        bindings_records.append({
            "field_code": field.code,
            "openapi_spec_path": field.binding.openapi_spec,
            "endpoint": field.binding.endpoint,
            "method": field.binding.method,
            "values_path": field.binding.values_path,
            "fetched_at": _now_iso(),
            "value_count": domain_count,
        })

    return {
        "generator": _GENERATOR_NAME,
        "generator_version": _GENERATOR_VERSION,
        "generated_at": _now_iso(),
        "form": {
            "name": spec.form.name,
            "title": spec.form.title,
            "field_count": len(spec.fields),
        },
        "bindings": bindings_records,
    }
