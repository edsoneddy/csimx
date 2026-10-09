#!/usr/bin/env python3
"""Resumable, parallel sweep of the pruning config of one csimx language, scored by FIDELITY.

Every candidate change to `csimx/<lang>/utils.py` is measured on a real corpus with the protocol of
docs/pruning_fidelity.md: the similarity index of the pruned trees against a near-raw reference
(only trivia and identifiers dropped; no exclusion, collapsing, hashing or canonical forms), plus
the tree size and the index of random cross-problem pairs (the collapse trap: different programs
that start to look alike). Nothing is written to the repo; progress is checkpointed to a JSON
state file after every candidate, so the sweep can be stopped and resumed.

Candidates (only constructs that occur in at least --min-files sampled files):
  add    token  -> EXCLUDED_TOKEN_TYPES             (strategy `token`)
  add    rule   -> EXCLUDED_RULE_TYPES / COLLAPSED_RULE_INDICES / HASHED_RULE_INDICES
                   (strategies `exclude`, `collapse`, `hash`)
  remove every current member of those four sets      (does an existing entry cost fidelity?)

Modes:
  run       measure the pending candidates (default)
  report    markdown report of the state file
  combine   greedy forward selection among the recommended/marginal changes on the sample of `run`:
            add them one at a time (best MAE first, one strategy per rule) and keep a change only if
            the combined MAE does not get worse; prints the accepted set (the combined effect of
            changes is NOT the sum of their effects, so always run this before applying several)
  validate  apply every recommended change at once and score baseline vs. combined on a fresh sample
            (use a seed that was not used for `run`)

Usage:
  python fidelity_sweep.py --lang java_20 --corpus ../jv-umsa-dataset/all_java --state java_20.json
  python fidelity_sweep.py --lang java_20 --state java_20.json --mode report
  python fidelity_sweep.py --lang java_20 --corpus ... --state java_20.json --mode validate --seed 23

Run from an environment where csimx is importable (PYTHONPATH=<repo> works).
"""
import argparse
import copy
import importlib
import itertools
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from langs import LANG_MODULES, LANGUAGES  # noqa: E402

SETS = {
    "token": "EXCLUDED_TOKEN_TYPES",
    "exclude": "EXCLUDED_RULE_TYPES",
    "collapse": "COLLAPSED_RULE_INDICES",
    "hash": "HASHED_RULE_INDICES",
}
TRIVIA_TOKENS = ("WS", "COMMENT", "LINE_COMMENT", "NEWLINE", "BlockComment", "LineComment", "Whitespace",
                 "Newline", "MultiLineComment", "SingleLineComment", "INDENT", "DEDENT", "Comment",
                 "DelimitedComment", "ShebangLine", "ENCODING")
IDENT_HINTS = ("identifier", "name", "typeidentifier")

# thresholds of the verdicts
MIN_REDUCTION = 0.02       # an addition must remove at least 2% of the nodes
MAX_DMAE_ADD = 0.003       # ... without raising the MAE by more than this
MAX_DCROSS = 0.01          # ... or the mean index of cross-problem pairs by more than this
MIN_DMAE_REMOVE = -0.004   # a removal must lower the MAE by at least this
MAX_GROWTH_REMOVE = 0.10   # ... for at most 10% more nodes

# ---- globals filled before the pool forks --------------------------------------------------------
G = {}


def load_modules(lang):
    cfg = LANG_MODULES[lang]
    from antlr4 import Token
    lexer = getattr(importlib.import_module(cfg["lexer_module"]), cfg["lexer_class"])
    parser = getattr(importlib.import_module(cfg["parser_module"]), cfg["parser_class"])
    utils = importlib.import_module(cfg["utils_module"])
    return Token, lexer, parser, utils


def snapshot(U):
    snap = {}
    for k in dir(U):
        if k.isupper():
            v = getattr(U, k)
            snap[k] = copy.deepcopy(v) if isinstance(v, (set, dict, list)) else v
    return snap


def restore(U, snap):
    """Put the original config back IN PLACE: csimx/Visitors.py binds COLLAPSED_RULE_INDICES at
    import time, so rebinding the name would silently have no effect there."""
    for k, v in snap.items():
        cur = getattr(U, k, None)
        if isinstance(v, set) and isinstance(cur, set):
            cur.clear(); cur.update(v)
        elif isinstance(v, dict) and isinstance(cur, dict):
            cur.clear(); cur.update(copy.deepcopy(v))
        else:
            setattr(U, k, copy.deepcopy(v))


