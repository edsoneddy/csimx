#!/usr/bin/env python3
"""
Enumerate ANTLR-generated tokens and rules for a csim-supported language, and
classify each one against the compression dictionaries/sets already defined
in csimx/<lang>/utils.py.

This must run in an environment where csim is importable (e.g. `pip install -e .`
was run in the csim repo, per its CLAUDE.md).

Usage:
    python enumerate_candidates.py --lang cpp
    python enumerate_candidates.py --lang java --json java_candidates.json

Output (stdout, JSON):
{
  "lang": "cpp",
  "tokens": [
    {"id": 5, "name": "Comma", "classified_as": []},
    ...
  ],
  "rules": [
    {"id": 0, "name": "translationUnit", "classified_as": []},
    {"id": 3, "name": "ifStatement", "classified_as": ["HASHED_RULE_INDICES"]},
    ...
  ]
}

A rule/token with an empty "classified_as" list has never been evaluated for
any compression strategy in this language's utils.py -- it is a genuine
candidate for the csimx-tree-compressor LOOP described in SKILL.md.

Items that already have entries are included too (for context / auditing),
but the LOOP should normally skip them -- unless you are deliberately
re-testing whether a smarter strategy exists for something already
classified (e.g. an EXCLUDED_RULE_TYPES entry that might do better as
HASHED_RULE_INDICES instead). That kind of re-evaluation is a judgment call,
not something this script decides for you.
"""
import argparse
import importlib
import json
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from langs import LANG_MODULES




def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang", required=True, choices=sorted(LANG_MODULES))
    ap.add_argument("--json", help="Optional path to also write the JSON to a file.")
    args = ap.parse_args()

    cfg = LANG_MODULES[args.lang]

    lexer_mod = importlib.import_module(cfg["lexer_module"])
    parser_mod = importlib.import_module(cfg["parser_module"])
    utils_mod = importlib.import_module(cfg["utils_module"])

    Lexer = getattr(lexer_mod, cfg["lexer_class"])
    Parser = getattr(parser_mod, cfg["parser_class"])

    excluded_tokens = getattr(utils_mod, "EXCLUDED_TOKEN_TYPES", set())
    excluded_rules = getattr(utils_mod, "EXCLUDED_RULE_TYPES", set())
    collapsed_rules = getattr(utils_mod, "COLLAPSED_RULE_INDICES", set())
    hashed_rules = getattr(utils_mod, "HASHED_RULE_INDICES", set())
    exclude_children = getattr(utils_mod, "EXCLUDE_CHILDRENS_FROM_RULE", dict())
    control_equiv = getattr(utils_mod, "CONTROL_EQUIVALENCE_RULE_INDICES", dict())

    tokens = []
    for token_type, name in enumerate(Lexer.symbolicNames):
        if name in (None, "<INVALID>"):
            continue
        classified_as = []
        if token_type in excluded_tokens:
            classified_as.append("EXCLUDED_TOKEN_TYPES")
        tokens.append(
            {"id": token_type, "name": name, "classified_as": classified_as}
        )

    rules = []
    for rule_index, name in enumerate(Parser.ruleNames):
        classified_as = []
        if rule_index in excluded_rules:
            classified_as.append("EXCLUDED_RULE_TYPES")
        if rule_index in collapsed_rules:
            classified_as.append("COLLAPSED_RULE_INDICES")
        if rule_index in hashed_rules:
            classified_as.append("HASHED_RULE_INDICES")
        if rule_index in exclude_children:
            classified_as.append("EXCLUDE_CHILDRENS_FROM_RULE (partial)")
        if rule_index in control_equiv:
            classified_as.append("CONTROL_EQUIVALENCE_RULE_INDICES")
        rules.append({"id": rule_index, "name": name, "classified_as": classified_as})

    out = {"lang": args.lang, "tokens": tokens, "rules": rules}
    text = json.dumps(out, indent=2)
    print(text)
    if args.json:
        with open(args.json, "w") as f:
            f.write(text)


if __name__ == "__main__":
    main()
