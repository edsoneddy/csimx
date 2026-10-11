"""Lower bounds of the tree edit distance (`group` skips the pairs they rule out)."""
import itertools

import pytest

from csimx.processing.distance_metrics import SimilarityIndex, TreeEditDistance
from csimx.processing.lower_bounds import (
    CanReachThreshold,
    LabelLowerBound,
    LabelTable,
    SequenceLowerBound,
    SizeLowerBound,
    TreeProfile,
    UpperBoundIndex,
)
from csimx.utils import group_by_exhaustive_search, preprocess_code
from test_lexical import SAMPLES, LANGS

# one more program per language, so that there are pairs of every kind (equal, close, far)
EXTRA = {
    "python_3": "def f(a, b):\n    if a > b:\n        return a - b\n    return b - a\n",
    "java_20": "class D { int f(int a, int b) { if (a > b) { return a - b; } return b - a; } }",
    "cpp_14": "int f(int a, int b) { if (a > b) { return a - b; } return b - a; }",
    "c": "int f(int a, int b) { if (a > b) { return a - b; } return b - a; }",
    "kotlin": "fun f(a: Int, b: Int): Int { if (a > b) { return a - b }; return b - a }",
}
EXTRA["python_3_13"] = EXTRA["python_3"]
EXTRA["java_24"] = EXTRA["java_20"]


def programs(lang):
    return [*SAMPLES[lang], EXTRA[lang]]


@pytest.mark.parametrize("lang", LANGS)
def test_bounds_never_exceed_the_edit_distance(lang):
    trees = [preprocess_code(f"s{i}", code, lang) for i, code in enumerate(programs(lang))]
    table = LabelTable()
    profiles = [TreeProfile(t, m, table) for t, m in trees]
    for i, j in itertools.combinations(range(len(trees)), 2):
        d = TreeEditDistance(trees[i][0], trees[j][0], "apted")
        a, b = profiles[i], profiles[j]
        assert SizeLowerBound(a, b) <= d + 1e-9
        assert LabelLowerBound(a, b) <= d + 1e-9
        # a cutoff above the real distance returns a value that is still a bound
        assert SequenceLowerBound(a, b, d + 5, table) <= d + 1e-9
        # a cutoff under it may only say "at least the cutoff"
        low = max(d - 1.0, 0.5)
        assert SequenceLowerBound(a, b, low, table) <= max(d, low) + 1e-9


@pytest.mark.parametrize("formula", ["legacy", "ratio", "metric"])
def test_upper_bound_index_covers_every_larger_distance(formula):
    for mass_a, mass_b in [(5, 5), (10, 30), (40, 41)]:
        for d_lb in [0.0, 1.0, 4.5, 10.0, 25.0, 60.0]:
            top = UpperBoundIndex(d_lb, mass_a, mass_b, formula, SimilarityIndex)
            for extra in [0.0, 0.5, 3.0, 17.0, 100.0]:
                assert SimilarityIndex(d_lb + extra, mass_a, mass_b, formula) <= top + 1e-9


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("formula", ["legacy", "ratio"])
@pytest.mark.parametrize("threshold", [0.3, 0.7, 0.9])
def test_a_pair_over_the_threshold_is_never_ruled_out(lang, formula, threshold):
    trees = [preprocess_code(f"s{i}", code, lang) for i, code in enumerate(programs(lang))]
    table = LabelTable()
    profiles = [TreeProfile(t, m, table) for t, m in trees]
    for i, j in itertools.combinations(range(len(trees)), 2):
        d = TreeEditDistance(trees[i][0], trees[j][0], "apted")
        index = SimilarityIndex(d, trees[i][1], trees[j][1], formula)
        if index > threshold:
            assert CanReachThreshold(profiles[i], profiles[j], threshold, formula, SimilarityIndex, table)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("threshold", [0.5, 0.8])
def test_group_is_the_same_with_and_without_bounds(lang, threshold):
    codes = programs(lang) + [programs(lang)[0].replace("a", "alpha")]
    names = [f"f{i}.txt" for i in range(len(codes))]
    plain = group_by_exhaustive_search(names, codes, lang, threshold, "apted", bounds=False)
    fast = group_by_exhaustive_search(names, codes, lang, threshold, "apted", bounds=True)
    assert plain == fast
    # the connected-pairs skip keeps the groups, only the averages may change
    stats = {}
    kept = group_by_exhaustive_search(
        names, codes, lang, threshold, "apted", printable_output=False, skip_connected=True, stats=stats
    )
    reference = group_by_exhaustive_search(
        names, codes, lang, threshold, "apted", printable_output=False, bounds=False
    )
    assert sorted(map(sorted, kept[0])) == sorted(map(sorted, reference[0]))
    assert stats["compared"] + stats["bound_skipped"] + stats["connected_skipped"] == stats["pairs"]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("threshold", [0.3, 0.7])
def test_group_keeps_its_groups_with_skip_connected(lang, threshold):
    codes = programs(lang) + [programs(lang)[0].replace("a", "alpha"), programs(lang)[1]]
    names = [f"f{i}.txt" for i in range(len(codes))]
    reference = group_by_exhaustive_search(
        names, codes, lang, threshold, "apted", printable_output=False, bounds=False
    )
    for options in ({"skip_connected": True},):
        fast = group_by_exhaustive_search(
            names, codes, lang, threshold, "apted", printable_output=False, **options
        )
        assert sorted(map(sorted, fast[0])) == sorted(map(sorted, reference[0]))
        assert sorted(fast[2]) == sorted(reference[2])