def raw_config(U, snap, raw_tokens, raw_rules):
    restore(U, snap)
    U.EXCLUDED_TOKEN_TYPES.intersection_update(raw_tokens)
    U.EXCLUDED_RULE_TYPES.intersection_update(raw_rules)
    for name in ("HASHED_RULE_INDICES", "COLLAPSED_RULE_INDICES", "STRUCTURAL_RULE_INDICES"):
        if isinstance(getattr(U, name, None), set):
            getattr(U, name).clear()
    if isinstance(getattr(U, "EXCLUDE_CHILDRENS_FROM_RULE", None), dict):
        U.EXCLUDE_CHILDRENS_FROM_RULE.clear()
    U.HASH_MASS_ALPHA = None
    U.CANONICAL_FORMS = False


def apply_ops(U, ops):
    for action, strategy, ident in ops:
        target = getattr(U, SETS[strategy])
        if action == "add":
            target.add(ident)
        else:
            target.discard(ident)


# ---- sampling ------------------------------------------------------------------------------------
def walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.getChild(i) for i in range(n.getChildCount()))


def load_sample(args, lang, U, snap, raw_tokens, raw_rules):
    from csimx.language.parser import ANTLR_parse
    from csimx.processing.tree_processing import Normalize
    from csimx.utils import count_tree_nodes

    ext = LANG_MODULES[lang]["extension"]
    rnd = random.Random(args.seed)
    probs = sorted(p for p in Path(args.corpus).iterdir() if p.is_dir())
    if args.problem_subset != "all":
        probs = probs[0::2] if args.problem_subset == "even" else probs[1::2]
    rnd.shuffle(probs)
    raw_config(U, snap, raw_tokens, raw_rules)
    groups = []
    for p in probs:
        files = sorted(p.glob(f"*{ext}"))
        rnd.shuffle(files)
        good = []
        for f in files:
            if len(good) == args.files:
                break
            try:
                t = ANTLR_parse(f.name, f.read_text(errors="ignore"), lang)
                n = count_tree_nodes(Normalize(t, lang))
            except Exception:
                continue
            if args.min_nodes <= n <= args.max_nodes:
                good.append(t)
        if len(good) >= 6:
            groups.append(good)
        if len(groups) == args.problems:
            break
    restore(U, snap)
    trees, owner = [], []
    for gi, g in enumerate(groups):
        for t in g:
            trees.append(t)
            owner.append(gi)
    within = [(a, b) for a, b in itertools.combinations(range(len(trees)), 2) if owner[a] == owner[b]]
    cross_pool = [(a, b) for a, b in itertools.combinations(range(len(trees)), 2) if owner[a] != owner[b]]
    rnd.shuffle(cross_pool)
    cross = cross_pool[: args.cross]
    return trees, within, cross


# ---- measurement ---------------------------------------------------------------------------------
def build(ops, cfg_fn=None):
    """Index of every pair under the given ops (plus the node counts); runs in a worker or parent."""
    from csimx.processing.tree_processing import Normalize, PruneAndHash
    from csimx.processing.distance_metrics import SimilarityIndex, TreeEditDistance
    from csimx.utils import count_tree_nodes

    U, lang = G["U"], G["lang"]
    if cfg_fn is not None:
        cfg_fn()
    else:
        restore(U, G["snap"])
    apply_ops(U, ops)
    pruned = [PruneAndHash(Normalize(t, lang), lang) for t in G["trees"]]
    nodes = statistics.mean(count_tree_nodes(p[0]) for p in pruned)
    return pruned, nodes, SimilarityIndex, TreeEditDistance


def pair_indices(pruned, pairs, SimilarityIndex, TreeEditDistance):
    return [SimilarityIndex(TreeEditDistance(pruned[a][0], pruned[b][0]), pruned[a][1], pruned[b][1])
            for a, b in pairs]


def score(ops, prescreen=False):
    t0 = time.time()
    pruned, nodes, SI, TED = build(ops)
    base = G["baseline"]
    if prescreen and base and nodes > base["nodes"] * (1 - 0.005):
        return {"skipped": "no_reduction", "nodes": nodes}
    within = pair_indices(pruned, G["within"], SI, TED)
    cross = pair_indices(pruned, G["cross"], SI, TED)
    ref_w = G["ref_within"]
    err = [abs(x - y) for x, y in zip(within, ref_w)]
    return {
        "mae": statistics.mean(err),
        "bias": statistics.mean(x - y for x, y in zip(within, ref_w)),
        "nodes": nodes,
        "cross_mean": statistics.mean(cross),
        "cross_false": sum(c >= 0.7 for c in cross),
        "secs": round(time.time() - t0, 1),
    }


