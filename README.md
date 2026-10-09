# Code Similarity (csimx)

Code Similarity (csimx) provide a module designed to detect similarities between source code files, even when obfuscation techniques have been applied. It is particularly useful for programming instructors and students who need to verify code originality.

> **Origin.** csimx started from [csim](https://github.com/EdsonEddy/csim) 4.1.0 and keeps its structural comparison unchanged (same trees, same index). What it adds is a lexical stage that `group` can use to skip pairs of files that are too different. The version history of csim before this fork is in `CHANGELOG.md`; the documents in `docs/` were written for csim and still call the project csim.

## Key Features

- **Source Code Similarity Analysis:** Compares source code files to determine their degree of similarity.
- **Pairwise Reporting:** Generate detailed similarity reports for all file pairs.
- **File Grouping:** Cluster similar files into groups based on a configurable threshold.
- **Flexible Search Strategies:** 
  - **Exhaustive Search:** All-pairs comparison for maximum precision
- **Two Stages:** A fast lexical stage (Pygments tokens + Myers diff) can filter the pairs that `group` sends to the structural stage (parse trees + tree edit distance).
- **Advanced Analysis:** Utilizes parse trees and the tree edit distance algorithm for in-depth analysis.
- **Parse Trees:** Represents the syntactic structure of source code, enabling detailed comparisons.
- **Tree Edit Distance:** Measures the similarity between different code structures.
- **Hash-Based Pruning:** Optimizes the comparison process by reducing tree size while preserving essential structure.
- **Multi-Language Support:** Supports Python 3.13, Python 3 (universal grammar), Java 20, Java 24, C++14, Kotlin (experimental), and C (experimental) source code analysis.

## Technologies Used

- **Python:** The core programming language for the tool.
- **ANTLR:** A parser generator for creating parse trees from source code.
- **apted:** A library for computing the tree edit distance (default algorithm).
- **zss:** A library for calculating the tree edit distance, alternatively to apted.
- **NumPy:** Used for efficient numerical operations.
- **Pygments:** Tokenizer of the lexical stage (one for every supported language).

## Installation
For the installation `pip` is required, you can either clone the repository and install it locally or install it directly from PyPI.

1.  Clone the repository:
    ```sh
    git clone https://github.com/EdsonEddy/csimx.git
    ```
2.  Navigate to the project directory:
    ```sh
    cd csimx
    ```
3.  Install the package:
    ```sh
    pip install .
    ```

Alternatively, you can install it directly from PyPI:

```sh
pip install csimx
```


### Version Compatibility
- **Python:** 3.10–3.12 (recommended 3.11)
- **ANTLR4 Python Runtime:** 4.13.2
- **zss:** 1.2.0
- **apted:** 1.0.3
- **numpy:** 1.26.4

## Quick Start

**New to csimx?** Start here: [GETTING_STARTED.md](GETTING_STARTED.md)

For detailed information about search strategies, see: [docs/STRATEGIES.md](docs/STRATEGIES.md)

csimx supports three main actions: **report** (for pairwise similarity analysis), **group** (for clustering similar files), and **tree**/**view** (for visualizing a file's normalized/pruned parse tree). The tool supports Python 3.13, Python 3, Java 20, Java 24, C++14, Kotlin (experimental), and C (experimental) source code files.

### General Command Structure
```sh
csimx <action> --path <directory> [options]
```

### Action 1: `report` - Generate Similarity Report

Generates a pairwise similarity report comparing all files in a directory.

```sh
csimx report --path /path/to/directory
```

**Example Output:**
```
file1.py is similar to file2.py with similarity index: 0.95
file1.py is similar to file3.py with similarity index: 0.45
file2.py is similar to file3.py with similarity index: 0.50
```

**Options:**
- `--lang, -l`: Programming language (default: `python_3_13`). Options: `python_3_13`, `python_3`, `java_20`, `java_24`, `cpp_14`, `kotlin`, `c`
- `--talg, -ta`: Tree edit distance algorithm (default: `apted`). Options: `zss`, `apted`
- `--index, -ix`: Similarity index formula (default: `legacy`). Options: `legacy`, `ratio`, `metric`

**Example with options:**
```sh
csimx report --path /path/to/directory --lang java_20 --talg zss --index ratio
```

### Action 2: `group` - Group Files by Similarity

Groups files by similarity using a specified threshold and strategy.

```sh
csimx group --path /path/to/directory --threshold 0.8
```

**Example Output:**
```
Threshold: 0.8
Total files processed: 4
Group 1 (Average Similarity: 0.98):
./file1.py
./file2.py
Group 2 (Average Similarity: 0.95):
./file3.py
./file4.py
```

#### Strategy Options

The `group` action supports two strategies for finding similar files:

##### 1. **exhaustive** (Default)
Compares every file against every other file (O(n²)). This is the most thorough approach but slower for large datasets.

```sh
csimx group --path /path/to/directory --threshold 0.8 --strategy exhaustive
```

**When to use each:**
- **exhaustive**: Small datasets (< 100 files), when maximum precision is critical

#### Group Action Options

- `--threshold, -t`: Similarity threshold (0.0 to 1.0). **Required.**
- `--strategy, -s`: Grouping strategy (default: `exhaustive`). Options: `exhaustive`
- `--lang, -l`: Programming language (default: `python_3_13`). Options: `python_3_13`, `python_3`, `java_20`, `java_24`, `cpp_14`, `kotlin`, `c`
- `--talg, -ta`: Tree edit distance algorithm (default: `apted`). Options: `zss`, `apted`
- `--index, -ix`: Similarity index formula (default: `legacy`). Options: `legacy`, `ratio`, `metric`
- `--prefilter`: Compare the tokens of each pair first and run the structural comparison only on the pairs whose lexical index reaches `--threshold` minus 0.05 (see below). Off by default.
- `--prefilter-margin X`: Same, with margin `X` (0.0 to 0.30); it turns the prefilter on by itself.

**Complete example:**
```sh
csimx group --path /path/to/directory --threshold 0.9 --strategy exhaustive --lang python_3_13 --talg zss
```

#### Lexical prefilter (`group` only)

csimx has two stages: the **structural** one (parse tree, tree edit distance) gives the index, and a **lexical** one compares the token sequences of two files with the Myers diff algorithm (`1 - d / (len_a + len_b)`, comments and layout dropped, names, numbers and strings generalized to their type). With `--prefilter` the lexical stage goes first and the structural one only runs on the pairs that are not too different in tokens, so the time of a big directory drops by a few times; files that take part in no such pair are not even parsed.

```sh
csimx group --path /path/to/directory --threshold 0.7 --lang python_3 --prefilter
csimx group --path /path/to/directory --threshold 0.7 --lang python_3 --prefilter-margin 0.1
```

The filter is lossy: a pair with the same structure and very different tokens (a moved block, reordered statements) can be skipped even though the structural stage would group it. The margin is how far under `--threshold` the lexical index may be; a larger margin loses fewer pairs and skips fewer. It pays off from a threshold of about 0.6 up. See the 0.1.0 entry of `CHANGELOG.md` for the numbers. `report` has no prefilter.

#### Similarity Index Formulas

`--index` chooses how the tree edit distance `d` is normalized into the
similarity index. With `m = max(n1, n2)` and `s = n1 + n2`:

| Value | Formula | Notes |
|---|---|---|
| `legacy` (default) | `1 - d / m` | The index of csim <= 3.4.2. |
| `ratio` | `m / (m + d)` | Always in (0, 1]. Ranks pairs exactly as `legacy` does, on a different scale. |
| `metric` | `(s - d) / (s + d)` | Metric normalization of tree edit distance (Li & Zhang); satisfies the triangle inequality. Ranks by total size instead of by the larger tree. |

**Thresholds do not carry over between formulas.** `ratio` is a monotone
rescaling of `legacy`, so it groups files in exactly the same order, but on a
different scale. To reproduce a `legacy` threshold under `ratio`, use
`t_ratio = 1 / (2 - t_legacy)`:

| `legacy` | `ratio` |
|---|---|
| 0.70 | 0.769 |
| 0.80 | 0.833 |
| 0.90 | 0.909 |

Because `ratio` never reaches 0 in practice (a pair with nothing in common
sits near 0.5, where `legacy` puts it near 0), a threshold taken straight from
the `legacy` scale will be far more lenient than intended. `legacy` is the
default so that existing thresholds keep their meaning.

### Action 3: `tree` (alias: `view`) - Visualize Parse Trees

Prints the normalized/pruned tree for a single file — the exact tree that gets passed to the tree edit distance algorithm. Useful for debugging how the normalization, collapsing, and hashing rules affect a specific file before it's compared against others.

```sh
csimx tree --path /path/to/file.py --lang python_3_13
```

**Example Output:**
```
=== Normalized + Pruned Tree (input to Tree Edit Distance) ===
statements
   function_def_raw
      param [hashed:e3b0c442]
      statements
         STRING
         if_stmt
            comparison [hashed:93e10dca]
            return_stmt [hashed:337adaa9]
   assignment [hashed:118045cc]
   primary [hashed:e1b0c7ab]

Total nodes after pruning: 24
```

Rule and token names are resolved for readability, `LOOP` marks nodes collapsed under control-flow equivalence (e.g. `for`/`while`), and `[hashed:xxxxxxxx]` marks subtrees that were hashed into a single node instead of compared structurally.

**Options:**
- `--path, -p`: Path to a single source code file (**required**).
- `--lang, -l`: Programming language (default: `python_3_13`). Options: `python_3_13`, `python_3`, `java_20`, `java_24`, `cpp_14`, `kotlin`, `c`
- `--show-raw`: Also print the raw ANTLR parse tree before normalization/pruning, for side-by-side comparison.

**Example with `--show-raw`:**
```sh
csimx tree --path /path/to/file.py --lang python_3_13 --show-raw
```

### Language Support

The tool supports the following programming languages:

**Python 3.13:**
```sh
csimx report --path /path/to/python/files --lang python_3_13
```

**Python 3 (universal grammar):**
```sh
csimx report --path /path/to/python/files --lang python_3
```

Same `.py` files as `python_3_13`, parsed with grammars-v4's "universal Python 2/3"
grammar, which publishes a C++ target -- giving a large speedup once the native
parser is built (see [Native Parsers](#native-parsers) below). Grouping output is
byte-identical to `python_3_13` on most real-world code (verified against
hundreds of real judge submissions); a narrow, understood exception remains for
files with very few top-level statements, where tree-size differences can
slightly overstate similarity — see `csimx/python_3/utils.py` for the full
writeup. Does not parse positional-only parameters (`/`, PEP 570), the walrus
operator (`:=`, PEP 572), or `match`/`case` (PEP 634); csimx falls back to
`python_3_13` automatically for files using those, so results stay correct,
just slower for that subset.

**Java 20:**
```sh
csimx report --path /path/to/java/files --lang java_20
```

**Java 24 (experimental):**
```sh
csimx report --path /path/to/java/files --lang java_24
```

Java 24 uses an optimized grammar (grammars-v4/java/java) that parses much faster
than `java_20` when the native parser is available (see [Native Parsers](#native-parsers)
below), and supports the same modern Java syntax (records, sealed classes, pattern
matching, switch expressions, text blocks). **However, its similarity/grouping
output is not yet tuned to match `java_20` and can be significantly less accurate**
(verified on real submissions — see `CHANGELOG.md`). Use `java_20` for `group`/`report`
until this is resolved; `java_24` is available for parse-speed experimentation only.

**C++14:**
```sh
csimx report --path /path/to/cpp/files --lang cpp_14
```

**Kotlin (experimental):**
```sh
csimx report --path /path/to/kotlin/files --lang kotlin
```

First-cut integration (grammars-v4/kotlin/kotlin) with a working native parser
(no C++ base class needed at all -- this grammar declares no `superClass`).
Unlike `java_24`/`python_3`, there is no real-world Kotlin corpus in this
project's benchmark set to tune or validate grouping precision against yet, so
the normalization rules (`csimx/kotlin/utils.py`) follow the same *categories*
already validated for other languages (structural punctuation, identifier
text, import/package plumbing, body-wrapping content) but haven't been
corpus-measured for false-positive/false-negative rates. Treat `group`/`report`
results as a reasonable starting point, not a tuned config, until a real
corpus drives the next pass.

**C (experimental):**
```sh
csimx report --path /path/to/c/files --lang c
```

First-cut integration (grammars-v4/c, ISO C23 + GNU/MSVC extensions), with a
working native parser backed by a real symbol-table implementation for
typedef disambiguation. Like Kotlin, there's no real-world C corpus in this
project's benchmark set to tune grouping precision against yet -- same
caveats apply, see `csimx/c/utils.py`.

Runs with preprocessing disabled (`--nopp`) always: a real preprocessor can't
be assumed present in a production container, and judge submissions have no
consistent include paths anyway. `#include`/`#define`/etc. lines are
swallowed as hidden tokens rather than expanded, which means macro-dependent
code (token-pasting tricks, macros used for control flow) can fail to parse
or parse differently than a real compiler would see it -- real submissions
essentially never rely on that, but it's a known, real limitation.

### Native Parsers

For `java_20`, `java_24`, `cpp_14`, `python_3`, `kotlin`, and `c`, csimx can
use a compiled C++ ANTLR parser instead of the pure-Python one, giving a
large speedup with identical (or, for `java_24`, not-yet-identical -- see
above) output. `python_3_13` always uses the pure-Python parser (no C++
target is available for that grammar).

Check which backend is active for each language:

```sh
csimx info
```

If a native library isn't present for a language, csimx falls back to the
pure-Python parser automatically — results are unaffected, only speed. Build
the native parsers from source with:

```sh
scripts/build_native_parsers.sh
```

Set `CSIM_DISABLE_NATIVE=1` to force the pure-Python parsers for every
language, e.g. for debugging or benchmarking.

### Threshold Guidance

The similarity threshold represents the structural similarity of the code (based on the Abstract Syntax Tree). Choose appropriate thresholds based on your use case:

- **0.95+**: Nearly identical code (likely plagiarism)
- **0.85-0.95**: Very similar code (probable plagiarism)
- **0.70-0.85**: Moderately similar code (review recommended)
- **<0.70**: Low similarity (likely independent work)

### Using csimx as a Python Module

You can also use csimx programmatically within your Python code. The library provides low-level functions for advanced use cases:

```python
from csimx.utils import group_by_exhaustive_search, report_pairwise_similarity

# Example: Group files by similarity
file_names = ["file1.py", "file2.py", "file3.py"]
file_contents = [code1, code2, code3]

results = group_by_exhaustive_search(
    file_names=file_names,
    file_contents=file_contents,
    lang="python_3_13",
    threshold=0.8,
    ted_algorithm="apted"
)

print(results)
```

#### Estimating the time of `group`, and following its progress

`group` compares every pair, so its time grows with the square of the number of files and with the
square of the size of the pruned trees. `estimate_group` tells you before running it, from the real
size of the trees (cost per pair ~ `a[lang] * (nodes_i * nodes_j) ** 1.2`, fitted on the seven
languages):

```python
from csimx import calibrate, estimate_group

speed = calibrate()   # speed of this machine against the reference one (about 0.3 s, cached)
est = estimate_group(file_names, file_contents, "java_24", threshold=0.7,
                     prefilter_margin=0.05, speed_factor=speed)
print(est["estimated_seconds"], est["range_seconds"], est["structural_pairs"], est["pairs"])
```

With a prefilter margin, `exact_prefilter=False` skips the lexical pass (which is not free for long
files) and returns the upper bound. On 100 files per language the estimate was within -1% to +13% of
the measured time (range: 0.7x to 1.5x of the point value); other machines and loaded CPUs will be
worse, so refine it with the real progress while it runs. `group_by_exhaustive_search` takes
`progress=callable(phase, done, total)` (phases `parse`, `lexical`, `structural`; it only reports and
never changes the result). csimx has no cancellation of its own: to stop a long `group`, run it in a
separate process and terminate it.

Or use the legacy Compare class for simple pairwise comparisons:

```python
from csimx import Compare

code_a = "a = 5"
code_b = "c = 50"
similarity = Compare(name_a='example A', content_a=code_a, name_b='example B', content_b=code_b)
print(f"Similarity: {similarity}") # Output: Similarity: X.XX
```

To see how much a program shrinks when it is normalized, pruned and hashed, count its nodes before and after:

```python
from csimx import count_nodes

nodes_before, nodes_after = count_nodes("example.py", code, lang="python_3_13")
```

`nodes_before` is every node of the raw ANTLR parse tree; `nodes_after` is the size of the tree handed to the tree edit distance (the same number `csimx tree` prints as "Total nodes after pruning").

## Documentation

- [Getting Started Guide](GETTING_STARTED.md) - Quick tutorial for new users
- [Search Strategies Guide](docs/STRATEGIES.md) - Detailed explanation of available search strategies
- [ANTLR Parser Generation](grammars/parser_gen_guide.md) - For grammar customization

## ANTLR4 Installation and Parser/Lexer Generation

This installation is not required—the generated files are already included in the project. If you'd like to review the steps to generate them yourself, see [grammars/parser_gen_guide.md](grammars/parser_gen_guide.md).

Note: The included generated files were produced by **ANTLR 4.13.2** and are compatible with the pinned runtime listed above.

## Contributing

Contributions are welcome! To contribute, please follow these steps:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/new-feature`).
3.  Make your changes and commit them (`git commit -am 'Add new feature'`).
4.  Push to the branch (`git push origin feature/new-feature`).
5.  Open a Pull Request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Support

- **Questions?** Open a [GitHub Discussion](https://github.com/EdsonEddy/csimx/discussions)
- **Found a bug?** File a [GitHub Issue](https://github.com/EdsonEddy/csimx/issues)
- **Want to contribute?** See [Contributing](#contributing) section

## References

For more information on the techniques and tools used in this project, refer to the following resources:

- [ANTLR](https://www.antlr.org/)
- [Parse Tree (Wikipedia)](https://en.wikipedia.org/wiki/Parse_tree)
- [Tree Edit Distance (Wikipedia)](https://en.wikipedia.org/wiki/Tree_edit_distance)
- [Locality Sensitive Hashing (Wikipedia)](https://en.wikipedia.org/wiki/Locality-sensitive_hashing)
- [MinHash (Wikipedia)](https://en.wikipedia.org/wiki/MinHash)
- [zss (PyPI)](https://pypi.org/project/zss/)
- [Hashing (Python Docs)](https://docs.python.org/3/library/hashlib.html)
- [apted (GitHub)](https://github.com/JoaoFelipe/apted)

## Third-Party Licenses

This project utilizes the following third-party libraries:

### ANTLR (ANother Tool for Language Recognition)
- **Purpose:** A parser generator used to create parse trees from source code.
- **License:** BSD 3-Clause
- **Website:** [https://www.antlr.org/](https://www.antlr.org/)
- **Repository:** [https://github.com/antlr/antlr4](https://github.com/antlr/antlr4)

### ANTLR4-parser-for-Python-3.14 by RobEin
- **Purpose:** Python 3.14 grammar for ANTLR4
- **License:** MIT License
- **Repository:** [https://github.com/RobEin/ANTLR4-parser-for-Python-3.14](https://github.com/RobEin/ANTLR4-parser-for-Python-3.14)

### zss (Zhang-Shasha)
- **Purpose:** Tree edit distance algorithm implementation for comparing tree structures
- **License:** MIT License
- **Repository:** [https://github.com/timtadh/zhang-shasha](https://github.com/timtadh/zhang-shasha)

### apted (All Path Tree Edit Distance)
- **Purpose:** Python APTED algorithm for the Tree Edit Distance, an alternative to zss
- **License:** MIT License
- **Repository:** [https://github.com/JoaoFelipe/apted](https://github.com/JoaoFelipe/apted)

