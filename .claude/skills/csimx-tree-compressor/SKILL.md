---
name: csimx-tree-compressor
description: Bootstraps and tunes the tree-compression / obfuscation-resistance config (EXCLUDED_TOKEN_TYPES, EXCLUDED_RULE_TYPES, COLLAPSED_RULE_INDICES, HASHED_RULE_INDICES, EXCLUDE_CHILDRENS_FROM_RULE, STRUCTURAL_RULE_INDICES, HASH_MASS_ALPHA, plus CONTROL_EQUIVALENCE_RULE_INDICES / ASIGN_OP_NORMALIZED / CANONICAL_FORMS) in a csimx language's csimx/<lang>/utils.py, so ANTLR parse trees shrink, tree-edit-distance runs faster, and obfuscated-but-equivalent code (renamed identifiers, swapped for/while loops, x+=1 vs x=x+1) still compares as similar. ALWAYS requires a target language (python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin) -- ask if not stated. Use whenever the user wants to reduce/compress csimx's parse trees, harden it against obfuscation/plagiarism-evasion, bootstrap or fill out a language's utils.py, find new dict/set candidates, or asks e.g. "which rules can we prune for java_20" or mentions PruneAndHash or `csimx tree`. For a measured, automated sweep use csimx-batch-tuner.
---

# csimx Tree Compressor

## Why this exists

csim exists to catch plagiarism, and plagiarists rarely submit an untouched copy -- they obfuscate it. Code-clone-detection research has a standard taxonomy for exactly this, worth knowing because every knob in `csimx/<lang>/utils.py` maps onto one level of it:

- **Type-1**: identical code except formatting, whitespace, and comments.
- **Type-2**: Type-1 plus renamed identifiers and changed literal values.
- **Type-3**: Type-2 plus statement-level edits -- lines added, removed, reordered, or rewritten into an equivalent form (swapping a `for` loop for a `while` loop that does the same thing, writing `x = x + 1` instead of `x += 1`, and so on).
- **Type-4**: same behavior, arbitrarily different syntax (e.g. an iterative vs. a recursive implementation of the same algorithm). This requires actually reasoning about semantics/execution, not just tree structure -- it's out of reach for a structural, TED-based tool like csim, and it's worth being upfront about that limit rather than overclaiming what the config can catch.

csim measures similarity by computing tree edit distance (TED) between normalized ANTLR parse trees, and every entry in `csimx/<lang>/utils.py` either shrinks that tree (so TED runs faster and irrelevant noise stops distorting the score) or normalizes it (so a Type-2/Type-3 obfuscation trick still produces close-to-identical trees instead of looking like a different submission). `csimx/processing/tree_processing.py`'s `Normalize()` and `PruneAndHash()` already know how to apply all seven:

