"""Focused stdlib adaptations of pinned upstream regression tests, not full suites.

Attribution/license texts and exact upstream test locations are in the manifests.
Upstream test vectors and assertions are retained; pytest parameters become
unittest subTests and tmp_path becomes a temporary directory under /tmp.
Only execute this file inside the documented bubblewrap sandbox.
"""
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from itertools import count


class LicenseCase(unittest.TestCase):
    def test_licenseref_case_variants_use_first_spelling(self):
        from packaging.licenses import canonicalize_license_expression
        pairs = [
            ("LicenseRef-mit OR licenseref-MIT", "LicenseRef-mit OR LicenseRef-mit"),
            ("licenseref-MIT AND LicenseRef-mit", "LicenseRef-MIT AND LicenseRef-MIT"),
            ("(LICENSEREF-Foo OR licenseref-foo) AND MIT AND LicenseRef-FOO", "(LicenseRef-Foo OR LicenseRef-Foo) AND MIT AND LicenseRef-Foo"),
            ("licenseref-public-domain", "LicenseRef-public-domain"),
        ]
        for expression, expected in pairs:
            with self.subTest(expression=expression):
                self.assertEqual(canonicalize_license_expression(expression), expected)


class MarkerQuotes(unittest.TestCase):
    def test_value_serialize_chooses_quote_delimiter(self):
        from packaging._parser import Value
        for value, expected in [("plain", '"plain"'), ('a"b', "'a\"b'"), ("a'b", '"a\'b"')]:
            with self.subTest(value=value):
                self.assertEqual(Value(value).serialize(), expected)

    def test_value_serialize_rejects_both_quote_delimiters(self):
        from packaging._parser import Value
        with self.assertRaisesRegex(ValueError, "Cannot serialize marker value containing both quote characters"):
            Value("a\"b'c").serialize()

    def test_marker_normalization_embedded_quotes(self):
        from packaging.markers import Marker
        text = '\'a" == os_name or python_version >= "0" or "b\' == os_name'
        self.assertEqual(str(Marker(text)), text)

    def test_requirement_marker_with_embedded_double_quote_round_trips(self):
        from packaging.requirements import Requirement
        req_string = 'demo; \'a" == os_name or python_version >= "0" or "b\' == os_name'
        req = Requirement(req_string)
        self.assertEqual(str(req), req_string)
        self.assertIsNotNone(req.marker)
        self.assertIs(req.marker.evaluate(), False)
        marker = Requirement(str(req)).marker
        self.assertIsNotNone(marker)
        self.assertIs(marker.evaluate(), False)


class SiblingErrors(unittest.TestCase):
    def test_diamond_shaped_dependencies_result_in_one_error(self):
        from packaging.dependency_groups import resolve_dependency_groups
        data = {"root": [{"include-group": "group1"}, {"include-group": "group2"}], "group1": [{"include-group": "err"}], "group2": [{"include-group": "err"}], "err": ["invalid requirement"]}
        with self.assertRaises(ExceptionGroup) as ctx:
            resolve_dependency_groups(data, "root")
        self.assertEqual(len(ctx.exception.exceptions), 1)

    def test_error_in_later_sibling_include_is_collected(self):
        from packaging.dependency_groups import resolve_dependency_groups
        groups = {"root": [{"include-group": "bad"}, {"include-group": "wrapper"}], "bad": ["!!! bad invalid"], "wrapper": [{"include-group": "also-bad"}], "also-bad": ["!!! also invalid"]}
        with self.assertRaises(ExceptionGroup) as ctx:
            resolve_dependency_groups(groups, "root")
        messages = [str(e) for e in ctx.exception.exceptions]
        self.assertEqual(len(messages), 2)
        self.assertIn("!!! bad invalid", messages[0])
        self.assertIn("!!! also invalid", messages[1])


class LargeRange(unittest.TestCase):
    def test_eq_above_maxsize(self):
        import more_itertools as mi
        stop = 10**30
        cases = [((0, stop, 1), (0, stop, 1), True), ((0, stop, 2), (0, stop - 1, 2), True), ((stop, 0, -2), (stop, 1, -2), True), ((0, stop, 1), (0, stop + 1, 1), False), ((0, stop, 1), (1, stop + 1, 1), False), ((0, stop, 1), (0, stop * 2, 2), False)]
        for args1, args2, expected in cases:
            with self.subTest(args1=args1, args2=args2):
                r1, r2 = mi.numeric_range(*args1), mi.numeric_range(*args2)
                self.assertEqual(range(*args1) == range(*args2), expected)
                self.assertEqual(r1 == r2, expected)

    def test_hash_above_maxsize(self):
        import more_itertools as mi
        stop = 10**30
        for args in [(0, stop, 1), (0, stop, 2), (stop, 0, -2)]:
            with self.subTest(args=args):
                r = mi.numeric_range(*args)
                self.assertEqual(hash(r), hash(range(*args)))
                self.assertEqual({r: "value"}[mi.numeric_range(*args)], "value")
                self.assertRaises(OverflowError, len, r)


