---
name: csimx-tree-compressor
description: Bootstraps and tunes the tree-compression / obfuscation-resistance config (EXCLUDED_TOKEN_TYPES, EXCLUDED_RULE_TYPES, COLLAPSED_RULE_INDICES, HASHED_RULE_INDICES, EXCLUDE_CHILDRENS_FROM_RULE, STRUCTURAL_RULE_INDICES, HASH_MASS_ALPHA, plus CONTROL_EQUIVALENCE_RULE_INDICES / ASIGN_OP_NORMALIZED / CANONICAL_FORMS) in a csimx language's csimx/<lang>/utils.py, so ANTLR parse trees shrink, tree-edit-distance runs faster, and obfuscated-but-equivalent code (renamed identifiers, swapped for/while loops, x+=1 vs x=x+1) still compares as similar. ALWAYS requires a target language (python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin) -- ask if not stated. Use whenever the user wants to reduce/compress csimx's parse trees, harden it against obfuscation/plagiarism-evasion, bootstrap or fill out a language's utils.py, find new dict/set candidates, or asks e.g. "which rules can we prune for java_20" or mentions PruneAndHash or `csimx tree`. For a measured, automated sweep use csimx-batch-tuner.
---

# csimx Tree Compressor

## Why this exists

csimx exists to catch plagiarism, and plagiarists rarely submit an untouched copy. Code-clone research has a standard taxonomy, and every knob in `csimx/<lang>/utils.py` maps onto one level:

- **Type-1**: identical except formatting, whitespace and comments.
- **Type-2**: Type-1 plus renamed identifiers and changed literals.
- **Type-3**: Type-2 plus statement-level edits (added, removed, reordered or rewritten lines; `for` -> `while`, `x = x + 1` for `x += 1`).
- **Type-4**: same behavior, arbitrarily different syntax. Out of reach for a structural tool; do not overclaim.

csimx computes tree edit distance (TED) between normalized ANTLR parse trees. Each entry in `utils.py` either shrinks that tree (faster TED, less noise) or normalizes it (an obfuscation trick still gives a near-identical tree). `Normalize()` and `PruneAndHash()` in `csimx/processing/tree_processing.py` apply all of them:

| Name | Effect | Defends against | Applied in |
|---|---|---|---|
| `EXCLUDED_TOKEN_TYPES` | Drops a token | Type-1 | `Normalize` |
| `EXCLUDED_RULE_TYPES` | Drops a rule's whole subtree | Type-2 (identifiers) | `Normalize` |
| `COLLAPSED_RULE_INDICES` | Collapses a subtree to a bare leaf, content discarded | Type-2 (literal containers) | `Normalize` |
| `HASHED_RULE_INDICES` | Collapses a subtree to one hashed leaf; different content gets partial credit (`distance_metrics.py:label_distance`) | Type-3 near-misses | `PruneAndHash` |
| `EXCLUDE_CHILDRENS_FROM_RULE` | Prunes given children of one rule | Type-1/2 cleanup scoped to a rule | `PruneAndHash` |
| `CONTROL_EQUIVALENCE_RULE_INDICES` | Maps several rules to one tag (`for`/`while` -> `"LOOP"`), keeping children | Type-3 control-structure swaps | `PruneAndHash` |
| `ASIGN_OP_NORMALIZED` | Rewrites `x += 1` to `x = x + 1` | Type-3 operator forms | per-language `visitAssignment` in `Visitors.py` |

The first five are size reduction and are what Steps 1-7 automate. The last two do not shrink the tree; see "Optional secondary pass".

`csimx/python_3/utils.py` and `csimx/java_20/utils.py` are the reference configs: their comments say why each decision was made and why plausible ones were rejected.

## What the csimx sweeps taught (read before proposing anything)

From `docs/pruning_fidelity.md` and the CHANGELOG:

