# agent-tool-chorus-form-builder v0.1 — design

**Date:** 2026-05-23
**Status:** Approved (brainstorm)
**Scope:** First ship — combobox + text fields, bake-at-generation OpenAPI binding, CLI + library.

## Goal

Generate deployable Chorus forms (`.csd` + UXB JSON + provenance manifest) from a single declarative YAML spec, with optional bake-time binding of combobox `domain_values` to OpenAPI endpoints.

## Sub-project context

This is sub-project A+B of the larger form-generation track originally proposed at the start of the 2026-05-22 session:

- **A. IR + emitter wiring** — confirm the chorus_forms `CsdForm` IR works as a generation target, expose the existing builders through a callable surface
- **B. OpenAPI → CsdForm adapter** — deterministic mapper from spec + endpoint → form

Combined into one first ship because A alone is plumbing; B without A is a half-pipeline. Together they produce a tangible end-to-end demo: "drop in the Oracle distro-combo OpenAPI spec, get a Chorus form bound to that endpoint."

Future sub-projects, **explicitly out of scope** for v0.1:

- **C. Procedure JS generator** — emit Classic / UXB-dialect JS handlers (form-open / field-change / button-click)
- **D. Text-prompt → CsdForm adapter** — LLM produces CsdForm from natural language
- **E. Image → CsdForm adapter** — vision model interprets a screenshot / paper form

## Non-goals (v0.1)

- **Runtime-bound combos.** All bindings are baked at generation time. Forms ship with snapshotted values; upstream churn requires a regenerate. Runtime-bind via JS depends on sub-project C; runtime-bind via DLL hook is out of Python-only scope.
- **Existing-form augmentation.** v0.1 generates greenfield forms only. Mutating a parsed `CsdForm` from disk to apply bindings is a natural follow-up, not in this ship.
- **Field types beyond combobox and text.** date, number, checkbox, radio, button, label, image — add when a real user case demands.
- **Spec formats beyond OpenAPI 3.0.** Swagger 2, RAML, OpenAPI 3.1, gRPC — defer.
- **Authentication beyond pre-fetched bearer tokens / custom headers.** No OAuth flow, no AWS SigV4.
- **Response-schema validation.** The OpenAPI spec is used for endpoint discovery, not response validation. Trust the JSONPath result.
- **Retry on transient HTTP failure.** First-ship behavior is fail-fast.
- **Subcommands, daemons, watch mode.** Single CLI entry point only.

## Design

### Section 1 — Architecture

**Repo layout:**

```
agent-tool-chorus-form-builder/
├── pyproject.toml                 # uv-installable; depends on chorus_forms (editable)
├── README.md
├── src/chorus_form_builder/
│   ├── __init__.py                # exports build_form(spec_path, output_dir, *, fetcher=None)
│   ├── cli.py                     # argparse entry point: chorus-form-build
│   ├── spec.py                    # Pydantic models for the form-spec YAML
│   ├── binding.py                 # OpenAPI fetch + JSONPath traversal
│   ├── emit.py                    # chorus_forms wrappers — produces .csd + .uxb.json
│   └── manifest.py                # provenance JSON
└── tests/
    ├── goldens/                   # input YAML + expected .csd / .uxb.json bytes
    └── test_*.py
```

**Data flow:**

```
form.yaml ──┬──> spec.py (parse + validate)  ──> FormSpec (Pydantic)
            │                                       │
            ↓                                       │
   binding.py: for each field with binding,         │
   fetch OpenAPI endpoint, apply JSONPath,          │
   produce list[(value, description)]               │
            │                                       │
            ↓                                       ↓
            └─────────> emit.py: build CsdForm ────┘
                          │
                          ├──> chorus_forms.builders.classic ──> {form}.csd
                          ├──> chorus_forms.builders.uxb     ──> {form}.uxb.json
                          └──> manifest.py                   ──> {form}_manifest.json
```

Module responsibilities are narrow: `spec` parses, `binding` fetches, `emit` assembles, `manifest` annotates. They communicate through `FormSpec` (input Pydantic) and `chorus_forms.CsdForm` (existing model). No module reaches into another's internals.

**Dependencies:**
- `chorus_forms` (editable, from `D:/chorus-repos/chorus-forms`) — IR + builders
- `pydantic>=2.0` — spec validation
- `pyyaml` — spec parsing
- `httpx` — OpenAPI fetches (matches `agent-tool-chorus-v1-client`)
- `jsonpath-ng` — JSONPath traversal

