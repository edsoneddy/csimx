---
name: csimx-corpus-tuner
description: Validates and extends a csimx language's already-populated csimx/<lang>/utils.py against a REAL code corpus (a programming-judge dataset laid out as problem-folder/submission files, e.g. jv-umsa-dataset/all_py, all_java, all_cpp, all_c, all_kotlin) instead of synthetic snippets. Runs an adaptive, round-based sampling LOOP that benchmarks real node-count reduction, hunts for remaining unclassified tokens/rules, flags already-applied entries that collapse genuinely different code, and mines same-problem pairs for the equivalence knobs. ALWAYS requires a target language (python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin) and a corpus root path -- ask if either is missing. Use when the user wants to validate csimx's compression config against real code. For fidelity-scored sweeps (MAE against a near-raw tree) use csimx-batch-tuner.
---

# csimx Corpus Tuner

## How this relates to csimx-tree-compressor

That skill finds compression candidates with hand-written snippets. A real corpus is better evidence: candidates that looked safe on hand-picked examples failed on a real 115-pair sweep (see the comments in `python_3/utils.py`). This skill is that sweep, made repeatable: same pipeline (`Normalize` -> `PruneAndHash`), same knobs, different evidence. Once a language's `utils.py` is mostly filled in, its job shifts from finding candidates to proving the existing config holds on thousands of real submissions, and saying exactly where it does not.

Read "What the csimx sweeps taught" in csimx-tree-compressor first. For a fidelity-scored sweep (MAE against a near-raw tree) use csimx-batch-tuner.

## Step 0 -- Confirm the target language and corpus root

Both are required; ask if missing. The corpus is `<root>/<problem_id>/<submission_file>`. Files directly under the root are grouped under a synthetic `_ungrouped` problem, which loses the cross-problem pairs of Step 3; tell the user if that happens.

## Prerequisites

`csimx` importable (`pip install -e .`).

Note: `Visitors.py` binds `COLLAPSED_RULE_INDICES` at import time, so `collapsed_rule` results from `run_round.py` before it mutated the set in place (see `apply_config()`) measured the untouched config and should be re-run. The other four strategies were never affected.

## Step 1 -- Build (or refresh) the manifest

```
python scripts/build_manifest.py --lang python_3 --corpus-root /path/to/corpus --out manifest_python_3.json
```

