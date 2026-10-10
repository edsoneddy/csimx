"""Time estimate for `group`, from the size of the pruned trees.

The cost of a structural comparison grows with the product of the two tree sizes:
seconds per pair ~= a[lang] * (nodes_i * nodes_j) ** 1.2 (see CHANGELOG 0.3.0 for the fit).
`calibrate()` scales the result to the speed of the current machine. It is an estimate, so
the result carries a range.
"""
import itertools
import statistics
import time

EXPONENT = 1.2
# seconds per (nodes_i * nodes_j) ** EXPONENT, reference machine (Apple M4 Pro, one core)
SECONDS_PER_UNIT = {
    "python_3": 1.38e-06,
    "python_3_13": 1.23e-06,
    "java_20": 7.57e-07,
    "java_24": 7.59e-07,
    "cpp_14": 1.07e-06,
    "c": 7.77e-07,
    "kotlin": 1.02e-06,
}
# range reported as [LOW, HIGH] x the point value
RANGE_LOW, RANGE_HIGH = 0.7, 1.5

_CAL_A = '''
def solve(values, limit):
    total = 0
    best = None
    for i in range(len(values)):
        if values[i] > limit:
            total += values[i] * 2
        elif values[i] < 0:
            total -= values[i]
        else:
            for j in range(i, len(values)):
                if values[j] % 2 == 0:
                    total += values[j]
                    if best is None or values[j] > best:
                        best = values[j]
    while total > 1000:
        total = total // 2
    return total, best
'''
_CAL_B = '''
def compute(items, bound):
    acc = 0
    top = None
    idx = 0
    while idx < len(items):
        v = items[idx]
        if v > bound:
            acc = acc + v * 3
        else:
            for k in range(idx, len(items)):
                if items[k] % 3 == 0 and items[k] != 0:
                    acc = acc + items[k]
                    top = items[k] if top is None else max(top, items[k])
        idx += 1
    if acc > 500:
        acc = acc - 500
    return acc, top
'''
# calibration workload time on the reference machine
REFERENCE_CALIBRATION_SECONDS = 0.085
_calibration_cache = {}


def _calibration_seconds(repeats=3, batch=20):
    from .utils import get_similarity_coefficient, preprocess_code

    a = preprocess_code("a.py", _CAL_A, "python_3")
    b = preprocess_code("b.py", _CAL_B, "python_3")
    best = None
    for _ in range(repeats):
        t = time.perf_counter()
        for _ in range(batch):
            get_similarity_coefficient(a, b, "apted")
        dt = time.perf_counter() - t
        best = dt if best is None else min(best, dt)
    return best


def calibrate(force=False):
    """Speed of this machine relative to the reference: 1.0 is the same, 2.0 twice as slow.
    Cached after the first call (about 0.3 s); `force=True` measures again."""
    if force or "factor" not in _calibration_cache:
        measured = _calibration_seconds()
        _calibration_cache["factor"] = max(0.1, measured / REFERENCE_CALIBRATION_SECONDS)
    return _calibration_cache["factor"]


def pair_cost(nodes_a, nodes_b, lang):
    """Seconds on the reference machine for one structural comparison."""
    return SECONDS_PER_UNIT[lang] * (nodes_a * nodes_b) ** EXPONENT


def estimate_group(
    file_names,
    file_contents,
    lang,
    threshold=0.7,
    prefilter_margin=None,
    speed_factor=1.0,
    exact_prefilter=True,
):
    """Estimate the time of `group_by_exhaustive_search` without running it.

    Parses every file. With `prefilter_margin` and `exact_prefilter=True` it also runs the
    lexical stage to know which pairs remain (slow for long files); `exact_prefilter=False`
    skips that and returns the upper bound (every pair). `speed_factor` comes from `calibrate()`.

    Returns a dict: files, pairs, structural_pairs, skipped, nodes {total, mean, median, max},
    parse_seconds, lexical_seconds, prefilter_evaluated, estimated_seconds,
    upper_bound_seconds (cost if the prefilter skipped nothing), range_seconds [low, high],
    speed_factor.
    """
    from .utils import MAX_PREFILTER_MARGIN, count_tree_nodes, preprocess_code

    if lang not in SECONDS_PER_UNIT:
        raise ValueError(f"No time model for language: {lang}")

    n = len(file_names)
    t0 = time.perf_counter()
    nodes = []
    for name, content in zip(file_names, file_contents):
        nodes.append(count_tree_nodes(preprocess_code(name, content, lang)[0]))
    parse_seconds = time.perf_counter() - t0

    total_pairs = n * (n - 1) // 2
    skipped = 0
    lexical_seconds = 0.0
    if prefilter_margin is None or not exact_prefilter:
        pairs = itertools.combinations(range(n), 2)
    else:
        if not 0.0 <= prefilter_margin <= MAX_PREFILTER_MARGIN:
            raise ValueError(f"prefilter_margin must be between 0 and {MAX_PREFILTER_MARGIN}")
        from .lexical import LexicalAtLeast, Tokenize

        t1 = time.perf_counter()
        tokens = []
        for content in file_contents:
            tokens.append(Tokenize(content, lang))
        minimum = max(0.0, threshold - prefilter_margin)
        kept = []
        for i, j in itertools.combinations(range(n), 2):
            if LexicalAtLeast(tokens[i], tokens[j], minimum) is None:
                skipped += 1
            else:
                kept.append((i, j))
        pairs = kept
        lexical_seconds = time.perf_counter() - t1

    pairs = list(pairs)
    structural = sum(pair_cost(nodes[i], nodes[j], lang) for i, j in pairs) * speed_factor
    fixed = parse_seconds + lexical_seconds  # measured on this machine, not scaled
    point = structural + fixed
    if prefilter_margin is not None and exact_prefilter:
        every_pair = sum(pair_cost(nodes[i], nodes[j], lang) for i, j in itertools.combinations(range(n), 2))
        upper_bound = every_pair * speed_factor + fixed
    else:
        upper_bound = point
    return {
        "files": n,
        "pairs": total_pairs,
        "structural_pairs": len(pairs),
        "skipped": skipped,
        "nodes": {
            "total": sum(nodes),
            "mean": round(statistics.mean(nodes), 1) if nodes else 0,
            "median": statistics.median(nodes) if nodes else 0,
            "max": max(nodes) if nodes else 0,
        },
        "parse_seconds": round(parse_seconds, 4),
        "lexical_seconds": round(lexical_seconds, 4),
        "prefilter_evaluated": prefilter_margin is not None and exact_prefilter,
        "estimated_seconds": round(point, 4),
        "upper_bound_seconds": round(upper_bound, 4),
        "range_seconds": [
            round(structural * RANGE_LOW + fixed, 4),
            round(structural * RANGE_HIGH + fixed, 4),
        ],
        "speed_factor": round(speed_factor, 3),
    }