### Section 2 — Spec YAML schema

Pydantic-validated; minimal at first.

```yaml
form:
  name: ORACLE_DCMB              # CSD file name (Chorus convention: uppercase, alphanumeric, ≤8 chars)
  title: Distribution Combination Code
  type: user_screen              # default; future: work_screen, lookup, etc.
  pages: 1                       # default 1

openapi_defaults:
  base_url: https://oracle.example.com/api/v1
  headers:
    Authorization: "${ORACLE_API_TOKEN}"   # env-var interpolation
  timeout_seconds: 30

fields:
  - code: DCMB                    # 4-char Chorus field code
    label: "Distribution Combination"
    control_type: combobox
    required: true
    binding:
      openapi_spec: ./oracle.json          # path relative to this YAML
      endpoint: /get_distribution_combination_codes
      method: GET                          # default GET
      values_path: $.codes[0].distro_combo_list
      value_field: value
      description_field: description

  - code: MEMO
    label: "Memo"
    control_type: text
    length: 60
    required: false

  - code: STAT
    label: "Status"
    control_type: combobox
    values:                                 # static — no binding
      - {value: A, description: Active}
      - {value: I, description: Inactive}
```

**Pydantic constraints:**
- `form.name` — regex `^[A-Z][A-Z0-9_]{0,7}$`
- `fields[].code` — regex `^[A-Z][A-Z0-9]{3}$`
- `fields[]` — exactly one of `binding` (dynamic) or `values` (static) for combobox; mutually exclusive
- `fields[].control_type` — `Literal["combobox", "text"]` for v0.1
- `openapi_defaults.headers` values — template strings with `${VAR}` substitution at fetch time

**Field types in v0.1:** `combobox` (bound + static), `text`. Sufficient for the Oracle case and most simple lookups. Add types as user cases demand.

**Env-var interpolation:** `${VAR}` only (no shell expansion, no defaults, no nesting). Missing env var → `SpecValidationError`, not silent empty string.

### Section 3 — Binding resolution (`binding.py`)

Happens AFTER spec validation, BEFORE emit. Per-binding flow:

```python
def resolve_binding(binding: BindingSpec, *, openapi_root: Path, fetcher: Fetcher) -> list[DomainValue]:
    # 1. Load and parse the OpenAPI spec
    spec = load_openapi(openapi_root / binding.openapi_spec)

    # 2. Find the endpoint; pick up base URL + method
    endpoint_def = spec["paths"][binding.endpoint][binding.method.lower()]

    # 3. Build the HTTP request
    base_url = binding.base_url_override or spec_default_base_url(spec) or form_defaults.base_url
    headers = merge_headers(spec, binding, form_defaults)  # form_defaults < binding > env-var-resolved

    # 4. Fetch
    response = fetcher.get(f"{base_url}{binding.endpoint}", headers=headers, timeout=binding.timeout_seconds)
    response.raise_for_status()
    payload = response.json()

    # 5. Apply JSONPath
    matches = jsonpath.parse(binding.values_path).find(payload)
    if not matches:
        raise BindingError(f"JSONPath {binding.values_path!r} returned no matches against response")

    # 6. Map to domain values
    extracted = matches[0].value
    if not isinstance(extracted, list):
        raise BindingError(f"JSONPath {binding.values_path!r} resolved to {type(extracted).__name__}, expected list")

    return [
        DomainValue(value=entry[binding.value_field], description=entry.get(binding.description_field, ""))
        for entry in extracted
    ]
```

**Fetcher abstraction (DI seam for tests):**

```python
class Fetcher(Protocol):
    def get(self, url: str, *, headers: dict, timeout: float) -> Response: ...

class HttpxFetcher: ...     # production, uses httpx.Client
class GoldenFetcher: ...    # tests, returns canned responses from disk fixtures
```

`build_form` accepts `fetcher: Fetcher = None` (default: `HttpxFetcher`). Tests inject `GoldenFetcher`. CLI uses default; `--no-fetch` injects a `GoldenFetcher` that errors on any binding lookup, so static-only specs work offline and bound specs fail clean.

**Validation done:**
- OpenAPI file exists and parses (JSON or YAML)
- Endpoint+method declared in the spec (mismatch → `BindingError`, not 404 at fetch time)
- JSONPath compiles
- Fetch succeeds (4xx/5xx → fail loudly, no partial form)
- JSONPath resolves to a list (not scalar, not empty)
- Every entry has the configured `value_field`

