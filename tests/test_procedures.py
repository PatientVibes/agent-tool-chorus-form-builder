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
    assert ast == In(FieldRef("STAT"), (Literal("A"), Literal("P")))


def test_parser_not_in():
    ast = parse_rule_expr('STAT not in ["A", "P"]')
    assert ast == NotIn(FieldRef("STAT"), (Literal("A"), Literal("P")))


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
    """`STAT == FROM` is field-to-field — out of Tier 2 scope.

    Expected behaviour: parser sees FROM and tries to read it as a literal,
    fails because field codes aren't valid literals. Assertion narrows on
    the 'literal' substring so this catches the right error class, not just
    any SpecValidationError.
    """
    with pytest.raises(SpecValidationError) as exc:
        parse_rule_expr("STAT == FROM")
    assert "literal" in str(exc.value).lower(), \
        f"expected 'literal' in error msg, got: {exc.value}"


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
    certainly a typo. Parser rejects it — _parse_literal_list calls
    _parse_literal unconditionally before the comma loop, so the closing
    `]` is seen where a literal was expected."""
    with pytest.raises(SpecValidationError) as exc:
        parse_rule_expr("STAT in []")
    assert "literal" in str(exc.value).lower(), \
        f"expected 'literal' in error msg, got: {exc.value}"


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
    """Identical inputs produce byte-identical JS output. Uses two independently
    built FieldSpec lists so this also rules out object-identity shortcuts —
    purely content-driven determinism."""
    def _make_fields():
        return [
            _field("STAT", control_type="combobox",
                   values=[DomainValueSpec(value="A", description="A")]),
            _field("MEMO", length=60,
                   visible_when='STAT == "A"', required_when='STAT == "A"'),
        ]
    js1 = compile_rules(_make_fields()).custom_rules_js
    js2 = compile_rules(_make_fields()).custom_rules_js
    assert js1 == js2


def test_compile_rules_reserved_word_field_code():
    """Codex caught: a valid 4-char field code that lowercases to a JS reserved
    word (NULL, TRUE, THIS, VOID, WITH, ...) would have emitted invalid JS like
    `var null = awdForm.getValue("NULL");`. _safe_var prefixes those names
    with an underscore so the emitted JS is syntactically valid.
    """
    fields = [
        _field("NULL", control_type="combobox",
               values=[DomainValueSpec(value="A", description="A")]),
        _field("MEMO", length=60, visible_when='NULL == "A"'),
    ]
    js = compile_rules(fields).custom_rules_js
    # The local var name for NULL must be sanitized to '_null', not 'null'.
    assert 'var _null = awdForm.getValue("NULL");' in js, \
        f"NULL field code should sanitize to _null; got: {js}"
    # The condition referencing NULL must also use the sanitized name.
    assert 'awdForm[(_null === "A") ? "show" : "hide"]("MEMO");' in js, \
        f"NULL field reference should use _null in the condition; got: {js}"
    # The event subscription still uses the original CODE (which is what
    # the runtime dispatches on — only the local JS var name is sanitized).
    assert 'awdForm.on("field-change:NULL", applyAll);' in js


def test_compile_rules_compound_conditions():
    """Cross-branch review caught: And / Or / Not / NotIn codegen paths were
    only exercised indirectly via the golden — no dedicated codegen test
    asserted the JS produced for compound conditions. Each rendering path in
    _render_condition deserves a direct assertion so a future refactor of
    that dispatch surfaces here, not in a golden diff.
    """
    fields = [
        _field("STAT", control_type="combobox",
               values=[DomainValueSpec(value="A", description="A")]),
        _field("AMTV", length=10),
        # `and` + numeric comparison
        _field("FLD1", length=60, visible_when='STAT == "A" and AMTV > 100'),
        # `or`
        _field("FLD2", length=60, visible_when='STAT == "A" or STAT == "P"'),
        # `not` + parens
        _field("FLD3", length=60, visible_when='not (STAT == "R")'),
        # `not in`
        _field("FLD4", length=60, visible_when='STAT not in ["R", "C"]'),
    ]
    js = compile_rules(fields).custom_rules_js

    # And — wraps the whole compound in outer parens, sub-expressions bare
    assert '(stat === "A" && amtv > 100)' in js, \
        f"And path didn't render expected JS; got: {js}"
    # Or — same pattern
    assert '(stat === "A" || stat === "P")' in js, \
        f"Or path didn't render expected JS; got: {js}"
    # Not (with Paren) — !((inner)). The double parens come from Not wrapping
    # the Paren node which itself adds parens around its inner.
    assert '!((stat === "R"))' in js, \
        f"Not/Paren paths didn't render expected JS; got: {js}"
    # NotIn — each comparison wrapped in parens, joined by &&
    assert '((stat !== "R") && (stat !== "C"))' in js, \
        f"NotIn path didn't render expected JS; got: {js}"
