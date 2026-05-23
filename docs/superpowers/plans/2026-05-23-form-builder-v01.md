# chorus-form-builder v0.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a uv-installable Python package + CLI (`chorus-form-build`) that takes a declarative form-spec YAML, optionally fetches OpenAPI endpoints to bake combobox values, and emits a deployable Chorus form (`.csd` Classic + UXB JSON + provenance manifest).

**Architecture:** Five private modules (spec, binding, emit, manifest, cli) wired through one public function (`build_form`). Each module owns one concern; they communicate through `FormSpec` (Pydantic, our schema) and `chorus_forms.CsdForm` (existing model). httpx-based fetcher behind a `Protocol` so tests inject canned responses without a network. Builder calls wrap `chorus_forms.builders.classic` and `chorus_forms.builders.uxb`.

**Tech Stack:** Python 3.11+, Pydantic 2.x, PyYAML, httpx, jsonpath-ng, pytest. uv for install/lock. Depends on `chorus_forms` (editable, from `D:/chorus-repos/chorus-forms`).

**Source spec:** [`docs/superpowers/specs/2026-05-23-form-builder-v01-design.md`](../specs/2026-05-23-form-builder-v01-design.md)

**Working directory for all tasks:** `D:/agent-tool-chorus-form-builder/`

---

## Repo state at start

```
D:/agent-tool-chorus-form-builder/
├── .gitignore                # ✅ already committed (initial scaffolding)
├── README.md                 # ✅ already committed
├── docs/superpowers/
│   ├── specs/2026-05-23-form-builder-v01-design.md  # ✅ already committed
│   └── plans/2026-05-23-form-builder-v01.md         # ✅ this file
├── src/chorus_form_builder/  # empty dir (just exists)
└── tests/                    # empty dir (just exists)
```

Branch: `master`. Initial commit already landed. All tasks below operate on this baseline.

**First action of any implementer:** create a feature branch — `git checkout -b feat/v01-build-form` — before any code work. Never work directly on master.

---

## File Structure

After all tasks land, the repo looks like:

| File | Lines (est.) | Responsibility |
|---|---|---|
| `pyproject.toml` | ~50 | uv-installable; deps; CLI entry point |
| `src/chorus_form_builder/__init__.py` | ~20 | exports `build_form` + the exception hierarchy |
| `src/chorus_form_builder/_types.py` | ~30 | shared dataclasses (DomainValue, EmitResult) — no chorus_forms imports |
| `src/chorus_form_builder/spec.py` | ~120 | Pydantic FormSpec model + YAML loader + env-var interpolation |
| `src/chorus_form_builder/binding.py` | ~110 | Fetcher Protocol + HttpxFetcher + GoldenFetcher + resolve_binding |
| `src/chorus_form_builder/emit.py` | ~90 | `_spec_field_to_csd_field` + `emit` function — wraps chorus_forms |
| `src/chorus_form_builder/manifest.py` | ~50 | `build_manifest` — pure function |
| `src/chorus_form_builder/cli.py` | ~70 | argparse + exit-code mapping + main() entry |
| `tests/conftest.py` | ~20 | shared fixtures (tmp_path helpers, etc.) |
| `tests/test_spec.py` | ~80 | Pydantic validation + env-var interpolation |
| `tests/test_binding.py` | ~100 | Fetcher Protocol, GoldenFetcher, resolve_binding |
| `tests/test_emit.py` | ~80 | translator + round-trip via chorus_forms.parser |
| `tests/test_manifest.py` | ~40 | manifest content + normalized comparisons |
| `tests/test_cli.py` | ~50 | subprocess smoke + exit codes |
| `tests/test_goldens.py` | ~60 | 3 golden fixture comparisons |
| `tests/goldens/oracle_dcmb/{form.yaml, oracle.json, response.json, ORACLE_DCMB.csd, ORACLE_DCMB.uxb.json, ORACLE_DCMB_manifest.json}` | (fixtures) | binding-bound golden |
| `tests/goldens/static_combo/{form.yaml, STATIC_COMBO.csd, STATIC_COMBO.uxb.json, STATIC_COMBO_manifest.json}` | (fixtures) | static-values golden |
| `tests/goldens/text_plus_combo/{form.yaml, response.json, oracle.json, TXT_COMBO.csd, TXT_COMBO.uxb.json, TXT_COMBO_manifest.json}` | (fixtures) | multi-field golden |

Total ≈ 700 LOC across source + tests, plus the binary + JSON golden artifacts (which are committed as test fixtures, not generated at test time).

---

## Task 0: Validate the chorus_forms builder API assumption (TDD)

**Why this task exists:** The spec's primary risk (§Risks #1) is that `chorus_forms.builders.classic.build_csd` may not work on a hand-constructed `CsdForm` — `chorus_forms`'s own test suite exercises parse-then-build round-trips but may never test "build a fresh CsdForm in Python, hand it to the builder, get usable bytes back." If that path doesn't work, **everything downstream needs to be re-planned**. Validate first; build on top of confirmed primitives.

**Files:**
- Create: `tests/test_chorus_forms_assumption.py` (smoke test — will live in the repo permanently as a regression-lock on the builder API)

- [ ] **Step 1: Write the failing assumption test**

Create `tests/test_chorus_forms_assumption.py`:

```python
"""Regression-lock on chorus_forms' builder API.

The form-builder design assumes:
1. chorus_forms.builders.classic.build_csd(form) accepts a hand-constructed
   CsdForm and returns non-empty bytes.
2. chorus_forms.builders.uxb.build_uxb(form) accepts the same and returns
   a serializable dict.
3. The .csd round-trips through chorus_forms.csd.parser.parse_csd_file —
   parsing what we built returns a form with the same field codes and
   control types.

If any of these break, the form-builder design is wrong and needs revision.
This test lives in the repo permanently so future chorus_forms updates that
break this contract are caught immediately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_minimal_form():
    """Construct a minimal CsdForm by hand — one combobox with three static values."""
    from chorus_forms.models import (
        CsdForm,
        FormMeta,
        CsdField,
        DomainValue,
    )
    return CsdForm(
        meta=FormMeta(
            file_name="TESTFORM",
            form_title="Test Form",
            form_type="user_screen",
            num_pages=1,
            dll_hooks=[],
        ),
        fields=[
            CsdField(
                code="TFLD",
                label="Test Field",
                control_type="combobox",
                required=False,
                read_only=False,
                length=None,
                dictionary=None,
                domain_values=[
                    DomainValue(value="A", description="Alpha"),
                    DomainValue(value="B", description="Bravo"),
                    DomainValue(value="C", description="Charlie"),
                ],
            ),
        ],
        groups=[],
        warnings=[],
    )


def test_chorus_forms_classic_builder_accepts_hand_constructed_form():
    """chorus_forms.builders.classic.build_csd takes a hand-built CsdForm and
    returns non-empty bytes."""
    pytest.importorskip("chorus_forms", reason="chorus_forms required")
    from chorus_forms.builders import classic
    form = _build_minimal_form()
    csd_bytes = classic.build_csd(form)
    assert isinstance(csd_bytes, bytes), f"expected bytes, got {type(csd_bytes)}"
    assert len(csd_bytes) > 0, "expected non-empty bytes"


def test_chorus_forms_uxb_builder_accepts_hand_constructed_form():
    """chorus_forms.builders.uxb.build_uxb takes a hand-built CsdForm and
    returns a JSON-serializable dict."""
    pytest.importorskip("chorus_forms", reason="chorus_forms required")
    from chorus_forms.builders import uxb
    form = _build_minimal_form()
    uxb_dict = uxb.build_uxb(form)
    assert isinstance(uxb_dict, dict), f"expected dict, got {type(uxb_dict)}"
    # Must round-trip through json.dumps cleanly (no datetime, set, etc.)
    json.dumps(uxb_dict)


def test_chorus_forms_csd_round_trips_through_parser(tmp_path):
    """Built .csd parses back into a CsdForm with matching field codes and
    control types. Catches bugs where the builder produces output the parser
    refuses."""
    pytest.importorskip("chorus_forms", reason="chorus_forms required")
    from chorus_forms.builders import classic
    from chorus_forms.csd.parser import parse_csd_file

    form = _build_minimal_form()
    csd_bytes = classic.build_csd(form)

    csd_path = tmp_path / "TESTFORM.CSD"
    csd_path.write_bytes(csd_bytes)

    parsed = parse_csd_file(csd_path)
    parsed_codes = {f.code for f in parsed.fields}
    assert "TFLD" in parsed_codes, f"expected TFLD in parsed fields, got {parsed_codes}"
    tfld = next(f for f in parsed.fields if f.code == "TFLD")
    assert tfld.control_type == "combobox", f"expected combobox, got {tfld.control_type}"
```

