# chorus-form-builder — sub-project C v0.1: Procedure JS generator (design)

**Date:** 2026-05-23
**Status:** Approved (brainstorm)
**Scope:** First ship — Classic-dialect procedure JS for conditional show/hide, enable/disable, required-toggling, and default-value rules.

## Goal

Extend `chorus-form-builder` so a YAML form spec can declare conditional show/hide / enable/disable / required-toggling / default-value rules. The generator emits Classic XML CSD with the rules baked into `<customRules>` as a JS string, plus a `<jsFile>` reference to a small `awdForm.js` shim shipped with the package.

## Sub-project context

This is sub-project **C** of the larger 5-piece form-generation track. v0.1 (sub-projects **A + B**) shipped 2026-05-23 as [PR #1 on github.com/PatientVibes/agent-tool-chorus-form-builder](https://github.com/PatientVibes/agent-tool-chorus-form-builder/pull/1) — declarative YAML → `.csd` + `.uxb.json` + provenance manifest, with optional bake-time OpenAPI binding for combobox `domain_values`.

Sub-project C targets the **Classic dialect only**. UXB handler generation is explicitly deferred to a later ship — the UXB JSON output continues to ship without handlers in v0.1 (a documented limitation; see Risks).

Future sub-projects (out of scope for this design):

- **C v0.2** — bridge from the awdForm shim to the real `/awd/forms/lib/` runtime, including a Chorus dev-soak verification recipe
- **D. Text-prompt → CsdForm adapter** — LLM produces CsdForm from natural language
- **E. Image → CsdForm adapter** — vision model interprets a screenshot / paper form

## Non-goals (v0.1)

- **UXB handler generation.** UXB output ships handler-less; manifest reports `uxb_handlers_emitted: false`.
- **Cross-field comparisons.** `STAT == FROM` is not supported. All conditions compare a field reference against a literal.
- **Arithmetic in conditions.** `AMTV * 2 > 100` is not supported.
- **Truthy / presence checks.** `MEMO` as a bare field reference (meaning "non-empty") is not supported. Use explicit `MEMO != ""` if needed against an unbound text field.
- **Regex conditions.** `ACCT =~ /^\d{10}$/` is deferred to a future tier.
- **Free-form JS escape hatch.** Users cannot drop raw JS into the spec. All conditions go through the parser. (Hand-editing the emitted `.csd` is always possible, but that bypasses our pipeline.)
- **Cascading rules from `setValue`.** Default-value writes do NOT re-trigger field-change events in v0.1. Cascades require a careful design and are deferred.
- **Real Chorus runtime verification.** v0.1 ships against a stubbed shim; the bridge to the production runtime is the v0.2 milestone.
- **CLI flags.** `chorus-form-build` gains no new flags. Rules are entirely spec-driven.

## Design

### Section 1 — Architecture

Single-repo, single-CLI extension. The form-builder package gains one new module (`procedures.py`), one new package-data file (`awdForm.js`), and a thin integration point in `emit.py`. Public API and CLI flags are unchanged.

```
chorus-form-builder v0.1            +    sub-project C additions
─────────────────────────────────         ─────────────────────────
spec.py   (Pydantic)                +    new FieldSpec attrs +
                                          model_validators
binding.py                          (no change)
emit.py   (CsdForm assembly)        +    populates customRules + includeList
                                          + copies awdForm.js to output_dir
manifest.py                         +    records rules + uxb_handlers_emitted
__init__.py / cli.py                (no change to public API or flags)
                                    +    procedures.py — NEW MODULE
                                    +    src/chorus_form_builder/runtime/
                                          awdForm.js — NEW: shim shipped
                                          via includeList + package data
                                    +    tests/js_runtime/ — NEW: Node-based
                                          shim runner driving synthetic events
```

**Key boundary**: `procedures.py` is the only Python module that knows JS exists. The rest of the pipeline treats its output as opaque strings (DSL → JS) that flow into the existing `CsdForm.customRules` slot and `includeList`. The codegen is a pure function over `list[FieldSpec]`.

**Data flow**:

```
spec.yaml → load_spec → FormSpec (Pydantic; rules pre-parsed)
                    ↓
        (existing) resolve_bindings → resolved_bindings
                    ↓
        (existing) CsdForm assembly
                    ↓
        procedures.compile_rules(spec.fields)
                    ↓
        attach: CsdForm.custom_rules + CsdForm.include_list
                    ↓
        (existing) Classic XML chain → bytes
        (existing) UXB JSON chain    → dict (NO rules embedded as JS in v0.1)
                    ↓
        copy awdForm.js → output_dir/   (only when there are rules)
                    ↓
        build_manifest now includes "rules" + "uxb_handlers_emitted"
```

### Section 2 — DSL schema + condition grammar

**YAML additions** (per-field, all optional):

```yaml
fields:
  - code: STAT
    label: Status
    control_type: combobox
    values:
      - {value: A, description: Active}
      - {value: R, description: Rejected}
      - {value: P, description: Pending}

  - code: MEMO
    label: "Rejection memo"
    control_type: text
    length: 200
    visible_when: STAT == "R"
    required_when: STAT == "R"

  - code: ACCT
    label: Account
    control_type: text
    length: 10
    enabled_when: STAT in ["A", "P"]

  - code: BATC
    label: Batch
    control_type: text
    length: 6
    default_when: STAT == "A"
    default_value: "BATCH-AUTO"
```

**Pydantic additions to `FieldSpec`**:

| Field | Type | Notes |
|---|---|---|
| `visible_when` | `Optional[str]` | None = always visible |
| `enabled_when` | `Optional[str]` | None = always enabled |
| `required_when` | `Optional[str]` | None = uses the existing `required: bool` |
| `default_when` | `Optional[str]` | None = no default-set rule |
| `default_value` | `Optional[str \| int \| float \| bool]` | Required if `default_when` is set; forbidden otherwise (enforced by `model_validator`) |

**Condition grammar** (Tier 2 — equality + numeric ordering + membership + boolean):

```
expr         := or_expr
or_expr      := and_expr ( "or" and_expr )*
and_expr     := not_expr ( "and" not_expr )*
not_expr     := "not" comparison | comparison
comparison   := field_ref op literal
              | field_ref "in" "[" literal_list "]"
              | field_ref "not in" "[" literal_list "]"
              | "(" expr ")"
op           := "==" | "!=" | "<" | ">" | "<=" | ">="
field_ref    := [A-Z][A-Z0-9]{3}      # field code, e.g. STAT
literal      := STRING | NUMBER | "true" | "false" | "null"
literal_list := literal ( "," literal )*
STRING       := '"' [^"]* '"' | "'" [^']* "'"
NUMBER       := -?\d+(\.\d+)?
```

**Examples**:

- `STAT == "A"` ✓
- `STAT != "R" and AMTV > 100` ✓
- `STAT in ["A", "P"]` ✓
- `not (STAT == "R")` ✓
- `STAT or PAID` ✗ — bare field refs not allowed
- `AMTV * 2 > 100` ✗ — no arithmetic
- `STAT == FROM` ✗ — no field-to-field comparison

**Operator precedence**: matches Python — `or` (lowest) < `and` < `not` < comparison ops < `in` / `not in`. Test fixtures lock this with explicit cases (`a or b and c` ≡ `a or (b and c)`).

**Parser implementation**: ~120 LOC hand-rolled recursive-descent (no PLY, no Lark). Produces a small typed AST. Validation errors (unknown field code, bad literal, dangling `and`) surface as `SpecValidationError` at `load_spec` time via a `model_validator` that invokes `parse_rule_expr` on each non-None rule string.

**Field-reference scope**: a rule can reference any field declared in the same `fields:` list, before or after the field carrying the rule. Unknown field code → `SpecValidationError(f"rule on {field.code}: references unknown field {ref!r}")` at load time. Catches typos before they become silent never-firing rules.

**`default_value` semantics**: fires on form-open AND on field-change of any field referenced in `default_when`, **only if the target field is currently empty/null**. Standard "set if not already set" pattern; protects against clobbering user input or persisted data.

### Section 3 — Mini-runtime API + generated JS shape

**`awdForm.js` shim API** (the ~80-LOC runtime shipped with v0.1):

```javascript
window.awdForm = {
  // State accessors
  getValue(code),       // current value of field <code>
  isEmpty(code),        // true if value is "", null, or undefined

  // State mutators (stubbed in v0.1; real DOM calls land in C v0.2 bridge)
  show(code),
  hide(code),
  enable(code),
  disable(code),
  setRequired(code, b),
  setValue(code, v),    // does NOT fire a field-change event — see Risks

  // Event hookup
  on(eventName, fn),    // events: "form-open", "field-change:<CODE>"
};
```

In v0.1 the mutator bodies delegate to a `__awdFormHost` global that the test runner supplies. The v0.2 bridge swaps that for real Chorus DOM calls without changing the public surface.

**Generated `customRules` JS shape** — for the example spec above:

```javascript
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO visible_when STAT == "R"
    awdForm[(stat === "R") ? "show" : "hide"]("MEMO");
    // MEMO required_when STAT == "R"
    awdForm.setRequired("MEMO", stat === "R");
    // ACCT enabled_when STAT in ["A", "P"]
    awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");
    // BATC default_when STAT == "A" (default_value "BATCH-AUTO", set-if-empty)
    if ((stat === "A") && awdForm.isEmpty("BATC")) {
      awdForm.setValue("BATC", "BATCH-AUTO");
    }
  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
```

**Codegen properties**:

| Property | Value |
|---|---|
| Function granularity | Single `applyAll()` reads referenced field values once at top, then applies each rule. O(rules) per change. |
| Event subscriptions | `form-open` always; `field-change:<CODE>` for each unique referenced field |
| `setRequired(false)` for non-rule fields | Not emitted — the existing `required: bool` on FieldSpec governs the static case. |
| `default_value` semantics | Set-if-empty (guarded by `isEmpty`) — prevents clobbering user input. |
| Determinism | Identical input → identical JS bytes. Enables byte-exact `.csd` goldens. |
| Self-documentation | One comment line per rule with the literal source so the JS is readable in a debugger. |

**`<includeList>` wiring**: `<jsFile>awdForm.js</jsFile>` is added to the CsdForm's `includeList` only when at least one rule exists. The Chorus runtime resolves these against `/awd/forms/lib/`, so users deploy `awdForm.js` there once site-wide. The CLI also copies `awdForm.js` from package data into the output dir so users have the file to deploy.

**Zero-rules behavior**: if a form declares no rules, the generator emits empty `customRules`, no `awdForm.js` in includeList, no `awdForm.js` copy. Output is byte-identical to v0.1 form-builder for handler-free specs — zero behavior change for existing users.

### Section 4 — Emit pipeline integration

**`procedures.py` internal layout**:

| Function | Purpose |
|---|---|
| `parse_rule_expr(source: str) -> RuleAST` | Recursive-descent parser; ~120 LOC. Returns typed AST (`Eq`, `Neq`, `Lt`, `Gt`, `Le`, `Ge`, `In`, `NotIn`, `And`, `Or`, `Not`, `Paren`, `FieldRef`, `Literal`). Errors → `SpecValidationError`. |
| `validate_rule(ast, known_field_codes) -> None` | Walks the AST. Unknown field refs → `SpecValidationError` naming the rule + the missing code. |
| `compile_rules(fields: list[FieldSpec]) -> CompiledRules` | Top-level. Returns dataclass with `custom_rules_js`, `include_list`, `rule_summary`. |
| `_render_condition(ast) -> str` | AST → JS expression. |
| `_unique_referenced_fields(rules) -> list[str]` | Used for `var stat = awdForm.getValue("STAT")` block + `field-change:<CODE>` subscriptions. |

**`emit.py` change** (minimal, ~15 added lines):

```python
# after CsdForm assembly, before classic/UXB chains:
from chorus_form_builder import procedures
compiled = procedures.compile_rules(spec.fields)
form.custom_rules = compiled.custom_rules_js
form.include_list.extend(compiled.include_list)

# after the chains, if rules exist, copy shim to output_dir:
if compiled.custom_rules_js:
    shim_src = Path(__file__).parent / "runtime" / "awdForm.js"
    (output_dir / "awdForm.js").write_bytes(shim_src.read_bytes())
```

**`manifest.py` additions**:

```json
{
  "rules": [
    {"field_code": "MEMO", "kind": "visible_when",  "source": "STAT == \"R\""},
    {"field_code": "MEMO", "kind": "required_when", "source": "STAT == \"R\""},
    {"field_code": "ACCT", "kind": "enabled_when",  "source": "STAT in [\"A\", \"P\"]"},
    {"field_code": "BATC", "kind": "default_when",  "source": "STAT == \"A\"",
                                  "default_value": "BATCH-AUTO"}
  ],
  "uxb_handlers_emitted": false,
  "runtime_validated": false,
  "shim_version": "0.1.0"
}
```

`runtime_validated: false` is the v0.1 → v0.2 boundary — it flips to `true` once the Chorus dev-soak verification recipe (Risks) is run and passes.

### Section 5 — Tests + error handling

**Test layers**:

| Layer | What | Count |
|---|---|---|
| **A: parser unit tests** | `parse_rule_expr` against valid + invalid expressions across the Tier-2 grammar. Each grammar production gets at least one passing + one failing case. Operator-precedence cases (`a or b and c`) included. | ~12 |
| **B: codegen unit tests** | Given a small `FieldSpec` list with a known rule set, assert the emitted JS string equals a golden (whitespace-normalized). Covers each rule kind + multi-rule + multi-field. | ~10 |
| **C: Node shim integration** | Boot the emitted customRules JS against the awdForm shim in Node + a `__awdFormHost` recorder. Drive synthetic `form-open` + `field-change:<CODE>` events. Assert the mutator-call sequence matches expectations. | ~5 |
| **D: golden form** | New `tests/goldens/with_rules/` — full v0.1 form with all 4 rule kinds. Byte-exact `.csd`, structural `.uxb.json`, structural manifest (with new `rules` block). | 1 |

Layer C runs Node via subprocess from pytest. If `node` isn't on PATH, those tests `pytest.skip()` with a clear message; the Python suite still runs.

**Exception hierarchy** — no new classes. Rule parse and validation errors surface as `SpecValidationError` (the existing class), since they happen during `load_spec` and the failure is fundamentally a spec-shape problem from the user's perspective.

**Error message style**:

- Always name the offending field and the offending rule kind (e.g. `field MEMO: visible_when: unknown field reference 'STAT2'`)
- Always say expected vs seen for parser errors (e.g. `expected literal after '==' but got 'and' at position 12`)
- No bare tracebacks at CLI boundary (the existing exit-code chain handles this)

**Verbose output**: the existing `--verbose` flag adds per-binding resolution lines. v0.1 of sub-project C does NOT extend `--verbose` to print per-rule compilation — the manifest's `rules` array already captures that information.

## Files in this ship

New files under `D:/agent-tool-chorus-form-builder/`:

| File | Purpose | Size estimate |
|---|---|---|
| `src/chorus_form_builder/procedures.py` | DSL parser + codegen | ~250 LOC |
| `src/chorus_form_builder/runtime/awdForm.js` | Mini-runtime shim shipped alongside emitted forms | ~80 LOC |
| `src/chorus_form_builder/runtime/__init__.py` | Empty marker so package-data globs apply | ~5 LOC |
| `tests/test_procedures.py` | Parser + codegen unit tests (Layers A + B) | ~180 LOC |
| `tests/js_runtime/runner.js` | Node shim runner | ~50 LOC |
| `tests/js_runtime/host_recorder.js` | `__awdFormHost` stub recording mutator calls | ~30 LOC |
| `tests/js_runtime/test_cases/*.js` | One file per Layer-C scenario | ~5 × 30 LOC |
| `tests/test_js_runtime.py` | pytest wrapper invoking Node; skips if `node` missing | ~80 LOC |
| `tests/goldens/with_rules/{form.yaml, *.csd, *.uxb.json, *_manifest.json, awdForm.js}` | New golden fixture | (fixtures) |

Modified files:

| File | Change |
|---|---|
| `src/chorus_form_builder/spec.py` | Add 5 optional `FieldSpec` attributes + `model_validator` enforcing `default_when ↔ default_value` pairing + `model_validator` calling `procedures.parse_rule_expr` on each non-None rule string |
| `src/chorus_form_builder/emit.py` | After CsdForm assembly call `procedures.compile_rules`, attach JS to `CsdForm.custom_rules`, push `<jsFile>awdForm.js</jsFile>` into `CsdForm.include_list` (when rules exist), copy `awdForm.js` from package data to `output_dir/` |
| `src/chorus_form_builder/manifest.py` | Add `rules`, `uxb_handlers_emitted`, `runtime_validated`, `shim_version` fields |
| `pyproject.toml` | Extend package-data: `"runtime/*.js"` |
| `README.md` | New "Rules" section with the running example + one-time `/awd/forms/lib/awdForm.js` deployment step |
| `tests/test_spec.py` | New tests for the 5 attributes + pairing validator + rule-string parse-fail propagation |
| `tests/test_emit.py` | New tests: rule-free form emits empty customRules + no includeList entry + no awdForm.js copy; rule-bearing form emits expected attachments |
| Existing v0.1 goldens | Regenerate after the manifest schema bump (empty `rules: []` + `uxb_handlers_emitted: false` defaults appear in all manifests) |

Total new source ≈ 330 LOC; modified source ≈ 100 LOC; new tests ≈ 280 LOC + 5 small JS test files + 1 new golden fixture.

## Risks

| Risk | Mitigation |
|---|---|
| **The Chorus minified runtime doesn't expose the hooks our shim assumes** (`form-open`, `field-change:<CODE>` events, the host-call methods). v0.1 ships against a stubbed shim, so a real-runtime mismatch isn't caught until the v0.2 bridge. | Manifest carries `runtime_validated: false` until a Chorus dev-soak verification is performed. Verification recipe (deferred to v0.2): load a generated `.csd` into a dev-soak environment, manually trigger field changes, confirm visibility / enabled / required toggle. Once that passes, the C v0.2 ship sets the flag to `true`. |
| **DSL grammar ambiguity around operator precedence.** `a or b and c` should bind as `a or (b and c)`. Hand-rolled parsers often grow precedence bugs. | Layer-A tests include explicit precedence cases with expected ASTs. Precedence follows Python conventions (`or` < `and` < `not` < comparison < `in`) since users will reach for Python semantics. |
| **Field-reference scope mistakes** — typo `MEM0` instead of `MEMO`. Catches at `load_spec`; but a typo that coincidentally matches another existing field code (`FROM` vs `FORM`) silently binds to the wrong field. | Manifest's `rules` array exposes the parsed references for code-review scrutiny. Future v0.2 could add a stricter declared-references mode. |
| **`setValue` triggering infinite cascading rules** — if a default-value set naively fired a field-change event, anything depending on the target field would re-trigger, recursively. | The shim documents that `setValue` does NOT fire a field-change event. Codegen relies on this. Layer-C tests assert no cascading event fires when a default is set. The v0.2 bridge to the real Chorus runtime must enforce this contract too. |
| **awdForm.js byte drift across releases** — the shim ships from package data; a v0.1.1 with a different shim could break deployed forms that referenced the v0.1.0 shim until redeployed. | Shim file carries its semver inline (`/* awdForm.js v0.1.0 */`). Manifest records `shim_version` emitted alongside the form. Future v0.2 emits a versioned filename (`awdForm-0.2.0.js`) so multiple versions can coexist in `/awd/forms/lib/`. |
| **UXB JSON output advertising rule data the UXB runtime ignores.** The UXB JSON serialization includes the FieldSpec attributes (`visible_when` etc.) as plain data, but the UXB runtime doesn't honor them in v0.1. A user reading the UXB JSON might assume the rules are live. | Manifest carries `uxb_handlers_emitted: false`. README's Limits section: "UXB output preserves rule declarations as raw fields for round-trip purposes; the UXB runtime does NOT execute them in v0.1." Future v0.2-UXB ship sets the flag to `true`. |
| **Golden churn from manifest schema bump** — adding `rules: []` + `uxb_handlers_emitted: false` + `runtime_validated: false` + `shim_version: "0.1.0"` defaults to existing v0.1 form manifests causes them to differ on byte-comparison. | Regenerate goldens (`REGENERATE_GOLDENS=1 pytest tests/test_goldens.py`) as part of this ship. Commit the regenerated artifacts. Document this in the C v0.1 PR body so a reviewer sees it's intentional. |
