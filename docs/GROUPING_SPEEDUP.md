# Speeding up `group`: what was tried and measured

`group` compares every pair (O(n²) pairs) and the tree edit distance (TED) is ~97 % of the time.
Union-find itself is near O(α(n)) and is not the cost. This page records the research and the
experiments, so they are not repeated. Everything below is single process, single core (the target
is a 512 MB free tier, no parallelism).

## What is in csimx

| Piece | Where | Effect on the groups | Default |
|---|---|---|---|
| Lower bounds of the TED | `csimx/processing/lower_bounds.py` | none (exact) | on (`CSIM_DISABLE_BOUNDS=1`, or `bounds=False` in Python, turns it off) |
| Skip pairs already in one group | `group_by_exhaustive_search(skip_connected=True)`, `--skip-connected` | none | off |
| Group average = mean of a maximum spanning tree | `spanning_averages` in `csimx/utils.py` | none (the number changes) | always |
| Estimator that models the bounds | `csimx/estimate.py` | none | `bounds=True` |

### Lower bounds (filter and verify)

A pair can be skipped when its best possible index cannot exceed the threshold. With `d_lb <= TED`:

1. size: `|n1 - n2|` (node weights are >= 1);
2. labels: at most the multiset intersection of labels maps to equal labels; the other mapped pairs
   cost >= 0.5 (`rename_cost` is 0.5 at least);
3. sequence: the edit distance of the pre- and postorder label sequences, with the real costs (node
   weight to insert/delete, `rename_cost` memoized per pair of labels), banded by the cutoff and
   aborted when a whole row reaches it (Guha 2002, Akutsu 2006).

`DistanceCutoff` is the smallest distance beyond which the index cannot exceed the threshold
(bisection on `UpperBoundIndex`). The `legacy` index is **not monotone** in `d`: it switches
denominator when `d > max(T1, T2)`, so the bound takes both branches. A first version with unit
costs pruned too little on real same-problem files; the weighted costs are what made it work.

### Skip connected pairs

Groups are the connected components of "index > threshold", so a pair whose files are already in
one component cannot change them. Cheap, valid at any threshold, and the only thing that helps at
low thresholds (see below).

### Group average

The old "Average Similarity" was the index of the *last* positive pair of each member (`i < j`
order), dropping the first member: it depended on file order and was not a mean of anything. It is
now the mean of the maximum spanning tree of the group's positive links (Kruskal, ties by `i, j`).
It is informative only; membership is what the threshold guarantees.

Measured on six 100-file sets (cpp, java, c, kotlin, python x2; thresholds 0.7 and 0.5), mean
absolute difference of the group value:

| Comparison | thr 0.7 | thr 0.5 |
|---|---|---|
| new vs old | 0.02 – 0.09 | 0.06 – 0.24 |
| spanning tree with `--skip-connected` vs without | 0.002 – 0.07 (max 0.13) | 0.02 – 0.25 (max 0.27) |
| spanning tree vs mean of **all** pairs in the group | 0.03 – 0.12 | 0.07 – 0.42 |

So the value depends on `--skip-connected` at low thresholds (the links found are a spanning tree
in visiting order, not the maximum one) and overstates the real mean of the group (chains A–B–C).
The exact mean of all pairs was measured and **rejected as a default**: it needs the pairs
inside each group again, 1.4–7.6x the time of `group --skip-connected`; at threshold 0.3 a 100-file
group costs ~40 s, the same as the old code. A sampled mean was proposed but not built.

## Measurements

`csimx group`, single core, Apple M4 Pro, seconds. Base is csimx 0.3.0 (same groups in every case).

### 100 files per run (the csim-online limit)

| Set | Base 0.7 | bounds 0.7 / +skip | bounds 0.5 / +skip | bounds 0.3 / +skip |
|---|---|---|---|---|
| cpp_14 (`all_cpp/1006`) | 37.7 | 3.0 / 2.8 | 10.6 / 4.7 | 39.3 / 4.5 |
| java_20 (`all_java/1051`) | 39.2 | 12.0 / 8.5 | 20.1 / 8.5 | 41.1 / 10.7 |
| c (three problems) | 36.6 | 0.9 / 0.9 | 5.3 / 3.0 | 27.8 / 4.4 |
| kotlin (`all_kotlin`) | 6.5 | 1.9 / 1.8 | 3.5 / 2.1 | 6.8 / 1.7 |
| python_3_13 (`all_py/1299`) | 4.9 | 1.7 / 1.2 | 2.6 / 1.2 | 5.1 / 1.2 |
| python_3_13 (scsc B) | 25.5 | 2.3 / 2.0 | 3.1 / 2.3 | 21.4 / 3.5 |

