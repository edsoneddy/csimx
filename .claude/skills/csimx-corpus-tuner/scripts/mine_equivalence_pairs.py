#!/usr/bin/env python3
"""Mine same-problem solution pairs from a corpus manifest to validate candidates for
CONTROL_EQUIVALENCE_RULE_INDICES and (python only) ASIGN_OP_NORMALIZED, the knobs that make
Type-3-equivalent code (for/while swap, `x += 1` vs `x = x + 1`) compare as more similar.
These are measured with the tree edit distance, not node count.

Usage:
    python mine_equivalence_pairs.py --lang python_3 --manifest manifest_python_3.json \\
        --equivalence-candidates equivalence_candidates.json \\
        --max-pairs-per-problem 15 --max-files-per-problem 40 --out equivalence_results.json

equivalence_candidates.json:
{
  "control_groups": [
    {"name": "for/while loop", "tag": "LOOP", "rules": {"71": "for_stmt", "72": "while_stmt"}}
  ],
  "assign_op_candidates": [
    {"name": "+= as x=x+1", "operand_text": "+=", "rule": 143, "operator_token": 14}
  ]
}

This script only measures a proposed mapping. Rule indices come from Parser.ruleNames (see
enumerate_candidates.py). For assign_op_candidates, "rule" must be the rule the grammar uses for
the expanded binary-op form and "operator_token" the plain operator (PLUS, not PLUS_ASSIGN).

Visitors.py binds COLLAPSED_RULE_INDICES and ASIGN_OP_NORMALIZED at import time, so override
ASIGN_OP_NORMALIZED by mutating the existing dict in place. CONTROL_EQUIVALENCE_RULE_INDICES is
read fresh and can be reassigned. assign_op_candidates only works for python (no visitAssignment
override for java/cpp yet).
"""
import argparse
import importlib
import itertools
import json
import random
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from langs import LANG_UTILS_MODULE




def parse_file(path, lang):
    from csimx.language.parser import ANTLR_parse

    with open(path, "r", encoding="utf-8", errors="strict") as f:
        content = f.read()
    return ANTLR_parse(path, content, lang)


def rule_ids_present(node, target_ids):
    """Single walk over the raw ANTLR tree, returns the subset of
    `target_ids` (rule indices) that actually appear somewhere in it.
    """
    from antlr4 import TerminalNode

    found = set()

    def walk(n):
        if isinstance(n, TerminalNode):
            return
        if n.getRuleIndex() in target_ids:
            found.add(n.getRuleIndex())
        for child in n.getChildren():
            walk(child)

    walk(node)
    return found


def token_present(node, target_id):
    from antlr4 import TerminalNode

    if isinstance(node, TerminalNode):
        return node.symbol.type == target_id
    return any(token_present(child, target_id) for child in node.getChildren())


