"""End-to-end tests for crumbs against a synthetic repo."""

import os
import tempfile
import unittest
from pathlib import Path

# Isolate the store before importing modules that read CRUMBS_HOME lazily.
_TMP = tempfile.mkdtemp(prefix="crumbs-test-")
os.environ["CRUMBS_HOME"] = _TMP

from crumbs import digest, extractors, indexer, query, store  # noqa: E402


def make_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        '"""Auth helpers."""\n\n'
        "import os\n\n"
        "def login(user, password):\n"
        '    """Authenticate a user."""\n'
        "    # body is intentionally substantial so source clearly exceeds the map\n"
        "    attempts = 0\n"
        "    while attempts < 3:\n"
        "        if password and user:\n"
        "            token = os.urandom(16).hex()\n"
        "            return token\n"
        "        attempts += 1\n"
        "    return None\n\n"
        "class TokenStore:\n"
        '    """Holds tokens."""\n'
        "    def save(self, t):\n"
        "        self._tokens.append(t)\n"
        "        return len(self._tokens)\n"
        "    def _private(self): pass\n"
    )
    (root / "src" / "api.ts").write_text(
        "export function createServer() {}\n"
        "export const PORT = 3000;\n"
        "export interface Config { port: number }\n"
    )
    (root / "README.md").write_text("# Demo\n\nA demo repo for crumbs.\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("function shouldBeIgnored(){}\n")


class TestExtractors(unittest.TestCase):
    def test_python_signatures(self):
        text = (root_text := Path(__file__).read_text())  # any python file
        syms = extractors.extract("x.py", text)
        names = {s["name"] for s in syms}
        self.assertIn("make_repo", names)

    def test_python_class_methods(self):
        syms = extractors.extract("a.py", "class C:\n def pub(self): pass\n def _p(self): pass\n")
        cls = [s for s in syms if s["kind"] == "class"][0]
        self.assertIn("pub", cls["doc"])
        self.assertNotIn("_p", cls["doc"])

    def test_typescript(self):
        syms = extractors.extract("a.ts", "export function go(){}\nexport interface Cfg{}\n")
        names = {s["name"] for s in syms}
        self.assertEqual(names, {"go", "Cfg"})

    @unittest.skipUnless(hasattr(__import__("ast"), "unparse"), "needs ast.unparse (3.9+)")
    def test_python_type_signature(self):
        src = "def f(a: int, b: str = 'x', *, c: bool = False) -> dict:\n    pass\n"
        sym = extractors.extract("a.py", src)[0]
        self.assertEqual(sym["sig"], "def f(a: int, b: str = 'x', *, c: bool = False) -> dict")

    def test_symbol_line_numbers(self):
        src = "import os\n\n\ndef first():\n    pass\n\n\ndef second():\n    pass\n"
        syms = extractors.extract("a.py", src)
        by_name = {s["name"]: s for s in syms}
        self.assertEqual(by_name["first"]["line"], 4)
        self.assertEqual(by_name["second"]["line"], 8)
        self.assertGreaterEqual(by_name["first"]["end_line"], by_name["first"]["line"])


class TestIndexAndQuery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp(prefix="demo-repo-"))
        make_repo(cls.repo)
        cls.data = indexer.index_repo(str(cls.repo), name="demo")

    def test_ignores_node_modules(self):
        paths = {f["path"] for f in self.data["files"]}
        self.assertNotIn("node_modules/junk.js", paths)

    def test_indexed_symbols(self):
        all_names = {
            s["name"] for f in self.data["files"] for s in f["symbols"]
        }
        self.assertIn("login", all_names)
        self.assertIn("TokenStore", all_names)
        self.assertIn("createServer", all_names)

    def test_registry_roundtrip(self):
        rid = store.repo_id(str(self.repo))
        self.assertIsNotNone(store.load_repo(rid))
        self.assertEqual(store.resolve("demo"), rid)

    def test_search_ranks_exact_name(self):
        hits = query.search("login")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["name"], "login")

    def test_map_is_smaller_than_source(self):
        rid = store.repo_id(str(self.repo))
        m = digest.repo_map(rid)
        sav = digest.savings(self.data, m)
        self.assertLessEqual(sav["map_tokens"], sav["source_tokens"])
        self.assertIn("login", m)

    def test_context_output(self):
        out = query.context("token")
        self.assertIn("demo", out)


if __name__ == "__main__":
    unittest.main()
