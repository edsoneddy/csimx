#!/usr/bin/env python3
"""Measurement engine of csimx-corpus-tuner. Takes one round's file sample (from
sample_round.py) and a list of candidate token/rule strategies, and optionally runs a
leave-one-out regression check of the config already applied, all in ONE process.

Each file is parsed with ANTLR once and the raw trees are kept in memory: the compression knobs
only affect Normalize() and PruneAndHash(), which are re-run per candidate. The real config sets
are snapshotted at startup and never mutated; every measurement builds new sets from the snapshot
plus one override. Nothing is written to utils.py.

Usage:
    python run_round.py --lang python_3 --round-file round_3.json \\
        --candidates candidates.json --regression-check --out round_3_results.json

candidates.json:
{
  "tokens": [{"id": 44, "name": "SOME_TOKEN"}],
  "rules": [{"id": 12, "name": "someRule", "strategies": ["excluded_rule", "collapsed_rule", "hashed_rule"]}],
  "exclude_children": [{"rule_id": 12, "rule_name": "someRule", "child_label": 1044, "child_name": "COLON"}]
}
"strategies" defaults to all three.
"""
import argparse
import copy
import hashlib
import importlib
import json
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from langs import LANG_UTILS_MODULE



KNOB_NAMES = (
    "EXCLUDED_TOKEN_TYPES",
    "EXCLUDED_RULE_TYPES",
    "COLLAPSED_RULE_INDICES",
    "HASHED_RULE_INDICES",
    "EXCLUDE_CHILDRENS_FROM_RULE",
)


def snapshot_pristine(utils_mod):
    return {
        "EXCLUDED_TOKEN_TYPES": set(getattr(utils_mod, "EXCLUDED_TOKEN_TYPES", set())),
        "EXCLUDED_RULE_TYPES": set(getattr(utils_mod, "EXCLUDED_RULE_TYPES", set())),
        "COLLAPSED_RULE_INDICES": set(getattr(utils_mod, "COLLAPSED_RULE_INDICES", set())),
        "HASHED_RULE_INDICES": set(getattr(utils_mod, "HASHED_RULE_INDICES", set())),
        "EXCLUDE_CHILDRENS_FROM_RULE": {
            k: list(v) for k, v in getattr(utils_mod, "EXCLUDE_CHILDRENS_FROM_RULE", {}).items()
        },
    }


def apply_config(utils_mod, pristine, overrides):
    """Build a fresh config from `pristine` + `overrides` and assign it to
    the module. `overrides` is a dict with the same five keys as
    KNOB_NAMES, each either an iterable of ids to ADD (for the four
    sets) or a dict of {rule_id: [extra_child_labels]} to MERGE (for
    EXCLUDE_CHILDRENS_FROM_RULE) -- and, for regression checks, ids to
    REMOVE, passed as (set_name, "remove", id).

    IMPORTANT, and the source of a real bug in an earlier version of this
    script: EXCLUDED_TOKEN_TYPES, EXCLUDED_RULE_TYPES, HASHED_RULE_INDICES,
    and EXCLUDE_CHILDRENS_FROM_RULE are all read fresh on every
    Normalize()/PruneAndHash() call via csimx/utils.py's get_* dispatcher
    functions (each does `from .python.utils import X` INSIDE the function
    body), so reassigning utils_mod.X to a brand new object is safely picked
    up immediately -- that's what this function does for those four.

    COLLAPSED_RULE_INDICES is different: Visitors.py imports it ONCE, at
    Visitors.py's own module-load time (`from .python.utils import
    COLLAPSED_RULE_INDICES as PYTHON_COLLAPSED_RULES`), and checks that name
    directly in visit() -- completely bypassing the get_* dispatcher.
    Reassigning utils_mod.COLLAPSED_RULE_INDICES to a new set therefore does
    NOTHING to what Visitors.py actually checks; it silently keeps testing
    against the ORIGINAL pristine set no matter what override was
    requested, which would make every collapsed_rule strategy result read
    as "no measurable difference" regardless of the real answer. The fix is
    to mutate the SAME set object in place (clear + update) instead of
    replacing it, since Visitors.py's PYTHON_COLLAPSED_RULES and this
    module's COLLAPSED_RULE_INDICES are, before any reassignment, aliases
    to that one shared object -- in-place mutation is visible through both
    names, reassignment only through one of them.
    """
    tokens = set(pristine["EXCLUDED_TOKEN_TYPES"])
    rules_excluded = set(pristine["EXCLUDED_RULE_TYPES"])
    collapsed = set(pristine["COLLAPSED_RULE_INDICES"])
    hashed = set(pristine["HASHED_RULE_INDICES"])
    children = {k: list(v) for k, v in pristine["EXCLUDE_CHILDRENS_FROM_RULE"].items()}

    for op, id_ in overrides.get("EXCLUDED_TOKEN_TYPES", []):
        (tokens.add if op == "add" else tokens.discard)(id_)
    for op, id_ in overrides.get("EXCLUDED_RULE_TYPES", []):
        (rules_excluded.add if op == "add" else rules_excluded.discard)(id_)
    for op, id_ in overrides.get("COLLAPSED_RULE_INDICES", []):
        (collapsed.add if op == "add" else collapsed.discard)(id_)
    for op, id_ in overrides.get("HASHED_RULE_INDICES", []):
        (hashed.add if op == "add" else hashed.discard)(id_)
    for op, rule_id, child_label in overrides.get("EXCLUDE_CHILDRENS_FROM_RULE", []):
        existing = children.setdefault(rule_id, [])
        if op == "add" and child_label not in existing:
            existing.append(child_label)
        elif op == "remove" and child_label in existing:
            existing.remove(child_label)

    utils_mod.EXCLUDED_TOKEN_TYPES = tokens
    utils_mod.EXCLUDED_RULE_TYPES = rules_excluded
    # In place on purpose -- see the docstring above. Do NOT change this to
    # `utils_mod.COLLAPSED_RULE_INDICES = collapsed`.
    utils_mod.COLLAPSED_RULE_INDICES.clear()
    utils_mod.COLLAPSED_RULE_INDICES.update(collapsed)
    utils_mod.HASHED_RULE_INDICES = hashed
    utils_mod.EXCLUDE_CHILDRENS_FROM_RULE = children


