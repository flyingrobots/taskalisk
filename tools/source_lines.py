"""Count physical source and logical function bodies using Python tokens."""

from __future__ import annotations

import ast
import io
import tokenize

TRIVIA = {tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}


def source_tokens(source: str) -> list[tokenize.TokenInfo]:
    """Tokenize a parsed source string without executing it."""
    return list(tokenize.generate_tokens(io.StringIO(source).readline))


def physical_lines(source: str, tokens: list[tokenize.TokenInfo]) -> int:
    """Count nonblank lines carrying code or string content, excluding real comments."""
    occupied: set[int] = set()
    for token in tokens:
        if token.type not in TRIVIA | {tokenize.NEWLINE}:
            occupied.update(range(token.start[0], token.end[0] + 1))
    return sum(
        bool(line.strip()) and number in occupied
        for number, line in enumerate(source.split("\n"), 1)
    )


def _docstring_ranges(node: ast.AST) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Find actual leading docstrings, including those in nested owned declarations."""
    ranges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.body:
            first = child.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ranges.append(
                    (
                        (first.lineno, first.col_offset),
                        (first.end_lineno or first.lineno, first.end_col_offset or 0),
                    )
                )
    return ranges


def _byte_position(position: tuple[int, int], lines: list[str]) -> tuple[int, int]:
    """Translate tokenizer character columns to the UTF-8 byte columns used by the AST."""
    row, column = position
    return row, len(lines[row - 1][:column].encode("utf-8"))


def logical_lines(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    tokens: list[tokenize.TokenInfo],
    lines: list[str],
) -> int:
    """Count body statements and suite headers, splitting semicolons and omitting docstrings."""
    first = node.body[0]
    start = (first.lineno, first.col_offset)
    end = (node.end_lineno or node.lineno, node.end_col_offset or 0)
    docstrings = _docstring_ranges(node)
    count = 0
    active = False
    for token in tokens:
        if token.type in TRIVIA or not start[0] <= token.start[0] <= end[0]:
            continue
        beginning = _byte_position(token.start, lines)
        ending = _byte_position(token.end, lines)
        if not start <= beginning <= end:
            continue
        if token.type == tokenize.NEWLINE or token.string == ";":
            count += int(active)
            active = False
        elif not any(low <= beginning and ending <= high for low, high in docstrings):
            active = True
    return count + int(active)
