"""Edit distance between two token sequences (Myers, 1986) and the index built from it."""


def LexicalDistance(seq_a, seq_b, max_distance=None):
    """Number of insertions and deletions that turn `seq_a` into `seq_b` (O(ND), Myers 1986).

    With `max_distance` the search stops as soon as the distance is known to be larger and
    None is returned, which is what makes it cheap on pairs that have little in common.
    """
    n, m = len(seq_a), len(seq_b)
    start = 0
    while start < n and start < m and seq_a[start] == seq_b[start]:
        start += 1
    end = 0
    while end < n - start and end < m - start and seq_a[n - 1 - end] == seq_b[m - 1 - end]:
        end += 1
    a, b = seq_a[start:n - end], seq_b[start:m - end]
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        d = n + m
        return d if max_distance is None or d <= max_distance else None

    limit = n + m if max_distance is None else min(n + m, max_distance)
    offset = limit + 1
    v = [0] * (2 * limit + 3)
    for d in range(limit + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]
            else:
                x = v[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return d
    return None


def LexicalIndex(d, len_a, len_b):
    """Similarity in [0, 1] of two sequences at distance `d`: 1 - d / (len_a + len_b)."""
    total = len_a + len_b
    return 1.0 - d / total if total else 0.0


def LexicalBound(len_a, len_b):
    """Highest index two sequences of these lengths can have (all of the shorter one matched)."""
    total = len_a + len_b
    return 2.0 * min(len_a, len_b) / total if total else 0.0


def LexicalAtLeast(seq_a, seq_b, minimum):
    """The lexical index of the pair if it is at least `minimum`, else None.

    Two cheap exits come first: the length bound, and Myers stopped at the largest distance
    that still reaches `minimum`.
    """
    len_a, len_b = len(seq_a), len(seq_b)
    if LexicalBound(len_a, len_b) < minimum:
        return None
    total = len_a + len_b
    # index >= minimum  <=>  d <= (1 - minimum) * total
    d = LexicalDistance(seq_a, seq_b, int((1.0 - minimum) * total + 1e-9))
    return None if d is None else LexicalIndex(d, len_a, len_b)