def work(item):
    key, ops = item
    try:
        return key, ops, score(ops, prescreen=ops[0][0] == "add")
    except Exception as e:  # keep the sweep alive; the state records why
        return key, ops, {"error": f"{type(e).__name__}: {e}"}


def verdict(ops, res, base):
    if "error" in res or "skipped" in res:
        return res.get("skipped", "error")
    action = ops[0][0]
    dmae = res["mae"] - base["mae"]
    dcross = res["cross_mean"] - base["cross_mean"]
    dfalse = res["cross_false"] - base["cross_false"]
    change = res["nodes"] / base["nodes"] - 1
    if action == "add":
        if -change >= MIN_REDUCTION and dmae <= MAX_DMAE_ADD and dcross <= MAX_DCROSS and dfalse <= 0:
            return "recommend"
        if -change >= MIN_REDUCTION and dmae <= 2 * MAX_DMAE_ADD:
            return "marginal"
        return "reject"
    if dmae <= MIN_DMAE_REMOVE and change <= MAX_GROWTH_REMOVE and dcross <= 0.005 and dfalse <= 0:
        return "recommend"
    return "keep"


# ---- state / names -------------------------------------------------------------------------------
def names(lexer, parser):
    sym = list(getattr(lexer, "symbolicNames", []))
    rules = list(getattr(parser, "ruleNames", []))
    return sym, rules


def describe(strategy, ident, sym, rules):
    if strategy == "token":
        return sym[ident] if ident < len(sym) else str(ident)
    return rules[ident] if ident < len(rules) else str(ident)


def key_of(action, strategy, ident):
    return f"{action}:{strategy}:{ident}"


def enumerate_candidates(trees, U, lexer, parser, min_files, TOK_OFFSET=None):
    from antlr4.tree.Tree import TerminalNode
    tok_files, rule_files = {}, {}
    for t in trees:
        toks, rls = set(), set()
        for n in walk(t):
            if isinstance(n, TerminalNode):
                toks.add(n.symbol.type)
            else:
                rls.add(n.getRuleIndex())
        for x in toks:
            tok_files[x] = tok_files.get(x, 0) + 1
        for x in rls:
            rule_files[x] = rule_files.get(x, 0) + 1
    n_rules = len(getattr(parser, "ruleNames", []))
    tokens = {t for t, c in tok_files.items() if c >= min_files and t > 0}
    rls = {r for r, c in rule_files.items() if c >= min_files and 0 <= r < n_rules}
    ops = []
    classified_rules = U.EXCLUDED_RULE_TYPES | U.COLLAPSED_RULE_INDICES | U.HASHED_RULE_INDICES
    for t in sorted(tokens - U.EXCLUDED_TOKEN_TYPES):
        ops.append([("add", "token", t)])
    for r in sorted(rls - classified_rules):
        for s in ("exclude", "collapse", "hash"):
            ops.append([("add", s, r)])
    for s, setname in SETS.items():
        pool = tokens if s == "token" else rls
        for x in sorted(getattr(U, setname) & pool):
            ops.append([("remove", s, x)])
    return ops, tok_files, rule_files


def load_state(path):
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return None


def save_state(path, state):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


