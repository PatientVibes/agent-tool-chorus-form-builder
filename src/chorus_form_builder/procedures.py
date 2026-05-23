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

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Union

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


# --- codegen ---


@dataclass(frozen=True)
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
    return json.dumps(v)  # handles escaping; produces double-quoted


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
            f"({varmap[node.left.code]} === {_render_literal_js(lit)})"
            for lit in node.right
        )
        return f"({parts})"
    if isinstance(node, NotIn):
        parts = " && ".join(
            f"({varmap[node.left.code]} !== {_render_literal_js(lit)})"
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


def _collect_rules(fields) -> list[tuple[str, str, str, Any, object]]:
    """Return list of (field_code, kind, source, default_value, ast) tuples in
    declaration + kind order. Skips fields with no rules.

    The AST is parsed once here and threaded through to downstream consumers
    (`_referenced_field_codes` + `compile_rules`) so the rule string is not
    re-parsed at every consumer call.
    """
    out: list[tuple[str, str, str, Any, object]] = []
    for f in fields:
        for kind, attr in _RULE_KINDS_AND_ATTRS:
            src = getattr(f, attr)
            if src is None:
                continue
            dv = f.default_value if kind == "default_when" else None
            ast = parse_rule_expr(src)
            out.append((f.code, kind, src, dv, ast))
    return out


def _referenced_field_codes(rules: list[tuple[str, str, str, Any, object]]) -> list[str]:
    """Unique field codes referenced in any rule, in first-seen order.
    Consumes the cached AST from `_collect_rules` — no re-parse."""
    seen: list[str] = []
    for (_target, _kind, _src, _dv, ast) in rules:
        for ref in _walk_field_refs(ast):
            if ref.code not in seen:
                seen.append(ref.code)
    return seen


# JS reserved words that are EXACTLY 4 characters long. Field codes are
# also exactly 4 characters (regex ^[A-Z][A-Z0-9]{3}$), so a field code
# that lowercases to one of these would emit syntax-invalid JS like
# `var null = awdForm.getValue("NULL");`. _safe_var below adds an
# underscore prefix only on collision so the emitted JS stays valid
# without churning the existing tests that use STAT/MEMO/etc.
_JS_RESERVED_4CHAR = frozenset({
    "null", "true", "case", "else", "enum", "void", "with", "this",
    "byte", "char", "goto", "long",
})


def _safe_var(code: str) -> str:
    """Lowercase the field code into a JS-safe local variable name.
    Prefixes with '_' only when the lowercased code collides with a JS
    reserved word — non-colliding codes (STAT, MEMO, ACCT, ...) keep
    their natural lowercase form."""
    lower = code.lower()
    return f"_{lower}" if lower in _JS_RESERVED_4CHAR else lower


def compile_rules(fields) -> CompiledRules:
    """Top-level: list[FieldSpec] -> CompiledRules.

    Pure function. Same input -> byte-identical output (lets goldens work).
    """
    rules = _collect_rules(fields)
    if not rules:
        return CompiledRules(custom_rules_js="", include_list=[], rule_summary=[])

    referenced_codes = _referenced_field_codes(rules)
    varmap = {code: _safe_var(code) for code in referenced_codes}

    lines: list[str] = []
    lines.append("(function(awdForm) {")
    lines.append("  function applyAll() {")
    for code in referenced_codes:
        lines.append(f'    var {varmap[code]} = awdForm.getValue("{code}");')
    lines.append("")

    for (target, kind, src, default_val, ast) in rules:
        cond = _render_condition(ast, varmap)
        lines.append(f"    // {target} {kind} {src}")
        # Wrap bare (non-parenthesised) conditions in parens so the JS ternary
        # and && operator bind correctly at each call-site.
        wrapped = cond if cond.startswith("(") else f"({cond})"
        if kind == "visible_when":
            lines.append(f'    awdForm[{wrapped} ? "show" : "hide"]("{target}");')
        elif kind == "enabled_when":
            lines.append(f'    awdForm[{wrapped} ? "enable" : "disable"]("{target}");')
        elif kind == "required_when":
            lines.append(f'    awdForm.setRequired("{target}", {cond});')
        elif kind == "default_when":
            lit = _render_literal_js(Literal(default_val))
            lines.append(f'    if ({wrapped} && awdForm.isEmpty("{target}")) {{')
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
    for (target, kind, src, default_val, _ast) in rules:
        entry = {"field_code": target, "kind": kind, "source": src}
        if kind == "default_when":
            entry["default_value"] = default_val
        summary.append(entry)

    return CompiledRules(
        custom_rules_js=js,
        include_list=[{"js_file": "awdForm.js"}],
        rule_summary=summary,
    )
