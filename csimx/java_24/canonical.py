"""Canonical operator forms for java_24 (see ../canonical_common.py).

java_24 folds every binary operator into the single `expression` rule and excludes the tokens of
`<`, `>`, `&&`, `||`, ... so a two-child `expression` is ambiguous (a call, a field access, a
logical or relational operator) and is left alone. Only the operators that keep their token are
unified: `+`, `*`, `==`, `!=` (operand order) and `>=` -> `<=`.
"""
from ..canonical_common import CanonicalSpec, canonicalize_with
from .Java24Lexer import Java24Lexer as L
from .Java24Parser import Java24Parser as P
from ..utils import TOKEN_TYPE_OFFSET

_T = TOKEN_TYPE_OFFSET
SPEC = CanonicalSpec(
    commutative=frozenset({P.RULE_expression}),
    commutative_ops=frozenset({L.ADD + _T, L.MUL + _T, L.EQUAL + _T, L.NOTEQUAL + _T}),
    orient=(frozenset({P.RULE_expression}), {L.GE + _T: L.LE + _T}),
)


def canonicalize(tree):
    return canonicalize_with(SPEC, tree)
