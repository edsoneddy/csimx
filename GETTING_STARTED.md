# Getting Started with csimx

This guide will help you get started with csimx in just a few minutes.

## Installation

### From PyPI (Recommended)

```bash
pip install csimx
```

### From Source

```bash
git clone https://github.com/EdsonEddy/csimx.git
cd csimx
pip install .
```

## Quick Start

### 1. Generate a Similarity Report

The simplest way to get started is to generate a report comparing all files in a directory:

```bash
csimx report --path ./my_assignments
```

**Output:**
```
file1.py is similar to file2.py with similarity index: 0.92
file1.py is similar to file3.py with similarity index: 0.45
file2.py is similar to file3.py with similarity index: 0.50
```

This tells you which files are most similar to each other.

### 2. Group Similar Files

To automatically cluster files into groups of similar submissions:

```bash
csimx group --path ./my_assignments --threshold 0.8
```

**Output:**
```
Threshold: 0.8
Total files processed: 3
Group 1 (Average Similarity: 0.92):
./file1.py
./file2.py

Unique Files (similarity below threshold):
./file3.py
```

This groups `file1.py` and `file2.py` together (92% similar), and marks `file3.py` as unique.

### 3. Choose a Search Strategy

For small datasets (< 100 files), the default exhaustive search is fine and guarantees finding all copies:

```bash
csimx group --path ./small_dataset --threshold 0.8
```

**Note:** Exhaustive search is O(n²) and may be slow on large datasets.

---

## Common Use Cases

### Use Case 1: Detect Plagiarism in Programming Assignments

You have 30 Python 3.13 submissions for a programming assignment:

```bash
# Generate a report to see all similarities
csimx report --path ./submissions/assignment1

# Group them to identify suspicious pairs
csimx group --path ./submissions/assignment1 --threshold 0.85
```

**Interpretation:**
- Threshold 0.85 means files need to be 85% structurally similar to be grouped together
- This is intentionally high to minimize false positives
- Review the grouped files manually

### Use Case 2: Quick Duplicate Detection

You have many code files and want to find exact or near-exact duplicates:

```bash
# Threshold 0.95 = nearly identical
csimx group --path ./codebase --threshold 0.95
```

### Use Case 3: Code Quality Check

Find copy-pasted functions or redundant code in a codebase:

```bash
# Threshold 0.80 = significantly similar (possible refactoring opportunity)
csimx group --path ./src --threshold 0.80 --lang java_20
```

---

## Understanding Thresholds

The `--threshold` parameter determines how similar files must be to be considered a match.

| Threshold | Meaning | Use Case |
|-----------|---------|----------|
| **0.95+** | Nearly identical | Finding exact duplicates |
| **0.85-0.95** | Very similar | Plagiarism detection |
| **0.70-0.85** | Moderately similar | Code review / refactoring suggestions |
| **<0.70** | Somewhat similar | Finding conceptually similar code |

**Recommendation:** Start with 0.85 for plagiarism detection and adjust based on results.

---

## Supported Languages

csimx supports seven programming language configurations:

### Python 3.13
```bash
csimx report --path ./python_files --lang python_3_13
```

### Python 3 (universal grammar, faster)
```bash
csimx report --path ./python_files --lang python_3
```
Same `.py` files as `python_3_13`, parsed with a grammar that has a native C++
target (see `csimx info`). Grouping output matches `python_3_13` on real code;
does not parse positional-only params (`/`), walrus (`:=`), or `match`/`case` --
csimx falls back to `python_3_13` automatically for those files.

### Java 20
```bash
csimx report --path ./java_files --lang java_20
```

### Java 24 (experimental — parsing only)
```bash
csimx report --path ./java_files --lang java_24
```
Same `.java` files as `java_20`, parsed with an optimized grammar that's much
faster when the native C++ parser is built (see `csimx info`). **Not yet
recommended for `group`/`report`**: its similarity output hasn't been tuned to
match `java_20` and can under-report similarity on real code. Use `java_20`
for actual comparisons for now.

### C++14
```bash
csimx report --path ./cpp_files --lang cpp_14
```

### Kotlin (experimental — new language, untuned)
```bash
csimx report --path ./kotlin_files --lang kotlin
```
A fully new language for csimx, not just a native accelerator for an existing
one: both the pure-Python parser and a native C++ parser (no base class
needed) are new. Unlike the other languages here, there's no real Kotlin
corpus in this project's benchmark set to tune grouping precision against
yet — treat `group`/`report` results as a reasonable starting point, not a
tuned config.

### C (experimental — new language, untuned)
```bash
csimx report --path ./c_files --lang c
```
Also a fully new language (pure-Python parser + native C++ parser, this one
backed by a real symbol table for typedef disambiguation). Always runs with
preprocessing disabled — `#include`/`#define`/etc. lines are swallowed as
hidden tokens rather than expanded, so macro-dependent code (token-pasting
tricks, macros used for control flow) can parse differently than a real
compiler would see it. Real submissions essentially never rely on that, but
it's a known limitation. Same "no tuning corpus yet" caveat as Kotlin.

---

## Advanced Options

### Change Tree Edit Distance Algorithm

By default, csimx uses the `apted` algorithm. You can switch to `zss`:

```bash
csimx group --path ./files --threshold 0.8 --talg zss
```

Both algorithms compute the same tree edit distance; `apted` is the default.

### Combine Options

```bash
# Large Java 20 assignment dataset (exhaustive search with zss algorithm)
csimx group --path ./java_submissions \
  --threshold 0.8 \
  --strategy exhaustive \
  --lang java_20 \
  --talg zss
```

---

## Using csimx as a Python Library

For programmatic access, import csimx functions directly:

```python
from csimx.utils import report_pairwise_similarity

# Your file data
file_names = ["file1.py", "file2.py", "file3.py"]
file_contents = [
    "a = 5\nprint(a)",
    "b = 10\nprint(b)", 
    "import os\nprint('hello')"
]

# Get similarity report
results = report_pairwise_similarity(
    file_names=file_names,
    file_contents=file_contents,
    lang="python_3_13",
    ted_algorithm="apted"
)

print(results)
```

---

## Troubleshooting

### Issue: "No files found"

```bash
csimx report --path ./my_directory
```

**Solution:** Make sure the directory contains files with the correct extension (`.py` for Python 3.13, `.java` for Java 20, `.cpp` for C++14).

### Issue: Command not found

```bash
csimx: command not found
```

**Solution:** Make sure csimx is installed:
```bash
pip install csimx
```

Or if installed from source, use:
```bash
python -m csimx report --path ./files
```

### Issue: Slow performance on large datasets

```bash
# If you ran this and it's slow:
csimx group --path ./1000_files --threshold 0.8 --strategy exhaustive
```

---

## Next Steps

- **Read the full documentation:** See [README.md](README.md)
- **Understand strategies:** Read [docs/STRATEGIES.md](docs/STRATEGIES.md) for detailed comparison
- **Report issues:** Visit [GitHub Issues](https://github.com/EdsonEddy/csimx/issues)

---

## Getting Help

- **Questions?** Open a GitHub Discussion
- **Found a bug?** Open a GitHub Issue
- **Want to contribute?** See [README.md](README.md#contributing) for guidelines

Happy plagiarism detection! 🔍
