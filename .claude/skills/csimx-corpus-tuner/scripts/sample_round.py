#!/usr/bin/env python3
"""
Draw one round of a stratified, cumulative sample from a corpus manifest
(built by build_manifest.py), for the csimx-corpus-tuner adaptive LOOP.

Two things per round:

1. The round's file sample -- stratified by problem (capped per problem so
   one huge problem folder can't dominate a round and skew statistics),
   drawn only from files not already used in a previous round (state is
   persisted in --state, so repeated calls accumulate rather than
   overlapping -- that's what makes "round 2" a genuinely bigger sample
   than "round 1", not just a different one).

2. A batch of cross-problem pairs -- two files from two DIFFERENT problem
   folders, paired up. Since every problem in a judge dataset is a
   different task, any cross-problem pair is a legitimate "these two are
   algorithmically different" example for free, without hand-writing one.
   These are what run_round.py's distinctiveness/regression checks use;
   they're drawn fresh each round (not tracked in the "used" state) since
   their job is just to be *some* honest pair of different problems, not to
   contribute unique coverage the way the main sample does.

Usage:
    python sample_round.py --manifest manifest_python.json \\
        --state sampling_state_python.json \\
        --round-size 300 --per-problem-cap 5 --cross-pairs 10

Prints one JSON object to stdout describing the round; also updates --state
so the next call continues from where this one left off. Use --reset to
discard state and start over (e.g. after the manifest changes).
"""
import argparse
import json
import os
import random
import re


def load_state(state_path):
    if os.path.exists(state_path):
        with open(state_path) as f:
            return json.load(f)
    return {"round": 0, "used_files": [], "manifest_signature": None}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--round-size", type=int, default=300)
    ap.add_argument("--per-problem-cap", type=int, default=5,
                     help="Max files drawn from a single problem folder in this round.")
    ap.add_argument("--cross-pairs", type=int, default=10,
                     help="Number of cross-problem (different-problem) file pairs to draw.")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--reset", action="store_true", help="Ignore/overwrite existing state.")
    ap.add_argument(
        "--keyword-regex", default=None,
        help="Restrict the sampling pool to files whose CONTENT matches this regex "
             "before drawing the round -- for validating a rare construct (e.g. "
             r"'\bdel\b' for del statements) efficiently instead of waiting for it to "
             "show up by chance in a large random sample. Applied fresh each round "
             "(not tracked/cached), since it's cheap text search, no ANTLR involved. "
             "Cross-pairs are NOT filtered by this -- they're still drawn from the "
             "full corpus, since their job is to be an honest 'different problem' "
             "pair, not to contain the keyword.",
    )
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    with open(args.manifest) as f:
        manifest = json.load(f)

    state = {"round": 0, "used_files": [], "manifest_signature": None} if args.reset else load_state(args.state)

    if state["manifest_signature"] not in (None, manifest["corpus_signature"]):
        print(
            "WARNING: manifest has changed since this sampling state was created "
            "(corpus_signature mismatch). Consider --reset so the used-file "
            "tracking doesn't reference a stale manifest.",
        )
    state["manifest_signature"] = manifest["corpus_signature"]

    used = set(state["used_files"])
    corpus_root = manifest["corpus_root"]
    problems = manifest["problems"]

    # Build the available pool: {problem_id: [relative_path, ...]}, valid
    # files only, excluding anything already used in a prior round.
    pool = {}
    for problem_id, bucket in problems.items():
        remaining = [p for p in bucket["valid"] if p not in used]
        if remaining:
            pool[problem_id] = remaining

    keyword_pattern = re.compile(args.keyword_regex) if args.keyword_regex else None
    keyword_matched_count = None
    if keyword_pattern is not None:
        # Cheap text search, no ANTLR -- filters the pool down to files that
        # are actually worth spending a parse on for a rare-construct
        # validation run. This is a plain content grep, not a token/rule
        # check, so it can have false positives (e.g. the word "del" inside
        # a string literal or comment) -- run_round.py's own
        # raw_tree_contains() check on the parsed tree is still what
        # ultimately decides whether a file is "relevant" for a candidate;
        # this filter's only job is to raise the hit rate before parsing.
        filtered_pool = {}
        keyword_matched_count = 0
        for problem_id, rel_paths in pool.items():
            matches = []
            for rel_path in rel_paths:
                abs_path = os.path.join(corpus_root, rel_path)
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue
                if keyword_pattern.search(content):
                    matches.append(rel_path)
            if matches:
                filtered_pool[problem_id] = matches
                keyword_matched_count += len(matches)
        pool = filtered_pool

    if not pool:
        reason = (
            f"No unused files matched --keyword-regex {args.keyword_regex!r}."
            if keyword_pattern is not None
            else "Corpus exhausted -- no unused valid files remain."
        )
        print(json.dumps({"error": reason, "round": state["round"]}))
        return

    # Stratified draw: shuffle problem order, then draw up to
    # per_problem_cap files from each in turn, round-robin, until we hit
    # round_size or run out of problems -- this spreads the sample across
    # as many different problems as possible before doubling up on any one.
    problem_ids = list(pool.keys())
    random.shuffle(problem_ids)
    for problem_id in problem_ids:
        random.shuffle(pool[problem_id])

    sample = []
    cursor = {pid: 0 for pid in problem_ids}
    progress = True
    while len(sample) < args.round_size and progress:
        progress = False
        for problem_id in problem_ids:
            if len(sample) >= args.round_size:
                break
            files = pool[problem_id]
            taken_from_this_problem = sum(1 for s in sample if s["problem_id"] == problem_id)
            if taken_from_this_problem >= args.per_problem_cap:
                continue
            if cursor[problem_id] >= len(files):
                continue
            rel_path = files[cursor[problem_id]]
            cursor[problem_id] += 1
            sample.append({
                "problem_id": problem_id,
                "relative_path": rel_path,
                "absolute_path": os.path.join(corpus_root, rel_path),
            })
            progress = True

    # Cross-problem pairs: pick two DIFFERENT problem IDs (with >=1 valid
    # file each in the full manifest, not just the round's sample -- more
    # variety than restricting to this round's draw) and one random file
    # from each.
    all_problem_ids = [pid for pid, b in problems.items() if b["valid"]]
    cross_pairs = []
    attempts = 0
    while len(cross_pairs) < args.cross_pairs and attempts < args.cross_pairs * 20 and len(all_problem_ids) >= 2:
        attempts += 1
        pid_a, pid_b = random.sample(all_problem_ids, 2)
        file_a = random.choice(problems[pid_a]["valid"])
        file_b = random.choice(problems[pid_b]["valid"])
        cross_pairs.append({
            "problem_a": pid_a,
            "file_a": os.path.join(corpus_root, file_a),
            "problem_b": pid_b,
            "file_b": os.path.join(corpus_root, file_b),
        })

    state["round"] += 1
    state["used_files"] = sorted(used | {s["relative_path"] for s in sample})

    with open(args.state, "w") as f:
        json.dump(state, f, indent=2)

    result = {
        "round": state["round"],
        "lang": manifest["lang"],
        "sample_size": len(sample),
        "cumulative_files_used": len(state["used_files"]),
        "corpus_total_valid_files": manifest["summary"]["valid"],
        "keyword_regex": args.keyword_regex,
        "keyword_matched_files_available": keyword_matched_count,
        "files": sample,
        "cross_pairs": cross_pairs,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