| Name | Effect | Defends against | Applied in |
|---|---|---|---|
| `EXCLUDED_TOKEN_TYPES` | Drops a token entirely | Type-1 (comments, whitespace tokens, redundant punctuation) | `Normalize` |
| `EXCLUDED_RULE_TYPES` | Drops a rule's whole subtree during traversal | Type-2 (e.g. dropping the `name`/identifier rule so renamed variables/functions still match) | `Normalize` |
| `COLLAPSED_RULE_INDICES` | Collapses a rule's subtree to a bare leaf, content fully discarded | Type-2 (literal containers whose exact contents don't matter, e.g. a hardcoded list padded with extra junk values) | `Normalize` (via the visitor's `visit()` override) |
| `HASHED_RULE_INDICES` | Collapses a rule's subtree to a single hashed leaf; different content still gets a different hash, so TED gives it "partial credit" (0.5 instead of 1.0 mismatch cost -- see `distance_metrics.py:label_distance`) instead of full mismatch | Type-3 near-misses (a rewritten expression of the same *kind* stops looking like a total mismatch) | `PruneAndHash` |
| `EXCLUDE_CHILDRENS_FROM_RULE` | Prunes specific children (by label) from one specific rule, everything else in that rule stays | Type-1/Type-2 cleanup scoped to a single rule | `PruneAndHash` |
| `CONTROL_EQUIVALENCE_RULE_INDICES` | Remaps two or more rules' labels to the same equivalence tag (e.g. `for`/`while` -> `"LOOP"`), without discarding their children | Type-3 (control-structure substitution -- swapping one loop/branch construct for a behaviorally equivalent one) | `PruneAndHash` |
| `ASIGN_OP_NORMALIZED` | Rewrites an operator's shorthand form into its canonical expanded form before comparison (e.g. `x += 1` -> `x = x + 1`) | Type-3 (operator-form substitution) | `Visitors.py`'s per-language `visitAssignment`-style override |

The first five are pure size reduction and are what the main LOOP (Steps 1-7 below) automates and measures. The last two, `CONTROL_EQUIVALENCE_RULE_INDICES` and `ASIGN_OP_NORMALIZED`, don't shrink the tree at all -- they're about accuracy against Type-3 obfuscation, need different (more judgment-based) validation, and are covered in "Optional secondary pass" near the end.

`csimx/python_3/utils.py` (the oldest config) and `csimx/java_20/utils.py` are the reference implementations -- read its comments before touching any other language, they document exactly why each decision was made and, just as importantly, why several plausible-looking ones were rejected. That's the bar to match for other languages (every other language and any future one).


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

## Step 0 -- Confirm the target language

Every run of this skill operates on exactly one language's `csimx/<lang>/utils.py` at a time -- python_3, python_3_13, java_20, java_24, cpp_14, c, kotlin or whatever gets added later via ANTLR. If the request doesn't already say which one, ask before doing anything else; don't guess or default to python just because it's the most mature. Everywhere below that says `<lang>`, that's this confirmed value, and it's the `--lang` argument every bundled script takes.

## Prerequisites

This all assumes you're working inside a checkout of the csimx repo with it importable (`pip install -e .`, or `PYTHONPATH=<repo>`), so `import csimx` works and `csimx tree` is on PATH. The two bundled scripts (`scripts/enumerate_candidates.py`, `scripts/harness.py`) need that same environment.

## The core idea, in one paragraph

For every token and rule ANTLR generated for a language that `csimx/<lang>/utils.py` hasn't classified yet, try adding it to each dict/set where it could plausibly belong, measure the resulting `PruneAndHash` node count on representative snippets, and check that the size win doesn't come at the cost of making genuinely different code look identical. Keep the best safe strategy per candidate, write it all up in one report, and only touch the real `utils.py` after the user has looked at the report and approved specific entries.

## Step 1 -- Enumerate candidates

```
python scripts/enumerate_candidates.py --lang <lang>
```

This imports the generated `<Lang>Lexer`/`<Lang>Parser` and the language's `utils.py`, and returns every token and rule with a `classified_as` list showing which of the five dicts/sets (if any) already cover it. Your candidates are everything with an empty list. (Items that already have an entry are shown too, for context -- only revisit those if you have a specific reason to think a different strategy would do better, that's a judgment call, not something to sweep automatically.)

For a language like cpp with an almost-empty `utils.py`, expect this to return most of the grammar. That's fine -- work through it methodically rather than trying to shortcut it; a half-tuned config is worse than an honest empty one because it looks done.

## Step 2 -- For each candidate, write snippets

For each candidate rule or token, write 2-4 short, syntactically valid source files in the target language that exercise it, varying what's *inside* the construct across the snippets (different conditions, different bodies, different literal contents). You're generating these yourself, using what you know about the language and, if useful, by reading the actual grammar production -- either `grammars/<lang>.g4` if it's present in the repo (much more readable), or the generated method for that rule inside `<Lang>Parser.py` (e.g. search for `def ifStatement` or similar -- the generated code mirrors the grammar's structure closely enough to tell you what's optional vs mandatory).

You also need, for every candidate, **one pair of snippets that are algorithmically different from each other** but both exercise the candidate construct -- e.g. for a rule about `if` conditions, one snippet comparing `x > 0` and another checking `y.is_valid()`. This pair is what Step 4's safety check runs against. Keep this pair around per candidate; don't discard it after generating.