* **Judge a change by fidelity, not node count.** The metric is the mean absolute error of the index of the pruned trees against a near-raw reference (only trivia and identifiers dropped), on real same-problem pairs of the `jv-umsa-dataset` corpora, plus the index of random cross-problem pairs (the collapse trap). `csimx-batch-tuner/scripts/fidelity_sweep.py` does this; the snippet workflow below is for a first look at a new grammar.
* **Never hash the control-flow skeleton.** Hashing `if`/`while`/`for`/`def`/`class`/method bodies turned programs into 1-8 nodes and made 34-40% of *unrelated* pairs look >= 0.7 similar. Only expression/declaration "islands" are hashed; `STRUCTURAL_RULE_INDICES` stops a hashed rule containing control flow from being collapsed.
* **Hashed nodes should carry weight.** `HASH_MASS_ALPHA` (python_3 0.6, java_20 0.4, cpp_14 0.6, c 0.6, kotlin 0.6; java_24 none) makes a hashed node weigh `(subtree size + 1) ** alpha`. Sweep alpha per language (none, 0.25, 0.4, 0.6, 0.75).
* **Canonical forms** (`CANONICAL_FORMS`, `csimx/canonical_common.py` + `<lang>/canonical.py`) unify equivalent operator forms before pruning; fidelity should not move. Inlining of temporaries was prototyped and rejected.
* **Mutate config sets in place.** `Visitors.py` binds `COLLAPSED_RULE_INDICES` at import time; rebinding the name in a script silently measures the untouched config.
* **Do not trust one seed.** Choose with two seeds, confirm on a third (`validate` mode). The Kotlin corpus is synthetic with 12 problems, so its numbers are indicative.

## Step 0 -- Confirm the target language

Each run works on one language's `csimx/<lang>/utils.py` (python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin). If the request does not say which, ask. `<lang>` below is that value and the `--lang` of every script.

## Prerequisites

A csimx checkout that is importable (`pip install -e .` or `PYTHONPATH=<repo>`). The bundled scripts need the same environment.

## The core idea

For every token and rule not yet classified in `utils.py`, try adding it to each set where it could belong, measure the `PruneAndHash` node count on representative snippets, and check that the size win does not make different code look identical. Write one report; touch `utils.py` only after the user approves specific entries.

## Step 1 -- Enumerate candidates

```
python scripts/enumerate_candidates.py --lang <lang>
```

Returns every token and rule with a `classified_as` list. Candidates are those with an empty list; revisit classified ones only with a specific reason. A language with an almost-empty `utils.py` returns most of the grammar: work through it methodically, since a half-tuned config looks done and is not.

## Step 2 -- Write snippets

For each candidate write 2-4 short valid files exercising it, varying what is *inside* the construct. Read the grammar (`grammars/<lang>.g4` or the generated `<Lang>Parser.py`) to know what is optional. Also keep **one pair of algorithmically different snippets** that both use the construct; Step 5 runs against it. If a real corpus is available, measure on it too: small hand-picked benchmarks approved things that failed at scale in the earlier python sweep.

## Step 3 -- Measure baseline

```
python scripts/harness.py --lang <lang> --file snippet.py
```

One JSON line: `{"file", "lang", "node_count"}`. Always compare against this baseline.

## Step 4 -- Test each strategy

- A **token**: `--add-excluded-token <id>`.
- A **rule**, each independently: `--add-excluded-rule <id>`, `--add-collapsed-rule <id>`, `--add-hashed-rule <id>`.
- A decorative child of one rule (colon, redundant parens): `--add-exclude-children '{"<rule_id>": [<child_label>]}'` (label = token type + 1000 for a token, bare rule id for a rule).

Run each against every snippet and compute `(before - after) / before`. Each run is an isolated subprocess that writes nothing. Then run the same override on the different-algorithm pair with `--show-tree` for Step 5.

## Step 5 -- Safety checks

A strategy that shrinks the tree by collapsing real differences is harmful, not neutral.

