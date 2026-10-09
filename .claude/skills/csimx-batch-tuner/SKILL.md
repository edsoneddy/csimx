---
name: csimx-batch-tuner
description: Resumable, parallel, fidelity-scored sweep of a csimx language's pruning config (EXCLUDED_TOKEN_TYPES, EXCLUDED_RULE_TYPES, COLLAPSED_RULE_INDICES, HASHED_RULE_INDICES) on a real corpus. For every token/rule that occurs in the sampled files it measures what adding it would do, and for every existing entry what removing it would do, in terms of tree size, mean absolute error of the similarity index against a near-raw reference, and false similarity of cross-problem pairs. Checkpoints after every candidate, so it can be stopped and resumed, then validates the recommended set on a held-out seed. Use when the user wants to finish or re-check a language's compression config methodically, run a long sweep across python_3 / python_3_13 / java_20 / java_24 / cpp_14 / c / kotlin, or says "keep going where we left off" or "work through everything still unclassified". Does NOT choose HASH_MASS_ALPHA or CANONICAL_FORMS (sweep those by hand with the same metric; see csimx-tree-compressor) and does not touch CONTROL_EQUIVALENCE_RULE_INDICES / ASIGN_OP_NORMALIZED (see csimx-corpus-tuner).
---

# csimx Batch Tuner

## How this relates to the other two csimx skills

- **csimx-tree-compressor**: concepts, the knobs, the safety reasoning, one language, interactive, snippets. Read its "What the csimx sweeps taught" section first.
- **csimx-corpus-tuner**: real-corpus rounds (node reduction, regression check) and the TED tool for the equivalence knobs.
- **csimx-batch-tuner** (this one): the automated version. It scores each candidate with the protocol of `docs/pruning_fidelity.md` instead of a hand-written snippet pair, so nothing needs to be written by hand and a whole language runs unattended.

The older version of this skill used synthetic snippets and a label-overlap proxy for "did two different programs become alike". The corpus makes that unnecessary: same-problem pairs give the fidelity, random cross-problem pairs give the collapse trap.

## What a candidate is measured against

* **Reference ("near-raw")**: only trivia (whitespace, comments, `NEWLINE`/`INDENT`/`DEDENT`, EOF) and identifier rules dropped; no other exclusion, no collapsing, no hashing, no `HASH_MASS_ALPHA`, no canonical forms. The sweep builds it by emptying the config sets **in place** (`Visitors.py` binds `COLLAPSED_RULE_INDICES` at import time, so rebinding a name would silently do nothing).
* **MAE**: mean |index(pruned) - index(reference)| over all same-problem pairs of the sample (default 8 problems x 8 files = 224 pairs, files of 5-200 nodes). Lower is better; the shipped configs are at 0.045-0.08.
* **Nodes**: mean node count of the pruned trees.
* **Cross-problem pairs** (default 80 random pairs from different problems): their mean index and how many reach 0.7. Different problems are different programs, so this must not go up.

Verdicts (constants at the top of `fidelity_sweep.py`; they are starting points, not validated laws):

| change | recommend when |
|---|---|
| **add** | removes >= 2% of the nodes, MAE rises by <= 0.003, cross mean rises by <= 0.01 and no new cross pair reaches 0.7 |
| **remove** an existing entry | MAE falls by >= 0.004, nodes grow by <= 10%, cross mean rises by <= 0.005, no new cross pair reaches 0.7 |

Additions that remove < 0.5% of the nodes are skipped without computing the (slow) edit distance. Constructs that occur in fewer than `--min-files` (3) sampled files are not tested: there is no evidence either way.

## The loop

Run from the repo root with csimx importable (`PYTHONPATH=.` works). One language at a time; a fast one (kotlin) first is a good smoke test. Corpora: `../jv-umsa-dataset/all_py`, `all_java`, `all_cpp`, `all_c`, `all_kotlin` (Kotlin is synthetic and has 12 problems: indicative only).

```
python .claude/skills/csimx-batch-tuner/scripts/fidelity_sweep.py \
    --lang java_20 --corpus ../jv-umsa-dataset/all_java --state java_20.json --seed 7
```

* It prints progress on stderr and the markdown report on stdout when it finishes. `--jobs N` sets the workers (default: cores - 2); `--max-candidates N` limits a smoke test.
* The state file is written after **every** candidate (atomically). Stop it any time; run the same command again and it resumes with the pending ones. A state file belongs to one seed; to change the sample use a new `--state`.
* Run time is dominated by the pure-Python edit distance: about a minute per candidate and worker for Java/C++/Python, a few seconds for Kotlin.

Then:

```
... --state java_20.json --mode report [--out report.md]      # re-render, safe anytime
... --corpus ... --state java_20.json --mode validate --seed 23   # all recommended together, held-out sample
```

`validate` applies every `recommend` change at once and prints baseline vs. combined MAE, nodes and cross-pair mean on a **fresh sample** (use a seed that was not used for `run`). Changes interact: if the combined MAE is worse than baseline, apply the recommendations one by one (largest node reduction first) and re-validate.

## Reading the result

* `Recommended` additions are candidates for the config, not decisions: look at what the construct is (`describe` names tokens and rules). Never accept a rule that wraps a statement body or block: read the rule in the grammar (the generated `<Lang>Parser.py`, or `grammars/`) and check it is a self-contained expression/declaration "island" (see csimx-tree-compressor, "Never hash the control-flow skeleton").
* `Existing entries worth keeping` is empty for a healthy config; a `recommend` *removal* means an old exclusion costs more fidelity than the nodes it saves.
* An empty `Recommended` list is a valid and common outcome: the shipped configs were already swept.

## Apply (only after the user has seen the report)

Edit `csimx/<lang>/utils.py` by hand, with a comment saying why (follow the style of the existing ones), then:

1. `python -m pytest test -q`
2. `validate` with the held-out seed; `csimx tree --path <file> --lang <lang> --show-raw` on a couple of files that were not in the sample.
3. Controlled clones (`jv-umsa-dataset/controlled/<lang>`: pairs scoring >= 0.7 must not drop) and a few hundred random cross-problem pairs.
4. Record the numbers in `CHANGELOG.md` and `docs/pruning_fidelity.md`.

## Script reference

- `scripts/fidelity_sweep.py` -- everything above. Flags: `--lang`, `--corpus`, `--state`, `--mode {run,report,validate}`, `--seed`, `--problems`, `--files`, `--cross`, `--min-nodes`, `--max-nodes`, `--min-files`, `--jobs`, `--max-candidates`, `--out`.
- `scripts/enumerate_candidates.py --lang L [--json out.json]` -- every token/rule and which set already classifies it (no corpus needed).
- `scripts/harness.py --lang L --file F [--add-excluded-token ID]... [--show-tree] [--show-raw]` -- one file through the real pipeline with in-memory overrides.
- `scripts/langs.py` -- the language wiring (lexer/parser/utils modules, entry rule, extension) shared by the scripts of the three skills.

Nothing in these scripts writes to `csimx/<lang>/utils.py`; only the state/report files are written.
