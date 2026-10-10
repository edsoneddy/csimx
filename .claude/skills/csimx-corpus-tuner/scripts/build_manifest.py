#!/usr/bin/env python3
"""Scan a real code corpus (<corpus_root>/<problem_id>/<submission>.<ext>) and build a manifest of
the files ANTLR parses cleanly for a csimx language.

ANTLR reports syntax errors through a listener instead of raising, so a clean parse is decided by
counting syntaxError() calls. The scan is the expensive part: rerun it only when the corpus changes.
sample_round.py and run_round.py read the manifest.

Usage:
    python build_manifest.py --lang python_3 --corpus-root /path/to/all_py --out manifest_python_3.json
"""
import argparse
import hashlib
import importlib
import json
import os
import time

from antlr4.error.ErrorListener import ErrorListener
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from langs import LANG_PARSE_CONFIG, EXTENSION_BY_LANG



class CountingErrorListener(ErrorListener):
    """Counts syntaxError() calls; attach the SAME instance to lexer and parser.
    It must subclass ErrorListener: the parser calls reportAmbiguity & co. on valid files too,
    and a bare object would raise AttributeError and be misread as a parse failure."""

    def __init__(self):
        self.count = 0
        self.messages = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.count += 1
        if len(self.messages) < 5:
            self.messages.append(f"line {line}:{column} {msg}")


def try_parse(file_path, lang):
    """Returns (is_valid, error_messages)."""
    from antlr4 import InputStream, CommonTokenStream

    cfg = LANG_PARSE_CONFIG[lang]
    lexer_mod = importlib.import_module(cfg["lexer_module"])
    parser_mod = importlib.import_module(cfg["parser_module"])
    LexerClass = getattr(lexer_mod, cfg["lexer_class"])
    ParserClass = getattr(parser_mod, cfg["parser_class"])

    try:
        with open(file_path, "r", encoding="utf-8", errors="strict") as f:
            content = f.read()
    except Exception as e:
        return False, [f"read-error: {e}"]

    listener = CountingErrorListener()
    try:
        input_stream = InputStream(content)
        lexer = LexerClass(input_stream)
        lexer.removeErrorListeners()
        lexer.addErrorListener(listener)
        token_stream = CommonTokenStream(lexer)
        parser = ParserClass(token_stream)
        parser.removeErrorListeners()
        parser.addErrorListener(listener)
        getattr(parser, cfg["entry_rule"])()
    except Exception as e:
        return False, [f"exception: {e}"]

    if listener.count > 0:
        return False, listener.messages
    return True, []


def corpus_signature(files):
    """Cheap fingerprint of the corpus so downstream tools (and you) can
    tell whether a manifest is stale: sorted (relative path, size, mtime)
    tuples, hashed. Doesn't need to be cryptographically strong, just
    sensitive to files being added/removed/modified.
    """
    h = hashlib.sha256()
    for rel_path, abs_path in sorted(files):
        try:
            st = os.stat(abs_path)
            h.update(f"{rel_path}|{st.st_size}|{int(st.st_mtime)}\n".encode("utf-8"))
        except OSError:
            h.update(f"{rel_path}|MISSING\n".encode("utf-8"))
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang", required=True, choices=sorted(LANG_PARSE_CONFIG))
    ap.add_argument(
        "--corpus-root", required=True,
        help="Root directory. Immediate subdirectories are treated as problem "
             "IDs; files directly under the root (no subdirectory) are grouped "
             "under the '_ungrouped' problem ID.",
    )
    ap.add_argument("--out", required=True, help="Path to write the manifest JSON to.")
    args = ap.parse_args()

    ext = EXTENSION_BY_LANG[args.lang]
    corpus_root = os.path.abspath(args.corpus_root)

    all_files = []  # (problem_id, relative_path, absolute_path)
    for dirpath, dirnames, filenames in os.walk(corpus_root):
        rel_dir = os.path.relpath(dirpath, corpus_root)
        problem_id = rel_dir.split(os.sep)[0] if rel_dir != "." else "_ungrouped"
        for fn in filenames:
            if not fn.endswith(ext):
                continue
            abs_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(abs_path, corpus_root)
            all_files.append((problem_id, rel_path, abs_path))

    signature = corpus_signature([(rel, abs_) for _, rel, abs_ in all_files])

    problems = {}
    total_valid = 0
    total_invalid = 0
    t0 = time.time()
    for i, (problem_id, rel_path, abs_path) in enumerate(all_files):
        is_valid, messages = try_parse(abs_path, args.lang)
        bucket = problems.setdefault(problem_id, {"valid": [], "invalid": []})
        if is_valid:
            bucket["valid"].append(rel_path)
            total_valid += 1
        else:
            bucket["invalid"].append({"path": rel_path, "reason": messages[:1]})
            total_invalid += 1
        if (i + 1) % 500 == 0:
            print(f"  scanned {i + 1}/{len(all_files)} files...", flush=True)

    manifest = {
        "lang": args.lang,
        "corpus_root": corpus_root,
        "extension": ext,
        "corpus_signature": signature,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scan_seconds": round(time.time() - t0, 1),
        "summary": {
            "problems": len(problems),
            "total_files": len(all_files),
            "valid": total_valid,
            "invalid": total_invalid,
        },
        "problems": problems,
    }

    with open(args.out, "w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps(manifest["summary"], indent=2))
    print(f"\nManifest written to {args.out}")
    if total_invalid:
        print(
            f"{total_invalid} file(s) failed to parse cleanly and were excluded "
            f"-- see the 'invalid' list per problem in the manifest for reasons."
        )


if __name__ == "__main__":
    main()