**Not done:**
- Response validation against OpenAPI schema (trust JSONPath)
- Retries (fail-fast)
- Auth beyond simple header-based

**Env-var interpolation** happens at fetch time. Missing env var → clear `BindingError("env var X required by ... is unset")`, not opaque HTTP 401.

### Section 4 — Emit (`emit.py` + `manifest.py`)

Thin assembler — wraps `chorus_forms` builders.

```python
def emit(spec: FormSpec, resolved_bindings: dict[FieldCode, list[DomainValue]], output_dir: Path) -> EmitResult:
    form = CsdForm(
        meta=FormMeta(
            file_name=spec.form.name,
            form_title=spec.form.title,
            form_type=spec.form.type,
            num_pages=spec.form.pages,
            dll_hooks=[],
        ),
        fields=[_spec_field_to_csd_field(f, resolved_bindings.get(f.code)) for f in spec.fields],
        groups=[],
        warnings=[],
    )
    csd_bytes = chorus_forms.builders.classic.build_csd(form)
    uxb_dict = chorus_forms.builders.uxb.build_uxb(form)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{spec.form.name}.csd").write_bytes(csd_bytes)
    (output_dir / f"{spec.form.name}.uxb.json").write_text(json.dumps(uxb_dict, indent=2), encoding="utf-8")
    (output_dir / f"{spec.form.name}_manifest.json").write_text(
        json.dumps(build_manifest(spec, resolved_bindings), indent=2), encoding="utf-8"
    )
    return EmitResult(...)
```

**Field translator** (`_spec_field_to_csd_field`) is the single seam between spec-schema and chorus_forms-schema. When new field types land (date, number), they're added here.

**Manifest schema:**

```json
{
  "generator": "chorus-form-builder",
  "generator_version": "0.1.0",
  "generated_at": "2026-05-23T14:32:01Z",
  "spec_path": "form.yaml",
  "spec_hash": "sha256:...",
  "form": {"name": "ORACLE_DCMB", "field_count": 3},
  "bindings": [
    {
      "field_code": "DCMB",
      "openapi_spec_path": "./oracle.json",
      "openapi_spec_hash": "sha256:...",
      "endpoint": "/get_distribution_combination_codes",
      "fetched_url": "https://oracle.example.com/api/v1/get_distribution_combination_codes",
      "fetched_at": "2026-05-23T14:32:00Z",
      "response_hash": "sha256:...",
      "value_count": 1847
    }
  ]
}
```

Makes "did this form actually get the values I think it did, when, from where?" answerable from the manifest alone.

**Task-1 validation item:** the implementer's first step is to import `chorus_forms.builders.classic.build_csd` and call it on a hand-constructed minimal `CsdForm` (one combobox, three static domain values), assert the output is non-empty bytes, optionally round-trip through `chorus_forms.parser.parse_csd_file` and confirm shape preservation. This validates the assumed builder API surface before anything else gets built on top.

### Section 5 — CLI + library surface

**Library API:**

```python
def build_form(
    spec_path: Path,
    output_dir: Path,
    *,
    fetcher: Fetcher | None = None,
) -> EmitResult:
    """Generate a Chorus form from a YAML spec."""
```

Single public entry point. Future shapes (`build_form_from_existing_csd`, etc.) add new top-level functions; this signature is frozen.

**CLI:**

```
chorus-form-build --spec PATH --output PATH [--quiet|--verbose] [--no-fetch]
```

Exit codes:
- `0` — success
- `1` — spec validation failure
- `2` — binding (fetch / JSONPath) failure
- `3` — emit failure
- `4` — IO failure (output dir, etc.)

Entry point via `pyproject.toml`:
```toml
[project.scripts]
chorus-form-build = "chorus_form_builder.cli:main"
```

`uv tool install agent-tool-chorus-form-builder` → `chorus-form-build` on `PATH`.

**`--no-fetch`** — skip all OpenAPI fetches; static-only specs proceed normally, any binding present errors clean. Lets CI / golden-test workflows run without network.

**No subcommands, no daemon, no watch mode.**

### Section 6 — Tests + error handling

**Test layers:**

| Layer | What | Count target |
|---|---|---|
| A: Pure unit | Pydantic validation, JSONPath resolution, field translator | ~8 |
| B: Goldens | 3 fixture pairs (`oracle_dcmb`, `static_combo`, `text_plus_combo`) — byte-exact on .csd, structural on .uxb.json, normalized-fields on manifest | 3 |
| C: Round-trip | Emit → parse via `chorus_forms.parser.parse_csd_file` → assert shape preserved | 1 |
| D: CLI smoke | `subprocess.run(["chorus-form-build", ...])`, check exit code + files exist | 1 |

