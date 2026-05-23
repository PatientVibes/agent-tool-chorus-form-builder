# agent-tool-chorus-form-builder

Generate Chorus forms (Classic XML `.csd` + UXB JSON) from a declarative YAML spec, with optional bake-at-generation-time binding to OpenAPI endpoints.

## Status

**v0.1 in design.** Spec landed; implementation pending. See [docs/superpowers/specs/](docs/superpowers/specs/).

## What it does

- Takes a single YAML spec describing a Chorus form (metadata + fields + optional OpenAPI bindings)
- For combobox fields with an OpenAPI binding, fetches the endpoint once at generation time and embeds the snapshotted values as the combo's static `domain_values`
- Emits a deployable Chorus Classic `.csd` binary, a UXB JSON representation of the same form, and a provenance manifest

## Why

Quickly stand up Chorus forms whose dropdowns are populated from external systems (Oracle, etc.) without hand-writing the .csd binary or wiring runtime API calls through DLL hooks.

## Quick start

```bash
uv tool install --editable D:/agent-tool-chorus-form-builder

chorus-form-build --spec form.yaml --output ./out/
# Wrote ORACLE_DCMB.csd (3 fields, 1847 domain values for DCMB) → ./out/
```

## Sibling tools

Part of the `agent-tool-*` ecosystem; see `D:/ai-agents/CLAUDE.md` for the catalog. Related:

- `agent-harness-chorus-csd-analyzer` — the inverse direction (parse + analyze existing CSDs)
- `agent-tool-chorus-v1-client` — the Chorus REST client (used by the analyzer; not used by this tool yet but a natural future composition for runtime-bound combos)
- `chorus-forms` (private) — the IR + XML/UXB builders this tool wraps
