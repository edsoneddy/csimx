"""Table-driven canonical forms for operators (languages other than python_3).

Runs on the normalized tree (dicts with "label" and "children"), before pruning and hashing, so
`a + b` / `b + a`, `a >= b` / `b <= a` and the like produce the same tree. Like
python_3/canonical.py it only looks at the shape of the tree and at token types: native
terminals carry no text, so nothing here compares identifiers, and the order key is built from
labels alone.

A language describes its grammar with a `CanonicalSpec`:

* `commutative`: rules whose nodes are `[left, op, right]` and whose `op` is in
  `commutative_ops`; the two operands are put in a fixed order.
* `symmetric`: rules whose nodes are `[left, right]` because the operator token is excluded from
  the tree (`&&`, `||`, `<`, `>`, ...) and swapping the operands keeps the meaning (`a < b` ==
  `b > a`); the two operands are put in a fixed order.
* `orient`: `(rules, {GE: LE, GT: LT})`: `[a, GE, b]` is rewritten to `[b, LE, a]` (and the other
  entries of the map likewise).

Not covered on purpose: chained operators of different kinds (`a - b + c`), and anything that
needs to know a type (`+` on strings is not commutative; the shape-only rule accepts that, as
python_3 does).
"""
from dataclasses import dataclass, field


@dataclass
class CanonicalSpec:
    commutative: frozenset = frozenset()
    commutative_ops: frozenset = frozenset()
    symmetric: frozenset = frozenset()
    orient: tuple = field(default=(frozenset(), {}))


def _key(node, cache):
    hit = cache.get(id(node))
    if hit is None:
        k = (str(node["label"]), tuple(_key(c, cache) for c in node["children"]))
        hit = cache[id(node)] = (node, k)  # keep the node so its id cannot be reused
    return hit[1]


def canonicalize_with(spec, tree):
    """Return `tree` (modified in place) with the operator forms of `spec` unified."""
    cache = {}
    orient_rules, orient_ops = spec.orient

    def run(node):
        # iterative post-order: real programs nest deeper than the recursion limit
        stack, order = [node], []
        while stack:
            n = stack.pop()
            order.append(n)
            stack.extend(n["children"])
        replaced = {}
        for n in reversed(order):
            n["children"] = [replaced.get(id(c), c) for c in n["children"]]
            new = rewrite(n)
            if new is not n:
                replaced[id(n)] = new
        return replaced.get(id(node), node)

    def rewrite(node):
        label, kids = node["label"], node["children"]
        if len(kids) == 3:
            left, op, right = kids
            if label in orient_rules and op["label"] in orient_ops and not op["children"]:
                swapped = {"label": orient_ops[op["label"]], "children": []}
                return {"label": label, "children": [right, swapped, left]}
            if label in spec.commutative and op["label"] in spec.commutative_ops and not op["children"]:
                if _key(left, cache) > _key(right, cache):
                    node["children"] = [right, op, left]
        elif len(kids) == 2 and label in spec.symmetric:
            if _key(kids[0], cache) > _key(kids[1], cache):
                node["children"] = [kids[1], kids[0]]
        return node

    return run(tree)
