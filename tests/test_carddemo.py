"""Checks against AWS CardDemo, a real mainframe sample. Set MMA_CARDDEMO to its app folder to run.

Expected values come from independent line-by-line scans here, never from the skill's own parsers.
"""
import os
import re
import shutil
import tempfile
import unittest

from mma.config import init_workspace
from mma.depmap import build_map, load_map
from mma.gaps import detect_gaps, load_gaps
from mma.inventory import load_catalogue, run_inventory
from mma.records import record_analysis, stale, status
from mma.slices import build_slices

APP = os.environ.get("MMA_CARDDEMO")


def code_lines(path):
    with open(path, errors="replace") as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if len(line) > 6 and line[6] not in "*/":
                yield number, line[7:72]


def scan_all(ws):
    run_inventory(ws)
    build_map(ws)
    detect_gaps(ws)
    build_slices(ws)


@unittest.skipUnless(APP, "set MMA_CARDDEMO to run")
class CardDemoAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = init_workspace(cls.tmp.name, [APP])
        scan_all(cls.ws)
        cls.map = load_map(cls.ws)
        cls.catalogue = load_catalogue(cls.ws)
        cls.by_path = {m["path"]: m for m in cls.catalogue}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cobol_files(self):
        return [m for m in self.catalogue if m["kind"] == "cobol_program"]

    def edges_from(self, node, types):
        return {e["to"].partition(":")[2] for e in self.map["edges"] if e["from"] == node and e["type"] in types}

    def test_every_cbl_file_is_a_program(self):
        folder = os.path.join(APP, "cbl")
        found = {m["name"] for m in self.cobol_files()}
        for name in os.listdir(folder):
            if name.lower().endswith(".cbl"):
                self.assertIn(name.split(".")[0].upper(), found)

    def test_every_jcl_file_is_jcl(self):
        folder = os.path.join(APP, "jcl")
        kinds = {m["path"].rsplit("/", 1)[-1]: m["kind"] for m in self.catalogue}
        for name in os.listdir(folder):
            if name.lower().endswith(".jcl"):
                self.assertIn(kinds[name], ("jcl_job", "jcl_proc"), name)

    def test_copybook_edges_match_independent_scan(self):
        for member in self.cobol_files():
            expected = set()
            for _, code in code_lines(self.ws.abs(member["path"])):
                m = re.match(r"^\s*COPY\s+'?([A-Za-z0-9#@$-]+)", code)
                if m:
                    expected.add(m.group(1).upper())
            found = self.edges_from("program:" + member["name"], {"copies"})
            system = {n for n in expected if n.startswith(("DFH", "CMQ"))} | {"SQLCA", "SQLDA"}
            self.assertEqual(expected - system, {f for f in found if f in expected} - system, member["name"])
            self.assertTrue(expected - system <= found, member["name"])

    def test_static_calls_match_independent_scan(self):
        total = 0
        for member in self.cobol_files():
            expected = set()
            for _, code in code_lines(self.ws.abs(member["path"])):
                m = re.search(r"(?<![\w-])CALL\s+'([A-Za-z0-9#@$-]+)'", code)
                if m and not re.match(r"^\s*(DISPLAY|MOVE)\b", code) and "'CALL" not in code:
                    expected.add(m.group(1).upper())
            found = self.edges_from("program:" + member["name"], {"calls"})
            expected = {n for n in expected if not n.startswith(("CEE", "MQ")) and n not in ("CBLTDLI", "AIBTDLI", "DSNTIAR")}
            self.assertTrue(expected <= found, "%s: %s not in %s" % (member["name"], expected, found))
            total += len(expected)
        self.assertGreater(total, 3)

    def test_cics_and_sql_statement_counts_match(self):
        from mma.inventory import load_facts
        for member in self.cobol_files():
            cics = sql = 0
            for _, code in code_lines(self.ws.abs(member["path"])):
                cics += len(re.findall(r"(?<![\w-])EXEC\s+CICS(?![\w-])", code, re.I))
                sql += len(re.findall(r"(?<![\w-])EXEC\s+SQL(?![\w-])", code, re.I))
            facts = load_facts(self.ws, member)
            self.assertEqual(cics, len(facts["cics"]), member["name"] + " CICS")
            parsed_sql = sum(1 for s in facts["sql"]) + sum(1 for u in facts["unrecognized"] if u.startswith("EXEC SQL"))
            self.assertLessEqual(parsed_sql, sql, member["name"] + " SQL")
            self.assertGreaterEqual(parsed_sql + 40, sql, member["name"] + " SQL")

    def test_every_program_transfer_gives_a_link_or_a_gap(self):
        """Nothing may vanish silently: each LINK or XCTL produces a link, or an open item for its program."""
        from mma.inventory import load_facts
        dynamic = {(d["from"], d["line"]) for d in self.map["dynamic"]}
        checked = 0
        for member in self.cobol_files():
            node = "program:" + member["name"]
            for statement in load_facts(self.ws, member)["cics"]:
                if statement["verb"] not in ("LINK", "XCTL"):
                    continue
                checked += 1
                self.assertIn("PROGRAM", statement["options"], "%s line %d" % (member["name"], statement["line"]))
                linked = any(e["from"] == node and e["type"] in ("links", "transfers_to") and
                             (e["line"] == statement["line"] or e["count"] > 1) for e in self.map["edges"])
                self.assertTrue(linked or (node, statement["line"]) in dynamic, "%s line %d" % (member["name"], statement["line"]))
        self.assertGreater(checked, 10)

    def test_menu_table_reported_as_runtime_value(self):
        gaps = {g["name"] for g in load_gaps(self.ws) if g["kind"] == "dynamic_reference"}
        self.assertIn("COMEN01C:CDEMO-MENU-OPT-PGMNAME", gaps)

    def test_jcl_program_steps_match_independent_scan(self):
        for member in self.catalogue:
            if member["kind"] not in ("jcl_job", "jcl_proc"):
                continue
            with open(self.ws.abs(member["path"]), errors="replace") as f:
                expected = {m.group(1).upper() for line in f if not line.startswith("//*")
                            for m in [re.match(r"^//\S*\s+EXEC\s+PGM=([A-Za-z0-9#@$]+)", line)] if m}
            found = set()
            prefix = "job:" if member["kind"] == "jcl_job" else "proc:"
            for edge in self.map["edges"]:
                if edge["from"].startswith(prefix) and edge["file"] == member["path"] and edge["type"] == "runs_program":
                    found.add(edge["to"].partition(":")[2])
            system = re.compile(r"^(SORT|IDCAMS|IEF|IEB|IEH|IKJ|ICE|DFH|DFS|DSN|SDSF|FTP)")
            self.assertEqual({n for n in expected if not system.match(n)}, {n for n in found if n in expected and not system.match(n)}, member["path"])

    def test_every_csd_transaction_found(self):
        path = os.path.join(APP, "csd", "CARDDEMO.CSD")
        with open(path, errors="replace") as f:
            expected = set(re.findall(r"DEFINE\s+TRANSACTION\((\w+)\)", f.read()))
        self.assertGreater(len(expected), 5)
        found = {e["from"].partition(":")[2] for e in self.map["edges"] if e["type"] == "starts"}
        self.assertTrue(expected <= found | set(self.map["present"]["transaction"]))

    def test_every_citation_points_at_its_target(self):
        """The anti-hallucination check: the cited line really mentions the thing it's cited for."""
        checked = wrong = 0
        problems = []
        cache = {}
        for edge in self.map["edges"]:
            if edge["confidence"] != "confirmed" or edge["type"] not in ("calls", "copies", "links", "transfers_to", "runs_program", "runs_proc"):
                continue
            path = self.ws.abs(edge["file"])
            if path not in cache:
                with open(path, errors="replace") as f:
                    cache[path] = f.read().splitlines()
            window = " ".join(cache[path][edge["line"] - 1:edge["line"] + 3]).upper()
            target = edge["to"].partition(":")[2]
            checked += 1
            if target not in window:
                wrong += 1
                problems.append("%s line %s: %s" % (edge["file"], edge["line"], target))
        self.assertGreater(checked, 100)
        self.assertEqual(problems, [])

    def test_missing_items_are_really_missing(self):
        names = {m["name"] for m in self.catalogue}
        for node in self.map["missing"]:
            self.assertNotIn(node.partition(":")[2], names, node)

    def test_mainframe_garbage_never_becomes_a_name(self):
        for gap in load_gaps(self.ws):
            if gap["kind"] in ("missing_program", "missing_copybook", "missing_proc", "missing_bms_map"):
                self.assertRegex(gap["name"], r"^[A-Z0-9#@$-]{1,30}$")


