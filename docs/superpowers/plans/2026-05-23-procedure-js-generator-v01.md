# Procedure JS Generator v0.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `chorus-form-builder` so a YAML form spec can declare conditional `visible_when` / `enabled_when` / `required_when` / `default_when` rules. Generator emits Classic XML CSD with the rules baked into `<customRules>` as a JS string + ships an `awdForm.js` shim referenced via `<includeList>`.

**Architecture:** One new module (`procedures.py`) handling DSL parsing + JS codegen, one new package-data file (`awdForm.js`), and ~15 added lines in `emit.py` to attach the compiled JS + copy the shim. UXB output remains handler-less in v0.1 (documented limit). All rule validation happens at `load_spec` time so parse failures fail fast.

**Tech Stack:** Python 3.11+, Pydantic 2.x, plain-JS (ES5-compat) for the shim, Node.js (optional, for Layer-C integration tests via pytest subprocess). No new Python dependencies.

**Source spec:** [`docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md`](../specs/2026-05-23-procedure-js-generator-v01-design.md)

**Working directory for all tasks:** `D:/agent-tool-chorus-form-builder/`

---

## Repo state at start

```
D:/agent-tool-chorus-form-builder/
├── .gitattributes          # ✅ already committed (LF for .csd + JSON goldens)
├── .gitignore              # ✅
├── README.md               # ✅
├── pyproject.toml          # ✅
├── docs/superpowers/
│   ├── specs/2026-05-23-form-builder-v01-design.md             # ✅
│   ├── specs/2026-05-23-procedure-js-generator-v01-design.md   # ✅ this plan's spec
│   └── plans/2026-05-23-form-builder-v01.md                    # ✅
├── src/chorus_form_builder/
│   ├── __init__.py
│   ├── _types.py
│   ├── binding.py
│   ├── cli.py
│   ├── emit.py
│   ├── manifest.py
│   └── spec.py
├── tests/
│   ├── test_binding.py
│   ├── test_build_form.py
│   ├── test_chorus_forms_assumption.py
│   ├── test_cli.py
│   ├── test_emit.py
│   ├── test_goldens.py
│   ├── test_spec.py
│   └── goldens/{static_combo,oracle_dcmb,text_plus_combo}/...
└── .venv/                   # ready: chorus_forms + pydantic + pyyaml + httpx + jsonpath-ng + lxml + pytest
```

Branch: `master` (clean). All 56 tests pass.

**First action of any implementer:** `git checkout -b feat/v02-procedure-js` before any code work. Never work directly on master.

---

## File Structure

After all tasks land, the repo has the following additions/modifications:

| File | Lines (est.) | Responsibility |
|---|---|---|
| `src/chorus_form_builder/procedures.py` | ~250 | DSL parser + AST + JS codegen — the single seam to JS |
| `src/chorus_form_builder/runtime/__init__.py` | ~5 | Empty marker so `[tool.setuptools.package-data]` globs apply |
| `src/chorus_form_builder/runtime/awdForm.js` | ~80 | Mini-runtime shim shipped alongside emitted forms |
| `tests/test_procedures.py` | ~280 | Parser + codegen unit tests (Layers A + B) |
| `tests/js_runtime/host_recorder.js` | ~30 | `__awdFormHost` stub recording mutator calls |
| `tests/js_runtime/runner.js` | ~50 | Node shim runner (loads shim + customRules JS, drives events, emits JSON-line results) |
| `tests/js_runtime/test_cases/*.js` | ~5 × 35 | One file per Layer-C scenario |
| `tests/test_js_runtime.py` | ~80 | pytest wrapper invoking Node via subprocess; skips if `node` missing |
| `tests/goldens/with_rules/{form.yaml, *.csd, *.uxb.json, *_manifest.json, awdForm.js}` | (fixtures) | New golden fixture covering all 4 rule kinds |

Modified files:

| File | Change |
|---|---|
| `src/chorus_form_builder/spec.py` | Add 5 optional `FieldSpec` attributes + 2 `model_validator`s |
| `src/chorus_form_builder/emit.py` | After CsdForm assembly: call `compile_rules`, attach JS, copy shim to output_dir |
| `src/chorus_form_builder/manifest.py` | Add `rules`, `uxb_handlers_emitted`, `runtime_validated`, `shim_version` fields |
| `pyproject.toml` | Add `"runtime/*.js"` to package-data |
| `tests/test_spec.py` | New tests for the 5 attributes + pairing validator |
| `tests/test_emit.py` | New tests: rule-free form / rule-bearing form |
| `tests/test_goldens.py` | New `test_golden_with_rules` test |
| `tests/goldens/{static_combo,oracle_dcmb,text_plus_combo}/*_manifest.json` | Regenerated to include the new manifest fields with empty defaults |
| `README.md` | New "Rules" section + one-time `awdForm.js` deployment step |

Total new source ≈ 330 LOC, modified source ≈ 100 LOC, new tests ≈ 280 LOC + 5 small JS test files + 1 new golden fixture.

---

## Task 0: Validate chorus_forms API for `customRules` + `includeList` slots (TDD canary)

**Why this task exists:** Sub-project A+B's emit chain never populated the `customRules` or `includeList` slots on `CsdForm`. Before building the codegen + emit integration on top of those slots, verify:

1. `CsdForm` (or `FormMeta`?) has a settable field for the inline JS body
2. There's a settable field for the include-list of `<jsFile>` references
3. Setting them causes the Classic XML chain to emit `<customRules>JS</customRules>` and `<includeList><jsFile>NAME</jsFile></includeList>` correctly
4. The UXB chain doesn't crash when those slots are populated

If the chorus_forms API for these slots differs from what we assume, fix the test and STOP — adjust Task 5's emit integration before proceeding.

**Files:**
- Create: `tests/test_chorus_forms_rules_assumption.py`

- [ ] **Step 1: Write the failing assumption test**

Create `tests/test_chorus_forms_rules_assumption.py`:

```python
"""Regression-lock on chorus_forms' customRules + includeList API.

Sub-project C v0.1 emits a JS body into customRules and a single jsFile
reference into includeList. This test verifies those slots exist on the
chorus_forms CsdForm IR and that the Classic XML chain serializes them
into the expected XML elements.

If a future chorus_forms update changes the slot names or shape, this
test fails first and signals the design needs revision before downstream
emit work lands.
"""
from __future__ import annotations

import pytest

pytest.importorskip("chorus_forms", reason="chorus_forms required for these contract tests")


def _build_form_with_rules_slots():
    """Hand-build a minimal CsdForm with customRules + a jsFile include.

    The exact field names + nesting are what THIS TEST DISCOVERS. The
    initial assumption (per the chorus-forms-app TS schema at
    src/io/csd/parse.ts:259-336):
      - CsdForm.custom_rules: str    (top-level, snake_case in chorus_forms)
      - CsdForm.include_list: list[dict]  with {"js_file": str}
    Adjust if the actual chorus_forms shape differs; document the discovery
    in the test's docstring.
    """
    from chorus_forms.csd.models import CsdForm, FormMeta, FormField
    form = CsdForm(
        meta=FormMeta(
            file_name="RULESFRM",
            form_title="Rules Test Form",
            form_type="user_screen",
            num_pages=1,
        ),
        fields=[
            FormField(code="STAT", label="Status", control_type="text"),
        ],
        custom_rules="(function(awdForm){ /* hello */ })(window.awdForm);",
        include_list=[{"js_file": "awdForm.js"}],
    )
    return form


def test_csdform_accepts_custom_rules_and_include_list():
    """CsdForm exposes settable custom_rules + include_list fields."""
    form = _build_form_with_rules_slots()
    assert form.custom_rules.startswith("(function(awdForm)")
    assert form.include_list == [{"js_file": "awdForm.js"}]


def test_classic_xml_chain_emits_custom_rules_element():
    """When custom_rules is set, the emitted XML contains a non-empty
    <customRules> element with the JS body."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.core.xml_builder import build_user_screen
    from lxml import etree

    form = _build_form_with_rules_slots()
    envelope = build_user_screen(csd_to_user_screen(form))
    xml = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    xml_text = xml.decode("utf-8")

    assert "<customRules>" in xml_text, f"no <customRules> in: {xml_text[:500]}"
    assert "(function(awdForm)" in xml_text, "custom_rules content didn't reach XML"
    assert "</customRules>" in xml_text


def test_classic_xml_chain_emits_include_list_with_js_file():
    """When include_list has a jsFile entry, the emitted XML contains
    <includeList><jsFile>awdForm.js</jsFile></includeList>."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.core.xml_builder import build_user_screen
    from lxml import etree

    form = _build_form_with_rules_slots()
    envelope = build_user_screen(csd_to_user_screen(form))
    xml = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    xml_text = xml.decode("utf-8")

    assert "<includeList>" in xml_text, f"no <includeList> in: {xml_text[:500]}"
    assert "<jsFile>awdForm.js</jsFile>" in xml_text


def test_uxb_chain_does_not_crash_with_populated_rules_slots():
    """UXB JSON path should handle a CsdForm with custom_rules + include_list
    set, even though v0.1 of sub-project C doesn't emit handlers into UXB
    output. Specifically: no exception, returns a JSON-serializable dict."""
    import json
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model

    form = _build_form_with_rules_slots()
    doc = csd_to_uxb(form)
    design = to_design_model(doc, form_type=form.meta.form_type)
    dumped = design.model_dump(exclude_none=True)
    # Round-trips through json.dumps without raising
    json.dumps(dumped)
```

- [ ] **Step 2: Run the assumption tests**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_chorus_forms_rules_assumption.py -v 2>&1 | tail -15`

**Three possible outcomes:**

- **Outcome A (target): all 4 tests pass.** API works as assumed. Proceed to Step 3 (commit).

- **Outcome B: `CsdForm(...)` constructor rejects `custom_rules=` and/or `include_list=`.** Read `D:/chorus-repos/chorus-forms/src/chorus_forms/csd/models.py` to find the real field names + types. Likely candidates: `customRules` (camelCase) instead of `custom_rules`, or nested under `meta`, or `includes` instead of `include_list`. Adjust `_build_form_with_rules_slots()` accordingly, re-run. If the fields don't exist AT ALL — STOP and report BLOCKED; design needs revision.

- **Outcome C: tests pass for construction but XML emit doesn't include the expected elements.** Read `D:/chorus-repos/chorus-forms/src/chorus_forms/csd/adapter.py` + `D:/chorus-repos/chorus-forms/src/chorus_forms/core/xml_builder.py` to see what the Classic XML chain serializes. If the slots are silently dropped, that's a real chorus_forms gap — STOP and report BLOCKED.

- [ ] **Step 3: Commit (only if Step 2 outcome is A, OR after fixing the field names per B/C)**

```bash
git add tests/test_chorus_forms_rules_assumption.py
git commit -m "test: lock chorus_forms customRules + includeList API for sub-project C

Smoke tests asserting that CsdForm exposes settable custom_rules + include_list
fields and that the Classic XML chain serializes them into <customRules>
and <includeList><jsFile/></includeList> elements. UXB chain is also probed
to confirm it doesn't crash when those slots are populated (v0.1 of
sub-project C ships UXB handler-less but the slots still get set on the
shared CsdForm IR).

These are foundational assumptions of the sub-project C design. If a
future chorus_forms update breaks them, this test fails first."
```

---

## Task 1: `procedures.py` — Parser + AST (TDD)

**Files:**
- Create: `src/chorus_form_builder/procedures.py` (parser portion only — codegen lands in Task 3)
- Create: `tests/test_procedures.py` (parser portion only)

- [ ] **Step 1: Write the failing parser tests**

Create `tests/test_procedures.py`:

```python
"""Procedure DSL parser + codegen tests.

The parser turns a string condition (Tier 2 grammar — see spec §2) into
a typed AST. The codegen (Task 3) turns the AST into a JS expression
string. This file covers both layers; parser tests first.
"""
from __future__ import annotations

import pytest

from chorus_form_builder.procedures import (
    And,
    Eq,
    FieldRef,
    Ge,
    Gt,
    In,
    Le,
    Literal,
    Lt,
    Neq,
    Not,
    NotIn,
    Or,
    Paren,
    SpecValidationError,
    parse_rule_expr,
    validate_rule,
)


