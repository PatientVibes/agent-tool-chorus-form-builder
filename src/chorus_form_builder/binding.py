"""OpenAPI endpoint binding resolution.

resolve_binding(binding, openapi_root, defaults, fetcher) returns the
list of DomainValue extracted from a fetched OpenAPI endpoint response.

Fetcher Protocol so tests can inject canned responses (GoldenFetcher) and
CLI --no-fetch can short-circuit (NoFetchFetcher).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

from chorus_form_builder._types import DomainValue
from chorus_form_builder.spec import BindingSpec, OpenAPIDefaultsSpec


class BindingError(Exception):
    """OpenAPI fetch or JSONPath resolution failed."""


@dataclass
class Response:
    """Minimal HTTP-response shape returned by Fetcher implementations."""
    status_code: int
    body: Any  # parsed JSON

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise BindingError(
                f"HTTP {self.status_code} response: {json.dumps(self.body)[:300]}"
            )


class Fetcher(Protocol):
    def get(self, url: str, *, headers: dict, timeout: float) -> Response: ...


class HttpxFetcher:
    """Production fetcher — uses httpx.Client for real HTTP."""

    def get(self, url: str, *, headers: dict, timeout: float) -> Response:
        import httpx
        try:
            r = httpx.get(url, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            raise BindingError(f"HTTP error fetching {url}: {e}") from e
        try:
            body = r.json()
        except json.JSONDecodeError as e:
            raise BindingError(
                f"response from {url} is not valid JSON: {e}; status={r.status_code}"
            ) from e
        return Response(status_code=r.status_code, body=body)


class GoldenFetcher:
    """Test fetcher — returns canned responses keyed on (method, url)."""

    def __init__(self, canned: dict[tuple[str, str], Response]):
        self._canned = canned

    def get(self, url: str, *, headers: dict, timeout: float) -> Response:
        key = ("GET", url)
        if key not in self._canned:
            raise BindingError(
                f"GoldenFetcher: no canned response for GET {url}; "
                f"known keys: {sorted(self._canned.keys())}"
            )
        return self._canned[key]


class NoFetchFetcher:
    """CLI --no-fetch fetcher — errors on any GET call."""

    def get(self, url: str, *, headers: dict, timeout: float) -> Response:
        raise BindingError(
            f"--no-fetch was set but a binding requires fetching {url}; "
            f"either remove the binding or run without --no-fetch"
        )


# --- env-var interpolation ---

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def interpolate_env_vars(headers: dict[str, str]) -> dict[str, str]:
    """Substitute ${VAR} → os.environ[VAR] in every value. Raises
    BindingError naming the unset variable on first missing."""
    out: dict[str, str] = {}
    for header_name, raw_value in headers.items():
        out[header_name] = _interpolate_one(header_name, raw_value)
    return out


def _interpolate_one(header_name: str, value: str) -> str:
    def _sub(m: re.Match) -> str:
        var_name = m.group(1)
        if var_name not in os.environ:
            raise BindingError(
                f"env var {var_name!r} required by header {header_name!r} is unset"
            )
        return os.environ[var_name]
    return _ENV_VAR_RE.sub(_sub, value)


# --- main entry point ---

def resolve_binding(
    binding: BindingSpec,
    *,
    openapi_root: Path,
    defaults: OpenAPIDefaultsSpec,
    fetcher: Fetcher,
) -> list[DomainValue]:
    """Fetch the OpenAPI endpoint, apply JSONPath, map entries to DomainValue."""
    # 1. Load and parse the OpenAPI spec
    spec_path = openapi_root / binding.openapi_spec
    if not spec_path.is_file():
        raise BindingError(f"OpenAPI spec file not found: {spec_path}")
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as e:
        raise BindingError(f"cannot read OpenAPI spec {spec_path}: {e}") from e
    try:
        if spec_path.suffix.lower() in (".yaml", ".yml"):
            openapi = yaml.safe_load(text)
        else:
            openapi = json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise BindingError(f"cannot parse OpenAPI spec {spec_path}: {e}") from e

    # 2. Find the endpoint definition
    paths = openapi.get("paths") or {}
    endpoint_obj = paths.get(binding.endpoint)
    if endpoint_obj is None:
        raise BindingError(
            f"endpoint {binding.endpoint!r} not declared in OpenAPI spec "
            f"{spec_path}; known paths: {sorted(paths.keys())[:10]}"
        )
    method_obj = endpoint_obj.get(binding.method.lower())
    if method_obj is None:
        raise BindingError(
            f"endpoint {binding.endpoint!r} does not declare method "
            f"{binding.method!r} in {spec_path}"
        )

    # 3. Build the HTTP request
    base_url = binding.base_url_override or defaults.base_url
    if not base_url:
        raise BindingError(
            f"no base URL configured — set openapi_defaults.base_url or "
            f"binding.base_url_override for endpoint {binding.endpoint!r}"
        )
    url = f"{base_url.rstrip('/')}/{binding.endpoint.lstrip('/')}"

    # 4. Resolve env vars in headers and fetch
    headers = interpolate_env_vars(defaults.headers)
    timeout = binding.timeout_seconds if binding.timeout_seconds is not None else defaults.timeout_seconds
    response = fetcher.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.body

    # 5. Compile + apply the JSONPath
    try:
        path_expr = jsonpath_parse(binding.values_path)
    except JsonPathParserError as e:
        raise BindingError(
            f"invalid JSONPath {binding.values_path!r}: {e}"
        ) from e

    matches = path_expr.find(payload)
    if not matches:
        raise BindingError(
            f"JSONPath {binding.values_path!r} returned no matches against "
            f"response from {url}"
        )

    # If JSONPath uses [*] or similar, jsonpath_ng yields one match per element.
    # If it points at a single list node, that one match's .value IS the list.
    if len(matches) == 1 and isinstance(matches[0].value, list):
        extracted = matches[0].value
    else:
        extracted = [m.value for m in matches]

    if not isinstance(extracted, list):
        raise BindingError(
            f"JSONPath {binding.values_path!r} resolved to "
            f"{type(extracted).__name__}, expected list"
        )

    # 6. Map each entry to DomainValue
    result: list[DomainValue] = []
    for i, entry in enumerate(extracted):
        if not isinstance(entry, dict):
            raise BindingError(
                f"entry #{i} from JSONPath {binding.values_path!r} is "
                f"{type(entry).__name__}, expected dict"
            )
        if binding.value_field not in entry:
            raise BindingError(
                f"entry #{i}: value_field {binding.value_field!r} missing; "
                f"available keys: {sorted(entry.keys())}"
            )
        desc = ""
        if binding.description_field:
            desc = str(entry.get(binding.description_field, ""))
        result.append(DomainValue(value=str(entry[binding.value_field]), description=desc))

    return result
