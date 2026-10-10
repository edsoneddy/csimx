"""Canonical operator forms for kotlin (see ../canonical_common.py).
"""
from ..canonical_common import CanonicalSpec, canonicalize_with
from .KotlinLexer import KotlinLexer as L
from .KotlinParser import KotlinParser as P
from ..utils import TOKEN_TYPE_OFFSET

_T = TOKEN_TYPE_OFFSET
SPEC = CanonicalSpec(
    commutative=frozenset({P.RULE_additiveExpression, P.RULE_multiplicativeExpression, P.RULE_equalityComparison}),
    commutative_ops=frozenset({L.ADD + _T, L.MULT + _T, L.EQEQ + _T, L.EXCL_EQ + _T}),
    symmetric=frozenset({P.RULE_conjunction, P.RULE_disjunction}),
    orient=(
        frozenset({P.RULE_comparison}),
        {L.RANGLE + _T: L.LANGLE + _T, L.GE + _T: L.LE + _T},
    ),
)


def canonicalize(tree):
    return canonicalize_with(SPEC, tree)