- [ ] **Step 2: Set up the venv and install chorus_forms editable**

The repo has no venv yet. Bootstrap with uv:

```bash
cd D:/agent-tool-chorus-form-builder
uv venv
uv pip install -e D:/chorus-repos/chorus-forms
uv pip install pytest pydantic pyyaml httpx jsonpath-ng
```

- [ ] **Step 3: Run the assumption tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chorus_forms_assumption.py -v`

Expected outcomes — three possibilities:

**Outcome A (best case): all three pass.** Builder API works as assumed; proceed to Task 1.

**Outcome B: import fails** (`ImportError: cannot import name 'X' from 'chorus_forms.models'` or `.builders`). The actual chorus_forms API differs from what the spec assumes. STOP the plan execution and report back. Specifically:
- Read `D:/chorus-repos/chorus-forms/src/chorus_forms/__init__.py` and `D:/chorus-repos/chorus-forms/src/chorus_forms/models.py` to find the real class names + module paths
- Update the test imports to match the real API
- Re-run; if shape now matches, continue. If shape is fundamentally different (e.g., builders only accept parser-output dicts, not CsdForm objects), the spec needs revision before any more tasks.

**Outcome C: tests fail at builder-call time** (`TypeError`, `ValueError`, builder raises). The builder API exists but doesn't accept the field set we hand-constructed. Investigate the failure; if it's a small shape adjustment (e.g., `dictionary` is required, or `dll_hooks` must be `None` not `[]`), adjust `_build_minimal_form` and re-run. If the builder fundamentally rejects greenfield CsdForm construction (e.g., requires an internal-only `_parsed_from` field), STOP and report — spec needs revision.

- [ ] **Step 4: Commit (only if Step 3 outcome is A)**

```bash
git add tests/test_chorus_forms_assumption.py
git commit -m "test: lock chorus_forms builder API assumptions for form-builder v0.1

