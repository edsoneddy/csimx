---
name: csimx-corpus-tuner
description: Validates and extends a csimx language's already-populated csimx/<lang>/utils.py against a REAL code corpus (a programming-judge dataset laid out as problem-folder/submission files, e.g. jv-umsa-dataset/all_py, all_java, all_cpp, all_c, all_kotlin) instead of synthetic snippets. Runs an adaptive, round-based sampling LOOP that benchmarks real node-count reduction, hunts for remaining unclassified tokens/rules, flags already-applied entries that collapse genuinely different code, and mines same-problem pairs for the equivalence knobs. ALWAYS requires a target language (python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin) and a corpus root path -- ask if either is missing. Use when the user wants to validate csimx's compression config against real code. For fidelity-scored sweeps (MAE against a near-raw tree) use csimx-batch-tuner.
---

# csimx Corpus Tuner

## How this relates to csimx-tree-compressor

That sibling skill finds and applies compression candidates using synthetic, hand-written snippets, one rule/token at a time. It works, but a real corpus is strictly better evidence -- `python_3/utils.py`'s own comments describe exactly this lesson: some candidates that looked safe on a handful of hand-picked examples failed once tested against a real 115-pair sweep. This skill is that real sweep, made repeatable, for whatever judge/plagiarism dataset you point it at. Same underlying pipeline (`Normalize` -> `PruneAndHash`, same five size-reducing dicts/sets, same obfuscation-resistance framing from the sibling skill's "Why this exists"), different evidence source.

Once most of a language's `utils.py` is filled in (the normal end state after running csimx-tree-compressor), this skill's job shifts from "find new candidates" to "prove the existing config actually holds up on thousands of real, messy submissions" -- and, if it doesn't, say exactly where.


## What the csimx sweeps taught (read before proposing anything)

These come from `docs/pruning_fidelity.md` and the CHANGELOG of csimx; they replace the older
"count the nodes and eyeball a pair" evidence of this skill.

* **Judge a pruning change by fidelity, not by node count.** The metric is the mean absolute error of
  the similarity index of the pruned trees against a near-raw reference (only trivia and identifiers
  dropped; no exclusion, collapsing, hashing or canonical forms), on real same-problem pairs of the
  `jv-umsa-dataset` corpora, plus the index of random cross-problem pairs (the collapse trap: do
  different programs start to look alike?). `csimx-batch-tuner/scripts/fidelity_sweep.py` does exactly
  this and is the preferred tool; the snippet workflow below is for a first look at a new grammar.
* **Never hash the control-flow skeleton.** Hashing whole `if`/`while`/`for`/`def`/`class`/method bodies
  turned programs into 1-8 nodes and made 34-40% of *unrelated* pairs look >= 0.7 similar. Only
  expression/declaration "islands" are hashed; `STRUCTURAL_RULE_INDICES` stops a hashed rule that
  contains control flow from being collapsed.
* **Hashed nodes should carry weight.** `HASH_MASS_ALPHA` (python_3 0.6, java_20 0.4, cpp_14 0.6, c 0.6,
  kotlin 0.6; java_24 none) makes a hashed node weigh `(subtree size + 1) ** alpha` and gives partial
  credit between hashes of the same rule. Sweep alpha per language (none, 0.25, 0.4, 0.6, 0.75); the
  best value differs.
* **Canonical forms** (`CANONICAL_FORMS`, `csimx/canonical_common.py` + `<lang>/canonical.py`, or
  `python_3/canonical.py`) unify equivalent operator forms before pruning. They should leave the
  fidelity unchanged and raise the score of rewritten pairs. Inlining of temporaries was prototyped
  and rejected.
* **Mutate config sets in place.** `csimx/Visitors.py` binds `COLLAPSED_RULE_INDICES` at import time:
  rebinding the name in a measurement script silently measures the untouched config.
* **Do not trust one seed.** Choose with two seeds and confirm on a third that was not used to choose
  (the sweep tool has a `validate` mode for that). The Kotlin corpus is synthetic and has only 12
  problems, so all seeds select the same set: its numbers are indicative.

## Step 0 -- Confirm the target language and corpus root

Two things must be known before anything else: which language (`python_3`, `python_3_13`, `java_20`, `java_24`, `cpp_14`, `c` or `kotlin`, or one added later), and the corpus's root directory. If either is missing from the request, ask. The corpus is assumed to be laid out as `<root>/<problem_id>/<submission_file>` -- files directly under the root with no subdirectory are still handled (grouped under a synthetic `_ungrouped` problem ID), but you lose the cross-problem-pairing trick described in Step 3, so flag that to the user if it happens.

## Prerequisites