# --- happy-path: each grammar production ---

def test_parser_equality():
    ast = parse_rule_expr('STAT == "R"')
    assert ast == Eq(FieldRef("STAT"), Literal("R"))


def test_parser_inequality():
    ast = parse_rule_expr('STAT != "R"')
    assert ast == Neq(FieldRef("STAT"), Literal("R"))


def test_parser_numeric_comparison():
    assert parse_rule_expr("AMTV > 100") == Gt(FieldRef("AMTV"), Literal(100))
    assert parse_rule_expr("AMTV >= 100") == Ge(FieldRef("AMTV"), Literal(100))
    assert parse_rule_expr("AMTV < 100") == Lt(FieldRef("AMTV"), Literal(100))
    assert parse_rule_expr("AMTV <= 100") == Le(FieldRef("AMTV"), Literal(100))


def test_parser_membership():
    ast = parse_rule_expr('STAT in ["A", "P"]')
    assert ast == In(FieldRef("STAT"), [Literal("A"), Literal("P")])


def test_parser_not_in():
    ast = parse_rule_expr('STAT not in ["A", "P"]')
    assert ast == NotIn(FieldRef("STAT"), [Literal("A"), Literal("P")])


def test_parser_boolean_and():
    ast = parse_rule_expr('STAT == "A" and AMTV > 100')
    assert ast == And(
        Eq(FieldRef("STAT"), Literal("A")),
        Gt(FieldRef("AMTV"), Literal(100)),
    )


def test_parser_boolean_or():
    ast = parse_rule_expr('STAT == "A" or STAT == "P"')
    assert ast == Or(
        Eq(FieldRef("STAT"), Literal("A")),
        Eq(FieldRef("STAT"), Literal("P")),
    )


def test_parser_not():
    ast = parse_rule_expr('not (STAT == "R")')
    assert ast == Not(Paren(Eq(FieldRef("STAT"), Literal("R"))))


def test_parser_parens():
    ast = parse_rule_expr('(STAT == "A")')
    assert ast == Paren(Eq(FieldRef("STAT"), Literal("A")))


def test_parser_operator_precedence_or_lower_than_and():
    """`a or b and c` binds as `a or (b and c)` (Python convention)."""
    ast = parse_rule_expr('STAT == "A" or STAT == "B" and AMTV > 100')
    assert ast == Or(
        Eq(FieldRef("STAT"), Literal("A")),
        And(
            Eq(FieldRef("STAT"), Literal("B")),
            Gt(FieldRef("AMTV"), Literal(100)),
        ),
    )


def test_parser_string_literals_both_quote_styles():
    assert parse_rule_expr("STAT == 'R'") == Eq(FieldRef("STAT"), Literal("R"))
    assert parse_rule_expr('STAT == "R"') == Eq(FieldRef("STAT"), Literal("R"))


def test_parser_boolean_and_null_literals():
    assert parse_rule_expr('PAID == true') == Eq(FieldRef("PAID"), Literal(True))
    assert parse_rule_expr('PAID == false') == Eq(FieldRef("PAID"), Literal(False))
    assert parse_rule_expr('MEMO == null') == Eq(FieldRef("MEMO"), Literal(None))


# --- error paths ---

def test_parser_rejects_arithmetic():
    with pytest.raises(SpecValidationError) as exc:
        parse_rule_expr("AMTV * 2 > 100")
    assert "expected" in str(exc.value).lower() or "unexpected" in str(exc.value).lower()


def test_parser_rejects_bare_field_ref():
    """`STAT or PAID` would be 'STAT is truthy or PAID is truthy', but
    truthy/presence checks aren't in Tier 2. A bare field reference where
    a comparison was expected is a parse error."""
    with pytest.raises(SpecValidationError):
        parse_rule_expr("STAT or PAID")


def test_parser_rejects_field_to_field_comparison():
    """`STAT == FROM` is field-to-field — out of Tier 2 scope."""
    with pytest.raises(SpecValidationError) as exc:
        parse_rule_expr("STAT == FROM")
    msg = str(exc.value).lower()
    # Expected behaviour: parser sees FROM and tries to read it as a literal,
    # fails because field codes aren't valid literals.
    assert "literal" in msg or "expected" in msg


def test_parser_rejects_dangling_and():
    with pytest.raises(SpecValidationError):
        parse_rule_expr('STAT == "A" and ')


def test_parser_rejects_unclosed_paren():
    with pytest.raises(SpecValidationError):
        parse_rule_expr('(STAT == "A"')


def test_parser_rejects_unknown_op():
    with pytest.raises(SpecValidationError):
        parse_rule_expr('STAT === "A"')  # triple-equal isn't in the grammar


def test_parser_rejects_empty_in_list():
    """`STAT in []` is meaningless (the condition is always false) and almost
    certainly a typo. Parser rejects it — see _parse_literal_list which
    requires at least one literal."""
    with pytest.raises(SpecValidationError):
        parse_rule_expr("STAT in []")


# --- validate_rule: field-reference scope check ---

def test_validate_rule_accepts_known_fields():
    ast = parse_rule_expr('STAT == "A" and AMTV > 100')
    # Should not raise:
    validate_rule(ast, known_field_codes={"STAT", "AMTV", "MEMO"})


def test_validate_rule_rejects_unknown_field():
    ast = parse_rule_expr('XYZQ == "A"')
    with pytest.raises(SpecValidationError) as exc:
        validate_rule(ast, known_field_codes={"STAT", "MEMO"})
    assert "XYZQ" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_procedures.py -v 2>&1 | tail -10`

Expected: all 18 tests fail with `ImportError` — `chorus_form_builder.procedures` module doesn't exist yet.

- [ ] **Step 3: Implement the parser**

Create `src/chorus_form_builder/procedures.py`:

```python
"""Procedure DSL parser + codegen.

The parser turns a string condition (Tier 2 grammar — see spec §2) into
a typed AST. The codegen (Task 3 — compile_rules) turns the AST into
the JS body that goes into <customRules>.

Tier 2 grammar:
    expr         := or_expr
    or_expr      := and_expr ( "or" and_expr )*
    and_expr     := not_expr ( "and" not_expr )*
    not_expr     := "not" comparison | comparison
    comparison   := field_ref op literal
                  | field_ref "in" "[" literal_list "]"
                  | field_ref "not in" "[" literal_list "]"
                  | "(" expr ")"
    op           := "==" | "!=" | "<" | ">" | "<=" | ">="
    field_ref    := [A-Z][A-Z0-9]{3}
    literal      := STRING | NUMBER | "true" | "false" | "null"

Parser is recursive-descent. SpecValidationError surfaces grammar
violations + unknown field references; the existing SpecValidationError
class is reused so callers can catch one type for all spec-shape errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Union

from chorus_form_builder.spec import SpecValidationError


# --- AST nodes ---

LiteralValue = Union[str, int, float, bool, None]


@dataclass(frozen=True)
class FieldRef:
    """A 4-char field code reference."""
    code: str


@dataclass(frozen=True)
class Literal:
    value: LiteralValue


@dataclass(frozen=True)
class Eq:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class Neq:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class Lt:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class Gt:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class Le:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class Ge:
    left: FieldRef
    right: Literal


@dataclass(frozen=True)
class In:
    left: FieldRef
    right: list[Literal]


@dataclass(frozen=True)
class NotIn:
    left: FieldRef
    right: list[Literal]


@dataclass(frozen=True)
class And:
    left: object
    right: object


@dataclass(frozen=True)
class Or:
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    inner: object


@dataclass(frozen=True)
class Paren:
    inner: object


# --- tokenizer ---

_TOKEN_PATTERNS = [
    ("WS",         r"\s+"),
    ("NUM",        r"-?\d+(\.\d+)?"),
    ("STRING_DQ",  r'"([^"]*)"'),
    ("STRING_SQ",  r"'([^']*)'"),
    ("FIELD_REF",  r"[A-Z][A-Z0-9]{3}\b"),  # 4-char uppercase code, word-bounded
    ("OP",         r"==|!=|<=|>=|<|>"),
    ("LBRACK",     r"\["),
    ("RBRACK",     r"\]"),
    ("LPAREN",     r"\("),
    ("RPAREN",     r"\)"),
    ("COMMA",      r","),
    ("KW",         r"\b(?:and|or|not|in|true|false|null)\b"),
    ("OTHER",      r"."),  # catch-all for error reporting
]

_TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_PATTERNS)
)


@dataclass
class Token:
    kind: str
    text: str
    pos: int


def _tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(source):
        kind = m.lastgroup
        text = m.group()
        if kind == "WS":
            continue
        if kind == "OTHER":
            raise SpecValidationError(
                f"unexpected character {text!r} at position {m.start()} in rule {source!r}"
            )
        tokens.append(Token(kind, text, m.start()))
    return tokens


# --- parser ---

class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = _tokenize(source)
        self.pos = 0

    def _peek(self, offset: int = 0) -> Optional[Token]:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return None
        return self.tokens[idx]

    def _consume(self) -> Token:
        if self.pos >= len(self.tokens):
            raise SpecValidationError(
                f"unexpected end of expression in rule {self.source!r}"
            )
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind: str, text: Optional[str] = None) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != kind or (text is not None and tok.text != text):
            wanted = f"{kind}={text!r}" if text else kind
            got = f"{tok.kind}={tok.text!r} at position {tok.pos}" if tok else "end of expression"
            raise SpecValidationError(
                f"expected {wanted} but got {got} in rule {self.source!r}"
            )
        return self._consume()

    def parse(self) -> object:
        result = self._parse_or()
        if self.pos < len(self.tokens):
            extra = self.tokens[self.pos]
            raise SpecValidationError(
                f"unexpected trailing token {extra.text!r} at position {extra.pos} "
                f"in rule {self.source!r}"
            )
        return result

    def _parse_or(self) -> object:
        left = self._parse_and()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "KW" and tok.text == "or":
                self._consume()
                right = self._parse_and()
                left = Or(left, right)
            else:
                return left

    def _parse_and(self) -> object:
        left = self._parse_not()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "KW" and tok.text == "and":
                self._consume()
                right = self._parse_not()
                left = And(left, right)
            else:
                return left

    def _parse_not(self) -> object:
        tok = self._peek()
        if tok is not None and tok.kind == "KW" and tok.text == "not":
            self._consume()
            return Not(self._parse_comparison())
        return self._parse_comparison()

    def _parse_comparison(self) -> object:
        tok = self._peek()
        if tok is None:
            raise SpecValidationError(
                f"unexpected end of expression in rule {self.source!r}"
            )
        if tok.kind == "LPAREN":
            self._consume()
            inner = self._parse_or()
            self._expect("RPAREN")
            return Paren(inner)
        if tok.kind != "FIELD_REF":
            raise SpecValidationError(
                f"expected field reference but got {tok.text!r} at position {tok.pos} "
                f"in rule {self.source!r}"
            )
        field = FieldRef(self._consume().text)

        nxt = self._peek()
        if nxt is None:
            raise SpecValidationError(
                f"expected comparison after field {field.code!r} in rule {self.source!r}"
            )

        # `in` / `not in`
        if nxt.kind == "KW" and nxt.text == "in":
            self._consume()
            self._expect("LBRACK")
            items = self._parse_literal_list()
            self._expect("RBRACK")
            return In(field, items)
        if nxt.kind == "KW" and nxt.text == "not":
            self._consume()
            self._expect("KW", "in")
            self._expect("LBRACK")
            items = self._parse_literal_list()
            self._expect("RBRACK")
            return NotIn(field, items)

        # binary op
        if nxt.kind != "OP":
            raise SpecValidationError(
                f"expected comparison operator after field {field.code!r} but got "
                f"{nxt.text!r} at position {nxt.pos} in rule {self.source!r}"
            )
        op_tok = self._consume()
        right = self._parse_literal()
        op_map = {
            "==": Eq,
            "!=": Neq,
            "<": Lt,
            ">": Gt,
            "<=": Le,
            ">=": Ge,
        }
        return op_map[op_tok.text](field, right)

    def _parse_literal_list(self) -> list[Literal]:
        items = [self._parse_literal()]
        while self._peek() and self._peek().kind == "COMMA":
            self._consume()
            items.append(self._parse_literal())
        return items

    def _parse_literal(self) -> Literal:
        tok = self._peek()
        if tok is None:
            raise SpecValidationError(
                f"expected literal but reached end of expression in rule {self.source!r}"
            )
        if tok.kind == "STRING_DQ":
            self._consume()
            return Literal(tok.text[1:-1])  # strip quotes
        if tok.kind == "STRING_SQ":
            self._consume()
            return Literal(tok.text[1:-1])
        if tok.kind == "NUM":
            self._consume()
            text = tok.text
            if "." in text:
                return Literal(float(text))
            return Literal(int(text))
        if tok.kind == "KW" and tok.text == "true":
            self._consume()
            return Literal(True)
        if tok.kind == "KW" and tok.text == "false":
            self._consume()
            return Literal(False)
        if tok.kind == "KW" and tok.text == "null":
            self._consume()
            return Literal(None)
        raise SpecValidationError(
            f"expected literal but got {tok.text!r} at position {tok.pos} "
            f"in rule {self.source!r}"
        )


def parse_rule_expr(source: str) -> object:
    """Parse a Tier-2 condition string into an AST. Raises SpecValidationError
    on grammar violation."""
    return _Parser(source).parse()


# --- validation ---

def _walk_field_refs(node: object) -> Iterable[FieldRef]:
    """Recursively yield every FieldRef node in the tree."""
    if isinstance(node, FieldRef):
        yield node
    elif isinstance(node, (Eq, Neq, Lt, Gt, Le, Ge, In, NotIn)):
        yield from _walk_field_refs(node.left)
    elif isinstance(node, (And, Or)):
        yield from _walk_field_refs(node.left)
        yield from _walk_field_refs(node.right)
    elif isinstance(node, (Not, Paren)):
        yield from _walk_field_refs(node.inner)
    # Literal / list[Literal]: no field refs


def validate_rule(ast: object, known_field_codes: set[str]) -> None:
    """Raise SpecValidationError if the AST references a field code not
    in the known set."""
    for ref in _walk_field_refs(ast):
        if ref.code not in known_field_codes:
            raise SpecValidationError(
                f"rule references unknown field {ref.code!r}; "
                f"known fields: {sorted(known_field_codes)}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_procedures.py -v 2>&1 | tail -25`

Expected: all 19 parser tests pass. Also run the full suite to verify no regressions: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -3` — expect 56 + 19 + 4 = 79 passing (assumes Task 0's 4 + this task's 19 added on top of the 56 baseline).

- [ ] **Step 5: Commit**

```bash
git add src/chorus_form_builder/procedures.py tests/test_procedures.py
git commit -m "feat(procedures): DSL parser + AST for Tier-2 condition grammar

Hand-rolled recursive-descent parser for the condition language used
by visible_when / enabled_when / required_when / default_when rules.
Supports equality, numeric ordering, in / not in, and / or / not, parens,
all 3 literal types (string with either quote style, numeric, boolean,
null). Operator precedence follows Python conventions (or < and < not <
comparison < in).

Parser errors surface as SpecValidationError so callers catch one type
for all spec-shape errors. validate_rule additionally walks the AST
asserting every FieldRef resolves to a known field code (called from
spec.py at load_spec time in Task 2).

Codegen (AST -> JS) lands in Task 3. This task ships the parser only.

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §2"
```

---

## Task 2: `spec.py` — FieldSpec attrs + model_validators (TDD)

**Files:**
- Modify: `src/chorus_form_builder/spec.py` (add 5 attributes + 2 model_validators)
- Modify: `tests/test_spec.py` (add ~6 new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec.py` (after the existing tests):

```python
# --- v0.2 rule attributes (sub-project C) ---

def test_field_visible_when_loads(tmp_path):
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
          - {code: MEMO, label: M, control_type: text, length: 60, visible_when: 'STAT == "A"'}
    """)
    spec = load_spec(p)
    memo = next(f for f in spec.fields if f.code == "MEMO")
    assert memo.visible_when == 'STAT == "A"'
    assert memo.enabled_when is None
    assert memo.required_when is None
    assert memo.default_when is None
    assert memo.default_value is None


