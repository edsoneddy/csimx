"""Lexical stage and the `group` prefilter, for every supported language."""
import os

import pytest

from csimx import LexicalAtLeast, LexicalDistance, LexicalIndex, Tokenize
from csimx.utils import group_by_exhaustive_search, process_files

# (language, a program, the same program with other names/values/comments/layout, an unrelated one)
SAMPLES = {
    "python_3": (
        "def f(a, b):\n    # sum\n    return a + b\n",
        "def g(x, y):\n    return   x + y  # other\n",
        "class A:\n    def run(self):\n        for i in range(10):\n            print(i)\n",
    ),
    "java_20": (
        "class A { int f(int a, int b) { /* sum */ return a + b; } }",
        "class B {\n  int g(int x, int y) { return x + y; } // other\n}",
        "class C { void run() { for (int i = 0; i < 10; i++) System.out.println(i); } }",
    ),
    "cpp_14": (
        "#include <vector>\nint f(int a, int b) { /* sum */ return a + b; }",
        "int g(int x, int y) {\n  return x + y; // other\n}",
        "void run() { for (int i = 0; i < 10; i++) std::cout << i << std::endl; }",
    ),
    "c": (
        "#include <stdio.h>\nint f(int a, int b) { /* sum */ return a + b; }",
        "int g(int x, int y) {\n  return x + y; // other\n}",
        "void run() { for (int i = 0; i < 10; i++) printf(\"%d\", i); }",
    ),
    "kotlin": (
        "fun f(a: Int, b: Int): Int { /* sum */ return a + b }",
        "fun g(x: Int, y: Int): Int {\n  return x + y // other\n}",
        "fun run() { for (i in 0 until 10) println(\"v $i\") }",
    ),
}
SAMPLES["python_3_13"] = SAMPLES["python_3"]
SAMPLES["java_24"] = SAMPLES["java_20"]
LANGS = sorted(SAMPLES)


def index(a, b, lang):
    ta, tb = Tokenize(a, lang), Tokenize(b, lang)
    return LexicalIndex(LexicalDistance(ta, tb), len(ta), len(tb))


@pytest.mark.parametrize("lang", LANGS)
def test_renamed_and_recommented_program_has_the_same_tokens(lang):
    a, b, _ = SAMPLES[lang]
    assert index(a, b, lang) == 1.0


@pytest.mark.parametrize("lang", LANGS)
def test_unrelated_program_is_far(lang):
    a, _, c = SAMPLES[lang]
    assert index(a, c, lang) < 0.6


@pytest.mark.parametrize("lang", LANGS)
def test_at_least_agrees_with_the_distance(lang):
    a, b, c = SAMPLES[lang]
    ta, tb, tc = (Tokenize(x, lang) for x in (a, b, c))
    assert LexicalAtLeast(ta, tb, 0.9) is not None
    assert LexicalAtLeast(ta, tc, 0.9) is None


def test_keyword_subtypes_are_kept_as_written():
    # Keyword.Type / Keyword.Declaration used to collapse to one id: `int` == `double`
    assert Tokenize("int x;", "c") != Tokenize("double x;", "c")
    assert Tokenize("public static void f() {}", "java_20") != Tokenize("static public void f() {}", "java_20")
    assert Tokenize("x = a and b", "python_3") != Tokenize("x = a or b", "python_3")


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError):
        Tokenize("x", "cobol")


@pytest.mark.parametrize("lang", LANGS)
def test_group_gives_the_same_groups_with_and_without_prefilter(lang, capsys):
    a, b, c = SAMPLES[lang]
    names, contents = ["a", "b", "c"], [a, b, c]
    plain = group_by_exhaustive_search(names, contents, lang, 0.7, "apted", printable_output=False)
    stats = {}
    filtered = group_by_exhaustive_search(
        names, contents, lang, 0.7, "apted", printable_output=False, prefilter_margin=0.05, stats=stats
    )
    assert filtered == plain
    assert stats["pairs"] == 3 and stats["files"] == 3
    assert stats["skipped"] >= 1  # the unrelated program is never parsed against the others


def test_unreadable_file_is_skipped(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "bad.py").write_bytes(b"x = '\xff\xfe'\n")
    names, contents = process_files(str(tmp_path), "python_3")
    assert [os.path.basename(n) for n in names] == ["ok.py"]
    assert contents == ["x = 1\n"]