Same as csimx-tree-compressor: `csimx` importable in the environment (`pip install -e .`), `import csimx` and `csimx tree` both working.

**Known-fixed issue, worth knowing about if you're looking at results from before this note existed:** `run_round.py`'s `collapsed_rule` strategy had a real bug where testing it never actually worked -- `csimx/Visitors.py` reads `COLLAPSED_RULE_INDICES` via a one-time import at its own module-load time (not through `csimx/utils.py`'s normally-dynamic dispatcher the other four knobs use), so overriding it by reassigning a new set silently had no effect; every `collapsed_rule` result was measuring against the untouched pristine config. This is fixed now (in-place mutation instead of reassignment -- see `apply_config()`'s docstring in `run_round.py` for the full explanation), but if you have a report generated before the fix, its `collapsed_rule` numbers can't be trusted and are worth re-running specifically -- the other four strategies (`excluded_token`, `excluded_rule`, `hashed_rule`, `exclude_children`) were never affected by this.

## Step 1 -- Build (or refresh) the file-validity manifest

```
python scripts/build_manifest.py --lang python --corpus-root /path/to/corpus --out manifest_python.json
```

This is the answer to "some files won't parse, skip them and keep going": it tries every file in the corpus once, using its own error-counting listener attached to both the lexer and the parser (not a try/except around csim's own `ANTLR_parse` -- that function's `ExtendedErrorListener` only prints, it doesn't raise, so something like inconsistent tab/space indentation in a python file would otherwise slip through as a silently-wrong tree instead of being excluded). Files that fail are recorded with a reason, not silently dropped -- worth glancing at the `invalid` counts per problem in case one problem folder is disproportionately broken (possibly a real, structural encoding issue worth telling the user about, not just noise).

This step is the expensive one and doesn't need to be repeated every run -- the manifest stores a `corpus_signature` (a hash over every file's path/size/mtime). If you're re-running against the same corpus later, check whether a manifest already exists before rebuilding; `sample_round.py` will warn you if it detects the signature has drifted.

## Step 2 -- Decide what this run is testing

Three things can happen in a run, and normally all three do together (per the earlier discussion with the user, this is the default -- don't skip the benchmark or regression check just because it seems like less work):

1. **Benchmark**: real average node count and reduction stats for the CURRENT config, replacing whatever synthetic-snippet estimates exist. This happens automatically every round regardless of what candidates you're testing -- it's just the baseline pass.
2. **Discovery**: run `scripts/enumerate_candidates.py --lang <lang>` the same way the sibling skill does. If most of the grammar is already classified, this list should be short -- that's expected and fine, it just means this run leans more on benchmarking and regression-checking than discovery.
3. **Regression check**: re-examine already-applied entries using real cross-problem pairs, looking for the same collapse-trap failure mode described in csimx-tree-compressor's Step 5, except this time the evidence is real code the synthetic snippets never saw. Controlled by `run_round.py --regression-check`.

Build a `candidates.json` for whatever Step 2's discovery scan turned up (see `run_round.py`'s docstring for the exact shape) -- if nothing is unclassified, you can omit `--candidates` entirely and the round becomes benchmark + regression-check only.

## Step 3 -- Run rounds until nothing new turns up

Each round is two script calls:

```
python scripts/sample_round.py \
    --manifest manifest_python.json --state state_python.json \
    --round-size 300 --per-problem-cap 5 --cross-pairs 10 \
    > round_1.json

python scripts/run_round.py \
    --lang python --round-file round_1.json --candidates candidates.json \
    --regression-check --out round_1_results.json
```

`sample_round.py` draws a stratified sample: up to `--per-problem-cap` files per problem folder, round-robin across problems, so a 300-file round spreads across as many different problems as possible before doubling up on any one -- broad grammar coverage fast, instead of pure random sampling that can over-represent whichever problem happens to have the most submissions. `--state` persists which files have already been used, so round 2's sample is a genuinely new 300 files, not an overlapping redraw; the corpus depletes as rounds accumulate (this was verified against a 7,879-file / 299-problem real corpus: three rounds of 300 covered every problem at least once with zero overlap between rounds).

The **cross-problem pairs** are the elegant part of using a judge dataset here: since every problem folder is a different task, any two files from different problems are automatically a legitimate "these two are algorithmically different" example -- no hand-written pair needed, unlike the sibling skill. `run_round.py` uses them two ways: forward (does applying a NEW candidate collapse a pair that was distinct under the current config -- the same safety check as before, just on real code) and backward (does REMOVING an already-applied entry, one at a time, turn a currently-identical pair back into two distinct trees -- which is the regression check, and it only runs the expensive leave-one-out sweep at all if the baseline pass actually found a suspiciously-identical pair to investigate).

