"""The test helpers that capture and read fixtures must not mislead: a missing compiler is an error,
not an empty rendering; a line ends only at a newline."""
import contextlib
import io
import pathlib
import shlex
import tempfile
import unittest
from unittest import mock

import capture_golden
import golden_scenarios as g
import parley_lines as pl


class CaptureGolden(unittest.TestCase):
    def test_a_missing_script_fails_and_overwrites_no_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            golden = pathlib.Path(tmp) / "golden"
            golden.mkdir()
            sentinel = golden / next(iter(g.SCENARIOS)).__add__(".json")
            sentinel.write_text("kept\n")
            with mock.patch.object(g, "GOLDEN", golden), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    capture_golden.main(str(pathlib.Path(tmp) / "no_such_compiler.py"), "0" * 40)
            self.assertNotEqual(raised.exception.code, 0)
            self.assertEqual(sentinel.read_text(), "kept\n")
            self.assertEqual(sorted(p.name for p in golden.iterdir()), [sentinel.name])


class ParseSplitsOnNewlineOnly(unittest.TestCase):
    def test_unicode_line_separators_inside_a_string_do_not_split_a_line(self):
        for sep in ("\u0085", " ", " "):
            with self.subTest(repr(sep)):
                self.assertEqual(pl.parse('{"a": "x%sy"}\n' % sep, "stdout"), [{"a": "x%sy" % sep}])


class GhWrapperQuotesPaths(unittest.TestCase):
    def test_the_interpreter_and_the_fake_gh_are_each_one_shell_word_even_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(g, "FAKE_GH", pathlib.Path("/a dir/fake gh.py")), mock.patch.object(g.sys, "executable", "/py thon/bin/python 3"):
                g.prepare(tmp)
            words = shlex.split((pathlib.Path(tmp) / "bin" / "gh").read_text().splitlines()[1])
            self.assertEqual(words, ["exec", "/py thon/bin/python 3", "/a dir/fake gh.py", "$@"])


if __name__ == "__main__":
    unittest.main()
