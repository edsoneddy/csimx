#!/usr/bin/env python3
"""
Run csim's real Normalize -> PruneAndHash pipeline on one source snippet,
optionally with candidate compression rules added IN MEMORY on top of the
language's actual csimx/<lang>/utils.py config. This never writes to any
file on disk -- run it once per candidate/strategy/snippet as a fresh
subprocess (that's what SKILL.md's LOOP does), and the override only ever
lives for that one process, so there's no risk of overrides leaking into
the real config or into other measurements.

This is the measurement tool behind the csimx-tree-compressor SKILL: it's
how you find out whether adding a token/rule ID to a given dict/set
actually shrinks the tree, and it's what you use to eyeball the resulting
tree for the safety checks described in SKILL.md (collapse trap, hashing a
body-wrapping rule, etc).

Must run in an environment where csim is importable (`pip install -e .` in
the csim repo).

Usage:
    # Baseline (current config, no overrides) -- equivalent to `csim tree`:
    python harness.py --lang cpp --file snippet.cpp --show-tree

    # Test adding rule 12 to EXCLUDED_RULE_TYPES:
    python harness.py --lang cpp --file snippet.cpp --add-excluded-rule 12

    # Test adding rule 30 to COLLAPSED_RULE_INDICES:
    python harness.py --lang cpp --file snippet.cpp --add-collapsed-rule 30

    # Test adding rule 7 to HASHED_RULE_INDICES:
    python harness.py --lang cpp --file snippet.cpp --add-hashed-rule 7

    # Test pruning a specific child (e.g. a COLON token, offset by 1000)
    # from a specific rule's children:
    python harness.py --lang cpp --file snippet.cpp \\
        --add-exclude-children '{"12": [1044]}'

Any --add-* flag may be repeated or combined. With no --add-* flags at all,
this reproduces the CURRENT baseline behavior of `csim tree` for that file
-- always measure baseline first, before any override, so the reduction
percentage means something.

Output: one line of JSON on stdout: {"file", "lang", "node_count"}.
With --show-tree, the human-readable pruned tree is also printed, but to
STDERR (so stdout stays clean, parseable JSON either way).
"""
import argparse
import importlib
import json
import sys
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from langs import LANG_UTILS_MODULE




def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang", required=True, choices=sorted(LANG_UTILS_MODULE))
    ap.add_argument("--file", required=True, help="Path to the source snippet to parse.")
    ap.add_argument(
        "--add-excluded-token", type=int, action="append", default=[],
        help="Token type ID to test adding to EXCLUDED_TOKEN_TYPES.",
    )
    ap.add_argument(
        "--add-excluded-rule", type=int, action="append", default=[],
        help="Rule index to test adding to EXCLUDED_RULE_TYPES.",
    )
    ap.add_argument(
        "--add-collapsed-rule", type=int, action="append", default=[],
        help="Rule index to test adding to COLLAPSED_RULE_INDICES.",
    )
    ap.add_argument(
        "--add-hashed-rule", type=int, action="append", default=[],
        help="Rule index to test adding to HASHED_RULE_INDICES.",
    )
    ap.add_argument(
        "--add-exclude-children", default=None,
        help='JSON object mapping rule id (string key) -> list of child labels to '
             'prune from that rule\'s children, e.g. \'{"12": [1044]}\'. Child labels '
             'use TOKEN_TYPE_OFFSET (1000) + token type for a token child, or the '
             'bare rule index for a rule child -- same convention as '
             'EXCLUDE_CHILDRENS_FROM_RULE in csimx/<lang>/utils.py.',
    )
    ap.add_argument(
        "--show-tree", action="store_true",
        help="Also print the resulting pruned/hashed tree, human-readable, to stderr.",
    )
    ap.add_argument(
        "--show-raw", action="store_true",
        help="Also print the raw (pre-normalization) ANTLR parse tree to stderr, "
             "for side-by-side comparison with --show-tree.",
    )
    return ap.parse_args()


def main():
    args = parse_args()

    from csimx.language.parser import ANTLR_parse
    from csimx.processing.tree_processing import Normalize, PruneAndHash
    from csimx.utils import print_tree, print_antlr_tree

    utils_mod = importlib.import_module(LANG_UTILS_MODULE[args.lang])

    # Mutate the REAL module-level set/dict objects that csimx/utils.py's
    # get_excluded_token_types() etc. return. Those functions do a fresh
    # `from .python.utils import EXCLUDED_TOKEN_TYPES` on every call, but
    # Python's module cache (sys.modules) means that import returns the
    # SAME object we're mutating here -- so this reliably feeds through to
    # Normalize/PruneAndHash without ever touching the file on disk. Since
    # this whole script is meant to be run as a fresh subprocess per
    # measurement, there's nothing to restore afterward.
    utils_mod.EXCLUDED_TOKEN_TYPES.update(args.add_excluded_token)
    utils_mod.EXCLUDED_RULE_TYPES.update(args.add_excluded_rule)
    utils_mod.COLLAPSED_RULE_INDICES.update(args.add_collapsed_rule)
    utils_mod.HASHED_RULE_INDICES.update(args.add_hashed_rule)
    if args.add_exclude_children:
        extra = json.loads(args.add_exclude_children)
        for rule_id_str, child_labels in extra.items():
            rule_id = int(rule_id_str)
            existing = utils_mod.EXCLUDE_CHILDRENS_FROM_RULE.setdefault(rule_id, [])
            for label in child_labels:
                if label not in existing:
                    existing.append(label)

    with open(args.file, "r", encoding="utf-8") as f:
        content = f.read()

    raw_tree = ANTLR_parse(args.file, content, args.lang)

    if args.show_raw:
        print("=== Raw ANTLR Parse Tree ===", file=sys.stderr)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_antlr_tree(raw_tree, args.lang)
        print(buf.getvalue(), file=sys.stderr)

    normalized = Normalize(raw_tree, args.lang)
    pruned_tree, node_count = PruneAndHash(normalized, args.lang)

    result = {"file": args.file, "lang": args.lang, "node_count": node_count}
    print(json.dumps(result))

    if args.show_tree:
        print("=== Normalized + Pruned Tree (with overrides applied) ===", file=sys.stderr)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_tree(pruned_tree, lang=args.lang)
        print(buf.getvalue(), file=sys.stderr)


if __name__ == "__main__":
    main()