**When to run another round:** keep going only if the last round changed something. Concretely, run another round if any of the following happened:
- A candidate that wasn't safe/well-supported enough to recommend became so (e.g. `relevant_files` was too small to trust, and a bigger sample now gives it enough support -- as a rule of thumb, don't trust `avg_reduction_pct` on fewer than ~10 relevant files).
- An already-recommended candidate's `avg_reduction_pct` moved by more than ~2 percentage points since the last round it was measured (small samples are noisy; if the estimate has stabilized, more data isn't telling you anything new).
- `regression_candidates` is non-empty and wasn't in the previous round's output.

Stop when a round changes none of the above, or when a hard cap is hit -- default to 2,000 total files or 6 rounds, whichever comes first, and say so explicitly in the report rather than silently trailing off. This mirrors exactly what the user asked for: sample a default batch, keep going only while still finding improvements, stop once it plateaus.

**Not every "not recommended" candidate needs more rounds -- some are already fully resolved, not under-evidenced.** It's tempting to read a plateau as "we ran out of time to find things," but two of the three ways a candidate can end up not-recommended are themselves conclusive, stable results that more sampling won't change:
- **Zero `relevant_files` across a full round that covered every problem folder at least once** means the construct genuinely doesn't appear in this corpus (e.g. testing match-statement internals against a corpus of pre-3.10 competitive-programming solutions) -- more files won't manufacture usage that isn't there.
- **A stable `avg_reduction_pct` of ~0% on hundreds of relevant files** is a real, confirmed measurement, not missing data -- it usually means the rule already gets removed for free by `visitChildren`'s existing single-child passthrough before any of the five compression knobs would even get a chance to act on it (the same mechanic documented throughout `python_3/utils.py`'s comments). Adding it anyway would be a no-op on real code.

The only genuinely open case is a candidate with a real, nonzero reduction but too few `relevant_files` to trust yet (e.g. under ~10) -- that's the one category where "not recommended this round" might become "recommended" with more data, and it's worth checking its growth rate (relevant files gained per round) before deciding whether another round is likely to get it there before the hard cap does.

