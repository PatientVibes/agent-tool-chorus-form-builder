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
    # tuple (not list) so frozen=True actually gives hashability — see Task 1
    # code-review note. list[X] is unhashable even inside a frozen dataclass.
    right: tuple[Literal, ...]


@dataclass(frozen=True)
class NotIn:
    left: FieldRef
    right: tuple[Literal, ...]


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
    # FIELD_REF intentionally appears BEFORE KW in the alternation. Order
    # matters in regex alternation when patterns could overlap. They don't
    # overlap here — field codes are uppercase ([A-Z]…) and keywords are
    # lowercase — so the order is safe today. Don't relax FIELD_REF to mixed
    # case without re-ordering this list.
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
            return In(field, tuple(items))
        if nxt.kind == "KW" and nxt.text == "not":
            self._consume()
            self._expect("KW", "in")
            self._expect("LBRACK")
            items = self._parse_literal_list()
            self._expect("RBRACK")
            return NotIn(field, tuple(items))

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