def test_field_default_when_requires_default_value(tmp_path):
    """default_when without default_value is rejected at load time."""
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
          - code: BATC
            label: B
            control_type: text
            length: 6
            default_when: STAT == "A"
            # no default_value -> error
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    msg = str(exc.value).lower()
    assert "default_when" in msg and "default_value" in msg


def test_field_default_value_without_default_when_rejected(tmp_path):
    """default_value without default_when is also rejected — they're paired."""
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: BATC
            label: B
            control_type: text
            length: 6
            default_value: "BATCH-AUTO"
            # no default_when -> error
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    msg = str(exc.value).lower()
    assert "default_when" in msg and "default_value" in msg


def test_field_rule_with_invalid_grammar_rejected(tmp_path):
    """A rule string with bad grammar fails at load_spec time."""
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
          - {code: MEMO, label: M, control_type: text, length: 60, visible_when: 'STAT === "A"'}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    # Either grammar message or "in rule" context
    assert "MEMO" in str(exc.value) or "===" in str(exc.value) or "visible_when" in str(exc.value)


def test_field_rule_with_unknown_field_reference_rejected(tmp_path):
    """A rule referencing a field that doesn't exist in this form fails."""
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - {code: STAT, label: S, control_type: combobox, values: [{value: A, description: Active}]}
          - {code: MEMO, label: M, control_type: text, length: 60, visible_when: 'XYZQ == "A"'}
    """)
    with pytest.raises(SpecValidationError) as exc:
        load_spec(p)
    assert "XYZQ" in str(exc.value)


def test_field_all_four_rule_kinds_load(tmp_path):
    """End-to-end: all 4 rule kinds + default_value coexist on a single form."""
    p = _write(tmp_path, "form.yaml", """
        form:
          name: TESTFORM
          title: T
        fields:
          - code: STAT
            label: Status
            control_type: combobox
            values: [{value: A, description: Active}, {value: R, description: Rejected}]
          - code: MEMO
            label: Memo
            control_type: text
            length: 60
            visible_when: 'STAT == "R"'
            required_when: 'STAT == "R"'
          - code: ACCT
            label: Account
            control_type: text
            length: 10
            enabled_when: 'STAT in ["A"]'
          - code: BATC
            label: Batch
            control_type: text
            length: 6
            default_when: 'STAT == "A"'
            default_value: "BATCH-AUTO"
    """)
    spec = load_spec(p)
    memo = next(f for f in spec.fields if f.code == "MEMO")
    acct = next(f for f in spec.fields if f.code == "ACCT")
    batc = next(f for f in spec.fields if f.code == "BATC")

    assert memo.visible_when == 'STAT == "R"'
    assert memo.required_when == 'STAT == "R"'
    assert acct.enabled_when == 'STAT in ["A"]'
    assert batc.default_when == 'STAT == "A"'
    assert batc.default_value == "BATCH-AUTO"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_spec.py -v 2>&1 | tail -15`

Expected: 6 new tests fail with `AttributeError: 'FieldSpec' object has no attribute 'visible_when'` (or similar) — fields don't exist yet.

- [ ] **Step 3: Modify `src/chorus_form_builder/spec.py`**

The current `FieldSpec` class looks like:

```python
class FieldSpec(BaseModel):
    """One field on the form."""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., pattern=r"^[A-Z][A-Z0-9]{3}$")
    label: str
    control_type: Literal["combobox", "text"]
    required: bool = False
    length: Optional[int] = None
    binding: Optional[BindingSpec] = None
    values: Optional[list[DomainValueSpec]] = None

    @model_validator(mode="after")
    def _binding_xor_values(self) -> "FieldSpec":
        # ... existing body unchanged
```

Add 5 new attributes + 2 new model_validators. Replace the FieldSpec class with:

```python
class FieldSpec(BaseModel):
    """One field on the form."""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., pattern=r"^[A-Z][A-Z0-9]{3}$")
    label: str
    control_type: Literal["combobox", "text"]
    required: bool = False
    length: Optional[int] = None
    binding: Optional[BindingSpec] = None
    values: Optional[list[DomainValueSpec]] = None

    # --- v0.2 rule attributes (sub-project C) ---
    visible_when: Optional[str] = None
    enabled_when: Optional[str] = None
    required_when: Optional[str] = None
    default_when: Optional[str] = None
    default_value: Optional[Union[str, int, float, bool]] = None

    @model_validator(mode="after")
    def _binding_xor_values(self) -> "FieldSpec":
        # Combobox forbids BOTH being set; the "neither set" case is allowed
        # by design — the emit translator handles it as an empty domain, and
        # constructing a FieldSpec directly (bypassing load_spec) is a
        # legitimate path for defensive tests in emit.py.
        if self.control_type == "combobox":
            if self.binding is not None and self.values is not None:
                raise ValueError(
                    f"field {self.code}: combobox must have exactly one of "
                    f"'binding' (dynamic) or 'values' (static); both are set"
                )
        return self

    @model_validator(mode="after")
    def _default_when_value_paired(self) -> "FieldSpec":
        """default_when and default_value must both be set or both absent.
        Set-without-pair on either side is a spec authoring error."""
        has_when = self.default_when is not None
        has_value = self.default_value is not None
        if has_when != has_value:
            raise ValueError(
                f"field {self.code}: default_when and default_value must be "
                f"set together (got default_when={self.default_when!r}, "
                f"default_value={self.default_value!r})"
            )
        return self
```

Also: the existing imports at the top of `spec.py` need `Union` added:

```python
from typing import Any, Literal, Optional, Union
```

Verify by reading the file's top. If `Union` is already imported, no change needed.

**The rule-grammar validation step is added in the next step** (so we don't introduce a circular import between `spec.py` and `procedures.py`).

- [ ] **Step 4: Add the rule-grammar validation step**

Append a third model_validator to `FieldSpec` that parses each non-None rule string at load time. Because `procedures` imports `SpecValidationError` from `spec`, do the `procedures` import **inside** the validator (deferred import) to avoid circular import at module load.

Add the following method to `FieldSpec` (alongside the other validators):

```python
    @model_validator(mode="after")
    def _rule_strings_parse(self) -> "FieldSpec":
        """Parse each non-None rule string at load_spec time.

        Catches grammar errors before any downstream code touches the rule.
        Field-reference scope validation happens at the FormSpec level
        (later, when the full set of field codes is known).

        Import is deferred to avoid a spec <-> procedures circular import.
        """
        from chorus_form_builder.procedures import parse_rule_expr
        for kind, src in (
            ("visible_when", self.visible_when),
            ("enabled_when", self.enabled_when),
            ("required_when", self.required_when),
            ("default_when", self.default_when),
        ):
            if src is None:
                continue
            try:
                parse_rule_expr(src)
            except Exception as e:
                # Re-raise with field + kind context
                raise ValueError(
                    f"field {self.code}: {kind}: {e}"
                ) from e
        return self
```

Now add the cross-field validation step to `FormSpec` — checks that every rule's field references resolve to fields in this form. Modify the `FormSpec` class:

```python
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

    @model_validator(mode="after")
    def _rule_field_refs_resolve(self) -> "FormSpec":
        """Every rule's field references must resolve to a field code in this
        form. Catches typos like 'XYZQ' instead of 'STAT'."""
        from chorus_form_builder.procedures import parse_rule_expr, validate_rule
        known_codes = {f.code for f in self.fields}
        for f in self.fields:
            for kind, src in (
                ("visible_when", f.visible_when),
                ("enabled_when", f.enabled_when),
                ("required_when", f.required_when),
                ("default_when", f.default_when),
            ):
                if src is None:
                    continue
                ast = parse_rule_expr(src)  # already validated to parse in FieldSpec
                try:
                    validate_rule(ast, known_codes)
                except Exception as e:
                    raise ValueError(
                        f"field {f.code}: {kind}: {e}"
                    ) from e
        return self
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_spec.py -v 2>&1 | tail -15`

Expected: all spec tests pass (existing 10 + new 6 = 16).

Also full suite regression: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -3` — expect 79 + 6 = 85 passing.

- [ ] **Step 6: Commit**

```bash
git add src/chorus_form_builder/spec.py tests/test_spec.py
git commit -m "feat(spec): FieldSpec rule attributes + load-time validation

Adds 5 optional FieldSpec attributes (visible_when, enabled_when,
required_when, default_when, default_value) for sub-project C's
declarative rules.

Three layers of validation at load_spec time:
1. Pydantic shape (the attrs themselves)
2. FieldSpec._default_when_value_paired — default_when xor default_value
   is rejected; they must both be set or both absent
3. FieldSpec._rule_strings_parse — each non-None rule string is parsed
   via procedures.parse_rule_expr; grammar errors surface with field +
   kind context
4. FormSpec._rule_field_refs_resolve — every rule's field references
   must resolve to a field code declared in this form (catches typos)

Deferred-import pattern avoids spec <-> procedures circular dep.

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §2"
```

---

## Task 3: `procedures.py` — `compile_rules` codegen (TDD)

**Files:**
- Modify: `src/chorus_form_builder/procedures.py` (add codegen)
- Modify: `tests/test_procedures.py` (add ~10 codegen tests)

- [ ] **Step 1: Write the failing codegen tests**

Append to `tests/test_procedures.py`:

```python
# --- codegen ---

from chorus_form_builder.procedures import CompiledRules, compile_rules
from chorus_form_builder._types import DomainValue
from chorus_form_builder.spec import DomainValueSpec, FieldSpec, FormMetaSpec, FormSpec


def _field(code: str, control_type: str = "text", **kw) -> FieldSpec:
    """Convenience FieldSpec builder for codegen tests."""
    return FieldSpec(code=code, label=code, control_type=control_type, **kw)


def test_compile_rules_no_rules_returns_empty():
    fields = [_field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="Active")])]
    result = compile_rules(fields)
    assert isinstance(result, CompiledRules)
    assert result.custom_rules_js == ""
    assert result.include_list == []
    assert result.rule_summary == []


def test_compile_rules_visible_when_eq():
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="R", description="Rejected")]),
        _field("MEMO", length=60, visible_when='STAT == "R"'),
    ]
    js = compile_rules(fields).custom_rules_js
    assert 'var stat = awdForm.getValue("STAT");' in js
    assert '// MEMO visible_when STAT == "R"' in js
    assert 'awdForm[(stat === "R") ? "show" : "hide"]("MEMO");' in js
    assert 'awdForm.on("form-open", applyAll);' in js
    assert 'awdForm.on("field-change:STAT", applyAll);' in js


def test_compile_rules_required_when_uses_set_required():
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="R", description="R")]),
        _field("MEMO", length=60, required_when='STAT == "R"'),
    ]
    js = compile_rules(fields).custom_rules_js
    assert 'awdForm.setRequired("MEMO", stat === "R");' in js


def test_compile_rules_enabled_when_membership():
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("ACCT", length=10, enabled_when='STAT in ["A", "P"]'),
    ]
    js = compile_rules(fields).custom_rules_js
    assert 'awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");' in js


def test_compile_rules_default_when_guarded_by_is_empty():
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("BATC", length=6, default_when='STAT == "A"', default_value="BATCH-AUTO"),
    ]
    js = compile_rules(fields).custom_rules_js
    assert 'if ((stat === "A") && awdForm.isEmpty("BATC")) {' in js
    assert 'awdForm.setValue("BATC", "BATCH-AUTO");' in js


def test_compile_rules_default_value_numeric_literal():
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("BATC", length=6, default_when='STAT == "A"', default_value=42),
    ]
    js = compile_rules(fields).custom_rules_js
    assert 'awdForm.setValue("BATC", 42);' in js


def test_compile_rules_event_subscriptions_for_each_referenced_field():
    """field-change:<CODE> subscription emitted exactly once per distinct
    referenced field, in declaration order."""
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("AMTV", length=10),
        _field("MEMO", length=60, visible_when='STAT == "A"', enabled_when='AMTV > 100'),
    ]
    js = compile_rules(fields).custom_rules_js
    assert js.count('awdForm.on("field-change:STAT", applyAll);') == 1
    assert js.count('awdForm.on("field-change:AMTV", applyAll);') == 1


def test_compile_rules_include_list_only_when_rules_present():
    """No rules -> no jsFile in include_list. Rules present -> awdForm.js added."""
    no_rules = compile_rules([_field("STAT", length=10)])
    assert no_rules.include_list == []
    with_rules = compile_rules([
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("MEMO", length=60, visible_when='STAT == "A"'),
    ])
    assert with_rules.include_list == [{"js_file": "awdForm.js"}]


def test_compile_rules_summary_records_each_rule():
    """rule_summary mirrors the manifest's `rules` array."""
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("BATC", length=6, default_when='STAT == "A"', default_value="X"),
    ]
    summary = compile_rules(fields).rule_summary
    assert {"field_code": "BATC", "kind": "default_when", "source": 'STAT == "A"', "default_value": "X"} in summary