Peak RSS 66–210 MB in every mode, same as the base (java_20 ~200 MB).

### Whole directories, threshold 0.7 (base → bounds → bounds + skip)

scsc A 17 → 2.8 → 2.2; B 68 → 4.6 → 3.4; C 134 → 9.9 → 3.4; D 117 → 15.6 → 4.5; E 960 → 98 → 33.
jv-umsa: cpp/1006 90 → 5.3 → 4.8; java/1051 174 → 41.6 → 15.9; c mix 254 → 4.4 → 3.9;
kotlin 7.9 → 2.1 → 1.9; py/1299 13 → 3.5 → 1.8. At threshold 0.3 the bounds alone gain nothing
(cpp 91 → 95, java 174 → 179, c 254 → 200); with `--skip-connected` cpp 6.2, java 23.7, c 6.8.

**Rule of thumb:** bounds win at high thresholds, skip-connected at low ones. What remains is mostly
parsing (java native ~31 ms/file), the bound DP (~0.1–0.2 ms/pair) and a few TEDs.

### Estimator

`estimate_group` before the bounds: 10–40x over (it priced every pair). With the bounds
(`bounds=True`): -25 % .. +20 % of the time of `group` without `skip_connected`, checked also on
108–223 files (14 of 15 cases within -17 % .. +9 %; python +26 % / +30 %, safe side).

A job that runs with `--skip-connected` is far cheaper than that estimate (2–25x at low
thresholds), and with the speed of Render (`speed_factor` ~21) it was rejected as `too_slow`
although it fits. `estimate_group(..., skip_connected=True)` models it:

1. The distance of a pair is unknown without computing it, but the sequence bound is close to it:
   TED / max(SED pre, SED post) has median 1.0 (python) to 1.2 (cpp) and 90th percentile 1.2–1.45
   on 10 sets of 100–223 files.
2. The pairs are walked in the order of `group` with a union-find; a pair counts as joining when
   the index of `ratio * bound` exceeds the threshold (`ratio` 1.2, python 1.1), and the pairs it
   connects are not charged.
3. Variants tried on the real outcomes of 10 sets x 3 thresholds (cost vs the real run with skip):
   charging every survivor 1.1–43x; "join if the best possible index passes" 0.2–1.0x (optimistic,
   bad); `ratio` 1.1 0.3–3x; **`ratio` 1.2 0.97–1.9x in 24 of 30 cases**, up to 3x at 0.3.

End to end (`estimate_group(skip_connected=True)` vs `group --skip-connected`, 36 set x threshold
cases, one core): error -12 % .. +30 % in 31 cases; the other five are three at threshold 0.3 (cpp_14 +89 %
and +121 %, python +142 %: pairs that the guess does not join but really do, safe side), python
+39 % at 0.7 and one -49 % that is the one-time library load of the first run in the process. The no-skip model was 2–25x over on the
same cases (e.g. c, 200 files, 0.3: 147 s vs 5.7 s real, now 5.8 s).

## Tried and discarded (do not repeat)

| Idea | Result |
|---|---|
| Top-down (Selkow) upper bound to accept positives without TED | valid, but <= 5 % on top of skip-connected; removed |
| Cache of identical trees | 0–4 % of the pairs are identical |
| `--talg zss` | 4–8x slower than `apted`, and its distances **differ** in cpp_14, c and kotlin (equal in python, java); cause not investigated |
| Memoize `rename_cost` inside `apted` | 15–22 % of the TED, but a cache that grows with the pairs; not built |
| Exact mean of the group | see "Group average": 1.4–7.6x, loses the gain |
| Touzet O(nk³), TJoin, metric-space index (MetricMatrix/HNSW), LSH | not worth it for n <= 100; not enough detail to implement soundly |
| Union-find replacements | not the bottleneck; the cost is the number of TEDs |

## Literature consulted

Moravec & Bača 2026 (arXiv 2609.03078, SED lower bounds of the TED); Guha et al. 2002 and
Akutsu 2006 (string edit distance of traversals bounds the TED); Augsten et al. 2010 (pq-grams);
Yang et al. 2005 (binary branches); Touzet 2005; SourcererCC; Dolos (winnowing, connected
components).

## Reproducing

Datasets: `scsc/notebooks/datasets` (A–F) and `jv-umsa-dataset` (`all_c`, `all_cpp`, `all_java`,
`all_kotlin`, `all_py`). Run `csimx group --path DIR --lang L --threshold T [--skip-connected]`
(`CSIM_DISABLE_BOUNDS=1` for the base); stderr reports `structural comparisons: X of Y pairs (bounds skipped …,
connected skipped …); bounds Ns, TED Ns`. Compare the groups (not the averages) with the base.