Total: ~13 tests for v0.1. `pytest` standard runner (no async — fetches are sync).

**Exception hierarchy:**

```python
class FormBuilderError(Exception): ...
class SpecValidationError(FormBuilderError): ...
class BindingError(FormBuilderError): ...
class EmitError(FormBuilderError): ...
class IOError(FormBuilderError): ...
```

CLI maps to exit codes. Library callers catch the same hierarchy.

**Error message style:**
- Always name the offending input (field code, JSONPath expression, env var name)
- Always say expected vs. seen
- No bare tracebacks at CLI boundary

Example: `BindingError: field DCMB: JSONPath '$.codes[0].distro_combo_list' resolved to type 'dict', expected 'list'. Check the OpenAPI response shape against the binding's values_path.`

**Verbose logging:** `--verbose` shows spec-loaded → per-field type+source → per-binding fetch URL+result → emit ✓ → output files. Default: silent on success, error-only on failure. One-line success summary: `Wrote ORACLE_DCMB.csd (3 fields, 1847 domain values for DCMB) → ./out/`.

## Files in this ship

New files in `D:/agent-tool-chorus-form-builder/`:

| File | Purpose | Size estimate |
|---|---|---|
| `pyproject.toml` | uv-installable package | ~40 lines |
| `README.md` | quickstart + status | (already written) |
| `src/chorus_form_builder/__init__.py` | exports `build_form` | ~10 lines |
| `src/chorus_form_builder/spec.py` | Pydantic models | ~80 lines |
| `src/chorus_form_builder/binding.py` | OpenAPI fetch + JSONPath | ~80 lines |
| `src/chorus_form_builder/emit.py` | CsdForm assembly + writes | ~70 lines |
| `src/chorus_form_builder/manifest.py` | provenance JSON | ~40 lines |
| `src/chorus_form_builder/cli.py` | argparse + exit-code mapping | ~50 lines |
| `tests/test_spec.py` | Pydantic validation | ~50 lines |
| `tests/test_binding.py` | JSONPath cases | ~50 lines |
| `tests/test_emit.py` | translator unit tests + round-trip | ~50 lines |
| `tests/test_cli.py` | CLI smoke | ~30 lines |
| `tests/goldens/oracle_dcmb/{form.yaml, oracle.json, response.json, ORACLE_DCMB.csd, ORACLE_DCMB.uxb.json, ORACLE_DCMB_manifest.json}` | golden fixture | (binary + JSON) |
| `tests/goldens/static_combo/{...}` | static-values golden | (binary + JSON) |
| `tests/goldens/text_plus_combo/{...}` | multi-field golden | (binary + JSON) |

Total source ≈ 400 LOC + ~180 LOC test + 3 golden fixtures.

## Risks

| Risk | Mitigation |
|---|---|
| `chorus_forms.builders.classic.build_csd` may not work on a hand-constructed `CsdForm` (only tested via parse-then-build round-trips in chorus_forms's own tests) | First implementation task validates this assumption with a minimal CsdForm. If it doesn't work, the spec needs revision before continuing — either add a `CsdForm` factory in chorus_forms, or take a different IR-construction path. |
| OpenAPI spec ambiguity — multiple endpoints, complex inheritance, `$ref` chains | v0.1 only handles top-level endpoint definitions with response bodies that match the `values_path` shape. Complex `$ref` traversal is out of scope; if the user's OpenAPI uses heavy `$ref`, they may need to manually flatten before passing it in. Future iteration could add `openapi-core` or `prance` for resolution. |
| Golden tests brittle to whitespace / ordering in JSON output | UXB and manifest goldens use structural comparison (dict-equal after normalizing dynamic fields like timestamps, hashes). Only the binary .csd is byte-exact. |
| Stale-snapshot complaints — user regenerates form, gets different values, doesn't notice | The manifest's `response_hash` + `value_count` gives a diff-able provenance. If a CI step ever cares about "no upstream drift since last generation," it can compare manifests. Not built into v0.1, but the data is there. |
| Env-var leaks in error messages — auth tokens appearing in stack traces | All `${VAR}` substitution happens in `binding.py` at the moment of header construction. Errors never include the substituted value, only the var name. |