Tries every file once with an error-counting listener (ANTLR's own listener only prints, so a file with e.g. mixed tab/space indentation would otherwise slip through as a wrong tree). Failed files are recorded with a reason; check the `invalid` counts per problem for a folder that is disproportionately broken. The scan is expensive: the manifest stores a `corpus_signature` and `sample_round.py` warns if it drifted, so reuse an existing manifest.

## Step 2 -- Decide what the run tests

Normally all three:

1. **Benchmark**: real mean node count and reduction of the CURRENT config (automatic every round).
2. **Discovery**: `scripts/enumerate_candidates.py --lang <lang>`. If most of the grammar is classified the list is short, which is fine.
3. **Regression check** (`run_round.py --regression-check`): re-examine applied entries with real cross-problem pairs, looking for the collapse trap of csimx-tree-compressor's Step 5.

Build a `candidates.json` for the discovery results (shape in the `run_round.py` docstring); with nothing unclassified, omit `--candidates` and the round is benchmark + regression only.

## Step 3 -- Run rounds until nothing new turns up

```
python scripts/sample_round.py \
    --manifest manifest_python_3.json --state state_python_3.json \
    --round-size 300 --per-problem-cap 5 --cross-pairs 10 > round_1.json

python scripts/run_round.py \
    --lang python_3 --round-file round_1.json --candidates candidates.json \
    --regression-check --out round_1_results.json
```

`sample_round.py` takes up to `--per-problem-cap` files per problem round-robin, so a round covers as many problems as possible; `--state` keeps rounds from overlapping (three rounds of 300 covered all 299 problems of a 7,879-file corpus with no overlap).

**Cross-problem pairs**: files from different problem folders are free "algorithmically different" examples. `run_round.py` uses them forward (does a NEW candidate collapse a pair that was distinct?) and backward (does REMOVING an applied entry make an identical pair distinct again? the leave-one-out sweep only runs if the baseline found a suspiciously identical pair).

**Run another round only if the last one changed something:**
- A candidate became recommendable because a bigger sample gave it enough support (do not trust `avg_reduction_pct` on fewer than ~10 relevant files).
- A recommended candidate's `avg_reduction_pct` moved by more than ~2 points.
- `regression_candidates` is non-empty and was not before.

Stop when a round changes none of these, or at the hard cap (2,000 files or 6 rounds), and say which in the report.

**Some "not recommended" results are already final:**
- Zero `relevant_files` over a round covering every problem: the construct is not in this corpus.
- A stable `avg_reduction_pct` of ~0% on hundreds of relevant files: the rule is already removed by `visitChildren`'s single-child passthrough, so adding it is a no-op.

Only a nonzero reduction with too few `relevant_files` (under ~10) can still flip; check its growth per round against the cap.

**For a real but rare candidate, target it** instead of raising `--round-size`: `sample_round.py --keyword-regex PATTERN` prefilters the pool by file text (a comment or string can false-match; `run_round.py`'s tree check still decides relevance) and can take the hit rate from under 1% to ~100%.

## Step 4 -- Investigate anything flagged

For each candidate with `cross_pairs_newly_collapsed` and each `regression_candidates` entry, open the triggering pair with `harness.py --show-tree` (or `csimx tree --show-raw`). This separates "unsafe to touch" from "fine except one child that belongs in `EXCLUDE_CHILDRENS_FROM_RULE`".

## Step 5 -- Write the report

```markdown
# csimx corpus validation: <lang>

Corpus: <root>, <N> problems, <M> valid files (<K> excluded, see manifest).
Rounds run: <R>. Files sampled: <N>. Stopped because: <plateau | hard cap>.

## Real-world benchmark (current config)
Mean node count across sample: <X>.

## New candidates recommended
(id/name, strategy, avg reduction %, relevant files, safety verdict, before/after examples)

## Regression findings
- `<SET_NAME>` entry `<name>` (id `<id>`): removing it un-collapses <problem_a> vs <problem_b>.
  Fix: <remove | narrow via EXCLUDE_CHILDRENS_FROM_RULE | keep, because ...>.

## Not enough evidence yet
```

Every recommendation needs the numbers behind it. Nothing is written to `csimx/<lang>/utils.py` until the user approves specific entries.

## Step 6 -- Apply approved changes

As in csimx-tree-compressor's Step 7: edit `utils.py` by hand with a short comment saying why, then check `csimx tree --path <file> --lang <lang> --show-raw` on corpus files not used as evidence.

## Optional: mine evidence for the equivalence knobs

`CONTROL_EQUIVALENCE_RULE_INDICES` and `ASIGN_OP_NORMALIZED` do not reduce tree size, so Steps 1-6 do not touch them; they are validated by TED. Two independent solutions to the SAME problem are a natural Type-3 example (a `for` vs an equivalent `while`, `x += 1` vs `x = x + 1`). Run this only when asked, and propose the candidate groups first (the script measures a mapping, it does not discover one):

```
python scripts/mine_equivalence_pairs.py --lang python_3 \
    --manifest manifest_python_3.json \
    --equivalence-candidates equivalence_candidates.json \
    --max-pairs-per-problem 15 --out equivalence_results.json
```

- `control_groups` (for/while): rule indices come from `Parser.ruleNames`, as in `enumerate_candidates.py`.
- `assign_op_candidates` (`+=`): `rule` MUST be the rule the grammar uses for the plain expanded form (what parses `x + y`), or the "equivalence" is fake even if a similarity gain is reported. Read the grammar to confirm. Every csimx language has a `visitAssignment` override (`AUG_ASSIGN_OPS` in its `utils.py`); the script skips and says so for a language that is not wired up.

Per candidate it reports `avg_similarity_gain` (positive: same-problem pairs got closer) and `pairs_worsened`; investigate any worsened pair through `examples`, since a negative result on independent real code is a warning. Report concrete example pairs so the user can eyeball the source before anything is added to `utils.py` or `Visitors.py`.

## Script reference

- `scripts/build_manifest.py --lang <lang> --corpus-root PATH --out manifest.json` -- corpus scan; which files parse cleanly and why the rest do not.
- `scripts/enumerate_candidates.py --lang <lang> [--json out.json]` -- unclassified tokens/rules.
- `scripts/sample_round.py --manifest manifest.json --state state.json [--round-size 300] [--per-problem-cap 5] [--cross-pairs 10] [--seed N] [--reset] [--keyword-regex PATTERN]` -- one cumulative stratified round plus cross-problem pairs.
- `scripts/run_round.py --lang <lang> --round-file round.json [--candidates candidates.json] [--regression-check] --out results.json` -- measurement engine: parses each file once, benchmarks, sweeps candidates and, if warranted, leave-one-out tests the config.
- `scripts/mine_equivalence_pairs.py --lang <lang> --manifest manifest.json --equivalence-candidates candidates.json [--max-pairs-per-problem 15] [--max-files-per-problem 40] --out results.json` -- TED-based tool for the two equivalence knobs.
- `scripts/harness.py` -- single-file spot check.

`<lang>` is one of python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin. Scripts only write their own manifest/state/results files; every write to `csimx/<lang>/utils.py` or `Visitors.py` is by hand, after approval.
