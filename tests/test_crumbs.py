"""End-to-end tests for crumbs against a synthetic repo."""

import os
import tempfile
import unittest
from pathlib import Path

# Isolate the store before importing modules that read CRUMBS_HOME lazily.
_TMP = tempfile.mkdtemp(prefix="crumbs-test-")
os.environ["CRUMBS_HOME"] = _TMP

from crumbs import digest, extractors, indexer, mcp, query, store  # noqa: E402


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


class TestHierarchicalMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp(prefix="hier-repo-"))
        make_repo(cls.repo)
        cls.data = indexer.index_repo(str(cls.repo), name="hier")
        cls.rid = store.repo_id(str(cls.repo))

    def test_overview_lists_directories_with_counts(self):
        out = digest.repo_overview(self.rid)
        self.assertIn("src/", out)
        # Counts the two source files under src/, without dumping signatures.
        self.assertIn("2 files", out)
        self.assertNotIn("def login", out)

    def test_path_filter_scopes_to_subtree(self):
        out = digest.repo_map(self.rid, path="src")
        self.assertIn("scope: src/", out)
        self.assertIn("login", out)

    def test_path_filter_unknown_dir_is_friendly(self):
        out = digest.repo_map(self.rid, path="does/not/exist")
        self.assertIn("no indexed files under", out)
        self.assertNotIn("### ", out)

    def test_small_repo_auto_maps_full(self):
        # Under the threshold, the default view is the complete map.
        out = digest.auto_map(self.rid)
        self.assertIn("login", out)

    def test_large_repo_defaults_to_overview(self):
        big = Path(tempfile.mkdtemp(prefix="big-repo-"))
        pkg = big / "pkg"
        pkg.mkdir(parents=True)
        for i in range(digest.OVERVIEW_THRESHOLD + 5):
            (pkg / f"mod{i}.py").write_text(f"def fn{i}():\n    return {i}\n")
        indexer.index_repo(str(big), name="big")
        rid = store.repo_id(str(big))
        auto = digest.auto_map(rid)
        self.assertIn("pkg/", auto)
        self.assertNotIn("def fn0", auto)  # overview omits signatures
        # --full / full=True forces the complete map.
        full = digest.repo_map(rid)
        self.assertIn("fn0", full)
        # The overview is strictly smaller than the full map.
        self.assertLess(len(auto), len(full))


class TestVisibility(unittest.TestCase):
    """#5 -- symbols are tagged public/internal and maps lead with the API."""

    def test_python_visibility(self):
        syms = extractors.extract("a.py", "def pub():\n pass\ndef _hidden():\n pass\n")
        vis = {s["name"]: s["vis"] for s in syms}
        self.assertEqual(vis, {"pub": "public", "_hidden": "internal"})

    def test_js_export_is_public(self):
        syms = extractors.extract(
            "a.ts", "export function shown(){}\nfunction hidden(){}\n"
        )
        vis = {s["name"]: s["vis"] for s in syms}
        self.assertEqual(vis["shown"], "public")
        self.assertEqual(vis["hidden"], "internal")

    def test_go_capitalization(self):
        syms = extractors.extract("a.go", "func Exported() {}\nfunc unexported() {}\n")
        vis = {s["name"]: s["vis"] for s in syms}
        self.assertEqual(vis["Exported"], "public")
        self.assertEqual(vis["unexported"], "internal")

    def test_rust_pub(self):
        syms = extractors.extract("a.rs", "pub fn open() {}\nfn closed() {}\n")
        vis = {s["name"]: s["vis"] for s in syms}
        self.assertEqual(vis["open"], "public")
        self.assertEqual(vis["closed"], "internal")

    def test_map_leads_with_public_and_marks_internal(self):
        repo = Path(tempfile.mkdtemp(prefix="vis-repo-"))
        repo.mkdir(exist_ok=True)
        (repo / "m.py").write_text(
            "def _early_internal():\n pass\ndef late_public():\n pass\n"
        )
        indexer.index_repo(str(repo), name="vis")
        rid = store.repo_id(str(repo))
        out = digest.repo_map(rid)
        # Public symbol is rendered before the internal one despite coming later
        # in source, and the internal one carries a marker.
        self.assertLess(out.index("late_public"), out.index("_early_internal"))
        self.assertIn("·internal", out)