class PeekableSlice(unittest.TestCase):
    def test_slicing_negative_step_omitted_stop(self):
        import more_itertools as mi
        it = iter(range(100))
        p = mi.peekable(it)
        self.assertEqual(p[5::-1], [5, 4, 3, 2, 1, 0])
        self.assertEqual(len(p._cache), 6)
        self.assertEqual(next(p), 0)
        # Exact upstream order: finite assertion fails before the infinite case
        # on the parent. CPU/address-space/wall limits still protect the process.
        p_inf = mi.peekable(count())
        self.assertEqual(p_inf[4::-2], [4, 2, 0])
        self.assertEqual(len(p_inf._cache), 5)
        self.assertEqual(next(p_inf), 0)


class ValueChain(unittest.TestCase):
    def test_type_error_while_iterating(self):
        import more_itertools as mi
        def gen():
            yield 1
            yield 2
            raise TypeError("failure inside the iterable")
        it = mi.value_chain(gen(), 3)
        self.assertEqual([next(it), next(it)], [1, 2])
        with self.assertRaises(TypeError):
            next(it)

    def test_type_error_from_iter(self):
        import more_itertools as mi
        class NotIterable:
            def __iter__(self):
                raise TypeError("not iterable")
        obj = NotIterable()
        self.assertEqual(list(mi.value_chain(1, obj, [2, 3])), [1, obj, 2, 3])


class DotenvBackslashes(unittest.TestCase):
    def test_set_key_round_trips(self):
        import dotenv
        values = ["C:\\Users", "C:\\Users\\", "\\d+", "back\\", "a\\'b", "it's", 'say "hi"', "a\\nb", "plain", ""]
        with tempfile.TemporaryDirectory(dir="/tmp") as temp:
            path = Path(temp) / "test.env"
            for value in values:
                with self.subTest(value=value):
                    path.write_text("")
                    dotenv.set_key(path, "a", value)
                    dotenv.set_key(path, "b", "sentinel")
                    self.assertEqual(dotenv.get_key(path, "a"), value)
                    self.assertEqual(dotenv.get_key(path, "b"), "sentinel")


class DotenvEmptyComment(unittest.TestCase):
    def test_dotenv_values_empty_value_with_inline_comment(self):
        import dotenv
        pairs = [("KEY= # comment", {"KEY": ""}), ("KEY=  # comment", {"KEY": ""}), ("KEY=val # comment", {"KEY": "val"}), ("KEY=a#b", {"KEY": "a#b"}), ("KEY=#novalue", {"KEY": "#novalue"}), ("KEY=# # comment", {"KEY": "#"}), ("KEY=\t# comment", {"KEY": ""}), ("KEY= # comment\nOTHER=val", {"KEY": "", "OTHER": "val"})]
        for string, expected in pairs:
            with self.subTest(string=string):
                self.assertEqual(dotenv.dotenv_values(stream=io.StringIO(string)), expected)


CASES = {"packaging-license-case": (LicenseCase, "packaging"), "packaging-marker-quotes": (MarkerQuotes, "packaging"), "packaging-sibling-errors": (SiblingErrors, "packaging"), "itertools-large-range": (LargeRange, "more_itertools"), "itertools-peekable-slice": (PeekableSlice, "more_itertools"), "itertools-value-chain": (ValueChain, "more_itertools"), "dotenv-backslashes": (DotenvBackslashes, "dotenv"), "dotenv-empty-comment": (DotenvEmptyComment, "dotenv")}


def main():
    if Path('/home').exists() or Path.cwd() != Path('/tmp') or not sys.flags.isolated or not sys.flags.no_site:
        raise RuntimeError("Run only in the documented isolated sandbox")
    sys.dont_write_bytecode = True
    sys.path.insert(0, "/source")
    case = sys.argv[1]
    cls, package = CASES[case]
    mod = importlib.import_module(package)
    if not str(mod.__file__).startswith('/source/'):
        raise RuntimeError("Wrong import provenance")
    print("ENVIRONMENT " + json.dumps({"python": sys.version, "executable": sys.executable, "cwd": os.getcwd(), "package_file": mod.__file__, "environment_keys": sorted(os.environ), "home_visible": Path('/home').exists()}))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(cls)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    loaded = {name: module.__file__ for name, module in sorted(sys.modules.items()) if getattr(module, '__file__', None) and str(module.__file__).startswith('/source/')}
    print("RESULT_JSON " + json.dumps({"case": case, "tests_run": result.testsRun, "failure_count": len(result.failures), "error_count": len(result.errors), "skipped": result.skipped, "failures": [{"test": str(t), "traceback": tb} for t, tb in result.failures], "errors": [{"test": str(t), "traceback": tb} for t, tb in result.errors], "success": result.wasSuccessful(), "loaded_source_modules": loaded}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
