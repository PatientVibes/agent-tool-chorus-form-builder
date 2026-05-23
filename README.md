# agent-tool-chorus-form-builder

Generate Chorus forms (Classic XML `.csd` + UXB JSON) from a declarative YAML spec, with optional bake-at-generation-time binding to OpenAPI endpoints.

## Quick start

```bash
# Install (run from a clone of this repo)
uv tool install --editable .

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

## Rules (conditional show/hide, etc.)

Form fields can carry optional rule attributes that drive conditional behavior at runtime:

```yaml
fields:
  - code: STAT
    label: Status
    control_type: combobox
    values:
      - {value: A, description: Active}
      - {value: R, description: Rejected}

  - code: MEMO
    label: "Rejection memo"
    control_type: text
    length: 200
    visible_when: STAT == "R"     # only show when STAT is Rejected
    required_when: STAT == "R"    # required only in that case

  - code: ACCT
    label: Account
    control_type: text
    length: 10
    enabled_when: STAT in ["A", "P"]   # editable for Active or Pending

  - code: BATC
    label: Batch
    control_type: text
    length: 6
    default_when: STAT == "A"
    default_value: "BATCH-AUTO"        # set-if-empty when STAT becomes Active
```

When the spec contains any rules, the generated `.csd` carries a `<customRules>` block of compiled JavaScript plus a `<jsFile>awdForm.js</jsFile>` entry in `<includeList>`. A copy of `awdForm.js` (the mini-runtime shim) is also written next to the `.csd` for deployment.

**Condition grammar** (Tier 2, Python-style operator precedence):

- `==`, `!=`, `<`, `>`, `<=`, `>=` against string / numeric / boolean / null literals
- `in [...]` and `not in [...]` membership
- `and`, `or`, `not`, parens
- Field references must be 4-character uppercase codes resolving to a field in the same form

**Deployment** (one-time per environment): copy `awdForm.js` into `/awd/forms/lib/` on the Chorus server so the runtime can resolve the `<jsFile>` reference site-wide.

**Limits in v0.1**: UXB JSON output does not honor rules (`uxb_handlers_emitted: false` in the manifest). `default_value` rules are set-if-empty only (no clobber). `setValue` does not cascade into field-change events. The shim is documented but not yet bridged to the live Chorus runtime (`runtime_validated: false` until a dev-soak verification recipe runs as part of C v0.2).

## Output

For each run, writes three files into the output directory:
- `{form.name}.csd` — Classic XML, deployable to Chorus today
- `{form.name}.uxb.json` — UXB JSON form representation
- `{form.name}_manifest.json` — provenance (generator version, timestamps, binding endpoints, value counts)

## Limits (v0.1)

- Field types: `combobox` (bound or static) and `text` only. Date, number, etc. add when a real case arrives.
- OpenAPI: 3.0 only.
- Binding: bake-at-generation only. Runtime-bind via JS procedures is a future sub-project.
- Auth: bearer / custom headers via `${VAR}` env-var interpolation; no OAuth flow.
- Single form per invocation.

## Exit codes (CLI)

- 0 — success
- 1 — spec validation failure
- 2 — binding (fetch / JSONPath) failure
- 3 — emit failure (`chorus_forms` builder rejected the form)
- 4 — IO failure (output dir, etc.)
- 5 — unexpected error (anything else; should not happen in normal use)

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

To regenerate golden fixtures after a deliberate output change:

```bash
REGENERATE_GOLDENS=1 .venv/Scripts/python.exe -m pytest tests/test_goldens.py
```

## Sibling tools

Part of the `agent-tool-*` ecosystem; see `D:/ai-agents/CLAUDE.md` for the catalog. Related:

- `agent-harness-chorus-csd-analyzer` — the inverse direction (parse + analyze existing CSDs)
- `agent-tool-chorus-v1-client` — the Chorus REST client (used by the analyzer; not used by this tool yet but a natural future composition for runtime-bound combos)
- `chorus-forms` (private) — the IR + XML/UXB builders this tool wraps