class TestRetrieval(unittest.TestCase):
    """#4 -- identifier splitting, stemming, and TF-IDF ranking."""

    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp(prefix="retr-repo-"))
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src" / "a.py").write_text(
            "def loginUser(name):\n"
            '    """Authenticate by name."""\n'
            "    return name\n\n"
            "def parseClasses(text):\n"
            '    """Parse class definitions."""\n'
            "    return text\n\n"
            "def helper():\n"
            '    """Common shared helper used everywhere."""\n'
            "    return 1\n"
        )
        indexer.index_repo(str(cls.repo), name="retr")

    def test_camelcase_subterm_match(self):
        # "login" should find loginUser even though the token is camelCase.
        names = [h["name"] for h in query.search("login", repo="retr")]
        self.assertIn("loginUser", names)

    def test_stemming_matches_inflection(self):
        # "class" (singular) should find parseClasses ("Classes" plural).
        names = [h["name"] for h in query.search("class", repo="retr")]
        self.assertIn("parseClasses", names)

    def test_exact_name_still_ranks_first(self):
        hits = query.search("loginUser", repo="retr")
        self.assertEqual(hits[0]["name"], "loginUser")

    def test_tfidf_prefers_rare_terms(self):
        # "parse" is specific to one symbol; it should outrank a query word that
        # also appears but is diluted. parseClasses must top a "parse" search.
        hits = query.search("parse", repo="retr")
        self.assertEqual(hits[0]["name"], "parseClasses")


class TestStaleness(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="stale-repo-"))
        make_repo(self.repo)
        self.data = indexer.index_repo(str(self.repo), name="stale")

    def test_fresh_index_is_not_stale(self):
        self.assertFalse(indexer.is_stale(self.data))

    def test_new_file_marks_index_stale(self):
        # Write a file whose mtime is newer than the recorded index time.
        new_file = self.repo / "src" / "added.py"
        new_file.write_text("def freshly_added():\n    return 1\n")
        os.utime(new_file, (self.data["indexed_at"] + 10, self.data["indexed_at"] + 10))
        self.assertTrue(indexer.is_stale(self.data))

    def test_map_auto_reindexes_when_stale(self):
        new_file = self.repo / "src" / "later.py"
        new_file.write_text("def added_later():\n    return 2\n")
        os.utime(new_file, (self.data["indexed_at"] + 10, self.data["indexed_at"] + 10))
        # crumbs_map should detect staleness and pick up the new symbol.
        out = mcp._tool_map({"repo": str(self.repo)})
        self.assertIn("added_later", out)

    def test_missing_path_is_not_stale(self):
        ghost = dict(self.data, path="/nonexistent/path/xyz")
        self.assertFalse(indexer.is_stale(ghost))


class TestMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp(prefix="mcp-repo-"))
        make_repo(cls.repo)
        indexer.index_repo(str(cls.repo), name="mcpdemo")

    def test_initialize_handshake(self):
        resp = mcp._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "crumbs")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_notification_returns_none(self):
        self.assertIsNone(mcp._handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list(self):
        resp = mcp._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("crumbs_map", names)
        self.assertIn("crumbs_search", names)

    def test_tools_call_search(self):
        resp = mcp._handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "crumbs_search", "arguments": {"query": "login"}}})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("login", resp["result"]["content"][0]["text"])

    def test_unknown_tool_is_error(self):
        resp = mcp._handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                            "params": {"name": "nope", "arguments": {}}})
        self.assertIn("error", resp)

    def test_unknown_method(self):
        resp = mcp._handle({"jsonrpc": "2.0", "id": 5, "method": "bogus/method"})
        self.assertEqual(resp["error"]["code"], mcp.METHOD_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