def test_compile_rules_deterministic():
    """Identical inputs produce byte-identical JS output."""
    fields = [
        _field("STAT", control_type="combobox", values=[DomainValueSpec(value="A", description="A")]),
        _field("MEMO", length=60, visible_when='STAT == "A"', required_when='STAT == "A"'),
    ]
    js1 = compile_rules(fields).custom_rules_js
    js2 = compile_rules(fields).custom_rules_js
    assert js1 == js2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_procedures.py -v 2>&1 | tail -10`

Expected: 10 new tests fail with `ImportError: cannot import name 'compile_rules' from 'chorus_form_builder.procedures'`.

- [ ] **Step 3: Implement codegen**

Append to `src/chorus_form_builder/procedures.py` (after the existing parser code):

```python
# --- codegen ---

import json as _json
from dataclasses import dataclass as _dataclass, field as _field


@_dataclass(frozen=True)
class CompiledRules:
    """Output of compile_rules — feeds into emit.py."""
    custom_rules_js: str
    include_list: list[dict]   # e.g. [{"js_file": "awdForm.js"}]
    rule_summary: list[dict]   # for manifest


_RULE_KINDS_AND_ATTRS = (
    ("visible_when",  "visible_when"),
    ("enabled_when",  "enabled_when"),
    ("required_when", "required_when"),
    ("default_when",  "default_when"),
)


def _render_literal_js(lit: Literal) -> str:
    """Pydantic-style literal -> JS literal."""
    v = lit.value
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v)
    # string
    return _json.dumps(v)  # handles escaping; produces double-quoted


def _render_condition(node: object, varmap: dict[str, str]) -> str:
    """AST -> JS expression string. varmap maps "STAT" -> "stat" (local var name)."""
    if isinstance(node, FieldRef):
        return varmap[node.code]
    if isinstance(node, Literal):
        return _render_literal_js(node)
    if isinstance(node, Eq):
        return f"{varmap[node.left.code]} === {_render_literal_js(node.right)}"
    if isinstance(node, Neq):
        return f"{varmap[node.left.code]} !== {_render_literal_js(node.right)}"
    if isinstance(node, Lt):
        return f"{varmap[node.left.code]} < {_render_literal_js(node.right)}"
    if isinstance(node, Gt):
        return f"{varmap[node.left.code]} > {_render_literal_js(node.right)}"
    if isinstance(node, Le):
        return f"{varmap[node.left.code]} <= {_render_literal_js(node.right)}"
    if isinstance(node, Ge):
        return f"{varmap[node.left.code]} >= {_render_literal_js(node.right)}"
    if isinstance(node, In):
        parts = " || ".join(
            f"{varmap[node.left.code]} === {_render_literal_js(lit)}"
            for lit in node.right
        )
        return f"({parts})"
    if isinstance(node, NotIn):
        parts = " && ".join(
            f"{varmap[node.left.code]} !== {_render_literal_js(lit)}"
            for lit in node.right
        )
        return f"({parts})"
    if isinstance(node, And):
        return f"({_render_condition(node.left, varmap)} && {_render_condition(node.right, varmap)})"
    if isinstance(node, Or):
        return f"({_render_condition(node.left, varmap)} || {_render_condition(node.right, varmap)})"
    if isinstance(node, Not):
        return f"!({_render_condition(node.inner, varmap)})"
    if isinstance(node, Paren):
        return f"({_render_condition(node.inner, varmap)})"
    raise SpecValidationError(f"unsupported AST node: {type(node).__name__}")


def _collect_rules(fields) -> list[tuple]:
    """Return list of (field_code, kind, source, default_value) tuples in
    declaration + kind order. Skips fields with no rules."""
    out: list[tuple] = []
    for f in fields:
        for kind, attr in _RULE_KINDS_AND_ATTRS:
            src = getattr(f, attr)
            if src is None:
                continue
            dv = f.default_value if kind == "default_when" else None
            out.append((f.code, kind, src, dv))
    return out


def _referenced_field_codes(rules: list[tuple]) -> list[str]:
    """Unique field codes referenced in any rule, in first-seen order."""
    seen: list[str] = []
    for (_target, _kind, src, _dv) in rules:
        ast = parse_rule_expr(src)
        for ref in _walk_field_refs(ast):
            if ref.code not in seen:
                seen.append(ref.code)
    return seen


