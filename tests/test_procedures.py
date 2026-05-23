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
