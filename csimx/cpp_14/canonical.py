"""Canonical operator forms for cpp_14 (see ../canonical_common.py).
"""
from ..canonical_common import CanonicalSpec, canonicalize_with
from .CPP14Lexer import CPP14Lexer as L
from .CPP14Parser import CPP14Parser as P
from ..utils import TOKEN_TYPE_OFFSET

_T = TOKEN_TYPE_OFFSET
SPEC = CanonicalSpec(
    commutative=frozenset({
        P.RULE_additiveExpression, P.RULE_multiplicativeExpression, P.RULE_equalityExpression,
        P.RULE_andExpression, P.RULE_inclusiveOrExpression,
    }),
    commutative_ops=frozenset({L.Plus + _T, L.Star + _T, L.Equal + _T, L.NotEqual + _T, L.And + _T, L.Or + _T}),
    symmetric=frozenset({P.RULE_logicalAndExpression, P.RULE_logicalOrExpression, P.RULE_exclusiveOrExpression}),
    orient=(
        frozenset({P.RULE_relationalExpression}),
        {L.Greater + _T: L.Less + _T, L.GreaterEqual + _T: L.LessEqual + _T},
    ),
)


def canonicalize(tree):
    return canonicalize_with(SPEC, tree)