**Collapse trap** (`EXCLUDED_TOKEN_TYPES`, `EXCLUDED_RULE_TYPES`, `EXCLUDE_CHILDRENS_FROM_RULE`): if what you drop was the only signal distinguishing a rule from another construct, the two collapse into one shape. `python_3/utils.py` keeps `DEL`/`AWAIT`/`RETURN` and `NOT` for this reason (`del obj.attr` vs `obj.attr`, `not x` vs `x`). Ask: does the rule have other mandatory children that survive? If yes the drop is safe; if only one optional child survives, it is not.

**Never hash or collapse a rule that wraps a statement body.** Hashing `for_stmt`/`else_block` compressed ~45% of nodes and destroyed the signal, because the body is the algorithm. `HASHED_RULE_INDICES` is for narrow expression/operator constructs; if the candidate's children include a statement list or block, it does not belong, whatever the reduction.

**Distinctiveness check:** apply the strategy to the different-algorithm pair. For exclude/collapse strategies the two trees must still differ, or the candidate is unsafe. For hashing, confirm the digests differ and the body-wrapping check passes.

"No change recommended, and why" is a legitimate outcome.

## Step 6 -- Write the report

One markdown file per run; do not touch `utils.py` yet.

```markdown
# csimx tree-compression candidates: <lang>

Generated: <date>. Candidates evaluated: <N>. Recommended additions: <M>.

## Recommended: <SET_NAME>   (one section per set)
- `NAME` (id `<id>`) -- reduction <X>% across <N> snippets (before/after node counts, which snippets). Safe: <one-line why>.
  ```python
  <Lang>Lexer.NAME,
  ```

## Rejected candidates
- `<name>` (id `<id>`): tried <strategies>, best <X>%, failed distinctiveness because <snippet A and B became identical>.

## Not evaluated / needs a real corpus
```

For `COLLAPSED_RULE_INDICES` say why discarding the content is acceptable; for `HASHED_RULE_INDICES` confirm the body-wrapping check passed.

## Step 7 -- Apply approved changes

Only for entries the user approved. Edit `csimx/<lang>/utils.py` with a short comment saying *why* it is safe, so a later run does not re-litigate or revert it. Then verify on held-out snippets:

```
csimx tree --path snippet.py --lang <lang> --show-raw
```

Confirm the node count dropped and the tree is sound.

## Optional secondary pass: Type-3 equivalence knobs

`CONTROL_EQUIVALENCE_RULE_INDICES` and `ASIGN_OP_NORMALIZED` do not reduce node count; skip unless asked. They claim semantic equivalence, so they need judgment rather than a percentage.

- **`CONTROL_EQUIVALENCE_RULE_INDICES`**: rules that express the same control-flow concept (python `for`/`while`, java `for`/`while`/enhanced-for). Write two snippets of the *same algorithm*, one per construct, and confirm the subtrees get closer under TED once both rules share a label, without flattening constructs that are only superficially alike. Present a worked example and let the user decide.
- **`ASIGN_OP_NORMALIZED`**: maps `+=`, `-=`, ... to the expanded form. Python wires it through a dict plus `PythonParserVisitorExtended.visitAssignment`; java and cpp have no such override, so a new language needs visitor code. Propose it as a diff, do not apply it unattended.
- **Beyond compound assignment** (`i++` / `i += 1` / `i = i + 1`, `a * 2` / `a + a`): propose each equivalence as its own small reviewed addition with a worked example. `a * 2` vs `a + a` is only equivalent for some types, and a sweeping "algebraic equivalence" rule is the collapse trap in disguise.

## Script reference

- `scripts/enumerate_candidates.py --lang <lang> [--json out.json]` -- every token/rule and what classifies it.
- `scripts/harness.py --lang <lang> --file <path> [--add-excluded-token ID]... [--add-excluded-rule ID]... [--add-collapsed-rule ID]... [--add-hashed-rule ID]... [--add-exclude-children JSON] [--show-tree] [--show-raw]` -- real pipeline with in-memory overrides; `{"node_count": ...}` on stdout, trees on stderr.

Both are read-only; every write to `csimx/<lang>/utils.py` happens by hand in Step 7.
