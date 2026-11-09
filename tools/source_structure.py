"""Measure Python source independently of formatting and Ruff statement counts."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .source_control import deepest, nesting, parameter_count, return_arity
from .source_lines import logical_lines, physical_lines, source_tokens


@dataclass(frozen=True)
class FunctionSize:
    """Explicit syntax measurements for one function at a stable source location."""

    name: str
    line: int
    logical_lines: int
    nesting: int
    parameters: int
    tuple_arity: int


@dataclass(frozen=True)
class SourceSize:
    """Physical source size and individually owned function measurements."""

    lines: int
    functions: list[FunctionSize]


def _static_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Recognize explicit staticmethod decorators without executing decorator expressions."""
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "staticmethod")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "staticmethod")
        for decorator in node.decorator_list
    )


def measure_source(source: str) -> SourceSize:
    """Measure source using the repository's declared Python 3.9 syntax floor."""
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    tree = ast.parse(source, feature_version=(3, 9))
    tokens = source_tokens(source)
    lines = source.split("\n")
    functions: list[FunctionSize] = []
    pending: list[tuple[ast.AST, str, bool]] = [(tree, "", False)]
    while pending:
        node, prefix, method = pending.pop()
        child_prefix = prefix
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            name = (
                node.name
                if not isinstance(node, ast.Lambda)
                else f"<lambda@{node.lineno}:{node.col_offset}>"
            )
            child_prefix = prefix + name + "."
            is_lambda = isinstance(node, ast.Lambda)
            functions.append(
                FunctionSize(
                    name=prefix + name,
                    line=node.lineno,
                    logical_lines=1 if is_lambda else logical_lines(node, tokens, lines),
                    nesting=nesting(node.body) if is_lambda else deepest(node.body),
                    parameters=parameter_count(
                        node.args,
                        method=method,
                        static=False if is_lambda else _static_method(node),
                    ),
                    tuple_arity=return_arity(node),
                )
            )
        elif isinstance(node, ast.ClassDef):
            child_prefix = prefix + node.name + "."
        children = list(ast.iter_child_nodes(node))
        pending.extend(
            (child, child_prefix, isinstance(node, ast.ClassDef)) for child in reversed(children)
        )
    return SourceSize(physical_lines(source, tokens), functions)