If the repo has a real corpus of sample files (`test/files/`, or whatever the python config's comments reference), and you have time, prefer measuring against a handful of those *in addition to* your synthetic snippets -- synthetic snippets tell you a strategy is directionally safe, a real corpus tells you it's actually true at scale. The prior python sweep (see comments above `HASHED_RULE_INDICES` in `python_3/utils.py`) explicitly called out that small hand-picked benchmarks approved things that failed on a larger sweep -- don't repeat that mistake if a bigger corpus is available.

## Step 3 -- Measure baseline

Before testing anything, run the harness with **no overrides** on each snippet to get the current node count:

```
python scripts/harness.py --lang <lang> --file snippet.py
```

Output is one line of JSON: `{"file": ..., "lang": ..., "node_count": N}`. This is your "before" number -- always compare against it, not against some other candidate's baseline.

## Step 4 -- Test each applicable strategy

- A **token** only has one strategy to test: `--add-excluded-token <id>`.
- A **rule** has three worth testing independently (don't assume one strictly dominates -- they behave very differently): `--add-excluded-rule <id>`, `--add-collapsed-rule <id>`, `--add-hashed-rule <id>`.
- If a rule has an optional decorative child (a colon, redundant parens, etc.) that's a poor fit for any of the above but looks safe to drop *within that specific rule*, test `--add-exclude-children '{"<rule_id>": [<child_label>]}'` instead (child label = token type + 1000 for a token child, or the bare rule id for a rule child -- same convention as the real `EXCLUDE_CHILDRENS_FROM_RULE`).

Run each candidate strategy against every snippet from Step 2, note the node count, and compute the reduction: `(before - after) / before`. Each harness invocation is a fresh, isolated subprocess and never writes to any file, so there's no cleanup needed between candidates and no risk of one candidate's test contaminating another's.

Then run the **same override** against your algorithmically-different pair from Step 2, with `--show-tree`, and look at the resulting trees (or just compare `node_count` plus the printed structure) to run the safety check below.

## Step 5 -- Safety checks (this is the part that actually matters)

Size reduction alone is not sufficient -- csim's whole job is telling genuinely different code apart, so a strategy that shrinks the tree by collapsing real differences into identical-looking nodes is actively harmful, not neutral. Two specific failure modes to check for every candidate, mirroring the reasoning already documented throughout `python_3/utils.py`:

**The collapse trap** (relevant to `EXCLUDED_TOKEN_TYPES`, `EXCLUDED_RULE_TYPES`, `EXCLUDE_CHILDRENS_FROM_RULE`): if the thing you're dropping was the *only* signal distinguishing a rule from some other, unrelated construct once everything else about it is optional or already stripped, dropping it makes the two collapse into the same tree shape. `python_3/utils.py`'s comments are full of examples: `DEL`/`AWAIT`/`RETURN` kept because dropping them would make e.g. `del obj.attr` look identical to a bare `obj.attr` reference; `NOT` kept because `not x` would otherwise look like bare `x`. Before approving a drop, ask: does this rule have other mandatory children that survive regardless? If yes, the token/rule you're dropping was redundant and it's safe. If the *only* thing surviving after the drop is one optional child, it's not.

**Never hash (or collapse) a rule that wraps an arbitrarily large statement body.** This was explicitly tried and rejected for `for_stmt`/`else_block` in the prior python sweep: it compressed ~45% of nodes on the benchmark but destroyed real signal, because the body isn't decoration, it's the actual algorithm. A rule like "if statement" or "for loop" wraps a *block*, not just an expression -- collapsing or hashing it throws away everything inside. `HASHED_RULE_INDICES` is meant for narrow, self-contained expression/operator constructs (comparisons, slices, string literals, single wrapped expressions) -- if the candidate rule's children include another statement-list or block-like rule, it almost certainly doesn't belong there, no matter how good the raw reduction number looks. This is exactly why raw node-reduction % can't be the only criterion.

**Distinctiveness check, concretely:** apply the candidate strategy to your algorithmically-different pair of snippets and compare the resulting trees. For `EXCLUDED_TOKEN_TYPES`/`EXCLUDED_RULE_TYPES`/`EXCLUDE_CHILDRENS_FROM_RULE`/`COLLAPSED_RULE_INDICES`, the two snippets' resulting trees (or at least the subtree at/above the candidate node) should still differ -- if they become byte-for-byte identical, flag it unsafe regardless of the size win. For `HASHED_RULE_INDICES`, this is less strict by design (that's the point of hashing -- collapsing similarly-shaped-but-not-identical content into partial credit rather than full mismatch), but still confirm the hash digests differ between the two snippets and that the rule doesn't fail the body-wrapping check above.

If a candidate fails every strategy's safety check, that's a legitimate outcome -- record "no change recommended, here's why" rather than forcing a marginal win through.

## Step 6 -- Write the report

One markdown file per run, don't touch `utils.py` yet. Use this structure:

```markdown
# csim tree-compression candidates: <lang>

Generated: <date>. Candidates evaluated: <N>. Recommended additions: <M>.

## Recommended: EXCLUDED_TOKEN_TYPES
- `TOKEN_NAME` (id `<id>`) -- avg reduction <X>% across <N> snippets. Safe: <one-line why, e.g. "parent rule always has >=2 other mandatory children">.
  ```python
  <Lang>Lexer.TOKEN_NAME,
  ```

## Recommended: EXCLUDED_RULE_TYPES
(same shape)

## Recommended: COLLAPSED_RULE_INDICES
(same shape, plus explicitly note why full content-discard is acceptable for this rule -- e.g. "static literal container, elements carry no algorithmic meaning")

## Recommended: HASHED_RULE_INDICES
(same shape, plus explicitly confirm it passed the body-wrapping check)

## Recommended: EXCLUDE_CHILDRENS_FROM_RULE
- Rule `<rule_name>` (id `<id>`), child `<child_name>` (label `<label>`) -- ...

## Rejected candidates
- `<name>` (id `<id>`): tried <strategies>, best reduction was <X>%, but failed the distinctiveness check because <specific example: snippet A and snippet B produced identical trees after the drop>.

## Not evaluated / needs a real corpus
- Anything you're not confident about from synthetic snippets alone.
```

Every recommended entry needs the actual before/after node counts and which snippet(s) demonstrated it, not just a percentage -- the user needs to be able to sanity-check your reasoning, not just trust the number.

## Step 7 -- Apply approved changes

Only after the user has told you which entries to apply. Edit the real `csimx/<lang>/utils.py` directly, following the same commenting convention `python_3/utils.py` already uses: explain *why* each addition is safe (the collapse-trap reasoning, or "static container" reasoning, etc.), not just what it does -- future readers (including a future run of this same LOOP) rely on those comments to avoid re-litigating settled questions or, worse, reverting something that only looks obviously safe until you remember the trap it's avoiding.

After editing, verify with the real CLI on a couple of held-out snippets (ones not used to justify the change), comparing with and without `--show-raw`:

```
csimx tree --path snippet.py --lang <lang> --show-raw
```

Confirm the node count actually dropped and the tree still looks structurally sound (no runtime errors, no unexpected total collapse).

## Optional secondary pass: Type-3 obfuscation equivalence knobs

`CONTROL_EQUIVALENCE_RULE_INDICES` and `ASIGN_OP_NORMALIZED` don't reduce node count -- skip this pass unless the user specifically asks for it. Their job is narrower and more specific than the size LOOP: two pieces of code that implement the *identical algorithm* but were deliberately rewritten with a different control construct or a different operator form (the Type-3 obfuscation moves described above) should still land close together under TED, instead of scoring as a mismatch just because the AST shape differs. That's a claim about semantic equivalence, not about redundant noise, so it needs different validation than "does this shrink the tree."

- **`CONTROL_EQUIVALENCE_RULE_INDICES`**: candidate groups are rules that implement the same control-flow concept through different syntax (e.g. Python's `for`/`while`, possibly Java's `for`/`while`/enhanced-for). For each candidate group, write two snippets implementing the *exact same algorithm*, one with each construct, and confirm that after remapping both rules to the same label, their subtrees genuinely get closer under TED -- and, just as important, that you're not also flattening together constructs that are only superficially similar (e.g. a C-style `for` used as a `while` vs. one used as a counted loop, if the language's grammar doesn't already separate those). This is inherently more judgment-based than the size LOOP -- present a worked example in the report rather than a bare percentage, and let the user decide.
- **`ASIGN_OP_NORMALIZED`**: mapping compound-assignment operators (`+=`, `-=`, ...) to their expanded binary-op equivalent. In python this is wired through a generic dict plus `PythonParserVisitorExtended.visitAssignment` in `Visitors.py`. Java and cpp don't have an equivalent visitor override yet -- adding this for a new language means writing that visitor method too, not just populating a dict. Treat this as a proposed code change (show the diff, don't apply it) rather than something this skill edits unattended.
- **Generalizing beyond compound assignment**: the same idea extends to other operator-level obfuscations a plagiarist might use -- `i++`/`++i`/`i += 1`/`i = i + 1` are all the same increment; `a * 2` and `a + a` are the same value for numbers. Resist the urge to implement this as a broad "algebraic equivalence" rule, though -- each equivalence needs its own deliberate visitor logic (the same way `ASIGN_OP_NORMALIZED` does today), and unlike the compound-assignment case, things like `a * 2` vs `a + a` are only equivalent for certain types and can silently stop being equivalent under operator overloading or floating-point edge cases. Propose each new equivalence as its own small, explicit, reviewed addition -- with a worked example showing it's actually sound for the language in question -- rather than one sweeping rule. Overgeneralizing here is worse than doing nothing: it's exactly the kind of change that quietly makes genuinely different code look identical, the same collapse-trap failure mode Step 5 warns about, just harder to notice because it hides behind "they're mathematically the same."

## Script reference

- `scripts/enumerate_candidates.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} [--json out.json]` -- lists every token/rule and what it's already classified as.
- `scripts/harness.py --lang {python_3,python_3_13,java_20,java_24,cpp_14,c,kotlin} --file <path> [--add-excluded-token ID]... [--add-excluded-rule ID]... [--add-collapsed-rule ID]... [--add-hashed-rule ID]... [--add-exclude-children JSON] [--show-tree] [--show-raw]` -- runs the real pipeline with those overrides applied in memory only, prints `{"node_count": ...}` as JSON on stdout, optional human-readable tree(s) on stderr.

Both scripts assume `csim` is importable in the current environment and never modify any file -- they're read-only measurement tools. Every write to `csimx/<lang>/utils.py` happens by hand, in Step 7, after approval.
