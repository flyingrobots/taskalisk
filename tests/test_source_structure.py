"""Check source measurements with small, independently counted Python specimens."""

from __future__ import annotations

import unittest

from tools.source_structure import measure_source


class SourceStructure(unittest.TestCase):
    """Formatting and equivalent syntax must not conceal source complexity."""

    def test_multiline_strings_are_source_and_comments_are_not(self) -> None:
        """A hash inside a literal is data, whereas a real comment is excluded."""
        source = '\n# comment\nvalue = """first\n# literal data\n\nlast"""\n\n'
        self.assertEqual(measure_source(source).lines, 3)

    def test_logical_lines_ignore_wrapping_and_docstrings(self) -> None:
        """A wrapped assignment remains one line and a function docstring is documentation."""
        source = 'def work():\n    """Explain\n    work.\n    """\n    value = (\n        1 +\n        2\n    )\n    return value\n'
        result = measure_source(source).functions[0]
        self.assertEqual((result.name, result.line, result.logical_lines), ("work", 1, 2))

    def test_semicolon_statements_count_separately(self) -> None:
        """Packing executable statements onto one physical line cannot evade the limit."""
        result = measure_source("def work():\n    a = 1; b = 2;\n    return a + b\n").functions[0]
        self.assertEqual(result.logical_lines, 3)

    def test_inline_function_body_is_counted(self) -> None:
        """A body on its declaration line still contributes logical work."""
        result = measure_source("def work(): return 1\n").functions[0]
        self.assertEqual(result.logical_lines, 1)

    def test_inline_docstring_does_not_hide_following_code(self) -> None:
        """Only the docstring token is omitted when a body shares its physical line."""
        result = measure_source('def work(): "documentation"; return 1\n').functions[0]
        self.assertEqual(result.logical_lines, 1)

    def test_unicode_byte_offsets_do_not_hide_inline_bodies(self) -> None:
        """AST byte columns and tokenizer character columns must name the same code."""
        for source in (
            "def caf\u00e9(): pass\n",
            'def work(): "\u03b1\u03b1\u03b1\u03b1\u03b1\u03b1\u03b1\u03b1"; pass\n',
        ):
            with self.subTest(source=source):
                self.assertEqual(measure_source(source).functions[0].logical_lines, 1)

    def test_python_newlines_and_literal_unicode_separators_are_distinct(self) -> None:
        """CRLF and CR are source newlines; a Unicode separator inside a string is literal data."""
        source = 'def work():\n    value = "a\u2028\u2028b"\n    return value\n'
        for newline in ("\n", "\r\n", "\r"):
            with self.subTest(newline=newline):
                result = measure_source(source.replace("\n", newline))
                self.assertEqual((result.lines, result.functions[0].logical_lines), (3, 2))

    def test_elif_siblings_do_not_add_nested_suites(self) -> None:
        """Mutually exclusive sibling alternatives have the same control depth."""
        source = "def work(x):\n    if x == 1:\n        return 1\n    elif x == 2:\n        return 2\n    else:\n        return 3\n"
        self.assertEqual(measure_source(source).functions[0].nesting, 1)

    def test_nested_suites_and_conditional_expressions_add_depth(self) -> None:
        """A conditional expression inside two suites has depth three."""
        source = (
            "def work(xs):\n    for x in xs:\n        if x:\n            yield 1 if x > 1 else 0\n"
        )
        self.assertEqual(measure_source(source).functions[0].nesting, 3)

    def test_comprehension_generators_add_depth_but_filters_do_not(self) -> None:
        """Each generator has a scope; a filter stays within its generator's scope."""
        source = (
            "def work(xs):\n    if xs:\n        return [(x, y) for x in xs for y in xs if x != y]\n"
        )
        self.assertEqual(measure_source(source).functions[0].nesting, 3)

    def test_try_handlers_and_cleanup_are_sibling_suites(self) -> None:
        """Handler, else and finally branches do not nest merely by belonging to one try."""
        source = "def work():\n    try:\n        read()\n    except OSError:\n        recover()\n    else:\n        accept()\n    finally:\n        close()\n"
        self.assertEqual(measure_source(source).functions[0].nesting, 1)

    def test_nested_functions_have_independent_depth_and_qualified_identity(self) -> None:
        """Inner control depth is measured on its own function, without losing outer source cost."""
        source = "def outer(x):\n    if x:\n        def inner(y):\n            if y:\n                return y\n        return inner(x)\n"
        result = measure_source(source).functions
        self.assertEqual([(f.name, f.nesting) for f in result], [("outer", 1), ("outer.inner", 1)])
        self.assertEqual(result[0].logical_lines, 5)

    def test_only_method_receivers_are_excluded_from_parameters(self) -> None:
        """A free function or static method cannot hide a parameter by naming it self."""
        source = "def free(self, x): pass\nclass Work:\n    def method(self, x): pass\n    @classmethod\n    def factory(cls, x): pass\n    @staticmethod\n    def static(self, x): pass\n"
        result = measure_source(source).functions
        self.assertEqual(
            [(f.name, f.parameters) for f in result],
            [("free", 2), ("Work.method", 1), ("Work.factory", 1), ("Work.static", 2)],
        )

    def test_all_parameter_kinds_count(self) -> None:
        """Positional-only, ordinary, variadic and keyword-only parameters remain visible."""
        result = measure_source("def work(a, /, b, *args, c, **kwargs): pass\n").functions[0]
        self.assertEqual(result.parameters, 5)

    def test_tuple_literals_and_annotations_expose_return_arity(self) -> None:
        """Both annotated and literal records contribute their explicit field count."""
        source = "def literal(): return 1, 2, 3, 4\ndef annotated() -> tuple[int, int, int, int]: return produce()\ndef sequence() -> tuple[int, ...]: return produce()\n"
        result = measure_source(source).functions
        self.assertEqual([f.tuple_arity for f in result], [4, 4, 0])

    def test_nested_returns_do_not_belong_to_the_outer_function(self) -> None:
        """An inner record return must not manufacture an outer tuple violation."""
        source = "def outer():\n    def inner(): return 1, 2, 3, 4\n    return inner\n"
        self.assertEqual([f.tuple_arity for f in measure_source(source).functions], [0, 4])

    def test_result_alternatives_include_boolean_and_assignment_expressions(self) -> None:
        """An explicit tuple remains a possible result through short-circuit or assignment syntax."""
        source = "def boolean(value): return value or (1, 2, 3, 4)\ndef named(): return (result := (1, 2, 3, 4))\n"
        self.assertEqual([f.tuple_arity for f in measure_source(source).functions], [4, 4])

    def test_quoted_fixed_annotations_and_collection_results_remain_distinct(self) -> None:
        """Resolve direct quoted tuple syntax without treating collection element types as the result."""
        source = 'def quoted() -> "typing.Tuple[int, int, int, int]": return produce()\ndef collection() -> list[tuple[int, int, int, int]]: return produce()\ndef singleton() -> tuple[int]: return produce()\n'
        self.assertEqual([f.tuple_arity for f in measure_source(source).functions], [4, 0, 1])

    def test_lambda_parameters_nesting_and_tuple_are_measured(self) -> None:
        """A lambda is a function even though it has no statement body."""
        result = measure_source("work = lambda a, b: (a, b, 3, 4) if a else ()\n").functions[0]
        self.assertEqual(
            (result.logical_lines, result.nesting, result.parameters, result.tuple_arity),
            (1, 1, 2, 4),
        )

    def test_invalid_and_unsupported_source_cannot_be_measured_as_empty(self) -> None:
        """Syntax errors and syntax newer than the preserved runtime floor fail explicitly."""
        for source in ("def (", "match value:\n    case 1: pass\n"):
            with self.subTest(source=source), self.assertRaises(SyntaxError):
                measure_source(source)
