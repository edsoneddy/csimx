"""Progress callback of `group` and the time estimate (csimx/estimate.py)."""
import pytest

from csimx import calibrate, estimate_group, group_by_exhaustive_search
from csimx.estimate import SECONDS_PER_UNIT, pair_cost

from test_lexical import LANGS, SAMPLES


def inputs(lang):
    a, b, c = SAMPLES[lang]
    return ["a", "b", "c", "d"], [a, b, c, a + "\n"]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("margin", [None, 0.05])
def test_progress_does_not_change_the_result_and_is_monotone(lang, margin):
    names, contents = inputs(lang)
    kw = dict(printable_output=False, prefilter_margin=margin)
    plain = group_by_exhaustive_search(names, contents, lang, 0.7, "apted", **kw)
    events = []
    stats = {}
    seen = group_by_exhaustive_search(
        names, contents, lang, 0.7, "apted", stats=stats, progress=lambda *e: events.append(e), **kw
    )
    assert seen == plain
    phases = [p for p, _, _ in events]
    assert phases == sorted(phases, key=["parse", "lexical", "structural"].index)  # never goes back
    structural = [(d, t) for p, d, t in events if p == "structural"]
    assert structural[0][0] == 0 and structural[-1][0] == structural[-1][1]
    assert [d for d, _ in structural] == sorted(d for d, _ in structural)
    assert structural[0][1] == stats["pairs"] - stats["skipped"]
    assert ("lexical" in phases) == (margin is not None) and ("parse" in phases) == (margin is None)


@pytest.mark.parametrize("lang", LANGS)
def test_estimate_counts_the_pairs_that_group_compares(lang):
    names, contents = inputs(lang)
    stats = {}
    group_by_exhaustive_search(
        names, contents, lang, 0.7, "apted", printable_output=False, prefilter_margin=0.05, stats=stats
    )
    est = estimate_group(names, contents, lang, threshold=0.7, prefilter_margin=0.05)
    assert est["pairs"] == stats["pairs"] == 6
    assert est["skipped"] == stats["skipped"]
    assert est["structural_pairs"] == stats["pairs"] - stats["skipped"]
    assert est["files"] == 4 and est["nodes"]["max"] >= est["nodes"]["median"] > 0
    low, high = est["range_seconds"]
    assert 0 < low <= est["estimated_seconds"] <= high


def test_estimate_without_prefilter_compares_every_pair_and_scales_with_speed():
    a, b, c = SAMPLES["python_3"]
    names = [str(i) for i in range(18)]
    contents = [(a, b, c)[i % 3] + "\n" * i for i in range(18)]
    one = estimate_group(names, contents, "python_3")
    slow = estimate_group(names, contents, "python_3", speed_factor=4.0)
    assert one["structural_pairs"] == one["pairs"] and one["skipped"] == 0
    structural_one = one["estimated_seconds"] - one["parse_seconds"]
    structural_slow = slow["estimated_seconds"] - slow["parse_seconds"]
    assert structural_slow == pytest.approx(4 * structural_one, rel=0.05)


def test_pair_cost_grows_with_tree_size_and_every_language_has_a_model():
    assert set(SECONDS_PER_UNIT) == set(LANGS)
    assert pair_cost(100, 100, "java_24") > 10 * pair_cost(30, 30, "java_24")


def test_estimate_rejects_a_bad_margin_and_calibrate_is_positive():
    with pytest.raises(ValueError):
        estimate_group(["a"], ["x = 1"], "python_3", prefilter_margin=0.9)
    assert calibrate() > 0
