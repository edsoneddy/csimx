"""Table-driven canonical operator forms (all languages except python_3).

Runs on the normalized tree before pruning and hashing, so `a + b` / `b + a` and
`a >= b` / `b <= a` give the same tree. Only tree shape and token types are used.

A language declares a `CanonicalSpec`:

* `commutative`: rules with nodes `[left, op, right]` and `op` in `commutative_ops`;
  the operands are put in a fixed order.
* `symmetric`: rules with nodes `[left, right]` (the operator token is excluded);
  the operands are put in a fixed order.
* `orient`: `(rules, {GE: LE, GT: LT})`; `[a, GE, b]` becomes `[b, LE, a]`.

Not covered: chains of different operators (`a - b + c`) and anything that needs types
(`+` on strings is not commutative).
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
        # iterative: real programs nest deeper than the recursion limit
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
