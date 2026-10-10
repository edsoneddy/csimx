"""Canonical operator forms for java_20 (see ../canonical_common.py).
"""
from ..canonical_common import CanonicalSpec, canonicalize_with
from .Java20Lexer import Java20Lexer as L
from .Java20Parser import Java20Parser as P
from ..utils import TOKEN_TYPE_OFFSET

_T = TOKEN_TYPE_OFFSET
SPEC = CanonicalSpec(
    commutative=frozenset({P.RULE_additiveExpression, P.RULE_multiplicativeExpression, P.RULE_equalityExpression}),
    commutative_ops=frozenset({L.ADD + _T, L.MUL + _T, L.EQUAL + _T, L.NOTEQUAL + _T}),
    symmetric=frozenset({
        P.RULE_relationalExpression, P.RULE_conditionalAndExpression, P.RULE_conditionalOrExpression,
        P.RULE_andExpression, P.RULE_exclusiveOrExpression, P.RULE_inclusiveOrExpression,
    }),
    orient=(frozenset({P.RULE_relationalExpression}), {L.GE + _T: L.LE + _T}),
)


def canonicalize(tree):
    return canonicalize_with(SPEC, tree)