# ---- report --------------------------------------------------------------------------------------
def report(state):
    base = state["baseline"]
    sym, rules = state["_names"]["tokens"], state["_names"]["rules"]
    out = [f"# Fidelity sweep: {state['lang']}", "",
           f"Sample: {state['sample']['files']} files, {state['sample']['within']} same-problem pairs, "
           f"{state['sample']['cross']} cross-problem pairs (seed {state['args']['seed']}).", "",
           f"Baseline: MAE {base['mae']:.3f}, bias {base['bias']:+.3f}, mean nodes {base['nodes']:.1f}, "
           f"cross mean {base['cross_mean']:.3f}, cross >= 0.7: {base['cross_false']}.",
           f"Reference (near-raw): mean nodes {state['reference']['nodes']:.1f} "
           f"({state['reference']['nodes'] / base['nodes']:.1f}x the current tree).", ""]
    groups = {"recommend": [], "marginal": [], "keep": [], "reject": []}
    other = 0
    for key, rec in state["results"].items():
        v = rec["verdict"]
        if v in groups:
            groups[v].append((key, rec))
        else:
            other += 1
    titles = {"recommend": "Recommended", "marginal": "Marginal (check by hand)",
              "keep": "Existing entries worth keeping", "reject": "Rejected"}
    for v in ("recommend", "marginal", "reject", "keep"):
        rows = groups[v]
        if not rows:
            continue
        out += [f"## {titles[v]} ({len(rows)})", "",
                "| change | name | d nodes | d MAE | d cross mean | d cross>=.7 |", "|---|---|---|---|---|---|"]
        def order(item):
            r = item[1]["result"]
            return r["mae"] - base["mae"]
        for key, rec in sorted(rows, key=order)[: (40 if v in ("reject", "keep") else None)]:
            r = rec["result"]
            action, strategy, ident = key.split(":")
            label = describe(strategy, int(ident), sym, rules)
            dn = r["nodes"] / base["nodes"] - 1
            out.append(f"| {action} {strategy} | `{label}` ({ident}) | {dn:+.1%} | {r['mae'] - base['mae']:+.4f} | "
                       f"{r['cross_mean'] - base['cross_mean']:+.3f} | {r['cross_false'] - base['cross_false']:+d} |")
        out.append("")
    skipped = sum(1 for r in state["results"].values() if r["verdict"] == "no_reduction")
    errors = sum(1 for r in state["results"].values() if r["verdict"] == "error")
    out += [f"Measured: {len(state['results'])} candidates ({skipped} skipped for removing <0.5% of the nodes, "
            f"{errors} errors). Pending: {state.get('pending', 0)}.", "",
            "Nothing here was written to the repo. Apply by hand, then run `--mode validate` with a held-out seed."]
    return "\n".join(out)


# ---- main ----------------------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", required=True, choices=LANGUAGES)
    ap.add_argument("--corpus", help="<root>/<problem>/<file>; needed for run and validate")
    ap.add_argument("--state", required=True)
    ap.add_argument("--mode", choices=("run", "report", "combine", "validate"), default="run")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--problems", type=int, default=8)
    ap.add_argument("--files", type=int, default=8)
    ap.add_argument("--cross", type=int, default=80)
    ap.add_argument("--problem-subset", choices=("all", "even", "odd"), default="all",
                    help="use only every other problem (sorted by name): run `run` on one half and "
                         "`validate` on the other for a problem-disjoint check on small corpora")
    ap.add_argument("--min-nodes", type=int, default=5)
    ap.add_argument("--max-nodes", type=int, default=200)
    ap.add_argument("--min-files", type=int, default=3, help="a construct must occur in this many files")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--max-candidates", type=int, default=None, help="measure at most this many (smoke tests)")
    ap.add_argument("--out", help="write the report here (report mode)")
    ap.add_argument("--only", help="validate mode: comma-separated operations action:strategy:id to apply "
                                   "instead of every recommended change (they need not be in the state file)")
    return ap.parse_args()


def setup(args):
    from csimx.processing.tree_processing import PruneAndHash  # noqa: F401  (import side effects)
    Token, lexer, parser, U = load_modules(args.lang)
    snap = snapshot(U)
    sym, rules = names(lexer, parser)
    raw_tokens = {Token.EOF} | {getattr(lexer, n) for n in TRIVIA_TOKENS if hasattr(lexer, n)}
    raw_rules = {getattr(parser, n) for n in dir(parser)
                 if n.startswith("RULE_") and any(h in n.lower() for h in IDENT_HINTS)}
    G.update(lang=args.lang, U=U, snap=snap)
    return Token, lexer, parser, U, snap, sym, rules, raw_tokens, raw_rules


def measure_reference_and_baseline(args, U, snap, raw_tokens, raw_rules):
    pruned, nodes, SI, TED = build([], cfg_fn=lambda: raw_config(U, snap, raw_tokens, raw_rules))
    ref_within = pair_indices(pruned, G["within"], SI, TED)
    ref_cross = pair_indices(pruned, G["cross"], SI, TED)
    G["ref_within"] = ref_within
    G["baseline"] = None
    base = score([])
    base["secs"] = base.get("secs")
    return {"nodes": nodes, "cross_mean": statistics.mean(ref_cross),
            "cross_false": sum(c >= 0.7 for c in ref_cross)}, base


