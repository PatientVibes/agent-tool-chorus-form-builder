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