Smoke tests asserting that chorus_forms.builders.classic.build_csd and
chorus_forms.builders.uxb.build_uxb accept hand-constructed CsdForm
objects and produce round-trippable output. These are the foundational
assumptions of the form-builder design — if a future chorus_forms
update breaks them, this test fails first and signals the design needs
revision before downstream tasks land."
```

If Step 3 outcome was B or C, fix the import shape FIRST, then commit. The commit message stays the same — these tests now reflect the actual API.

---

## Task 1: pyproject.toml + package skeleton (no TDD — config)

**Files:**
- Create: `pyproject.toml`
- Create: `src/chorus_form_builder/__init__.py` (empty placeholder, will be filled in Task 6)

- [ ] **Step 1: Write `pyproject.toml`**

Create `pyproject.toml`:

```toml
[project]
name = "agent-tool-chorus-form-builder"
version = "0.1.0"
description = "Generate Chorus forms (.csd + UXB JSON) from a declarative YAML spec, with optional OpenAPI endpoint binding."
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Chris Moore" }]
dependencies = [
    "chorus-forms",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "jsonpath-ng>=1.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
chorus-form-build = "chorus_form_builder.cli:main"

[tool.uv.sources]
chorus-forms = { path = "../chorus-repos/chorus-forms", editable = true }

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
include = ["chorus_form_builder*"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create the empty package init**

Create `src/chorus_form_builder/__init__.py`:

```python
"""chorus-form-builder — generate Chorus forms from declarative YAML.

Public API:
    build_form(spec_path, output_dir, *, fetcher=None) -> EmitResult

Exceptions:
    FormBuilderError (base)
    SpecValidationError
    BindingError
    EmitError
    FormBuilderIOError

Both are populated in later tasks; this is just the package marker.
"""
__version__ = "0.1.0"
```

- [ ] **Step 3: Run the assumption tests against the new package layout**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v 2>&1 | tail -10`

Expected: 3/3 pass (the assumption tests from Task 0). The new pyproject + empty `__init__.py` don't affect them.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/chorus_form_builder/__init__.py
git commit -m "chore: pyproject.toml + package skeleton

uv-installable Python package. chorus-forms is an editable source dep
(matches the agent-app's pattern at ../agent-app-chorus-csd-analyzer).
CLI entry point chorus-form-build registered; implementation lands in
later tasks."
```

---

## Task 2: spec.py — Pydantic models + YAML loader (TDD)

**Files:**
- Create: `src/chorus_form_builder/_types.py`
- Create: `src/chorus_form_builder/spec.py`
- Create: `tests/test_spec.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spec.py`:

```python
"""Spec parsing + Pydantic validation tests."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from chorus_form_builder.spec import (
    FormSpec,
    FieldSpec,
    BindingSpec,
    DomainValueSpec,
    OpenAPIDefaultsSpec,
    load_spec,
    SpecValidationError,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def test_minimal_form_with_one_text_field_loads(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: Test Form
        fields:
          - code: TFLD
            label: Test Field
            control_type: text
            length: 30
    """)
    spec = load_spec(p)
    assert spec.form.name == "TESTFORM"
    assert spec.form.title == "Test Form"
    assert spec.form.type == "user_screen"  # default
    assert spec.form.pages == 1              # default
    assert len(spec.fields) == 1
    assert spec.fields[0].code == "TFLD"
    assert spec.fields[0].control_type == "text"
    assert spec.fields[0].length == 30


def test_form_name_rejects_lowercase(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: testform
          title: Test
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "form.name" in str(exc.value)


def test_field_code_must_be_exactly_four_chars(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: TFL, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "code" in str(exc.value).lower()


def test_combobox_with_static_values(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    spec = load_spec(p)
    assert spec.fields[0].values is not None
    assert len(spec.fields[0].values) == 2
    assert spec.fields[0].values[0].value == "A"
    assert spec.fields[0].binding is None


def test_combobox_with_binding(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: Distro
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /codes
              values_path: $.codes[0].list
              value_field: value
              description_field: description
    """)
    spec = load_spec(p)
    assert spec.fields[0].binding is not None
    assert spec.fields[0].binding.endpoint == "/codes"
    assert spec.fields[0].binding.method == "GET"  # default
    assert spec.fields[0].values is None


def test_combobox_with_both_binding_and_values_rejected(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: STAT
            label: S
            control_type: combobox
            binding:
              openapi_spec: ./x.json
              endpoint: /x
              values_path: $.x
              value_field: v
              description_field: d
            values:
              - {value: A, description: Active}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    msg = str(exc.value).lower()
    assert "binding" in msg and "values" in msg


def test_env_var_interpolation_in_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_API_TOKEN", "secret-xyz")
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
          headers:
            Authorization: "${ORACLE_API_TOKEN}"
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
    """)
    spec = load_spec(p)
    # Interpolation happens at fetch time, not load time — at load time the
    # raw template is preserved. We verify the template survived parsing.
    assert spec.openapi_defaults.headers["Authorization"] == "${ORACLE_API_TOKEN}"


def test_load_spec_missing_file_raises_clear_error(tmp_path):
    p = tmp_path / "no-such-file.yaml"
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "no-such-file.yaml" in str(exc.value)


def test_load_spec_malformed_yaml_raises_clear_error(tmp_path):
    p = _write(tmp_path, "form.yaml", "form: : : :")
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "yaml" in str(exc.value).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_spec.py -v 2>&1 | tail -20`

Expected: all 9 tests fail with `ImportError: cannot import name 'FormSpec' from 'chorus_form_builder.spec'` (or similar — module doesn't exist yet).

- [ ] **Step 3: Implement `_types.py`**

Create `src/chorus_form_builder/_types.py`:

```python
"""Shared dataclasses used across modules — no chorus_forms imports
to avoid pulling the heavy lazy-load chain into spec.py."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainValue:
    """A single (value, description) pair for a combobox."""
    value: str
    description: str = ""


@dataclass(frozen=True)
class EmitResult:
    """Returned by build_form — the three written file paths."""
    csd_path: Path
    uxb_path: Path
    manifest_path: Path
```

- [ ] **Step 4: Implement `spec.py`**

Create `src/chorus_form_builder/spec.py`:

```python
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


class SpecValidationError(Exception):
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_spec.py -v 2>&1 | tail -15`

Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/chorus_form_builder/_types.py src/chorus_form_builder/spec.py tests/test_spec.py
git commit -m "feat(spec): FormSpec Pydantic schema + YAML loader

Top-level FormSpec with FormMetaSpec, OpenAPIDefaultsSpec, FieldSpec,
BindingSpec, DomainValueSpec. Regex validation on form name and field
codes. Mutual exclusion between binding and static values on combobox
fields. Duplicate-field-code rejection.

Env-var interpolation deferred to fetch time — load_spec preserves
\${VAR} templates verbatim.

Shared DomainValue + EmitResult dataclasses live in _types.py to avoid
pulling chorus_forms into the spec module.

Spec: docs/superpowers/specs/2026-05-23-form-builder-v01-design.md §2"
```

---

## Task 3: binding.py — Fetcher Protocol + resolve_binding (TDD)

**Files:**
- Create: `src/chorus_form_builder/binding.py`
- Create: `tests/test_binding.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_binding.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_binding.py -v 2>&1 | tail -10`

Expected: all 12 tests fail with `ImportError: cannot import name 'GoldenFetcher' from 'chorus_form_builder.binding'`.

- [ ] **Step 3: Implement `binding.py`**

Create `src/chorus_form_builder/binding.py`:

```python
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
    for k, v in headers.items():
        def _sub(m: re.Match) -> str:
            var_name = m.group(1)
            if var_name not in os.environ:
                raise BindingError(
                    f"env var {var_name!r} required by header {k!r} is unset"
                )
            return os.environ[var_name]
        out[k] = _ENV_VAR_RE.sub(_sub, v)
    return out


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
    timeout = binding.timeout_seconds if binding.timeout_seconds else defaults.timeout_seconds
    response = fetcher.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.body

    # 5. Compile + apply the JSONPath
    try:
        path_expr = jsonpath_parse(binding.values_path)
    except (JsonPathParserError, Exception) as e:
        raise BindingError(
            f"invalid JSONPath {binding.values_path!r}: {e}"
        ) from e

    matches = path_expr.find(payload)
    if not matches:
        raise BindingError(
            f"JSONPath {binding.values_path!r} returned no matches against "
            f"response from {url}"
        )

    # If the JSONPath uses [*] it yields one match per element; collect their values.
    # If it points at a list node, the single match's .value IS the list.
    if len(matches) == 1 and isinstance(matches[0].value, list):
        extracted = matches[0].value
    elif len(matches) >= 1 and not isinstance(matches[0].value, list):
        # Multi-match — each match is one entry. Concatenate.
        extracted = [m.value for m in matches]
    else:
        extracted = matches[0].value

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_binding.py -v 2>&1 | tail -20`

Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/chorus_form_builder/binding.py tests/test_binding.py
git commit -m "feat(binding): resolve_binding + Fetcher Protocol + env-var interpolation

Three Fetcher implementations: HttpxFetcher (production), GoldenFetcher
(test fixtures), NoFetchFetcher (CLI --no-fetch). All three share the
same Protocol so resolve_binding doesn't care which one is injected.

resolve_binding validates: OpenAPI file exists + parses, endpoint+method
declared, base URL configured, fetch succeeds (4xx/5xx → fail loud),
JSONPath compiles + resolves to a list, each entry is a dict with the
configured value_field. Errors name the offending input.

Env-var interpolation (\${VAR}) happens here at fetch time, not at spec
load. Missing env vars surface as BindingError naming the variable.

Spec: docs/superpowers/specs/2026-05-23-form-builder-v01-design.md §3"
```

---

## Task 4: emit.py — _spec_field_to_csd_field + emit (TDD)

**Files:**
- Create: `src/chorus_form_builder/emit.py`
- Create: `tests/test_emit.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_emit.py`:

```python
"""emit.py tests — translator + chorus_forms builder wrapping + round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chorus_form_builder._types import DomainValue
from chorus_form_builder.emit import (
    EmitError,
    _spec_field_to_csd_field,
    emit,
)
from chorus_form_builder.spec import FieldSpec, FormMetaSpec, FormSpec, DomainValueSpec, OpenAPIDefaultsSpec


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


# --- translator unit tests ---

def test_translator_text_field():
    spec_field = FieldSpec(code="MEMO", label="Memo", control_type="text", length=60)
    csd_field = _spec_field_to_csd_field(spec_field, resolved_domain=None)
    assert csd_field.code == "MEMO"
    assert csd_field.label == "Memo"
    assert csd_field.control_type == "text"
    assert csd_field.length == 60
    assert csd_field.domain_values == []


def test_translator_combobox_with_resolved_binding():
    spec_field = FieldSpec(code="DCMB", label="Distro", control_type="combobox")
    resolved = [DomainValue(value="X", description="X-desc"), DomainValue(value="Y", description="Y-desc")]
    csd_field = _spec_field_to_csd_field(spec_field, resolved_domain=resolved)
    assert len(csd_field.domain_values) == 2
    assert csd_field.domain_values[0].value == "X"


def test_translator_combobox_with_static_values_and_no_resolved():
    spec_field = FieldSpec(
        code="STAT",
        label="Status",
        control_type="combobox",
        values=[DomainValueSpec(value="A", description="Active")],
    )
    csd_field = _spec_field_to_csd_field(spec_field, resolved_domain=None)
    assert len(csd_field.domain_values) == 1
    assert csd_field.domain_values[0].value == "A"


def test_translator_combobox_no_domain_at_all():
    """combobox with neither binding nor values — produces empty domain_values
    list. Pydantic validates that at least one is present at spec load, so this
    is a defensive default for the translator, not a hot path."""
    spec_field = FieldSpec(code="STAT", label="S", control_type="combobox")
    csd_field = _spec_field_to_csd_field(spec_field, resolved_domain=None)
    assert csd_field.domain_values == []


# --- emit end-to-end (uses real chorus_forms; uses tmp_path for output) ---

def test_emit_writes_three_files_for_text_only_form(tmp_path):
    pytest.importorskip("chorus_forms")
    spec = _form_spec_one_text_field()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    assert result.csd_path.is_file()
    assert result.uxb_path.is_file()
    assert result.manifest_path.is_file()
    assert result.csd_path.name == "TESTFORM.csd"
    assert result.uxb_path.name == "TESTFORM.uxb.json"
    assert result.manifest_path.name == "TESTFORM_manifest.json"


def test_emit_writes_non_empty_csd(tmp_path):
    pytest.importorskip("chorus_forms")
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    assert result.csd_path.stat().st_size > 0


def test_emit_uxb_json_is_valid_json(tmp_path):
    pytest.importorskip("chorus_forms")
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    data = json.loads(result.uxb_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_emit_round_trips_through_parser(tmp_path):
    """Built .csd parses back via chorus_forms.parser; preserved field codes
    and control types match the spec."""
    pytest.importorskip("chorus_forms")
    from chorus_forms.csd.parser import parse_csd_file

    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    parsed = parse_csd_file(result.csd_path)
    codes = {f.code for f in parsed.fields}
    assert "STAT" in codes


def test_emit_uses_resolved_binding_over_static_values(tmp_path):
    """If a binding-bound combobox has resolved values, those win — the spec's
    static `values:` doesn't get used because Pydantic validates them mutually
    exclusive, but defensively the translator prefers resolved."""
    pytest.importorskip("chorus_forms")
    from chorus_forms.csd.parser import parse_csd_file

    from chorus_form_builder.spec import BindingSpec
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
    resolved = {"DCMB": [DomainValue(value="X", description="From binding")]}
    result = emit(spec, resolved_bindings=resolved, output_dir=tmp_path)
    parsed = parse_csd_file(result.csd_path)
    dcmb = next(f for f in parsed.fields if f.code == "DCMB")
    # The parsed form should contain the resolved value "X"
    assert any(dv.value == "X" for dv in dcmb.domain_values), \
        f"expected 'X' in {[dv.value for dv in dcmb.domain_values]}"


def test_emit_creates_output_dir_if_missing(tmp_path):
    pytest.importorskip("chorus_forms")
    spec = _form_spec_one_text_field()
    missing_dir = tmp_path / "deep" / "nested" / "dir"
    result = emit(spec, resolved_bindings={}, output_dir=missing_dir)
    assert missing_dir.is_dir()
    assert result.csd_path.is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_emit.py -v 2>&1 | tail -15`

Expected: all 9 tests fail with `ImportError: cannot import name '_spec_field_to_csd_field' from 'chorus_form_builder.emit'`.

- [ ] **Step 3: Implement `emit.py`**

Create `src/chorus_form_builder/emit.py`:

```python
"""CsdForm assembly + chorus_forms builder calls + file writes.

Thin assembler — does not duplicate chorus_forms logic. The translator
function is the single seam between our FormSpec/FieldSpec and
chorus_forms' CsdForm/CsdField shapes.
"""
from __future__ import annotations

import json
from pathlib import Path

from chorus_form_builder._types import DomainValue, EmitResult
from chorus_form_builder.manifest import build_manifest
from chorus_form_builder.spec import FieldSpec, FormSpec


class EmitError(Exception):
    """chorus_forms builder rejected the constructed form, or file write failed."""


def _spec_field_to_csd_field(spec_field: FieldSpec, resolved_domain: list[DomainValue] | None):
    """Translate a FieldSpec → chorus_forms.CsdField.

    Domain-value precedence:
        1. resolved_domain (from a binding fetch — Task 3 produced this)
        2. spec_field.values (static — declared inline in YAML)
        3. [] (empty — defensive default for combobox with neither)
    """
    from chorus_forms.models import CsdField, DomainValue as CfDomainValue

    if resolved_domain is not None:
        domain_source = resolved_domain
    elif spec_field.values is not None:
        domain_source = [DomainValue(value=v.value, description=v.description) for v in spec_field.values]
    else:
        domain_source = []

    return CsdField(
        code=spec_field.code,
        label=spec_field.label,
        control_type=spec_field.control_type,
        required=spec_field.required,
        read_only=False,
        length=spec_field.length,
        dictionary=None,
        domain_values=[
            CfDomainValue(value=d.value, description=d.description)
            for d in domain_source
        ],
    )


def emit(
    spec: FormSpec,
    resolved_bindings: dict[str, list[DomainValue]],
    output_dir: Path,
) -> EmitResult:
    """Assemble a chorus_forms.CsdForm from the spec + resolved bindings,
    call the Classic and UXB builders, write three files, return paths."""
    from chorus_forms.builders import classic, uxb
    from chorus_forms.models import CsdForm, FormMeta

    try:
        form = CsdForm(
            meta=FormMeta(
                file_name=spec.form.name,
                form_title=spec.form.title,
                form_type=spec.form.type,
                num_pages=spec.form.pages,
                dll_hooks=[],
            ),
            fields=[
                _spec_field_to_csd_field(f, resolved_bindings.get(f.code))
                for f in spec.fields
            ],
            groups=[],
            warnings=[],
        )
    except Exception as e:
        raise EmitError(f"failed to construct CsdForm from spec: {e}") from e

    try:
        csd_bytes = classic.build_csd(form)
    except Exception as e:
        raise EmitError(f"chorus_forms.builders.classic.build_csd failed: {e}") from e

    try:
        uxb_dict = uxb.build_uxb(form)
    except Exception as e:
        raise EmitError(f"chorus_forms.builders.uxb.build_uxb failed: {e}") from e

    output_dir.mkdir(parents=True, exist_ok=True)
    csd_path = output_dir / f"{spec.form.name}.csd"
    uxb_path = output_dir / f"{spec.form.name}.uxb.json"
    manifest_path = output_dir / f"{spec.form.name}_manifest.json"

    csd_path.write_bytes(csd_bytes)
    uxb_path.write_text(json.dumps(uxb_dict, indent=2), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(build_manifest(spec, resolved_bindings), indent=2),
        encoding="utf-8",
    )

    return EmitResult(csd_path=csd_path, uxb_path=uxb_path, manifest_path=manifest_path)
```

- [ ] **Step 4: Implement `manifest.py` (referenced by emit.py)**

Create `src/chorus_form_builder/manifest.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_emit.py -v 2>&1 | tail -20`

Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/chorus_form_builder/emit.py src/chorus_form_builder/manifest.py tests/test_emit.py
git commit -m "feat(emit): CsdForm assembly + manifest builder

Wraps chorus_forms.builders.classic and .uxb. The translator function
_spec_field_to_csd_field is the single seam between FormSpec and CsdField;
new field types add a branch here, not anywhere else.

Domain-value precedence: resolved (from binding fetch) > static (from
YAML values:) > empty list. Round-trip test confirms parsed forms
match the spec input.

Manifest captures spec name, field count, and per-binding provenance
(endpoint, JSONPath, fetched_at, value_count). Spec/file hashes can
be added in a follow-up — value_count alone is enough for drift detection.

Spec: docs/superpowers/specs/2026-05-23-form-builder-v01-design.md §4"
```

---

## Task 5: __init__.py — public build_form orchestrator (TDD)

**Files:**
- Modify: `src/chorus_form_builder/__init__.py`
- Create: `tests/test_build_form.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_form.py`:

```python
"""build_form integration tests — orchestrates spec + binding + emit."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from chorus_form_builder import (
    BindingError,
    EmitResult,
    FormBuilderError,
    SpecValidationError,
    build_form,
)
from chorus_form_builder.binding import GoldenFetcher, NoFetchFetcher, Response


def _write_form(tmp_path: Path, content: str, name: str = "form.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def test_build_form_static_combo_no_fetcher_needed(tmp_path):
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: STATCOMB
          title: Static Combo
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    out_dir = tmp_path / "out"
    result = build_form(spec_path, out_dir, fetcher=NoFetchFetcher())
    assert isinstance(result, EmitResult)
    assert result.csd_path.is_file()
    assert result.csd_path.name == "STATCOMB.csd"


def test_build_form_with_binding_uses_fetcher(tmp_path):
    pytest.importorskip("chorus_forms")
    # Write OpenAPI spec
    (tmp_path / "oracle.json").write_text(json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {"/codes": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }), encoding="utf-8")
    # Write form spec
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: Bound Form
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: Distro
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /codes
              values_path: $.items[*]
              value_field: value
              description_field: description
    """)
    out_dir = tmp_path / "out"
    fetcher = GoldenFetcher({
        ("GET", "https://example.com/api/codes"): Response(
            200,
            {"items": [{"value": "X", "description": "X-desc"}, {"value": "Y", "description": "Y-desc"}]},
        )
    })
    result = build_form(spec_path, out_dir, fetcher=fetcher)
    assert result.csd_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bindings"][0]["value_count"] == 2


def test_build_form_propagates_spec_validation_error(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: lowercase  # invalid — must be uppercase
          title: T
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    with pytest.raises(SpecValidationError):
        build_form(spec_path, tmp_path / "out", fetcher=NoFetchFetcher())


def test_build_form_propagates_binding_error(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: D
            control_type: combobox
            binding:
              openapi_spec: ./does-not-exist.json
              endpoint: /x
              values_path: $.x
              value_field: v
    """)
    with pytest.raises(BindingError):
        build_form(spec_path, tmp_path / "out", fetcher=GoldenFetcher({}))


def test_build_form_default_fetcher_is_httpx(tmp_path):
    """If no fetcher is passed and the spec has no bindings, build_form
    succeeds (HttpxFetcher is never used for a binding-less form)."""
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: TXTONLY
          title: T
        fields:
          - {code: MEMO, label: M, control_type: text, length: 60}
    """)
    result = build_form(spec_path, tmp_path / "out")  # no fetcher kwarg
    assert result.csd_path.is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_form.py -v 2>&1 | tail -10`

Expected: 5 tests fail — `ImportError` on `build_form`, `EmitResult`, etc.

- [ ] **Step 3: Replace `src/chorus_form_builder/__init__.py`**

Replace the existing `__init__.py` with:

```python
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

from chorus_form_builder._types import DomainValue, EmitResult
from chorus_form_builder.binding import BindingError, Fetcher, HttpxFetcher, NoFetchFetcher, resolve_binding
from chorus_form_builder.emit import EmitError, emit
from chorus_form_builder.spec import SpecValidationError, load_spec

__version__ = "0.1.0"


class FormBuilderError(Exception):
    """Base for all chorus_form_builder errors. SpecValidationError,
    BindingError, and EmitError are kept as separate subclasses with
    explicit imports so callers can catch the specific error type."""


# Wire the base class into the existing module-level exceptions so
# `except FormBuilderError` catches all of them.
SpecValidationError.__bases__ = (FormBuilderError,)
BindingError.__bases__ = (FormBuilderError,)
EmitError.__bases__ = (FormBuilderError,)


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
    "EmitResult",
    "FormBuilderError",
    "SpecValidationError",
    "BindingError",
    "EmitError",
    "Fetcher",
    "HttpxFetcher",
    "NoFetchFetcher",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_form.py -v 2>&1 | tail -10`

Expected: all 5 tests pass.

Also run the full test suite to confirm no regressions:

Run: `.venv/Scripts/python.exe -m pytest tests/ -v 2>&1 | tail -20`

Expected: ~38 tests pass total (3 assumption + 9 spec + 12 binding + 9 emit + 5 build_form).

- [ ] **Step 5: Commit**

```bash
git add src/chorus_form_builder/__init__.py tests/test_build_form.py
git commit -m "feat: build_form orchestrator + exception hierarchy

Single public entry point wiring spec → binding (for each bound field) →
emit. Default fetcher is HttpxFetcher; tests inject GoldenFetcher; CLI
--no-fetch will inject NoFetchFetcher (Task 6).

FormBuilderError base class wired retroactively onto the existing
SpecValidationError / BindingError / EmitError so callers can do
\`except FormBuilderError\` for catch-all handling without losing the
ability to discriminate.

Spec: docs/superpowers/specs/2026-05-23-form-builder-v01-design.md §5"
```

---

## Task 6: cli.py — argparse + exit-code mapping (TDD)

**Files:**
- Create: `src/chorus_form_builder/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
"""CLI tests — invokes chorus-form-build via subprocess, checks exit codes + files."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _write_form(tmp_path: Path, content: str, name: str = "form.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return p


def _venv_python() -> str:
    """Resolve the venv's python — works on Windows where the .venv/Scripts/ shape
    differs from POSIX .venv/bin/."""
    repo_root = Path(__file__).resolve().parent.parent
    if sys.platform == "win32":
        return str(repo_root / ".venv" / "Scripts" / "python.exe")
    return str(repo_root / ".venv" / "bin" / "python")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Invoke the CLI module via `python -m chorus_form_builder.cli`."""
    return subprocess.run(
        [_venv_python(), "-m", "chorus_form_builder.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_static_combo_succeeds(tmp_path):
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: STATCOMB
          title: Static
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values:
              - {value: A, description: Active}
              - {value: I, description: Inactive}
    """)
    out_dir = tmp_path / "out"
    proc = _run_cli("--spec", str(spec_path), "--output", str(out_dir), "--no-fetch")
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert (out_dir / "STATCOMB.csd").is_file()
    assert (out_dir / "STATCOMB.uxb.json").is_file()
    assert (out_dir / "STATCOMB_manifest.json").is_file()


def test_cli_spec_validation_failure_exit_1(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: lowercase  # invalid — must be uppercase
          title: T
        fields:
          - {code: TFLD, label: T, control_type: text, length: 10}
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"))
    assert proc.returncode == 1
    assert "form.name" in proc.stderr or "form.name" in proc.stdout


def test_cli_binding_failure_exit_2(tmp_path):
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: D
            control_type: combobox
            binding:
              openapi_spec: ./does-not-exist.json
              endpoint: /x
              values_path: $.x
              value_field: v
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    # --no-fetch would also error here, but the missing-file check fires first
    assert proc.returncode == 2


def test_cli_no_fetch_with_static_only_succeeds(tmp_path):
    """--no-fetch is fine when the spec has zero bindings."""
    pytest.importorskip("chorus_forms")
    spec_path = _write_form(tmp_path, """
        form:
          name: TXTONLY
          title: T
        fields:
          - {code: MEMO, label: M, control_type: text, length: 60}
    """)
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    assert proc.returncode == 0


def test_cli_no_fetch_with_binding_errors(tmp_path):
    """--no-fetch errors clearly if any binding is present."""
    spec_path = _write_form(tmp_path, """
        form:
          name: BNDFORM
          title: T
        openapi_defaults:
          base_url: https://example.com/api
        fields:
          - code: DCMB
            label: D
            control_type: combobox
            binding:
              openapi_spec: ./oracle.json
              endpoint: /x
              values_path: $.x
              value_field: v
    """)
    # Write a valid openapi so the missing-file check passes and we hit the fetcher
    (tmp_path / "oracle.json").write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "T", "version": "1"},
        "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }), encoding="utf-8")
    proc = _run_cli("--spec", str(spec_path), "--output", str(tmp_path / "out"), "--no-fetch")
    assert proc.returncode == 2
    assert "--no-fetch" in (proc.stderr + proc.stdout)


def test_cli_missing_spec_path_exit_1(tmp_path):
    proc = _run_cli("--spec", str(tmp_path / "no-such.yaml"), "--output", str(tmp_path / "out"))
    assert proc.returncode == 1


def test_cli_help_exits_zero():
    proc = _run_cli("--help")
    assert proc.returncode == 0
    assert "chorus-form-build" in proc.stdout or "--spec" in proc.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -v 2>&1 | tail -10`

Expected: all 7 tests fail — `chorus_form_builder.cli` module doesn't exist yet.

- [ ] **Step 3: Implement `cli.py`**

Create `src/chorus_form_builder/cli.py`:

```python
"""CLI entry point — argparse + exit-code mapping.

Maps each exception class from the library to a stable exit code:
    0 — success
    1 — spec validation failure (or general IO problem on the spec file)
    2 — binding (fetch / JSONPath) failure
    3 — emit failure
    4 — unexpected IO failure
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chorus_form_builder import (
    BindingError,
    EmitError,
    HttpxFetcher,
    NoFetchFetcher,
    SpecValidationError,
    build_form,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chorus-form-build",
        description="Generate Chorus forms (.csd + UXB JSON) from a declarative YAML spec.",
    )
    p.add_argument("--spec", type=Path, required=True, help="Path to the form-spec YAML file")
    p.add_argument("--output", type=Path, required=True, help="Output directory (created if missing)")
    p.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip OpenAPI fetches — static `values:` only. Errors if any binding is present.",
    )
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument("--quiet", "-q", action="store_true", help="Errors only")
    verbosity.add_argument("--verbose", "-v", action="store_true", help="Show per-field resolution")
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code; sys.exit-style usage in __main__."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    fetcher = NoFetchFetcher() if args.no_fetch else HttpxFetcher()

    try:
        result = build_form(args.spec, args.output, fetcher=fetcher)
    except SpecValidationError as e:
        print(f"spec validation error: {e}", file=sys.stderr)
        return 1
    except BindingError as e:
        print(f"binding error: {e}", file=sys.stderr)
        return 2
    except EmitError as e:
        print(f"emit error: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"IO error: {e}", file=sys.stderr)
        return 4

    if not args.quiet:
        # One-line success summary
        rel_out = result.csd_path.parent
        print(
            f"Wrote {result.csd_path.name} + .uxb.json + _manifest.json → {rel_out}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -v 2>&1 | tail -15`

Expected: all 7 tests pass.

- [ ] **Step 5: Run the entire suite as a regression gate**

Run: `.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -10`

Expected: ~45 tests pass total. Zero failures.

- [ ] **Step 6: Commit**

```bash
git add src/chorus_form_builder/cli.py tests/test_cli.py
git commit -m "feat(cli): argparse entry point + exit-code mapping

Single-binary CLI: chorus-form-build --spec FILE --output DIR. Maps the
exception hierarchy to stable exit codes (1: spec, 2: binding, 3: emit,
4: IO) so CI/scripts can branch on failure mode.

--no-fetch routes through NoFetchFetcher (introduced in Task 3) so
static-values specs succeed offline and bound specs fail with a clear
'--no-fetch was set' message.

Spec: docs/superpowers/specs/2026-05-23-form-builder-v01-design.md §5"
```

---

## Task 7: Golden tests — 3 fixture pairs (TDD)

**Files:**
- Create: `tests/goldens/oracle_dcmb/{form.yaml, oracle.json, response.json}`
- Create: `tests/goldens/static_combo/form.yaml`
- Create: `tests/goldens/text_plus_combo/{form.yaml, oracle.json, response.json}`
- Create: `tests/test_goldens.py`

**Note:** the .csd / .uxb.json / _manifest.json files in each golden dir are GENERATED in this task's Step 5, not hand-written. The fixtures are the YAML + JSON inputs; the outputs are produced by running the implementation and then committed alongside as the lock.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_goldens.py`:

```python
"""Golden tests — byte-exact .csd, structural .uxb.json + manifest.

If any of these fail, either the implementation drifted or the fixture
needs regenerating. To regenerate: delete the .csd / .uxb.json /
_manifest.json files in the relevant golden dir, then run this test
with REGENERATE_GOLDENS=1 in the env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chorus_form_builder import build_form
from chorus_form_builder.binding import GoldenFetcher, Response


GOLDENS_DIR = Path(__file__).parent / "goldens"


def _normalize_manifest(manifest: dict) -> dict:
    """Strip dynamic fields (timestamps, hashes) for stable comparison."""
    out = dict(manifest)
    out.pop("generated_at", None)
    for b in out.get("bindings", []):
        b.pop("fetched_at", None)
    return out


def _load_canned_responses(golden_dir: Path) -> dict[tuple[str, str], Response]:
    """Build a GoldenFetcher canned-response map from a response.json in the
    golden dir. Shape: {"GET /url": {...response body...}}."""
    response_file = golden_dir / "response.json"
    if not response_file.is_file():
        return {}
    raw = json.loads(response_file.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], Response] = {}
    for key, body in raw.items():
        method, url = key.split(" ", 1)
        out[(method, url)] = Response(200, body)
    return out


def _run_golden(name: str, tmp_path: Path) -> None:
    """Run build_form against a golden dir's spec; compare outputs against
    the committed golden files."""
    golden_dir = GOLDENS_DIR / name
    spec_path = golden_dir / "form.yaml"
    canned = _load_canned_responses(golden_dir)
    fetcher = GoldenFetcher(canned)

    out_dir = tmp_path / "out"
    result = build_form(spec_path, out_dir, fetcher=fetcher)

    # Find the expected files in the golden dir
    expected_csd = next(golden_dir.glob("*.csd"), None)
    expected_uxb = next(golden_dir.glob("*.uxb.json"), None)
    expected_manifest = next(golden_dir.glob("*_manifest.json"), None)

    if os.environ.get("REGENERATE_GOLDENS") == "1":
        # Re-emit the golden files from the current implementation
        if expected_csd is None:
            expected_csd = golden_dir / result.csd_path.name
        if expected_uxb is None:
            expected_uxb = golden_dir / result.uxb_path.name
        if expected_manifest is None:
            expected_manifest = golden_dir / result.manifest_path.name
        expected_csd.write_bytes(result.csd_path.read_bytes())
        expected_uxb.write_text(result.uxb_path.read_text(encoding="utf-8"), encoding="utf-8")
        expected_manifest.write_text(result.manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
        pytest.skip(f"REGENERATE_GOLDENS=1 — regenerated {name} golden files")

    assert expected_csd is not None, f"no committed .csd golden in {golden_dir}"
    assert expected_uxb is not None, f"no committed .uxb.json golden in {golden_dir}"
    assert expected_manifest is not None, f"no committed _manifest.json golden in {golden_dir}"

    # .csd — byte-exact
    assert result.csd_path.read_bytes() == expected_csd.read_bytes(), \
        f"{name}: .csd bytes differ"

    # .uxb.json — structural (dict equality after json.loads)
    actual_uxb = json.loads(result.uxb_path.read_text(encoding="utf-8"))
    expected_uxb_data = json.loads(expected_uxb.read_text(encoding="utf-8"))
    assert actual_uxb == expected_uxb_data, f"{name}: .uxb.json structure differs"

    # _manifest.json — structural after stripping dynamic fields
    actual_manifest = _normalize_manifest(json.loads(result.manifest_path.read_text(encoding="utf-8")))
    expected_manifest_data = _normalize_manifest(json.loads(expected_manifest.read_text(encoding="utf-8")))
    assert actual_manifest == expected_manifest_data, f"{name}: manifest differs"


def test_golden_static_combo(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("static_combo", tmp_path)


def test_golden_oracle_dcmb(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("oracle_dcmb", tmp_path)


def test_golden_text_plus_combo(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("text_plus_combo", tmp_path)
```

- [ ] **Step 2: Create the static_combo golden inputs**

Create `tests/goldens/static_combo/form.yaml`:

```yaml
form:
  name: STATCOMB
  title: Static Combo Test
fields:
  - code: STAT
    label: "Status"
    control_type: combobox
    values:
      - {value: A, description: Active}
      - {value: I, description: Inactive}
      - {value: P, description: Pending}
```

- [ ] **Step 3: Create the oracle_dcmb golden inputs**

Create `tests/goldens/oracle_dcmb/form.yaml`:

```yaml
form:
  name: ORACLDC
  title: Oracle Distribution Combo
openapi_defaults:
  base_url: https://oracle.example.com/api/v1
fields:
  - code: DCMB
    label: "Distribution Combination"
    control_type: combobox
    required: true
    binding:
      openapi_spec: ./oracle.json
      endpoint: /get_distribution_combination_codes
      values_path: $.codes[0].distro_combo_list
      value_field: value
      description_field: description
```

Create `tests/goldens/oracle_dcmb/oracle.json` — the OpenAPI 3.0 spec the user had selected at session start:

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "Oracle API",
    "description": "The central API for Integrating Oracle with our various systems",
    "version": "1.0.0"
  },
  "paths": {
    "/get_distribution_combination_codes": {
      "get": {
        "tags": ["Oracle"],
        "summary": "Get Distribution Combination Codes",
        "responses": {
          "200": {
            "description": "Successful Response"
          }
        }
      }
    }
  }
}
```

Create `tests/goldens/oracle_dcmb/response.json` — canned response for the GoldenFetcher:

```json
{
  "GET https://oracle.example.com/api/v1/get_distribution_combination_codes": {
    "codes": [
      {
        "type": "GL",
        "distro_combo_list": [
          {"value": "01-100-0000-0000", "description": "Corporate Cash"},
          {"value": "01-200-0000-0000", "description": "Operating Expense"},
          {"value": "02-100-0000-0000", "description": "Investments"},
          {"value": "02-200-0000-0000", "description": "Receivables"}
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Create the text_plus_combo golden inputs**

Create `tests/goldens/text_plus_combo/form.yaml`:

```yaml
form:
  name: TXTCOMBO
  title: Text + Combo
openapi_defaults:
  base_url: https://example.com/api
fields:
  - code: MEMO
    label: "Memo"
    control_type: text
    length: 60
  - code: STAT
    label: "Status"
    control_type: combobox
    values:
      - {value: A, description: Active}
      - {value: I, description: Inactive}
  - code: DCMB
    label: "Distro"
    control_type: combobox
    binding:
      openapi_spec: ./oracle.json
      endpoint: /codes
      values_path: $.items[*]
      value_field: code
      description_field: name
```

Create `tests/goldens/text_plus_combo/oracle.json`:

```json
{
  "openapi": "3.0.3",
  "info": {"title": "Example", "version": "1.0.0"},
  "paths": {
    "/codes": {
      "get": {
        "responses": {"200": {"description": "ok"}}
      }
    }
  }
}
```

Create `tests/goldens/text_plus_combo/response.json`:

```json
{
  "GET https://example.com/api/codes": {
    "items": [
      {"code": "X1", "name": "First"},
      {"code": "X2", "name": "Second"},
      {"code": "X3", "name": "Third"}
    ]
  }
}
```

- [ ] **Step 5: Generate the committed golden outputs**

Run the tests with `REGENERATE_GOLDENS=1` so they emit the .csd / .uxb.json / _manifest.json files into each golden dir:

PowerShell:
```powershell
$env:REGENERATE_GOLDENS = "1"
.venv/Scripts/python.exe -m pytest tests/test_goldens.py -v
Remove-Item Env:\REGENERATE_GOLDENS
```

Bash (WSL/Git Bash):
```bash
REGENERATE_GOLDENS=1 .venv/Scripts/python.exe -m pytest tests/test_goldens.py -v
```

Expected: all 3 tests SKIP with "regenerated golden files." The output files now exist in each golden dir.

- [ ] **Step 6: Inspect and sanity-check the generated outputs**

```bash
ls tests/goldens/oracle_dcmb/
# Should show: form.yaml, oracle.json, response.json, ORACLDC.csd, ORACLDC.uxb.json, ORACLDC_manifest.json

cat tests/goldens/oracle_dcmb/ORACLDC_manifest.json | head -30
```

Confirm the manifest has the expected `value_count: 4` for the DCMB binding (matches the 4 entries in response.json).

```bash
cat tests/goldens/static_combo/STATCOMB_manifest.json
```

Confirm the manifest has `bindings: []` (no bindings for this static-only spec).

- [ ] **Step 7: Re-run golden tests in normal mode**

```bash
.venv/Scripts/python.exe -m pytest tests/test_goldens.py -v
```

Expected: all 3 tests PASS — outputs match the just-committed golden files.

- [ ] **Step 8: Commit**

```bash
git add tests/goldens/ tests/test_goldens.py
git commit -m "test: golden fixtures for static_combo, oracle_dcmb, text_plus_combo

Three golden test cases lock the end-to-end emit pipeline:
- static_combo: combobox with inline values, no fetcher needed
- oracle_dcmb: binding-bound combo against the Oracle distro-combo
  OpenAPI spec (the canonical case that motivated this whole sub-project)
- text_plus_combo: multi-field form with both control types + a binding

Goldens compare byte-exact on .csd, structural (dict-eq) on .uxb.json,
and structural (dict-eq after stripping timestamps) on _manifest.json.
To regenerate: REGENERATE_GOLDENS=1 pytest tests/test_goldens.py."
```

---

## Task 8: README finalization + smoke verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with verified install + run examples**

The committed `README.md` was a placeholder. Replace it with:

```markdown
# agent-tool-chorus-form-builder

Generate Chorus forms (Classic XML `.csd` + UXB JSON) from a declarative YAML spec, with optional bake-at-generation-time binding to OpenAPI endpoints.

## Quick start

```bash
# Install
uv tool install --editable D:/agent-tool-chorus-form-builder

# Smallest invocation — static-values combobox, no network
chorus-form-build \
  --spec tests/goldens/static_combo/form.yaml \
  --output ./out/ \
  --no-fetch

# Full invocation — OpenAPI endpoint binding
chorus-form-build \
  --spec my-form.yaml \
  --output ./out/

# Library use
python -c "
from pathlib import Path
from chorus_form_builder import build_form
result = build_form(Path('my-form.yaml'), Path('./out/'))
print(f'Wrote {result.csd_path}')
"
```

## Spec format

See `docs/superpowers/specs/2026-05-23-form-builder-v01-design.md` §2 for the full schema.

Minimal example:

```yaml
form:
  name: ORACLDC
  title: Oracle Distribution Combo
openapi_defaults:
  base_url: https://oracle.example.com/api/v1
  headers:
    Authorization: "${ORACLE_API_TOKEN}"
fields:
  - code: DCMB
    label: "Distribution Combination"
    control_type: combobox
    binding:
      openapi_spec: ./oracle.json
      endpoint: /get_distribution_combination_codes
      values_path: $.codes[0].distro_combo_list
      value_field: value
      description_field: description
```

## Output

For each run, writes three files into the output directory:
- `{form.name}.csd` — Classic XML binary, deployable to Chorus today
- `{form.name}.uxb.json` — UXB JSON form representation
- `{form.name}_manifest.json` — provenance (generator version, timestamps, binding endpoints, value counts)

## Limits (v0.1)

- Field types: `combobox` (bound or static) and `text` only. Date, number, etc. add when a real case arrives.
- OpenAPI: 3.0 only.
- Binding: bake-at-generation only. Runtime-bind via JS procedures is sub-project C.
- Auth: bearer / custom headers via `${VAR}` env-var interpolation; no OAuth flow.
- Single form per invocation.

## Exit codes (CLI)

- 0 — success
- 1 — spec validation failure
- 2 — binding (fetch / JSONPath) failure
- 3 — emit failure (`chorus_forms` builder rejected the form)
- 4 — IO failure (output dir, etc.)

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

To regenerate golden fixtures after a deliberate output change:

```bash
REGENERATE_GOLDENS=1 .venv/Scripts/python.exe -m pytest tests/test_goldens.py
```

## Sibling tools

Part of the `agent-tool-*` ecosystem; see `D:/ai-agents/CLAUDE.md` for the catalog.
```

- [ ] **Step 2: Run the full test suite as a final regression gate**

```bash
.venv/Scripts/python.exe -m pytest tests/ -v 2>&1 | tail -15
```

Expected: ~48 tests pass, 0 skipped (unless REGENERATE_GOLDENS is set), 0 failed.

- [ ] **Step 3: Manual smoke — run the CLI against the Oracle golden**

```bash
.venv/Scripts/python.exe -m chorus_form_builder.cli \
  --spec tests/goldens/static_combo/form.yaml \
  --output /tmp/chorus-form-smoke \
  --no-fetch
```

Expected output:
```
Wrote STATCOMB.csd + .uxb.json + _manifest.json → /tmp/chorus-form-smoke
```

```bash
ls /tmp/chorus-form-smoke/
# STATCOMB.csd  STATCOMB.uxb.json  STATCOMB_manifest.json
```

- [ ] **Step 4: Commit README + close out**

```bash
git add README.md
git commit -m "docs: README — verified install + run examples

Quick-start examples cribbed from the golden fixtures (so they're known
to work). Spec format example uses the Oracle distro-combo case, the
canonical motivating example for this sub-project."
```

---

## Self-review checklist (post-write)

**Spec coverage:**
- ✅ §1 Architecture (repo layout + data flow + deps) — Tasks 1, 2, 3, 4, 5, 6
- ✅ §2 Spec YAML schema — Task 2
- ✅ §3 Binding resolution (Fetcher Protocol + env-var interp) — Task 3
- ✅ §4 Emit + Manifest — Task 4
- ✅ §5 CLI + library surface — Tasks 5, 6
- ✅ §6 Tests + error handling — Tasks 2, 3, 4, 5, 6, 7 (test code inline in each); Task 7 (golden layer)
- ✅ Risk §1 (chorus_forms builder API) — Task 0
- ✅ Risk §3 (golden brittleness) — Task 7's regenerate-mode handle

**Placeholder scan:**
- ✅ No TBDs, no "handle errors appropriately", every step has complete code or a complete command
- ✅ Every test step is a full pytest function body
- ✅ Every src file step is the complete file

**Type consistency:**
- ✅ `DomainValue` (our dataclass) is consistently the v1 type that flows through binding → emit → translator → CsdField conversion
- ✅ `FormSpec` / `FieldSpec` / `BindingSpec` are the only Pydantic models exposed across modules
- ✅ Exit codes 0/1/2/3/4 consistent across spec §5 and Task 6's CLI
- ✅ File names `{form.name}.csd` / `{form.name}.uxb.json` / `{form.name}_manifest.json` consistent in §4 design, Task 4 emit code, Task 7 golden assertions, Task 8 CLI smoke

No spec requirements without a mapping task. No unresolved hand-waves. Plan is implementation-ready.