def main():
    args = parse_args()
    state = load_state(args.state)
    if args.mode == "report":
        if not state:
            sys.exit("no state file")
        text = report(state)
        if args.out:
            Path(args.out).write_text(text)
        print(text)
        return
    if not args.corpus:
        sys.exit("--corpus is required for run and validate")

    Token, lexer, parser, U, snap, sym, rules, raw_tokens, raw_rules = setup(args)
    t0 = time.time()
    trees, within, cross = load_sample(args, args.lang, U, snap, raw_tokens, raw_rules)
    G.update(trees=trees, within=within, cross=cross)
    print(f"[{args.lang}] sample: {len(trees)} files, {len(within)}+{len(cross)} pairs "
          f"({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    reference, base = measure_reference_and_baseline(args, U, snap, raw_tokens, raw_rules)
    G["baseline"] = base
    print(f"[{args.lang}] baseline MAE {base['mae']:.3f}, nodes {base['nodes']:.1f} "
          f"(reference {reference['nodes']:.1f})", file=sys.stderr, flush=True)

    if args.mode == "combine":
        if not state:
            sys.exit("no state file to combine")
        rows = []
        for key, rec in state["results"].items():
            if rec["verdict"] in ("recommend", "marginal") and "mae" in rec["result"]:
                action, strategy, ident = key.split(":")
                rows.append((rec["result"]["mae"], key, (action, strategy, int(ident))))
        rows.sort()
        accepted, used_rules, cur = [], set(), base
        for _, key, op in rows:
            if op[1] != "token" and (op[2] in used_rules):
                continue  # one strategy per rule
            trial = score(accepted + [op])
            ok = trial["mae"] <= cur["mae"] + 0.0005 and trial["cross_false"] <= base["cross_false"] \
                and trial["cross_mean"] <= base["cross_mean"] + MAX_DCROSS
            print(f"  {key:28} MAE {trial['mae']:.4f} (was {cur['mae']:.4f}) nodes {trial['nodes']:.1f} "
                  f"-> {'accept' if ok else 'drop'}", file=sys.stderr, flush=True)
            if ok:
                accepted.append(op)
                used_rules.add(op[2]) if op[1] != "token" else None
                cur = trial
        print(json.dumps({"accepted": [key_of(*o) for o in accepted], "baseline": base, "combined": cur,
                          "d_mae": round(cur["mae"] - base["mae"], 4),
                          "d_nodes": f"{cur['nodes'] / base['nodes'] - 1:+.1%}"}, indent=1))
        return

    if args.mode == "validate":
        if not state:
            sys.exit("no state file to validate")
        ops = []
        if args.only:  # explicit operations, e.g. "add:token:75,remove:exclude:12"
            for key in args.only.split(","):
                action, strategy, ident = key.split(":")
                ops.append((action, strategy, int(ident)))
        else:
            for key, rec in state["results"].items():
                if rec["verdict"] == "recommend":
                    action, strategy, ident = key.split(":")
                    ops.append((action, strategy, int(ident)))
        if not ops:
            print("nothing recommended in the state file")
            return
        res = score(ops)
        change = res["nodes"] / base["nodes"] - 1
        print(json.dumps({"seed": args.seed, "applied": len(ops), "baseline": base, "combined": res,
                          "d_mae": round(res["mae"] - base["mae"], 4), "d_nodes": f"{change:+.1%}",
                          "d_cross_mean": round(res["cross_mean"] - base["cross_mean"], 4)}, indent=1))
        return

    fresh = enumerate_candidates(trees, U, lexer, parser, args.min_files)
    candidates = fresh[0]
    if state and state["args"]["seed"] != args.seed:
        sys.exit("the state file was made with another seed; use a new --state or the same --seed")
    if not state:
        state = {"lang": args.lang, "args": vars(args) | {"corpus": str(args.corpus)}, "results": {},
                 "sample": {"files": len(trees), "within": len(within), "cross": len(cross)},
                 "baseline": base, "reference": reference,
                 "_names": {"tokens": sym, "rules": rules}}
    else:
        state["baseline"], state["reference"] = base, reference  # same seed: should match
    pending = [(key_of(*ops[0]), ops) for ops in candidates if key_of(*ops[0]) not in state["results"]]
    if args.max_candidates:
        pending = pending[: args.max_candidates]
    state["pending"] = len(pending)
    save_state(args.state, state)
    print(f"[{args.lang}] {len(candidates)} candidates, {len(pending)} pending, {args.jobs} workers",
          file=sys.stderr, flush=True)

    done = 0
    ctx = mp.get_context("fork")
    with ctx.Pool(args.jobs) as pool:
        for key, ops, res in pool.imap_unordered(work, pending):
            state["results"][key] = {"result": res, "verdict": verdict(ops, res, base)}
            done += 1
            state["pending"] = len(pending) - done
            save_state(args.state, state)
            if done % 20 == 0 or done == len(pending):
                print(f"[{args.lang}] {done}/{len(pending)} ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    print(report(state))


if __name__ == "__main__":
    main()