@unittest.skipUnless(APP, "set MMA_CARDDEMO to run")
class CardDemoVariants(unittest.TestCase):
    """The same system, damaged the ways real extracts are, must give the same map."""

    def baseline(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = os.path.join(tmp.name, "src")
        os.makedirs(src)
        for folder in ("cbl", "cpy", "jcl", "bms", "csd"):
            shutil.copytree(os.path.join(APP, folder), os.path.join(src, folder))
        return tmp.name, src

    def edge_set(self, root):
        ws = init_workspace(root, ["src"])
        scan_all(ws)
        return {(e["from"], e["type"], e["to"], e["line"]) for e in load_map(ws)["edges"]}

    def rewrite(self, src, change):
        for folder, _, files in os.walk(src):
            for name in files:
                if name.startswith("."):
                    continue
                path = os.path.join(folder, name)
                with open(path, "rb") as f:
                    data = f.read()
                result = change(name, data)
                target = result[0] if isinstance(result, tuple) else path
                content = result[1] if isinstance(result, tuple) else result
                if target != path:
                    os.remove(path)
                    target = os.path.join(folder, target)
                with open(target, "wb") as f:
                    f.write(content)

    def assertSameMap(self, change):
        root, src = self.baseline()
        expected = self.edge_set(root)
        shutil.rmtree(os.path.join(root, "modernization"))
        self.rewrite(src, change)
        actual = self.edge_set(root)
        self.assertEqual(sorted(expected - actual)[:10], [])
        self.assertEqual(sorted(actual - expected)[:10], [])
        self.assertGreater(len(expected), 100)

    def test_crlf(self):
        self.assertSameMap(lambda n, d: d.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    def test_no_file_extensions(self):
        self.assertSameMap(lambda n, d: (n.split(".")[0], d))

    def test_ebcdic_with_line_breaks(self):
        self.assertSameMap(lambda n, d: d.decode("latin-1").encode("cp037", "replace"))

    def test_ebcdic_fixed_records_with_no_line_breaks(self):
        def change(_, data):
            lines = data.decode("latin-1").replace("\r\n", "\n").split("\n")
            if lines and lines[-1] == "":
                lines.pop()
            return "".join(l[:80].ljust(80) for l in lines).encode("cp037", "replace")
        self.assertSameMap(change)

    def test_lowercase_cobol_keeps_the_same_links(self):
        def change(name, data):
            if name.lower().endswith(".cbl"):
                return re.sub(rb"(?<![\w'-])(CALL|COPY|EXEC CICS|EXEC SQL|PERFORM|MOVE|END-EXEC)(?![\w'-])", lambda m: m.group(0).lower(), data)
            return data
        self.assertSameMap(change)


@unittest.skipUnless(APP, "set MMA_CARDDEMO to run")
class CardDemoGapLoop(unittest.TestCase):
    def test_removed_copybooks_are_found_and_loop_closes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = os.path.join(tmp.name, "src")
        shutil.copytree(APP, src, ignore=shutil.ignore_patterns("data"))
        ws = init_workspace(tmp.name, ["src"])
        scan_all(ws)
        users = {}
        for edge in load_map(ws)["edges"]:
            if edge["type"] == "copies" and edge["from"].startswith("program:"):
                users.setdefault(edge["to"].partition(":")[2], set()).add(edge["from"])
        catalogue = {m["name"]: m for m in load_catalogue(ws) if m["kind"] == "copybook"}
        chosen = sorted((n for n in users if n in catalogue), key=lambda n: -len(users[n]))[:3]
        held = {}
        unrelated = None
        all_users = set().union(*(users[n] for n in chosen))
        for member in load_catalogue(ws):
            node = "program:" + member["name"]
            if member["kind"] == "cobol_program" and node not in all_users:
                unrelated = member["name"]
                break
        analyzed = sorted(users[chosen[0]])[0].partition(":")[2]
        record_analysis(ws, "program", analyzed)
        if unrelated:
            record_analysis(ws, "program", unrelated)
        for name in chosen:
            path = ws.abs(catalogue[name]["path"])
            with open(path, "rb") as f:
                held[path] = f.read()
            os.remove(path)
        scan_all(ws)
        gaps = {g["name"]: g for g in load_gaps(ws) if g["kind"] == "missing_copybook" and g["status"] == "open"}
        for name in chosen:
            gap = gaps[name]
            self.assertEqual(set(gap["blocks"]), users[name])
            self.assertEqual(gap["owner"], "mainframe_team")
            reference = gap["references"][0]
            with open(ws.abs(reference["file"]), errors="replace") as f:
                self.assertIn(name, f.read().splitlines()[reference["line"] - 1].upper())
        self.assertEqual(status(ws, "program", analyzed)["state"], "incomplete")
        for path, data in held.items():
            with open(path, "wb") as f:
                f.write(data)
        scan_all(ws)
        for gap in load_gaps(ws):
            if gap["name"] in chosen:
                self.assertEqual(gap["status"], "resolved")
        self.assertEqual(status(ws, "program", analyzed)["state"], "complete" if not [g for g in status(ws, "program", analyzed)["blocking"]] else "incomplete")
        self.assertNotIn(unrelated, [s["name"] for s in stale(ws)])


if __name__ == "__main__":
    unittest.main()