**When a candidate is real but rare, don't just crank `--round-size` -- target it.** A candidate that only shows up in, say, 1 in every 200-300 random files will need thousands of files before random sampling accumulates enough `relevant_files` to trust, which can blow through the hard cap without resolving anything. If you already know roughly what the construct looks like in source (a keyword, an operator, an import), use `sample_round.py --keyword-regex` to prefilter the pool to files that actually mention it before drawing the round -- this is a plain text search over file contents, so it's not exact (a false-positive match inside a comment or string is possible, and `run_round.py`'s own tree-based `relevant_files` check is still what ultimately decides relevance), but it can turn a rare candidate's hit rate from under 1% to effectively 100%, resolving in one small targeted round what random sampling might not resolve in six.

## Step 4 -- Investigate anything flagged

For every candidate with `cross_pairs_newly_collapsed` non-empty, or every entry in `regression_candidates`, don't just report the flag -- pull up the actual triggering file pair with `harness.py --show-tree` (or plain `csimx tree --show-raw`) and look at what happened. This is where you distinguish "this rule is genuinely unsafe to touch" from "this rule is fine everywhere except one narrow child that should go through `EXCLUDE_CHILDRENS_FROM_RULE` instead of a blanket exclusion" -- the same kind of judgment call the sibling skill's Step 5 describes, just now anchored to a concrete real-code example instead of a synthetic one.

## Step 5 -- Write the report

```markdown
# csim corpus validation: <lang>

Corpus: <root>, <N> problems, <M> valid files (<K> excluded, parse errors -- see manifest).
Rounds run: <R>. Cumulative files sampled: <N>. Stopped because: <plateau | hard cap>.

## Real-world benchmark (current config)
Average node count across sample: <X> (round <R> estimate).

## New candidates recommended
(same shape as csimx-tree-compressor's report: id/name, strategy, avg reduction %,
relevant file count, safety verdict, before/after examples)

## Regression findings
- `<SET_NAME>` entry `<name>` (id `<id>`): removing it un-collapses <problem_a> vs <problem_b>
  (previously identical trees, now distinct). Recommended fix: <remove entirely | narrow via
  EXCLUDE_CHILDRENS_FROM_RULE instead | keep as-is, this is actually correct because ...>.

## Not enough evidence yet
- Candidates with too few relevant files to trust -- worth another round if this matters.
```

Same rule as the sibling skill: every recommendation needs the actual numbers behind it, not just a verdict, and nothing gets written to `csimx/<lang>/utils.py` until the user has reviewed this and told you which entries to apply.

## Step 6 -- Apply approved changes

Same as csimx-tree-compressor's Step 7: edit `csimx/<lang>/utils.py` by hand, with comments explaining *why*, and verify afterward with `csimx tree --path <file> --lang <lang> --show-raw` on a couple of real corpus files that weren't part of the evidence used to justify the change.

## Optional: mine real evidence for the equivalence knobs

`CONTROL_EQUIVALENCE_RULE_INDICES` and `ASIGN_OP_NORMALIZED` (the two knobs csimx-tree-compressor's "Optional secondary pass" covers) don't reduce tree size, so nothing in Steps 1-6 above touches them -- they're validated by tree edit distance / `SimilarityIndex`, not node count. A judge dataset happens to be unusually good evidence for exactly these knobs: two independent solutions to the SAME problem are a natural, real-world example of Type-3 obfuscation (one author's `for` loop vs another's equivalent `while` loop, one's `x += 1` vs another's `x = x + 1`) -- no hand-written pair needed, the same way cross-problem pairs replaced hand-written "different algorithm" pairs earlier.

Run this only if the user asks for it -- it's a separate objective from the main size-reduction LOOP, and it needs you to propose candidate equivalence groups first (this script measures whether a proposed mapping helps, it doesn't discover candidates on its own):

```
python scripts/mine_equivalence_pairs.py --lang python \
    --manifest manifest_python.json \
    --equivalence-candidates equivalence_candidates.json \
    --max-pairs-per-problem 15 --out equivalence_results.json
```

Building `equivalence_candidates.json` takes real grammar knowledge, not just IDs pulled from a list:
- For `control_groups` (e.g. for/while): the rule indices come straight from `Parser.ruleNames`, same as `enumerate_candidates.py` -- no special care needed beyond picking rules that plausibly represent the same control-flow concept.
- For `assign_op_candidates` (e.g. `+=`): the target `rule` MUST be whichever rule the grammar already uses for the plain expanded form (e.g. whatever rule parses `x + y` as a bare binary expression) -- get this wrong and the rewritten tree won't actually match what a human writing `x = x + 1` produces, so the "equivalence" would be fake even if the script reports a similarity gain. Read the grammar (or the relevant generated parser method) to confirm before proposing a candidate, the same way csimx-tree-compressor's Step 2 recommends for snippet-writing.
- `assign_op_candidates` needs a `visitAssignment`-style override in `Visitors.py`; every csimx language now has one (`AUG_ASSIGN_OPS` in its `utils.py`), but check that a new candidate's target rule is the one the grammar uses for the plain expanded form. The script will skip and tell you if you pass assign_op candidates for a language that isn't wired up.

The script reports, per candidate, `avg_similarity_gain` (positive means the mapping brought same-problem pairs closer together, which is the goal) and `pairs_worsened` (pairs where the mapping made things LESS similar -- investigate any of these via the `examples` field before recommending the candidate, since a negative result on real independent code is a meaningful warning sign, not noise to ignore). Same manual-approval gate as everything else: report the findings, including a couple of concrete example pairs so the user can eyeball the actual source before anything gets added to `csimx/<lang>/utils.py` or `Visitors.py`.

## Script reference

- `scripts/build_manifest.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} --corpus-root PATH --out manifest.json` -- one-time-ish corpus scan, records which files parse cleanly and why the rest don't.
- `scripts/enumerate_candidates.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} [--json out.json]` -- same as the sibling skill, lists unclassified tokens/rules.
- `scripts/sample_round.py --manifest manifest.json --state state.json [--round-size 300] [--per-problem-cap 5] [--cross-pairs 10] [--seed N] [--reset] [--keyword-regex PATTERN]` -- draws one cumulative, stratified round plus cross-problem pairs; `--keyword-regex` prefilters the pool by file content for validating rare constructs efficiently.
- `scripts/run_round.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} --round-file round.json [--candidates candidates.json] [--regression-check] --out results.json` -- the measurement engine: parses each file once, benchmarks the baseline, sweeps every candidate strategy, and (if requested and warranted) leave-one-out tests the existing config, all in one process.
- `scripts/mine_equivalence_pairs.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} --manifest manifest.json --equivalence-candidates candidates.json [--max-pairs-per-problem 15] [--max-files-per-problem 40] --out results.json` -- the TED-based tool for `CONTROL_EQUIVALENCE_RULE_INDICES` / `ASIGN_OP_NORMALIZED`, using real same-problem pairs.
- `scripts/harness.py` -- same single-file spot-check tool as the sibling skill, for manually inspecting one flagged file pair.

All scripts assume `csim` is importable and never modify any file except their own manifest/state/results JSON outputs -- every write to `csimx/<lang>/utils.py` or `Visitors.py` happens by hand, after approval.