def compute_similarity(raw_a, raw_b, lang, ted_algorithm="zss"):
    from csimx.processing.tree_processing import Normalize, PruneAndHash
    from csimx.processing.distance_metrics import TreeEditDistance, SimilarityIndex

    norm_a = Normalize(raw_a, lang)
    pruned_a, count_a = PruneAndHash(norm_a, lang)
    norm_b = Normalize(raw_b, lang)
    pruned_b, count_b = PruneAndHash(norm_b, lang)

    d = TreeEditDistance(pruned_a, pruned_b, ted_algorithm)
    return SimilarityIndex(d, count_a, count_b)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang", required=True, choices=sorted(LANG_UTILS_MODULE))
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--equivalence-candidates", required=True)
    ap.add_argument("--max-pairs-per-problem", type=int, default=15)
    ap.add_argument("--max-files-per-problem", type=int, default=40,
                     help="Cap how many of a problem's files get parsed at all, "
                          "before pairs are drawn from among them -- keeps a huge "
                          "problem folder from dominating parse time.")
    ap.add_argument("--ted-algorithm", choices=["zss", "apted"], default="zss")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    with open(args.manifest) as f:
        manifest = json.load(f)
    with open(args.equivalence_candidates) as f:
        eq_candidates = json.load(f)

    control_groups = eq_candidates.get("control_groups", [])
    assign_op_candidates = eq_candidates.get("assign_op_candidates", [])
    if assign_op_candidates and args.lang != "python":
        print(
            f"NOTE: {len(assign_op_candidates)} assign_op_candidates given for "
            f"--lang {args.lang}, but ASIGN_OP_NORMALIZED only has a visitAssignment "
            f"override wired up for python today. Skipping those; control_groups "
            f"will still run."
        )
        assign_op_candidates = []

    utils_mod = importlib.import_module(LANG_UTILS_MODULE[args.lang])
    pristine_control_equiv = dict(getattr(utils_mod, "CONTROL_EQUIVALENCE_RULE_INDICES", {}) or {})
    pristine_assign_op = dict(getattr(utils_mod, "ASIGN_OP_NORMALIZED", {}) or {})

    corpus_root = manifest["corpus_root"]
    problems = manifest["problems"]

    control_results = {g["name"]: {"pairs_tested": 0, "sim_before_sum": 0.0, "sim_after_sum": 0.0,
                                     "improved": 0, "worsened": 0, "examples": []}
                        for g in control_groups}
    assign_results = {a["name"]: {"pairs_tested": 0, "sim_before_sum": 0.0, "sim_after_sum": 0.0,
                                    "improved": 0, "worsened": 0, "examples": []}
                       for a in assign_op_candidates}

    problem_ids = [pid for pid, b in problems.items() if len(b["valid"]) >= 2]
    random.shuffle(problem_ids)

    for problem_id in problem_ids:
        files = list(problems[problem_id]["valid"])
        random.shuffle(files)
        files = files[: args.max_files_per_problem]
        if len(files) < 2:
            continue

        raw_trees = {}
        for rel_path in files:
            abs_path = f"{corpus_root}/{rel_path}"
            try:
                raw_trees[rel_path] = parse_file(abs_path, args.lang)
            except Exception:
                continue
        parsed_files = list(raw_trees.keys())
        if len(parsed_files) < 2:
            continue

        all_pairs = list(itertools.combinations(parsed_files, 2))
        if len(all_pairs) > args.max_pairs_per_problem:
            pairs = random.sample(all_pairs, args.max_pairs_per_problem)
        else:
            pairs = all_pairs

        for file_a, file_b in pairs:
            tree_a, tree_b = raw_trees[file_a], raw_trees[file_b]

            # --- control_groups ---
            for group in control_groups:
                rule_ids = {int(k) for k in group["rules"].keys()}
                present_a = rule_ids_present(tree_a, rule_ids)
                present_b = rule_ids_present(tree_b, rule_ids)
                if not present_a or not present_b or present_a == present_b:
                    continue  # not relevant: doesn't exercise a real substitution

                utils_mod.CONTROL_EQUIVALENCE_RULE_INDICES = dict(pristine_control_equiv)
                sim_before = compute_similarity(tree_a, tree_b, args.lang, args.ted_algorithm)

                override = dict(pristine_control_equiv)
                for rid in rule_ids:
                    override[rid] = group["tag"]
                utils_mod.CONTROL_EQUIVALENCE_RULE_INDICES = override
                sim_after = compute_similarity(tree_a, tree_b, args.lang, args.ted_algorithm)
                utils_mod.CONTROL_EQUIVALENCE_RULE_INDICES = dict(pristine_control_equiv)

                r = control_results[group["name"]]
                r["pairs_tested"] += 1
                r["sim_before_sum"] += sim_before
                r["sim_after_sum"] += sim_after
                delta = sim_after - sim_before
                if delta > 0.02:
                    r["improved"] += 1
                elif delta < -0.02:
                    r["worsened"] += 1
                if len(r["examples"]) < 5:
                    r["examples"].append({
                        "problem": problem_id, "file_a": file_a, "file_b": file_b,
                        "sim_before": round(sim_before, 3), "sim_after": round(sim_after, 3),
                    })

            # --- assign_op_candidates (python only) ---
            for cand in assign_op_candidates:
                op_token = cand["operator_token"]
                uses_op_a = token_present(tree_a, op_token)
                uses_op_b = token_present(tree_b, op_token)
                if not (uses_op_a or uses_op_b):
                    continue  # neither file uses this operator at all -- not relevant

                def set_assign_op(active):
                    utils_mod.ASIGN_OP_NORMALIZED.clear()
                    utils_mod.ASIGN_OP_NORMALIZED.update(pristine_assign_op)
                    if active:
                        utils_mod.ASIGN_OP_NORMALIZED[cand["operand_text"]] = (
                            cand["rule"], cand["operator_token"],
                        )

                set_assign_op(False)
                sim_before = compute_similarity(tree_a, tree_b, args.lang, args.ted_algorithm)
                set_assign_op(True)
                sim_after = compute_similarity(tree_a, tree_b, args.lang, args.ted_algorithm)
                set_assign_op(False)

                r = assign_results[cand["name"]]
                r["pairs_tested"] += 1
                r["sim_before_sum"] += sim_before
                r["sim_after_sum"] += sim_after
                delta = sim_after - sim_before
                if delta > 0.02:
                    r["improved"] += 1
                elif delta < -0.02:
                    r["worsened"] += 1
                if len(r["examples"]) < 5:
                    r["examples"].append({
                        "problem": problem_id, "file_a": file_a, "file_b": file_b,
                        "sim_before": round(sim_before, 3), "sim_after": round(sim_after, 3),
                    })

    def finalize(results):
        out = []
        for name, r in results.items():
            n = r["pairs_tested"]
            out.append({
                "name": name,
                "pairs_tested": n,
                "avg_sim_before": round(r["sim_before_sum"] / n, 3) if n else None,
                "avg_sim_after": round(r["sim_after_sum"] / n, 3) if n else None,
                "avg_similarity_gain": round((r["sim_after_sum"] - r["sim_before_sum"]) / n, 3) if n else None,
                "pairs_improved": r["improved"],
                "pairs_worsened": r["worsened"],
                "examples": r["examples"],
            })
        return out

    result = {
        "lang": args.lang,
        "problems_considered": len(problem_ids),
        "control_groups": finalize(control_results),
        "assign_op_candidates": finalize(assign_results),
    }

    # Leave the module's live config back at pristine before this process exits.
    utils_mod.CONTROL_EQUIVALENCE_RULE_INDICES = dict(pristine_control_equiv)
    utils_mod.ASIGN_OP_NORMALIZED.clear()
    utils_mod.ASIGN_OP_NORMALIZED.update(pristine_assign_op)

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "problems_considered": result["problems_considered"],
        "control_groups": [
            {"name": c["name"], "pairs_tested": c["pairs_tested"],
             "avg_similarity_gain": c["avg_similarity_gain"],
             "pairs_worsened": c["pairs_worsened"]}
            for c in result["control_groups"]
        ],
        "assign_op_candidates": [
            {"name": a["name"], "pairs_tested": a["pairs_tested"],
             "avg_similarity_gain": a["avg_similarity_gain"],
             "pairs_worsened": a["pairs_worsened"]}
            for a in result["assign_op_candidates"]
        ],
        "out": args.out,
    }, indent=2))


if __name__ == "__main__":
    main()
