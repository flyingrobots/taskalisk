"""Measure function-local control nesting, arguments and explicit tuple returns."""

from __future__ import annotations

import ast
from collections.abc import Iterable

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
SUITES = (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.IfExp)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def deepest(nodes: Iterable[ast.AST]) -> int:
    """Measure sibling subtrees without charging one sibling's depth to another."""
    return max((nesting(node) for node in nodes), default=0)


def nesting(node: ast.AST) -> int:
    """Count syntactic control suites and generators, stopping at nested definitions."""
    if isinstance(node, SCOPES):
        return 0
    if isinstance(node, ast.If):
        alternatives = node.orelse
        alternate_depth = deepest(alternatives)
        if not (len(alternatives) == 1 and isinstance(alternatives[0], ast.If)):
            alternate_depth += 1
        return max(1 + deepest([node.test, *node.body]), alternate_depth)
    children = list(ast.iter_child_nodes(node))
    if isinstance(node, COMPREHENSIONS):
        return len(node.generators) + deepest(children)
    return int(isinstance(node, SUITES)) + deepest(children)


def parameter_count(arguments: ast.arguments, *, method: bool, static: bool) -> int:
    """Count all parameter kinds, excluding only a conventional bound method receiver."""
    positional = [*arguments.posonlyargs, *arguments.args]
    count = len(positional) + len(arguments.kwonlyargs)
    count += int(arguments.vararg is not None) + int(arguments.kwarg is not None)
    receiver = method and not static and positional and positional[0].arg in {"self", "cls"}
    return count - int(bool(receiver))


def _returned_arity(value: ast.expr | None) -> int:
    """Inspect explicit result alternatives without counting tuples passed to another call."""
    if isinstance(value, ast.Tuple):
        return len(value.elts)
    if isinstance(value, ast.IfExp):
        return max(_returned_arity(value.body), _returned_arity(value.orelse))
    if isinstance(value, ast.BoolOp):
        return max(map(_returned_arity, value.values), default=0)
    if isinstance(value, ast.NamedExpr):
        return _returned_arity(value.value)
    return 0


def _annotated_arity(annotation: ast.expr | None) -> int:
    """Count explicit fixed tuple annotations; homogeneous variadic tuples are collections."""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        annotation = ast.parse(annotation.value, mode="eval", feature_version=(3, 9)).body
    if not isinstance(annotation, ast.Subscript):
        return 0
    name = annotation.value
    tuple_name = isinstance(name, ast.Name) and name.id in {"tuple", "Tuple"}
    tuple_name = tuple_name or (isinstance(name, ast.Attribute) and name.attr == "Tuple")
    if not tuple_name:
        return 0
    if not isinstance(annotation.slice, ast.Tuple):
        return 1
    items = annotation.slice.elts
    if any(isinstance(item, ast.Constant) and item.value is Ellipsis for item in items):
        return 0
    return len(items)


def return_arity(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    """Find the largest explicit anonymous result owned by this function."""
    if isinstance(node, ast.Lambda):
        return _returned_arity(node.body)
    largest = _annotated_arity(node.returns)
    pending: list[ast.AST] = list(node.body)
    while pending:
        child = pending.pop()
        if isinstance(child, ast.Return):
            largest = max(largest, _returned_arity(child.value))
        elif not isinstance(child, SCOPES):
            pending.extend(ast.iter_child_nodes(child))
    return largest
