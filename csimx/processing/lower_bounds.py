"""Lower bounds of the tree edit distance (TED): `group` skips the pairs they prove below the threshold.

Each bound uses costs never above the real ones of distance_metrics.TreeEditDistance (insert/delete
= node weight >= 1, rename to another label >= 0.5), so it holds for 'apted' and 'zss':

* size: |n1 - n2| nodes stay unmatched;
* labels: at most the multiset intersection can map to equal labels, the rest costs >= 0.5;
* sequence: a tree edit is a string edit of the pre/postorder label sequence (Guha 2002, Akutsu
  2006), so the sequence edit distance, with the real costs, is a bound.

Design, measurements and discarded ideas: docs/GROUPING_SPEEDUP.md.
"""
from collections import Counter

from .distance_metrics import node_weight, rename_cost

#: smallest rename_cost between two different labels (used by the label bound only)
MIN_RENAME = 0.5


class LabelTable:
    """Labels of one `group` run as ints, with their weights and memoized rename costs."""

    def __init__(self):
        self.ids = {}
        self.weights = []
        self._nodes = []  # per id: the fields rename_cost reads
        self._cost = {}

    def Id(self, node):
        label = node["label"]
        found = self.ids.get(label)
        if found is None:
            found = len(self._nodes)
            self.ids[label] = found
            self.weights.append(node_weight(node))
            self._nodes.append({k: node[k] for k in ("label", "weight", "sig") if k in node})
        return found

    def Rename(self, a, b):
        """rename_cost between two labels, by id (it only depends on the labels)."""
        cost = rename_cost(self._nodes[a], self._nodes[b])
        self._cost[(a, b)] = self._cost[(b, a)] = cost
        return cost


class TreeProfile:
    """Size, label counts and pre/postorder label sequences of a pruned tree."""

    __slots__ = ("size", "mass", "counts", "sequence", "post")

    def __init__(self, tree, mass, table):
        """`mass` is the weight total from PruneAndHash."""
        sequence = []
        post = []
        stack = [(tree, False)]
        while stack:
            node, done = stack.pop()
            if done:
                post.append(table.Id(node))
                continue
            sequence.append(table.Id(node))
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node["children"]))
        self.size = len(sequence)
        self.mass = mass
        self.counts = Counter(sequence)
        self.sequence = sequence  # preorder
        self.post = post  # postorder


def SizeLowerBound(a, b):
    return abs(a.size - b.size)


def LabelLowerBound(a, b):
    """|n1 - n2| plus 0.5 per mapped pair that cannot have equal labels."""
    small, large = (a.counts, b.counts) if len(a.counts) <= len(b.counts) else (b.counts, a.counts)
    common = sum(min(count, large.get(label, 0)) for label, count in small.items())
    return abs(a.size - b.size) + MIN_RENAME * max(0, min(a.size, b.size) - common)


def SequenceLowerBound(a, b, cutoff, table, postorder=False):
    """Edit distance of the pre/postorder label sequences, or `cutoff` if it is >= `cutoff`.

    Costs are the TED ones. Each step off the diagonal costs >= 1, so only the band
    `|i - j| <= cutoff` matters, and the DP stops when a whole row reaches `cutoff`.
    """
    x, y = (a.post, b.post) if postorder else (a.sequence, b.sequence)
    n, m = len(x), len(y)
    if abs(n - m) >= cutoff:
        return cutoff
    weights, costs, rename = table.weights, table._cost, table.Rename
    band = int(cutoff)
    inf = cutoff
    wy = [weights[k] for k in y]
    prev = [0.0] * (m + 1)
    acc = 0.0
    for j in range(1, m + 1):
        acc += wy[j - 1]
        prev[j] = acc if acc < inf else inf
    for i in range(1, n + 1):
        xi = x[i - 1]
        wx = weights[xi]
        lo = max(1, i - band)
        hi = min(m, i + band)
        cur = [inf] * (m + 1)
        first = prev[0] + wx
        cur[0] = first if first < inf else inf
        row_min = cur[0]
        left = cur[0] if lo == 1 else inf
        for j in range(lo, hi + 1):
            yj = y[j - 1]
            best = prev[j] + wx
            step = left + wy[j - 1]
            if step < best:
                best = step
            if xi == yj:
                step = prev[j - 1]
            else:
                c = costs.get((xi, yj))
                step = prev[j - 1] + (c if c is not None else rename(xi, yj))
            if step < best:
                best = step
            if best > inf:
                best = inf
            cur[j] = best
            left = best
            if best < row_min:
                row_min = best
        if row_min >= cutoff:
            return cutoff
        prev = cur
    return min(prev[m], cutoff)


def UpperBoundIndex(d_lb, mass_a, mass_b, index_formula, index_function):
    """Highest index a pair can have if its distance is at least `d_lb`.

    'ratio' and 'metric' fall as d grows. 'legacy' jumps up when d passes max(T1, T2) (it changes
    denominator), so both branches are considered.
    """
    if index_formula != "legacy":
        return index_function(d_lb, mass_a, mass_b, index_formula)
    m = max(mass_a, mass_b)
    if d_lb > m:
        return index_function(d_lb, mass_a, mass_b, index_formula)
    first = index_function(d_lb, mass_a, mass_b, index_formula)
    # smallest d past the switch, d -> m+: 1 - m / (T1 + T2)
    total = max(mass_a + mass_b, 1)
    return max(first, round(min(max(1 - m / total, 0.0), 1.0), 2))


def DistanceCutoff(mass_a, mass_b, threshold, index_formula, index_function):
    """Smallest distance from which no pair of these masses can exceed `threshold` (bisection)."""
    hi = float(mass_a + mass_b + 1)
    if UpperBoundIndex(hi, mass_a, mass_b, index_formula, index_function) > threshold:
        return hi
    lo = 0.0
    if UpperBoundIndex(lo, mass_a, mass_b, index_formula, index_function) <= threshold:
        return 0.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if UpperBoundIndex(mid, mass_a, mass_b, index_formula, index_function) > threshold:
            lo = mid
        else:
            hi = mid
    return hi


def ReachableDistanceBound(a, b, threshold, index_formula, index_function, table):
    """None if the bounds prove the pair's index cannot be above `threshold`, else the larger of
    the two sequence bounds (a lower bound of the distance, close to it: see estimate.py)."""
    cutoff = DistanceCutoff(a.mass, b.mass, threshold, index_formula, index_function)
    if cutoff <= 0.0:
        return None
    if SizeLowerBound(a, b) >= cutoff:
        return None
    if LabelLowerBound(a, b) >= cutoff:
        return None
    pre = SequenceLowerBound(a, b, cutoff, table)
    if pre >= cutoff:
        return None
    post = SequenceLowerBound(a, b, cutoff, table, postorder=True)
    if post >= cutoff:
        return None
    return max(pre, post)


def CanReachThreshold(a, b, threshold, index_formula, index_function, table):
    """False only if the bounds prove the pair's index cannot be above `threshold`."""
    return ReachableDistanceBound(a, b, threshold, index_formula, index_function, table) is not None