def raw_tree_contains(node, kind, target_id):
    """Walk the RAW (pre-normalization) ANTLR tree to check whether a given
    rule index or token type actually appears in this file -- checked
    against the raw tree so it's independent of whatever the CURRENT
    pristine config already excludes/collapses/hashes.
    """
    from antlr4 import TerminalNode

    if isinstance(node, TerminalNode):
        if kind == "token":
            return node.symbol.type == target_id
        return False
    if kind == "rule" and node.getRuleIndex() == target_id:
        return True
    for child in node.getChildren():
        if raw_tree_contains(child, kind, target_id):
            return True
    return False


def tree_hash(tree):
    return hashlib.sha256(json.dumps(tree).encode("utf-8")).hexdigest()


def parse_file(path, lang):
    from csimx.language.parser import ANTLR_parse

    with open(path, "r", encoding="utf-8", errors="strict") as f:
        content = f.read()
    return ANTLR_parse(path, content, lang)


def measure(raw_tree, lang):
    """Normalize + PruneAndHash the cached raw tree under WHATEVER config is
    currently assigned to the language's utils module (caller is
    responsible for calling apply_config() first). Returns (node_count,
    tree_hash).
    """
    from csimx.processing.tree_processing import Normalize, PruneAndHash

    normalized = Normalize(raw_tree, lang)
    pruned, count = PruneAndHash(normalized, lang)
    return count, tree_hash(pruned)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang", required=True, choices=sorted(LANG_UTILS_MODULE))
    ap.add_argument("--round-file", required=True, help="Output of sample_round.py.")
    ap.add_argument("--candidates", help="Path to candidates.json. Omit to only run the baseline benchmark.")
    ap.add_argument("--regression-check", action="store_true",
                     help="Also leave-one-out test every already-classified entry against "
                          "cross-pairs that turn out to be suspiciously identical under baseline.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.round_file) as f:
        round_data = json.load(f)
    candidates = {"tokens": [], "rules": [], "exclude_children": []}
    if args.candidates:
        with open(args.candidates) as f:
            candidates = json.load(f)

    utils_mod = importlib.import_module(LANG_UTILS_MODULE[args.lang])
    pristine = snapshot_pristine(utils_mod)

    # --- Parse everything once, cache raw trees ---
    files = round_data["files"]
    raw_trees = {}
    parse_failures = []
    for entry in files:
        try:
            raw_trees[entry["absolute_path"]] = parse_file(entry["absolute_path"], args.lang)
        except Exception as e:
            parse_failures.append({"path": entry["absolute_path"], "error": str(e)})

    cross_pairs = round_data.get("cross_pairs", [])
    cross_raw = {}
    valid_cross_pairs = []
    for pair in cross_pairs:
        try:
            if pair["file_a"] not in cross_raw:
                cross_raw[pair["file_a"]] = parse_file(pair["file_a"], args.lang)
            if pair["file_b"] not in cross_raw:
                cross_raw[pair["file_b"]] = parse_file(pair["file_b"], args.lang)
            valid_cross_pairs.append(pair)
        except Exception as e:
            parse_failures.append({"path": f"{pair['file_a']} / {pair['file_b']}", "error": str(e)})

    # --- Baseline pass (pristine config, no overrides) ---
    apply_config(utils_mod, pristine, {})
    baseline_counts = {}
    baseline_hashes = {}
    for path, tree in raw_trees.items():
        count, h = measure(tree, args.lang)
        baseline_counts[path] = count
        baseline_hashes[path] = h

    baseline_cross_hashes = {}
    for path, tree in cross_raw.items():
        _, h = measure(tree, args.lang)
        baseline_cross_hashes[path] = h

    already_identical_pairs = [
        p for p in valid_cross_pairs
        if baseline_cross_hashes.get(p["file_a"]) == baseline_cross_hashes.get(p["file_b"])
    ]

    avg_baseline = sum(baseline_counts.values()) / len(baseline_counts) if baseline_counts else 0

    result = {
        "round": round_data.get("round"),
        "lang": args.lang,
        "sample_size": len(files),
        "parse_failures": parse_failures,
        "baseline": {
            "avg_node_count": round(avg_baseline, 1),
            "files_measured": len(baseline_counts),
            "cross_pairs_tested": len(valid_cross_pairs),
            "cross_pairs_already_identical": [
                {"problem_a": p["problem_a"], "problem_b": p["problem_b"]}
                for p in already_identical_pairs
            ],
        },
        "candidates": [],
        "regression_candidates": [],
    }

    # --- Candidate sweep ---
    def eval_candidate(kind, id_, name, strategy, override_key, id_to_add):
        # override_key is one of the four *_TYPES/*_INDICES set names;
        # apply_config expects a list of ("add"|"remove", id) tuples for
        # those (EXCLUDE_CHILDRENS_FROM_RULE, a dict, is handled by its own
        # dedicated block below instead of going through this helper).
        overrides = {override_key: [("add", id_to_add)]}
        apply_config(utils_mod, pristine, overrides)

        relevant_paths = [
            path for path, tree in raw_trees.items()
            if raw_tree_contains(tree, kind, id_)
        ]
        if relevant_paths:
            reductions = []
            for path in relevant_paths:
                new_count, _ = measure(raw_trees[path], args.lang)
                before = baseline_counts[path]
                if before > 0:
                    reductions.append((before - new_count) / before)
            avg_reduction = sum(reductions) / len(reductions) if reductions else 0.0
        else:
            avg_reduction = None

        newly_collapsed = []
        for p in valid_cross_pairs:
            _, ha = measure(cross_raw[p["file_a"]], args.lang)
            _, hb = measure(cross_raw[p["file_b"]], args.lang)
            was_same = baseline_cross_hashes.get(p["file_a"]) == baseline_cross_hashes.get(p["file_b"])
            now_same = ha == hb
            if now_same and not was_same:
                newly_collapsed.append({"problem_a": p["problem_a"], "problem_b": p["problem_b"]})

        result["candidates"].append({
            "kind": kind,
            "id": id_,
            "name": name,
            "strategy": strategy,
            "relevant_files": len(relevant_paths),
            "sample_size": len(files),
            "avg_reduction_pct": None if avg_reduction is None else round(avg_reduction * 100, 1),
            "cross_pairs_newly_collapsed": newly_collapsed,
            "safe": len(newly_collapsed) == 0,
        })

    for tok in candidates.get("tokens", []):
        eval_candidate("token", tok["id"], tok.get("name", str(tok["id"])),
                        "excluded_token", "EXCLUDED_TOKEN_TYPES", tok["id"])

    for rule in candidates.get("rules", []):
        strategies = rule.get("strategies", ["excluded_rule", "collapsed_rule", "hashed_rule"])
        knob_by_strategy = {
            "excluded_rule": "EXCLUDED_RULE_TYPES",
            "collapsed_rule": "COLLAPSED_RULE_INDICES",
            "hashed_rule": "HASHED_RULE_INDICES",
        }
        for strategy in strategies:
            eval_candidate("rule", rule["id"], rule.get("name", str(rule["id"])),
                            strategy, knob_by_strategy[strategy], rule["id"])

    for ec in candidates.get("exclude_children", []):
        overrides = {"EXCLUDE_CHILDRENS_FROM_RULE": [("add", ec["rule_id"], ec["child_label"])]}
        apply_config(utils_mod, pristine, overrides)
        relevant_paths = [
            path for path, tree in raw_trees.items()
            if raw_tree_contains(tree, "rule", ec["rule_id"])
        ]
        reductions = []
        for path in relevant_paths:
            new_count, _ = measure(raw_trees[path], args.lang)
            before = baseline_counts[path]
            if before > 0:
                reductions.append((before - new_count) / before)
        avg_reduction = sum(reductions) / len(reductions) if reductions else None
        result["candidates"].append({
            "kind": "exclude_children", "id": ec["rule_id"],
            "name": ec.get("rule_name", str(ec["rule_id"])), "strategy": "exclude_children",
            "child_label": ec["child_label"], "child_name": ec.get("child_name"),
            "relevant_files": len(relevant_paths), "sample_size": len(files),
            "avg_reduction_pct": None if avg_reduction is None else round(avg_reduction * 100, 1),
            "cross_pairs_newly_collapsed": [], "safe": True,
        })

    # --- Regression check (leave-one-out), only if requested AND there's
    # something suspicious in the baseline to investigate ---
    if args.regression_check:
        if not already_identical_pairs:
            result["regression_note"] = (
                "No cross-problem pairs collapsed to identical trees under the current "
                "config -- nothing to attribute, leave-one-out skipped this round."
            )
        else:
            def eval_removal(set_name, id_, extra=None):
                if set_name == "EXCLUDE_CHILDRENS_FROM_RULE":
                    overrides = {set_name: [("remove", extra[0], extra[1])]}
                else:
                    overrides = {set_name: [("remove", id_)]}
                apply_config(utils_mod, pristine, overrides)
                triggers = []
                for p in already_identical_pairs:
                    _, ha = measure(cross_raw[p["file_a"]], args.lang)
                    _, hb = measure(cross_raw[p["file_b"]], args.lang)
                    if ha != hb:
                        triggers.append({"problem_a": p["problem_a"], "problem_b": p["problem_b"]})
                if triggers:
                    result["regression_candidates"].append({
                        "set": set_name, "id": id_, "extra": extra, "triggers_pairs": triggers,
                    })

            for id_ in pristine["EXCLUDED_TOKEN_TYPES"]:
                eval_removal("EXCLUDED_TOKEN_TYPES", id_)
            for id_ in pristine["EXCLUDED_RULE_TYPES"]:
                eval_removal("EXCLUDED_RULE_TYPES", id_)
            for id_ in pristine["COLLAPSED_RULE_INDICES"]:
                eval_removal("COLLAPSED_RULE_INDICES", id_)
            for id_ in pristine["HASHED_RULE_INDICES"]:
                eval_removal("HASHED_RULE_INDICES", id_)
            for rule_id, child_labels in pristine["EXCLUDE_CHILDRENS_FROM_RULE"].items():
                for child_label in child_labels:
                    eval_removal("EXCLUDE_CHILDRENS_FROM_RULE", rule_id, extra=(rule_id, child_label))

    # Always leave the module's live config back at pristine when this
    # process is about to exit (harmless since the process exits anyway,
    # but keeps behavior obviously correct if this is ever imported instead
    # of run as a script).
    apply_config(utils_mod, pristine, {})

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "round": result["round"],
        "sample_size": result["sample_size"],
        "baseline_avg_node_count": result["baseline"]["avg_node_count"],
        "cross_pairs_already_identical": len(result["baseline"]["cross_pairs_already_identical"]),
        "candidates_evaluated": len(result["candidates"]),
        "regression_candidates_found": len(result["regression_candidates"]),
        "parse_failures": len(parse_failures),
        "out": args.out,
    }, indent=2))


if __name__ == "__main__":
    main()
