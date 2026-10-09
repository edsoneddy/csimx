"""Operator canonical forms of java_20, java_24, cpp_14 and c (csimx/canonical_common.py)."""
import pytest

from csimx import Compare

JAVA = "class A { int f(int a, int b, int c) { %s } }"
CLIKE = "int f(int a, int b, int c) { %s }"
KOTLIN = "fun f(a: Int, b: Int, c: Int): Int { %s }"

# (language, template, body, equivalent body)
EQUIVALENT = [
    (lang, tpl, x, y)
    for lang, tpl in (("java_20", JAVA), ("java_24", JAVA), ("cpp_14", CLIKE), ("c", CLIKE))
    for x, y in (
        ("return a + b * c;", "return c * b + a;"),
        ("if (a >= b) return 1; return 2;", "if (b <= a) return 1; return 2;"),
        ("if (a > b + 1) return 1; return 2;", "if (1 + b < a) return 1; return 2;"),
        ("if (a == b && c != a * 2) return 1; return 2;", "if (a * 2 != c && b == a) return 1; return 2;"),
    )
    # java_24 folds `<`, `>` and `&&` (tokens excluded) into the shared `expression` rule, so
    # those two forms cannot be told apart from a call or a field access and are left alone.
    if not (lang == "java_24" and "b + 1" in x or lang == "java_24" and "&&" in x)
]

EQUIVALENT += [
    ("kotlin", KOTLIN, x, y)
    for x, y in (
        ("return a + b * c", "return c * b + a"),
        ("if (a >= b) return 1; return 2", "if (b <= a) return 1; return 2"),
        ("if (a > b + 1) return 1; return 2", "if (1 + b < a) return 1; return 2"),
        ("if (a == b && c != a * 2) return 1; return 2", "if (a * 2 != c && b == a) return 1; return 2"),
    )
]


@pytest.mark.parametrize("lang,tpl,x,y", EQUIVALENT)
def test_equivalent_operator_forms_give_the_same_tree(lang, tpl, x, y):
    assert Compare(content_a=tpl % x, content_b=tpl % y, lang=lang) == 1.0


@pytest.mark.parametrize(
    "lang,tpl,x,y",
    [
        ("java_20", JAVA, "return a + b;", "for (int i = 0; i < a; i++) c += i; return c;"),
        ("java_24", JAVA, "return a + b;", "for (int i = 0; i < a; i++) c += i; return c;"),
        ("cpp_14", CLIKE, "return a + b;", "for (int i = 0; i < a; i++) c += i; return c;"),
        ("c", CLIKE, "return a + b;", "for (int i = 0; i < a; i++) c += i; return c;"),
        ("kotlin", KOTLIN, "return a + b", "var s = c; for (i in 0 until a) { s += i }; return s"),
    ],
)
def test_different_programs_stay_different(lang, tpl, x, y):
    a, b = tpl % x, tpl % y
    assert Compare(content_a=a, content_b=b, lang=lang) < 0.6
