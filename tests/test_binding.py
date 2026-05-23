"""Binding resolution tests — JSONPath + env-var interpolation + fetcher abstraction."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from chorus_form_builder._types import DomainValue
from chorus_form_builder.binding import (
    BindingError,
    GoldenFetcher,
    NoFetchFetcher,
    Response,
    interpolate_env_vars,
    resolve_binding,
)
from chorus_form_builder.spec import BindingSpec, OpenAPIDefaultsSpec


def _write_openapi(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "oracle.json"
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


def _minimal_openapi_with_endpoint() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": {
            "/codes": {
                "get": {
                    "responses": {"200": {"description": "ok"}}
                }
            }
        },
    }


# --- env-var interpolation ---

def test_interpolate_env_vars_substitutes_set_vars(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "abc-123")
    out = interpolate_env_vars({"Authorization": "Bearer ${MY_TOKEN}"})
    assert out == {"Authorization": "Bearer abc-123"}


def test_interpolate_env_vars_raises_on_unset(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(BindingError) as exc:
        interpolate_env_vars({"X": "${MISSING_VAR}"})
    assert "MISSING_VAR" in str(exc.value)


def test_interpolate_env_vars_passes_through_no_template():
    out = interpolate_env_vars({"Content-Type": "application/json"})
    assert out == {"Content-Type": "application/json"}


# --- resolve_binding happy path ---

def test_resolve_binding_extracts_simple_list(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
        description_field="description",
    )
    canned_response = {"items": [{"value": "A", "description": "Alpha"}, {"value": "B", "description": "Bravo"}]}
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(200, canned_response)})

    result = resolve_binding(
        binding,
        openapi_root=tmp_path,
        defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
        fetcher=fetcher,
    )

    assert result == [
        DomainValue(value="A", description="Alpha"),
        DomainValue(value="B", description="Bravo"),
    ]


def test_resolve_binding_uses_default_description_when_field_missing(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
        description_field="description",
    )
    canned_response = {"items": [{"value": "X"}]}  # no description field
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(200, canned_response)})

    result = resolve_binding(
        binding,
        openapi_root=tmp_path,
        defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
        fetcher=fetcher,
    )
    assert result == [DomainValue(value="X", description="")]


# --- resolve_binding error cases ---

def test_resolve_binding_endpoint_not_in_spec(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/MISSING",  # not in the openapi
        values_path="$.items[*]",
        value_field="value",
    )
    fetcher = GoldenFetcher({})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    assert "/MISSING" in str(exc.value)


def test_resolve_binding_http_4xx_fails_loudly(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
    )
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(401, {"error": "unauthorized"})})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    assert "401" in str(exc.value)


def test_resolve_binding_jsonpath_no_match(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
    )
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(200, {"other": "shape"})})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    assert "$.items[*]" in str(exc.value)


def test_resolve_binding_jsonpath_returns_non_list(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.scalar",
        value_field="value",
    )
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(200, {"scalar": "single-string"})})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    assert "expected" in str(exc.value).lower() or "list" in str(exc.value).lower()


def test_resolve_binding_value_field_missing_in_entry(tmp_path):
    _write_openapi(tmp_path, _minimal_openapi_with_endpoint())
    binding = BindingSpec(
        openapi_spec="./oracle.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
    )
    fetcher = GoldenFetcher({("GET", "https://example.com/api/codes"): Response(200, {"items": [{"name": "no-value"}]})})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    msg = str(exc.value)
    assert "value_field" in msg or "'value'" in msg


def test_resolve_binding_openapi_file_not_found(tmp_path):
    binding = BindingSpec(
        openapi_spec="./does-not-exist.json",
        endpoint="/codes",
        values_path="$.items[*]",
        value_field="value",
    )
    fetcher = GoldenFetcher({})

    with pytest.raises(BindingError) as exc:
        resolve_binding(
            binding,
            openapi_root=tmp_path,
            defaults=OpenAPIDefaultsSpec(base_url="https://example.com/api"),
            fetcher=fetcher,
        )
    assert "does-not-exist.json" in str(exc.value)


# --- NoFetchFetcher (CLI --no-fetch flag) ---

def test_no_fetch_fetcher_errors_on_get(tmp_path):
    fetcher = NoFetchFetcher()
    with pytest.raises(BindingError) as exc:
        fetcher.get("https://anywhere/anything", headers={}, timeout=30.0)
    assert "--no-fetch" in str(exc.value)