def compile_rules(fields) -> CompiledRules:
    """Top-level: list[FieldSpec] -> CompiledRules.

    Pure function. Same input -> byte-identical output (lets goldens work).
    """
    rules = _collect_rules(fields)
    if not rules:
        return CompiledRules(custom_rules_js="", include_list=[], rule_summary=[])

    referenced_codes = _referenced_field_codes(rules)
    varmap = {code: code.lower() for code in referenced_codes}

    lines: list[str] = []
    lines.append("(function(awdForm) {")
    lines.append("  function applyAll() {")
    for code in referenced_codes:
        lines.append(f'    var {varmap[code]} = awdForm.getValue("{code}");')
    lines.append("")

    for (target, kind, src, default_val) in rules:
        ast = parse_rule_expr(src)
        cond = _render_condition(ast, varmap)
        lines.append(f"    // {target} {kind} {src}")
        if kind == "visible_when":
            lines.append(f'    awdForm[{cond} ? "show" : "hide"]("{target}");')
        elif kind == "enabled_when":
            lines.append(f'    awdForm[{cond} ? "enable" : "disable"]("{target}");')
        elif kind == "required_when":
            lines.append(f'    awdForm.setRequired("{target}", {cond});')
        elif kind == "default_when":
            lit = _render_literal_js(Literal(default_val))
            lines.append(f'    if ({cond} && awdForm.isEmpty("{target}")) {{')
            lines.append(f'      awdForm.setValue("{target}", {lit});')
            lines.append("    }")
        else:
            raise SpecValidationError(f"unsupported rule kind: {kind}")
        lines.append("")

    lines.append("  }")
    lines.append("")
    lines.append('  awdForm.on("form-open", applyAll);')
    for code in referenced_codes:
        lines.append(f'  awdForm.on("field-change:{code}", applyAll);')
    lines.append("})(window.awdForm);")
    lines.append("")  # trailing newline

    js = "\n".join(lines)

    summary: list[dict] = []
    for (target, kind, src, default_val) in rules:
        entry = {"field_code": target, "kind": kind, "source": src}
        if kind == "default_when":
            entry["default_value"] = default_val
        summary.append(entry)

    return CompiledRules(
        custom_rules_js=js,
        include_list=[{"js_file": "awdForm.js"}],
        rule_summary=summary,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_procedures.py -v 2>&1 | tail -15`

Expected: all 29 procedures tests pass (19 parser + 10 codegen). Full suite: 56 + 4 + 19 + 6 + 10 = 95 passing.

- [ ] **Step 5: Commit**

```bash
git add src/chorus_form_builder/procedures.py tests/test_procedures.py
git commit -m "feat(procedures): compile_rules codegen — AST -> JS body

Pure function: list[FieldSpec] -> CompiledRules(custom_rules_js,
include_list, rule_summary).

Generated JS structure:
- (function(awdForm) { ... })(window.awdForm) IIFE wrapper
- applyAll() reads all referenced field values once at top
- one if/branch per rule (show/hide for visible_when, enable/disable for
  enabled_when, setRequired for required_when, set-if-empty for
  default_when)
- on('form-open', applyAll) always
- on('field-change:<CODE>', applyAll) for each distinct referenced field

Determinism: same input -> byte-identical JS. Enables byte-exact .csd
goldens. include_list returns [{js_file: 'awdForm.js'}] when at least
one rule exists, [] otherwise. rule_summary is what the manifest will
record.

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §3"
```

---

## Task 4: `awdForm.js` shim + Node test infrastructure (TDD)

**Files:**
- Create: `src/chorus_form_builder/runtime/__init__.py`
- Create: `src/chorus_form_builder/runtime/awdForm.js`
- Create: `tests/js_runtime/host_recorder.js`
- Create: `tests/js_runtime/runner.js`
- Create: `tests/js_runtime/test_cases/shim_smoke.js`
- Modify: `pyproject.toml` (add `"runtime/*.js"` to package-data)

- [ ] **Step 1: Write the failing JS test case**

Create `tests/js_runtime/host_recorder.js`:

```javascript
// __awdFormHost stub that records every mutator call made by the shim.
// Tests inspect host.calls to verify the shim translated event -> method
// dispatch correctly. State lives in host.state so tests can prime values.

function makeHost() {
  return {
    state: {},     // field code -> current value
    calls: [],     // append-only list of {method, args}

    getValue(code) {
      this.calls.push({method: 'getValue', args: [code]});
      return this.state[code];
    },
    isEmpty(code) {
      const v = this.state[code];
      const empty = v === '' || v === null || v === undefined;
      this.calls.push({method: 'isEmpty', args: [code], result: empty});
      return empty;
    },
    show(code)             { this.calls.push({method: 'show',        args: [code]}); },
    hide(code)             { this.calls.push({method: 'hide',        args: [code]}); },
    enable(code)           { this.calls.push({method: 'enable',      args: [code]}); },
    disable(code)          { this.calls.push({method: 'disable',     args: [code]}); },
    setRequired(code, b)   { this.calls.push({method: 'setRequired', args: [code, b]}); },
    setValue(code, v) {
      this.calls.push({method: 'setValue', args: [code, v]});
      this.state[code] = v;  // mirror real runtime; but does NOT fire change event
    },
  };
}

module.exports = { makeHost };
```

Create `tests/js_runtime/runner.js`:

```javascript
// Generic Node runner for shim integration tests.
//
// Usage: node runner.js <test-case-file>
//
// The test-case file must export a single function `run({makeHost, loadShim})
// -> {assertions: [{name, ok, detail?}, ...]}`.
// Runner prints one JSON line `{name, ok, detail?}` per assertion and exits 0
// iff every assertion passed.

const path = require('path');
const fs = require('fs');
const vm = require('vm');

const {makeHost} = require('./host_recorder');

function loadShim(host) {
  // Load src/chorus_form_builder/runtime/awdForm.js into a fresh context
  // where window.__awdFormHost = host. Returns the populated context's
  // window.awdForm.
  const shimPath = path.resolve(
    __dirname,
    '..',
    '..',
    'src',
    'chorus_form_builder',
    'runtime',
    'awdForm.js'
  );
  const shimSrc = fs.readFileSync(shimPath, 'utf8');
  const ctx = vm.createContext({
    window: {__awdFormHost: host},
  });
  vm.runInContext(shimSrc, ctx);
  return ctx.window.awdForm;
}

function loadAndRunCustomRules(awdForm, customRulesSrc) {
  // Drop the customRules body into a fresh sub-context that sees `window`
  // as a thin shim binding window.awdForm to the loaded shim.
  const ctx = vm.createContext({window: {awdForm}});
  vm.runInContext(customRulesSrc, ctx);
}

const tcPath = process.argv[2];
if (!tcPath) {
  console.error('usage: node runner.js <test-case-file>');
  process.exit(2);
}

const tc = require(path.resolve(tcPath));
const result = tc.run({makeHost, loadShim, loadAndRunCustomRules});

let allOk = true;
for (const a of result.assertions) {
  console.log(JSON.stringify(a));
  if (!a.ok) allOk = false;
}
process.exit(allOk ? 0 : 1);
```

Create `tests/js_runtime/test_cases/shim_smoke.js`:

```javascript
// Layer-C smoke test for the awdForm shim — verifies the shim's public
// methods dispatch correctly to __awdFormHost and that on(eventName, fn)
// registers callbacks that fire on awdForm._emit().

module.exports = {
  run({makeHost, loadShim}) {
    const host = makeHost();
    host.state['STAT'] = 'R';
    const awdForm = loadShim(host);

    const assertions = [];

    // 1. getValue delegates to host and returns the host's stored value.
    const got = awdForm.getValue('STAT');
    assertions.push({
      name: 'getValue delegates to host',
      ok: got === 'R',
      detail: `expected 'R' got ${JSON.stringify(got)}`,
    });

    // 2. show / hide / enable / disable / setRequired / setValue
    awdForm.show('MEMO');
    awdForm.hide('ACCT');
    awdForm.enable('BATC');
    awdForm.disable('AMTV');
    awdForm.setRequired('MEMO', true);
    awdForm.setValue('BATC', 'BATCH-AUTO');

    const methodSeq = host.calls.filter(c => c.method !== 'getValue').map(c => c.method);
    assertions.push({
      name: 'mutator methods reach host in declared order',
      ok: methodSeq.join(',') === 'show,hide,enable,disable,setRequired,setValue',
      detail: 'got: ' + methodSeq.join(','),
    });

    // 3. isEmpty
    host.state['EMPTY'] = '';
    host.state['FILLED'] = 'x';
    assertions.push({
      name: 'isEmpty true for empty string',
      ok: awdForm.isEmpty('EMPTY') === true,
    });
    assertions.push({
      name: 'isEmpty false for non-empty',
      ok: awdForm.isEmpty('FILLED') === false,
    });

    // 4. on(eventName, fn) + emit. The shim must expose an internal _emit
    // so the runner can drive synthetic events. v0.1 design exposes:
    //   awdForm.on('form-open', fn)
    //   awdForm.on('field-change:STAT', fn)
    //   awdForm._emit(eventName)   <-- test-only escape hatch
    let openCount = 0;
    let changeCount = 0;
    awdForm.on('form-open', () => { openCount++; });
    awdForm.on('field-change:STAT', () => { changeCount++; });
    awdForm._emit('form-open');
    awdForm._emit('form-open');
    awdForm._emit('field-change:STAT');

    assertions.push({
      name: 'form-open callbacks fire on _emit',
      ok: openCount === 2,
      detail: `openCount=${openCount}`,
    });
    assertions.push({
      name: 'field-change:CODE callbacks fire on _emit',
      ok: changeCount === 1,
      detail: `changeCount=${changeCount}`,
    });

    // 5. setValue does NOT fire field-change (sub-project C v0.1 contract)
    let cascadeCount = 0;
    awdForm.on('field-change:BATC', () => { cascadeCount++; });
    awdForm.setValue('BATC', 'XYZ');
    assertions.push({
      name: 'setValue does NOT fire field-change (no-cascade contract)',
      ok: cascadeCount === 0,
      detail: `cascadeCount=${cascadeCount}`,
    });

    return {assertions};
  },
};
```

- [ ] **Step 2: Run the test case to verify it fails (shim doesn't exist)**

Run from `D:/agent-tool-chorus-form-builder/`:
```
node tests/js_runtime/runner.js tests/js_runtime/test_cases/shim_smoke.js
```

Expected: error — either `cannot find module` because awdForm.js doesn't exist, or assertions fail because the shim isn't loaded.

- [ ] **Step 3: Implement the awdForm shim**

Create `src/chorus_form_builder/runtime/__init__.py` (empty marker):

```python
"""Marks runtime/ as a Python sub-package so setuptools package-data
globs apply to runtime/*.js."""
```

Create `src/chorus_form_builder/runtime/awdForm.js`:

```javascript
/* awdForm.js v0.1.0 — chorus-form-builder mini-runtime shim
 *
 * Public API used by generated customRules JS:
 *   awdForm.getValue(code)
 *   awdForm.isEmpty(code)
 *   awdForm.show(code)
 *   awdForm.hide(code)
 *   awdForm.enable(code)
 *   awdForm.disable(code)
 *   awdForm.setRequired(code, b)
 *   awdForm.setValue(code, v)         -- does NOT fire field-change
 *   awdForm.on(eventName, fn)         -- 'form-open' or 'field-change:CODE'
 *   awdForm._emit(eventName)          -- TEST-ONLY: synthetic event trigger
 *
 * In v0.1, every state-mutator delegates to window.__awdFormHost (the test
 * runner or future Chorus bridge supplies that host). The bridge to the
 * real Chorus runtime is the C v0.2 milestone; the contract above is what
 * the bridge must satisfy.
 */
(function (root) {
  var host = (root && root.__awdFormHost) || {};
  var listeners = {};  // eventName -> [fn, fn, ...]

  function _call(method, args) {
    if (typeof host[method] === 'function') {
      return host[method].apply(host, args);
    }
    // No host method bound (e.g., stub environment). Silently no-op for
    // mutators; for getters, return undefined.
    return undefined;
  }

  var api = {
    // --- accessors ---
    getValue: function (code) { return _call('getValue', [code]); },
    isEmpty:  function (code) { return _call('isEmpty',  [code]); },

    // --- mutators ---
    show:        function (code)    { _call('show',        [code]); },
    hide:        function (code)    { _call('hide',        [code]); },
    enable:      function (code)    { _call('enable',      [code]); },
    disable:     function (code)    { _call('disable',     [code]); },
    setRequired: function (code, b) { _call('setRequired', [code, b]); },
    setValue:    function (code, v) { _call('setValue',    [code, v]); },
    //                                          ^^^^^^^^
    //   Intentionally does NOT also emit a field-change event. Sub-project
    //   C v0.1 forbids cascading rules; the codegen and the host contract
    //   both rely on this no-cascade guarantee.

    // --- events ---
    on: function (eventName, fn) {
      if (!listeners[eventName]) listeners[eventName] = [];
      listeners[eventName].push(fn);
    },

    // --- test-only ---
    _emit: function (eventName) {
      var fns = listeners[eventName] || [];
      for (var i = 0; i < fns.length; i++) {
        fns[i]();
      }
    },
  };

  root.awdForm = api;
})(typeof window !== 'undefined' ? window : this);
```

Modify `pyproject.toml` to ship the runtime via package data. Two additions are needed because this is the first `[tool.setuptools.package-data]` block in the repo and the project uses src-layout (`where = ["src"]`):

1. Add `include-package-data = true` under a `[tool.setuptools]` table so setuptools reliably picks up the package-data globs on a wheel install (editable installs read from src/ directly and don't care; but `uv tool install` builds a wheel and that's where the gotcha bites).
2. Add the `[tool.setuptools.package-data]` block.

Insert these two blocks just above the existing `[tool.setuptools.packages.find]` block:

```toml
[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
chorus_form_builder = ["runtime/*.js"]
```

(Gemini co-plan review flagged this; reasoning is defensive — `package-data` alone may work without `include-package-data` per the setuptools docs, but the combination is bulletproof across setuptools versions. The redundancy is one line of belt-and-suspenders. Verified the form-builder pyproject.toml currently has neither line, so we're adding both fresh.)

- [ ] **Step 4: Run the shim test to verify it passes**

Verify Node is available: `node --version 2>&1` — should print a v18+ version. If `node` isn't on PATH, install it first (Windows: download from nodejs.org; or `winget install OpenJS.NodeJS`).

Run from `D:/agent-tool-chorus-form-builder/`:
```
node tests/js_runtime/runner.js tests/js_runtime/test_cases/shim_smoke.js
```

Expected: 7 JSON lines each ending `"ok":true`, exit code 0. Sample output:

```
{"name":"getValue delegates to host","ok":true,"detail":"expected 'R' got \"R\""}
{"name":"mutator methods reach host in declared order","ok":true,"detail":"got: show,hide,enable,disable,setRequired,setValue"}
{"name":"isEmpty true for empty string","ok":true}
{"name":"isEmpty false for non-empty","ok":true}
{"name":"form-open callbacks fire on _emit","ok":true,"detail":"openCount=2"}
{"name":"field-change:CODE callbacks fire on _emit","ok":true,"detail":"changeCount=1"}
{"name":"setValue does NOT fire field-change (no-cascade contract)","ok":true,"detail":"cascadeCount=0"}
```

If any assertion fails, fix the shim. Python suite still passes regression-wise — run `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -3` and confirm 94 still pass.

- [ ] **Step 5: Commit**

```bash
git add src/chorus_form_builder/runtime/ tests/js_runtime/host_recorder.js tests/js_runtime/runner.js tests/js_runtime/test_cases/shim_smoke.js pyproject.toml
git commit -m "feat(runtime): awdForm.js shim + Node test infrastructure

Mini-runtime shim shipped via package-data (runtime/*.js). 80-LOC
ES5-compatible IIFE that publishes window.awdForm with getValue,
isEmpty, show, hide, enable, disable, setRequired, setValue, on, and
_emit (test-only).

setValue intentionally does NOT fire a field-change event — the
no-cascade contract that sub-project C v0.1's codegen relies on.

Node test infrastructure:
- host_recorder.js: __awdFormHost stub recording every mutator call
- runner.js: loads shim into a vm.context, drives a test-case file,
  emits one JSON line per assertion
- test_cases/shim_smoke.js: 7-assertion smoke covering accessors,
  mutators, isEmpty, event subscriptions, and the no-cascade contract

pytest wrapper invoking node lands in Task 6 along with codegen
integration tests.

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §3"
```

---

## Task 5: `emit.py` pipeline integration + `manifest.py` updates (TDD)

**Files:**
- Modify: `src/chorus_form_builder/emit.py`
- Modify: `src/chorus_form_builder/manifest.py`
- Modify: `tests/test_emit.py`
- Modify: `tests/test_build_form.py` (existing tests will continue to pass, but the manifest schema bump will surface in any test that checks manifest shape)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_emit.py`:

```python
# --- sub-project C: emit pipeline integration ---

from chorus_form_builder.spec import DomainValueSpec  # already imported but explicit for clarity


def _form_spec_with_visibility_rule() -> FormSpec:
    return FormSpec(
        form=FormMetaSpec(name="RULEFORM", title="Rule Form"),
        openapi_defaults=OpenAPIDefaultsSpec(),
        fields=[
            FieldSpec(code="STAT", label="Status", control_type="combobox",
                      values=[DomainValueSpec(value="A", description="Active"),
                              DomainValueSpec(value="R", description="Rejected")]),
            FieldSpec(code="MEMO", label="Memo", control_type="text", length=60,
                      visible_when='STAT == "R"'),
        ],
    )


def test_emit_rule_free_form_emits_no_custom_rules(tmp_path):
    """A form with no rules: emitted .csd has empty <customRules>, no jsFile
    in <includeList>, and no awdForm.js next to the .csd."""
    spec = _form_spec_static_combo()  # the existing rule-free fixture
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    xml = result.csd_path.read_text(encoding="utf-8")
    # customRules element may be present but empty
    assert "<jsFile>awdForm.js</jsFile>" not in xml
    assert not (tmp_path / "awdForm.js").exists(), "shim should not be copied for rule-free forms"


def test_emit_rule_bearing_form_attaches_js_and_include(tmp_path):
    spec = _form_spec_with_visibility_rule()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    xml = result.csd_path.read_text(encoding="utf-8")
    assert "<customRules>" in xml
    assert "(function(awdForm)" in xml
    assert 'awdForm.on("field-change:STAT", applyAll);' in xml
    assert "<jsFile>awdForm.js</jsFile>" in xml
    assert (tmp_path / "awdForm.js").is_file()
    # And the shipped shim should be the same as the package-data file
    shim_src = Path(__file__).resolve().parent.parent / "src" / "chorus_form_builder" / "runtime" / "awdForm.js"
    assert (tmp_path / "awdForm.js").read_bytes() == shim_src.read_bytes()


def test_emit_manifest_includes_new_fields(tmp_path):
    spec = _form_spec_with_visibility_rule()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    # New fields all present
    assert manifest["uxb_handlers_emitted"] is False
    assert manifest["runtime_validated"] is False
    assert manifest["shim_version"] == "0.1.0"
    assert isinstance(manifest["rules"], list)
    assert any(r["field_code"] == "MEMO" and r["kind"] == "visible_when" for r in manifest["rules"])


def test_emit_manifest_empty_rules_when_no_rules(tmp_path):
    """Rule-free form -> rules: [] in manifest; uxb_handlers_emitted still false."""
    spec = _form_spec_static_combo()
    result = emit(spec, resolved_bindings={}, output_dir=tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rules"] == []
    assert manifest["uxb_handlers_emitted"] is False
    assert manifest["runtime_validated"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_emit.py -v 2>&1 | tail -20`

Expected: 4 new tests fail — emit.py doesn't yet call compile_rules; manifest.py doesn't yet have the new fields.

- [ ] **Step 3: Modify `src/chorus_form_builder/emit.py`**

The current top-of-file imports include `from chorus_form_builder.manifest import build_manifest` and `from chorus_form_builder.spec import FieldSpec, FormSpec`. Add `from chorus_form_builder.procedures import compile_rules` to the imports.

Locate the current `emit()` function. Between CsdForm construction and the Classic XML chain, insert the rules-compile + attach step. The existing code is:

```python
def emit(
    spec: FormSpec,
    resolved_bindings: dict[str, list[DomainValue]],
    output_dir: Path,
) -> EmitResult:
    """Assemble a chorus_forms CsdForm from the spec + resolved bindings,
    drive the Classic XML and UXB JSON chains, write three files."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.csd.models import CsdForm, FormMeta
    from chorus_forms.core.xml_builder import build_user_screen
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model
    from lxml import etree

    try:
        form = CsdForm(
            meta=FormMeta(
                file_name=spec.form.name,
                form_title=spec.form.title,
                form_type=spec.form.type,
                num_pages=spec.form.pages,
            ),
            fields=[
                _spec_field_to_form_field(f, resolved_bindings.get(f.code))
                for f in spec.fields
            ],
        )
    except Exception as e:
        raise EmitError(f"failed to construct chorus_forms.csd.models.CsdForm from spec: {e}") from e

    # ... Classic XML chain ...
    # ... UXB JSON chain ...
    # ... write files + return ...
```

Replace the `emit` function with this new version (which adds the rule-compile step + shim copy + uses the rule_summary in the manifest call):

```python
def emit(
    spec: FormSpec,
    resolved_bindings: dict[str, list[DomainValue]],
    output_dir: Path,
) -> EmitResult:
    """Assemble a chorus_forms CsdForm from the spec + resolved bindings,
    compile any procedure rules into customRules + includeList, drive the
    Classic XML and UXB JSON chains, write the three artifacts (and the
    awdForm.js shim alongside if any rules were emitted)."""
    from chorus_forms.csd.adapter import csd_to_user_screen
    from chorus_forms.csd.models import CsdForm, FormMeta
    from chorus_forms.core.xml_builder import build_user_screen
    from chorus_forms.uxb.builder import csd_to_uxb, to_design_model
    from lxml import etree

    # ----- compile procedure rules (pure, no I/O) -----
    compiled = compile_rules(spec.fields)

    # ----- assemble the chorus_forms CsdForm -----
    try:
        form = CsdForm(
            meta=FormMeta(
                file_name=spec.form.name,
                form_title=spec.form.title,
                form_type=spec.form.type,
                num_pages=spec.form.pages,
            ),
            fields=[
                _spec_field_to_form_field(f, resolved_bindings.get(f.code))
                for f in spec.fields
            ],
            custom_rules=compiled.custom_rules_js,
            include_list=compiled.include_list,
        )
    except Exception as e:
        raise EmitError(f"failed to construct chorus_forms.csd.models.CsdForm from spec: {e}") from e

    # ----- Classic XML chain (unchanged) -----
    try:
        user_screen_model = csd_to_user_screen(form)
        envelope = build_user_screen(user_screen_model)
        csd_bytes = etree.tostring(
            envelope,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
    except Exception as e:
        raise EmitError(f"Classic XML chain failed: {e}") from e

    # ----- UXB JSON chain (unchanged) -----
    try:
        uxb_doc = csd_to_uxb(form)
        uxb_model = to_design_model(uxb_doc, form_type=form.meta.form_type)
        uxb_dict = uxb_model.model_dump(exclude_none=True)
    except Exception as e:
        raise EmitError(f"UXB JSON chain failed: {e}") from e

    output_dir.mkdir(parents=True, exist_ok=True)
    csd_path = output_dir / f"{spec.form.name}.csd"
    uxb_path = output_dir / f"{spec.form.name}.uxb.json"
    manifest_path = output_dir / f"{spec.form.name}_manifest.json"

    csd_path.write_bytes(csd_bytes)
    uxb_path.write_text(json.dumps(uxb_dict, indent=2), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            build_manifest(spec, resolved_bindings, rule_summary=compiled.rule_summary),
            indent=2,
        ),
        encoding="utf-8",
    )

    # ----- ship the shim alongside the .csd when rules were emitted -----
    if compiled.custom_rules_js:
        shim_src = Path(__file__).resolve().parent / "runtime" / "awdForm.js"
        (output_dir / "awdForm.js").write_bytes(shim_src.read_bytes())

    return EmitResult(csd_path=csd_path, uxb_path=uxb_path, manifest_path=manifest_path)
```

- [ ] **Step 4: Modify `src/chorus_form_builder/manifest.py`**

Update `build_manifest` to accept a `rule_summary` argument and emit the four new fields (`rules`, `uxb_handlers_emitted`, `runtime_validated`, `shim_version`). Replace the existing `build_manifest`:

```python
_SHIM_VERSION = "0.1.0"


def build_manifest(
    spec: FormSpec,
    resolved_bindings: dict[str, list[DomainValue]],
    *,
    rule_summary: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Construct the provenance JSON shape.

    All timestamps in a single manifest share one captured `now` — the
    binding-level `fetched_at` does not record the actual API fetch time
    (the resolver ran before this function), it records when the manifest
    was assembled. v0.1 trade-off; carrying the real fetch time would
    require threading it through from the binding resolver.

    `rule_summary` (sub-project C) carries the per-rule provenance:
    [{field_code, kind, source, default_value?}, ...]. Defaults to [] when
    not provided so callers that don't yet thread it through stay valid.
    """
    now = _now_iso()
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
            "fetched_at": now,
            "value_count": domain_count,
        })

    rule_records = rule_summary or []

    return {
        "generator": _GENERATOR_NAME,
        "generator_version": _GENERATOR_VERSION,
        "generated_at": now,
        "form": {
            "name": spec.form.name,
            "title": spec.form.title,
            "field_count": len(spec.fields),
        },
        "bindings": bindings_records,
        "rules": rule_records,
        "uxb_handlers_emitted": False,
        "runtime_validated": False,
        "shim_version": _SHIM_VERSION,
    }
```

Add `Optional` to the typing import line at the top of manifest.py if it's not already there:

```python
from typing import Any, Optional
```

- [ ] **Step 5: Run the suite, expect emit tests to pass + 3 golden tests to fail due to manifest schema bump**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -10`

Expected: 95 + 4 = 99 emit/spec/parser/codegen tests pass. The 3 existing golden tests (`test_golden_static_combo`, `test_golden_oracle_dcmb`, `test_golden_text_plus_combo`) FAIL because their committed manifests don't have the new fields. **That's intentional and expected — Task 7 regenerates them.**

Verify ONLY the 3 golden tests fail (not anything else):

```
D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ --tb=no -q 2>&1 | tail -10
```

Expected output snippet (numbers approximate):
```
FAILED tests/test_goldens.py::test_golden_static_combo
FAILED tests/test_goldens.py::test_golden_oracle_dcmb
FAILED tests/test_goldens.py::test_golden_text_plus_combo
3 failed, 99 passed in ...
```

If any non-golden test fails, fix it before continuing.

- [ ] **Step 6: Commit (emit + manifest changes; goldens not yet regenerated)**

```bash
git add src/chorus_form_builder/emit.py src/chorus_form_builder/manifest.py tests/test_emit.py
git commit -m "feat(emit): wire compile_rules into the emit pipeline + manifest schema bump

emit() now:
- calls procedures.compile_rules(spec.fields) before constructing CsdForm
- passes the compiled JS + include_list into CsdForm(custom_rules=, include_list=)
- copies runtime/awdForm.js to output_dir when at least one rule is present
- threads compiled.rule_summary into build_manifest

manifest.build_manifest now emits four new top-level fields:
- rules: [{field_code, kind, source, default_value?}, ...]
- uxb_handlers_emitted: false  (v0.1 of sub-project C is Classic-only)
- runtime_validated: false     (flips to true after a Chorus dev-soak
                                 verification recipe is run in C v0.2)
- shim_version: '0.1.0'         (matches the awdForm.js header)

The 3 existing golden tests now fail because their committed manifests
pre-date this schema bump. They get regenerated in Task 7."
```

---

## Task 6: Node-based shim integration tests via pytest (TDD)

**Files:**
- Create: `tests/test_js_runtime.py`
- Create: `tests/js_runtime/test_cases/visible_when.js`
- Create: `tests/js_runtime/test_cases/enabled_when.js`
- Create: `tests/js_runtime/test_cases/required_when.js`
- Create: `tests/js_runtime/test_cases/default_when.js`
- Create: `tests/js_runtime/test_cases/multi_rule.js`

- [ ] **Step 1: Write the failing pytest wrapper**

Create `tests/test_js_runtime.py`:

```python
"""Layer-C integration tests — drive emitted customRules JS against the
awdForm shim using Node.

Each test case is a JS file in tests/js_runtime/test_cases/. Pytest
invokes `node tests/js_runtime/runner.js <test-case>` as a subprocess,
parses one JSON line per assertion, and surfaces any failures.

If `node` isn't on PATH, every test in this module skips with a clear
message — the Python suite still runs end-to-end.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _REPO_ROOT / "tests" / "js_runtime" / "runner.js"
_CASES_DIR = _REPO_ROOT / "tests" / "js_runtime" / "test_cases"


def _require_node() -> str:
    """Return the path to a node executable, skipping the test if missing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; install Node 18+ to exercise Layer-C tests")
    return node


def _run_case(case_filename: str) -> list[dict]:
    """Invoke the Node runner against a single test-case file. Returns the
    list of parsed JSON-line assertions; pytest fails the test if any
    assertion's `ok` is False."""
    node = _require_node()
    case_path = _CASES_DIR / case_filename
    assert case_path.is_file(), f"missing test case: {case_path}"

    proc = subprocess.run(
        [node, str(_RUNNER), str(case_path)],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(_REPO_ROOT),
    )
    assertions = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            assertions.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(f"non-JSON output from runner: {line!r}\nstderr: {proc.stderr}")

    # Surface any failed assertion via pytest
    failed = [a for a in assertions if not a.get("ok", False)]
    if failed:
        pytest.fail(
            f"{len(failed)}/{len(assertions)} assertion(s) failed in {case_filename}:\n"
            + "\n".join(f"  - {a['name']}: {a.get('detail', '')}" for a in failed)
            + f"\nfull stderr: {proc.stderr}"
        )
    assert assertions, f"no assertions emitted by {case_filename}; stderr: {proc.stderr}"
    return assertions


def test_layer_c_shim_smoke():
    _run_case("shim_smoke.js")


def test_layer_c_visible_when():
    _run_case("visible_when.js")


def test_layer_c_enabled_when():
    _run_case("enabled_when.js")


def test_layer_c_required_when():
    _run_case("required_when.js")


def test_layer_c_default_when():
    _run_case("default_when.js")


def test_layer_c_multi_rule():
    _run_case("multi_rule.js")
```

- [ ] **Step 2: Run pytest to verify it fails (test-case files don't exist yet)**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_js_runtime.py -v 2>&1 | tail -10`

Expected: 5 tests fail with `missing test case: ...visible_when.js` (or similar). `test_layer_c_shim_smoke` passes (the file exists from Task 4).

- [ ] **Step 3: Write the 5 test-case files**

Create `tests/js_runtime/test_cases/visible_when.js`:

```javascript
// Drive a customRules JS that has one visible_when rule. Verify show/hide
// fires on form-open and on field-change with the correct boolean.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO visible_when STAT == "R"
    awdForm[(stat === "R") ? "show" : "hide"]("MEMO");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    host.state['STAT'] = 'A';  // initial: not Rejected -> MEMO should be hidden
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    const a = [];

    // form-open with STAT='A' -> hide MEMO
    awdForm._emit('form-open');
    const lastCall1 = host.calls[host.calls.length - 1];
    a.push({
      name: 'form-open with STAT=A hides MEMO',
      ok: lastCall1.method === 'hide' && lastCall1.args[0] === 'MEMO',
      detail: JSON.stringify(lastCall1),
    });

    // Change STAT to 'R' and re-emit -> show MEMO
    host.state['STAT'] = 'R';
    awdForm._emit('field-change:STAT');
    const lastCall2 = host.calls[host.calls.length - 1];
    a.push({
      name: 'field-change:STAT with STAT=R shows MEMO',
      ok: lastCall2.method === 'show' && lastCall2.args[0] === 'MEMO',
      detail: JSON.stringify(lastCall2),
    });

    return {assertions: a};
  },
};
```

Create `tests/js_runtime/test_cases/enabled_when.js`:

```javascript
// One enabled_when rule with membership condition.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // ACCT enabled_when STAT in ["A", "P"]
    awdForm[((stat === "A") || (stat === "P")) ? "enable" : "disable"]("ACCT");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    const a = [];

    // STAT='A' -> enable ACCT
    host.state['STAT'] = 'A';
    awdForm._emit('form-open');
    a.push({
      name: 'STAT=A -> enable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'enable',
      detail: JSON.stringify(host.calls[host.calls.length - 1]),
    });

    // STAT='P' (also in set) -> enable
    host.state['STAT'] = 'P';
    awdForm._emit('field-change:STAT');
    a.push({
      name: 'STAT=P -> enable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'enable',
    });

    // STAT='R' (not in set) -> disable
    host.state['STAT'] = 'R';
    awdForm._emit('field-change:STAT');
    a.push({
      name: 'STAT=R -> disable ACCT',
      ok: host.calls[host.calls.length - 1].method === 'disable',
    });

    return {assertions: a};
  },
};
```

Create `tests/js_runtime/test_cases/required_when.js`:

```javascript
const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // MEMO required_when STAT == "R"
    awdForm.setRequired("MEMO", stat === "R");

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    host.state['STAT'] = 'R';
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    awdForm._emit('form-open');
    const c1 = host.calls[host.calls.length - 1];

    host.state['STAT'] = 'A';
    awdForm._emit('field-change:STAT');
    const c2 = host.calls[host.calls.length - 1];

    return {
      assertions: [
        {name: 'STAT=R -> setRequired(MEMO, true)',
         ok: c1.method === 'setRequired' && c1.args[1] === true,
         detail: JSON.stringify(c1)},
        {name: 'STAT=A -> setRequired(MEMO, false)',
         ok: c2.method === 'setRequired' && c2.args[1] === false,
         detail: JSON.stringify(c2)},
      ],
    };
  },
};
```

Create `tests/js_runtime/test_cases/default_when.js`:

```javascript
// default_when: set BATC to 'BATCH-AUTO' iff STAT == 'A' and BATC is empty.

const customRules = `
(function(awdForm) {
  function applyAll() {
    var stat = awdForm.getValue("STAT");

    // BATC default_when STAT == "A" (default_value "BATCH-AUTO", set-if-empty)
    if ((stat === "A") && awdForm.isEmpty("BATC")) {
      awdForm.setValue("BATC", "BATCH-AUTO");
    }

  }

  awdForm.on("form-open", applyAll);
  awdForm.on("field-change:STAT", applyAll);
})(window.awdForm);
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const a = [];

    // Case A: STAT=A, BATC empty -> setValue should fire
    {
      const host = makeHost();
      host.state['STAT'] = 'A';
      host.state['BATC'] = '';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=A + empty BATC -> setValue("BATC", "BATCH-AUTO")',
        ok: set.length === 1 && set[0].args[0] === 'BATC' && set[0].args[1] === 'BATCH-AUTO',
        detail: JSON.stringify(set),
      });
    }

    // Case B: STAT=A, BATC already 'USER-VALUE' -> no setValue
    {
      const host = makeHost();
      host.state['STAT'] = 'A';
      host.state['BATC'] = 'USER-VALUE';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=A + non-empty BATC -> no setValue (set-if-empty)',
        ok: set.length === 0,
        detail: JSON.stringify(set),
      });
    }

    // Case C: STAT='R' -> no setValue regardless of BATC
    {
      const host = makeHost();
      host.state['STAT'] = 'R';
      host.state['BATC'] = '';
      const awdForm = loadShim(host);
      loadAndRunCustomRules(awdForm, customRules);
      awdForm._emit('form-open');
      const set = host.calls.filter(c => c.method === 'setValue');
      a.push({
        name: 'STAT=R + empty BATC -> no setValue (condition false)',
        ok: set.length === 0,
      });
    }

    return {assertions: a};
  },
};
```

Create `tests/js_runtime/test_cases/multi_rule.js`:

```javascript
// All 4 rule kinds on the canonical example (STAT + MEMO + ACCT + BATC).

const customRules = `
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
`;

module.exports = {
  run({makeHost, loadShim, loadAndRunCustomRules}) {
    const host = makeHost();
    host.state['STAT'] = 'A';
    host.state['BATC'] = '';
    const awdForm = loadShim(host);
    loadAndRunCustomRules(awdForm, customRules);

    awdForm._emit('form-open');

    const mutators = host.calls.filter(c => c.method !== 'getValue' && c.method !== 'isEmpty');
    const seq = mutators.map(c => `${c.method}(${c.args.map(JSON.stringify).join(',')})`);

    return {
      assertions: [
        {
          name: 'STAT=A + empty BATC fires hide(MEMO), setRequired(MEMO,false), enable(ACCT), setValue(BATC,BATCH-AUTO) — in declared order',
          ok: seq.join(' | ') === 'hide("MEMO") | setRequired("MEMO",false) | enable("ACCT") | setValue("BATC","BATCH-AUTO")',
          detail: seq.join(' | '),
        },
      ],
    };
  },
};
```

- [ ] **Step 4: Run pytest to verify Layer-C tests pass**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_js_runtime.py -v 2>&1 | tail -15`

Expected: 6 tests pass (1 smoke + 5 scenario). If `node` isn't on PATH, all 6 skip with a clear message — that's OK locally but the implementer should install Node before continuing.

Full suite regression: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ --tb=no -q 2>&1 | tail -5`

Expected (assuming node is installed): 99 + 6 = 105 passing, 3 failing (the golden tests — still pending Task 7).

If `node` isn't installed: 99 passing, 3 failing (goldens), 6 skipped.

- [ ] **Step 5: Commit**

```bash
git add tests/test_js_runtime.py tests/js_runtime/test_cases/visible_when.js tests/js_runtime/test_cases/enabled_when.js tests/js_runtime/test_cases/required_when.js tests/js_runtime/test_cases/default_when.js tests/js_runtime/test_cases/multi_rule.js
git commit -m "test: Layer-C integration tests for procedure-JS via Node

Five new test-case JS files exercising one rule kind each + one
multi-rule case. Each test case drives synthetic form-open and
field-change events through the awdForm shim against representative
host states, and asserts the mutator-call sequence matches what the
codegen promises.

tests/test_js_runtime.py is the pytest wrapper. It locates 'node' on
PATH and shells out to runner.js per case, parses one JSON line per
assertion, and surfaces failures with the failing assertion's name +
detail. If 'node' isn't installed, every Layer-C test skips with a
clear message; the Python suite still runs end-to-end.

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §5"
```

---

## Task 7: Goldens — regenerate existing + add `with_rules` (TDD)

**Files:**
- Create: `tests/goldens/with_rules/form.yaml`
- Modify: `tests/test_goldens.py` (add `test_golden_with_rules`)
- Regenerate (3 existing + 1 new): `tests/goldens/<name>/{*.csd, *.uxb.json, *_manifest.json, awdForm.js?}`

- [ ] **Step 1: Write the failing golden test**

Append to `tests/test_goldens.py`:

```python
def test_golden_with_rules(tmp_path):
    pytest.importorskip("chorus_forms")
    _run_golden("with_rules", tmp_path)

    # Additionally: confirm the awdForm.js shim was emitted alongside the .csd
    out_dir = tmp_path / "out"
    assert (out_dir / "awdForm.js").is_file(), \
        f"with_rules golden should ship awdForm.js next to the .csd; out_dir={list(out_dir.iterdir())}"
    # And it should equal the committed shim
    golden_shim = (Path(__file__).resolve().parent / "goldens" / "with_rules" / "awdForm.js")
    assert golden_shim.is_file(), "with_rules golden dir is missing awdForm.js"
    assert (out_dir / "awdForm.js").read_bytes() == golden_shim.read_bytes()
```

- [ ] **Step 2: Write the `with_rules` golden YAML**

Create `tests/goldens/with_rules/form.yaml`:

```yaml
form:
  name: RULEFRM1
  title: Rules Demo
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
    visible_when: 'STAT == "R"'
    required_when: 'STAT == "R"'
  - code: ACCT
    label: Account
    control_type: text
    length: 10
    enabled_when: 'STAT in ["A", "P"]'
  - code: BATC
    label: Batch
    control_type: text
    length: 6
    default_when: 'STAT == "A"'
    default_value: "BATCH-AUTO"
```

Note: `form.name: RULEFRM1` is 8 characters (within the regex `^[A-Z][A-Z0-9_]{0,7}$`).

- [ ] **Step 3: Run the golden test and observe it failing (no committed outputs yet)**

Run: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_goldens.py::test_golden_with_rules -v 2>&1 | tail -10`

Expected: fails with `no committed .csd golden in ...with_rules` (or similar — the assertions in `_run_golden` fire because no `*.csd` exists in the golden dir yet).

- [ ] **Step 4: Generate the committed outputs for all 4 goldens via REGENERATE_GOLDENS=1**

The 3 existing goldens also need regeneration because Task 5's manifest schema bump added `rules`, `uxb_handlers_emitted`, `runtime_validated`, `shim_version` fields. Run all golden tests in regen mode.

PowerShell from `D:/agent-tool-chorus-form-builder/`:

```powershell
$env:REGENERATE_GOLDENS = "1"
.venv/Scripts/python.exe -m pytest tests/test_goldens.py -v
Remove-Item Env:\REGENERATE_GOLDENS
```

Bash equivalent (from `D:/agent-tool-chorus-form-builder/`):

```bash
REGENERATE_GOLDENS=1 .venv/Scripts/python.exe -m pytest tests/test_goldens.py -v
```

Expected: all 4 tests SKIP with regen messages. New files now exist on disk:
- `tests/goldens/static_combo/{STATCOMB.csd, STATCOMB.uxb.json, STATCOMB_manifest.json}` — updated
- `tests/goldens/oracle_dcmb/{ORACLDC.csd, ORACLDC.uxb.json, ORACLDC_manifest.json}` — updated
- `tests/goldens/text_plus_combo/{TXTCOMBO.csd, TXTCOMBO.uxb.json, TXTCOMBO_manifest.json}` — updated
- `tests/goldens/with_rules/{RULEFRM1.csd, RULEFRM1.uxb.json, RULEFRM1_manifest.json}` — new
- `tests/goldens/with_rules/awdForm.js` — new (the shim ships only for rule-bearing forms)

The existing 3 goldens still ship NO `awdForm.js` (they have no rules).

- [ ] **Step 5: Inspect the generated outputs**

Confirm `tests/goldens/with_rules/RULEFRM1.csd` contains `<customRules>` with non-empty JS and `<jsFile>awdForm.js</jsFile>`:

```bash
grep -c "customRules\|jsFile" tests/goldens/with_rules/RULEFRM1.csd
```

Expected: at least 4 hits (open + close customRules + open + close jsFile).

Confirm `tests/goldens/with_rules/RULEFRM1_manifest.json` has all 4 rule entries:

```bash
.venv/Scripts/python.exe -c "import json; m=json.load(open('tests/goldens/with_rules/RULEFRM1_manifest.json')); print(len(m['rules']), 'rules:', [r['kind'] for r in m['rules']])"
```

Expected: `4 rules: ['visible_when', 'required_when', 'enabled_when', 'default_when']`.

Confirm `tests/goldens/static_combo/STATCOMB_manifest.json` has the new fields with empty/false defaults:

```bash
.venv/Scripts/python.exe -c "import json; m=json.load(open('tests/goldens/static_combo/STATCOMB_manifest.json')); print('rules:', m['rules'], 'uxb:', m['uxb_handlers_emitted'], 'rv:', m['runtime_validated'], 'shim:', m['shim_version'])"
```

Expected: `rules: [] uxb: False rv: False shim: 0.1.0`.

- [ ] **Step 6: Re-run all golden tests in normal mode**

```
D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/test_goldens.py -v 2>&1 | tail -10
```

Expected: all 4 tests PASS.

Full suite: `D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ --tb=no -q 2>&1 | tail -5`

Expected: 105 + 1 = 106 passing, 0 failures (when node is installed). If node is missing: 100 passing, 6 skipped, 0 failing.

- [ ] **Step 7: Commit**

```bash
git add tests/goldens/ tests/test_goldens.py
git commit -m "test(goldens): regenerate existing goldens + add with_rules fixture

Three existing goldens (static_combo, oracle_dcmb, text_plus_combo) get
their manifests regenerated to include the four new fields added by
Task 5: rules: [], uxb_handlers_emitted: false, runtime_validated: false,
shim_version: '0.1.0'. The .csd and .uxb.json bytes for those three
are unchanged.

New tests/goldens/with_rules/ fixture covers all 4 rule kinds:
- form.yaml: STAT (combobox) + MEMO (visible+required) + ACCT (enabled)
  + BATC (default-value)
- RULEFRM1.csd: includes <customRules> with full applyAll JS + <jsFile>
- RULEFRM1.uxb.json: handler-less (UXB v0.1 limit)
- RULEFRM1_manifest.json: rules array has 4 entries
- awdForm.js: byte-identical to the shipped runtime

Spec: docs/superpowers/specs/2026-05-23-procedure-js-generator-v01-design.md §5"
```

---

## Task 8: README + final smoke

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with a "Rules" section**

The current README documents the v0.1 form-builder. Append (or insert after the existing "Spec format" section) a new "Rules" section. Open `README.md`, find the heading `## Spec format`, and add this block immediately after that section (before `## Output`):

```markdown
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
```

- [ ] **Step 2: Run full suite as the final regression gate**

```
D:/agent-tool-chorus-form-builder/.venv/Scripts/python.exe -m pytest tests/ -v 2>&1 | tail -20
```

Expected: 106 passing (when node is on PATH), 0 failures, 0 unexpected skips.

If `node` isn't installed, 6 Layer-C tests skip — that's acceptable but flag it in the PR body so a reviewer knows the JS-runtime layer wasn't exercised on this machine.

- [ ] **Step 3: Manual CLI smoke against the new with_rules golden**

```bash
cd /d/agent-tool-chorus-form-builder
rm -rf /tmp/c-smoke 2>/dev/null   # Bash; PowerShell: Remove-Item -Recurse -Force $env:TEMP/c-smoke
.venv/Scripts/python.exe -m chorus_form_builder.cli \
  --spec tests/goldens/with_rules/form.yaml \
  --output /tmp/c-smoke \
  --no-fetch
```

Expected exit 0, expected stdout: `Wrote RULEFRM1.csd + .uxb.json + _manifest.json -> /tmp/c-smoke`.

Then verify all 4 files exist:

```bash
ls /tmp/c-smoke/
# Should show: RULEFRM1.csd  RULEFRM1.uxb.json  RULEFRM1_manifest.json  awdForm.js
```

Inspect the generated customRules:

```bash
grep -A1 customRules /tmp/c-smoke/RULEFRM1.csd | head -3
```

Should show non-empty `<customRules>` content.

- [ ] **Step 4: Commit + close out**

```bash
git add README.md
git commit -m "docs: README — Rules section + deployment step

New 'Rules' section between 'Spec format' and 'Output' covering the
running example (STAT + MEMO + ACCT + BATC with all 4 rule kinds), the
Tier-2 condition grammar, and the one-time awdForm.js deployment step
(/awd/forms/lib/awdForm.js).

Limits called out explicitly: UXB handler-less in v0.1, set-if-empty
defaults, no cascading from setValue, runtime not yet bridged to live
Chorus (validated flag stays false until C v0.2 runs the dev-soak
verification recipe)."
```

---

## Self-review checklist (post-write)

**Spec coverage:**

- ✅ §1 Architecture (single-repo extension, procedures.py + runtime/) — Tasks 1, 3, 4, 5
- ✅ §2 DSL schema (5 FieldSpec attrs, pairing validator, rule-grammar validator, field-ref scope validator, Tier-2 grammar) — Tasks 1, 2
- ✅ §3 Mini-runtime API (awdForm shim) + generated JS shape — Tasks 3, 4
- ✅ §4 Emit pipeline integration (compile_rules → CsdForm.custom_rules + include_list, shim copy, manifest updates) — Task 5
- ✅ §5 Tests (4 layers: parser, codegen, Node shim integration, golden) + error handling — Tasks 1, 3, 6, 7
- ✅ Risks §1 (real runtime not exposing our hooks) — manifest's `runtime_validated: false` from Task 5
- ✅ Risks §2 (DSL grammar precedence) — Task 1's precedence test
- ✅ Risks §3 (unknown-field-reference catching) — Task 2's FormSpec validator + Task 1's validate_rule
- ✅ Risks §4 (setValue no-cascade) — Task 4's shim contract + Task 6's smoke test
- ✅ Risks §5 (shim byte drift across releases) — Task 4's inline semver comment + Task 5's `shim_version` field
- ✅ Risks §6 (UXB output advertising un-honored rules) — manifest's `uxb_handlers_emitted: false` from Task 5
- ✅ Risks §7 (golden churn from manifest schema bump) — Task 7 regenerates all goldens

**Placeholder scan:**

- ✅ No TBDs, no "handle errors appropriately", every step has complete code or a complete command
- ✅ Every test step is a full pytest or JS function body
- ✅ Every src file step is the complete file body (or an `Append`/`Replace this function` with the full target code)

**Type consistency:**

- ✅ `compile_rules` returns a `CompiledRules` dataclass with `(custom_rules_js, include_list, rule_summary)` — used consistently in Task 3 (definition), Task 5 (emit consumes it), Task 7 (manifest test inspects fields)
- ✅ Rule AST node names (`Eq`, `Neq`, `Lt`, `Gt`, `Le`, `Ge`, `In`, `NotIn`, `And`, `Or`, `Not`, `Paren`, `FieldRef`, `Literal`) used identically in parser definition (Task 1) and codegen (Task 3)
- ✅ `FieldSpec` attribute names (`visible_when`, `enabled_when`, `required_when`, `default_when`, `default_value`) match across spec.py (Task 2), test fixtures (Tasks 2, 3, 5, 7), and README (Task 8)
- ✅ Shim API methods (`getValue`, `isEmpty`, `show`, `hide`, `enable`, `disable`, `setRequired`, `setValue`, `on`, `_emit`) match between shim (Task 4), codegen output (Task 3), Node test cases (Tasks 4, 6)
- ✅ Manifest new fields (`rules`, `uxb_handlers_emitted`, `runtime_validated`, `shim_version`) consistent across Task 5 (build), Task 7 (golden regenerate), README (Task 8)

No spec requirements without a mapping task. No unresolved hand-waves. Plan is implementation-ready.
