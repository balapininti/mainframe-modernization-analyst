import os
import re
import tempfile
import unittest

from mma.config import init_workspace
from mma.datadict import java_type, write_datadict
from mma.facts import program_facts, read_source
from mma.flows import write_flow
from mma.gaps import RecordError
from mma.planning import write_mapping, write_plan
from mma.slices import build_slices, load_slices, name_slice

from .helpers import sample_workspace
from .test_inventory import run_all


def pgm(name, *calls):
    body = "".join("           CALL '%s'.\n" % c for c in calls)
    return "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. %s.\n       PROCEDURE DIVISION.\n       A.\n%s           GOBACK.\n" % (name, body)


def job(name, *programs):
    steps = "".join("//S%d EXEC PGM=%s\n" % (i, p) for i, p in enumerate(programs))
    return "//%s JOB (A)\n%s" % (name, steps)


def synthetic(test, files):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    src = os.path.join(tmp.name, "src")
    os.makedirs(src)
    for name, text in files.items():
        with open(os.path.join(src, name), "w") as f:
            f.write(text)
    ws = init_workspace(tmp.name, ["src"])
    run_all(ws)
    return ws


class SliceTests(unittest.TestCase):
    def test_sample_slices(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        slices = {s["id"]: s for s in build_slices(ws)["slices"]}
        self.assertEqual(slices["SLICE-ORD1"]["programs"], ["ORDENTRY", "PRICECHK"])
        self.assertIn("ORDERS", slices["SLICE-ORD1"]["tables"])
        self.assertIn("BILLCALC", slices["SLICE-NITEBILL"]["programs"])
        self.assertIn("PROD.CUST.MASTER", slices["SLICE-NITEBILL"]["datasets"])

    def test_widely_shared_program_does_not_merge_flows(self):
        files = {"COMMON": pgm("COMMON")}
        for i in range(6):
            files["PGM%d" % i] = pgm("PGM%d" % i, "COMMON")
            files["JOB%d" % i] = job("JOB%d" % i, "PGM%d" % i)
        ws = synthetic(self, files)
        result = build_slices(ws)
        self.assertEqual(len(result["slices"]), 6)
        self.assertEqual(result["shared_programs"], ["COMMON"])
        self.assertEqual(result["slices"][0]["shared_programs"], ["COMMON"])

    def test_entry_program_stays_in_its_slice_even_when_widely_called(self):
        files = {"MENU": pgm("MENU"), "APP.csd": " DEFINE TRANSACTION(MN00) GROUP(G) PROGRAM(MENU)\n"}
        for i in range(6):
            files["PGM%d" % i] = pgm("PGM%d" % i, "MENU")
            files["JOB%d" % i] = job("JOB%d" % i, "PGM%d" % i)
        ws = synthetic(self, files)
        slices = {s["id"]: s for s in build_slices(ws)["slices"]}
        self.assertEqual(slices["SLICE-MN00"]["programs"], ["MENU"])
        self.assertEqual(slices["SLICE-JOB0"]["shared_programs"], ["MENU"])

    def test_oversized_cluster_split_by_entry_point(self):
        files = {"LIB": pgm("LIB"), "JA": job("JA", "A1"), "JB": job("JB", "B1"), "A1": pgm("A1", "LIB"), "B1": pgm("B1", "LIB")}
        ws = synthetic(self, files)
        ws.config["max_slice_programs"] = 2
        ws.save()
        self.assertEqual(len(build_slices(ws)["slices"]), 2)

    def test_programs_with_no_entry_are_listed(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        self.assertIn("ORPHAN", build_slices(ws)["unassigned"])

    def test_business_name_survives_rebuild(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        name_slice(ws, "SLICE-ORD1", "Order entry")
        build_slices(ws)
        self.assertEqual({s["id"]: s for s in load_slices(ws)["slices"]}["SLICE-ORD1"]["business_name"], "Order entry")


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.ws, _ = sample_workspace(self)
        run_all(self.ws)
        build_slices(self.ws)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def test_flow_from_transaction_reaches_data(self):
        text = self.read(write_flow(self.ws, "ORD1"))
        self.assertIn("```mermaid", text)
        self.assertIn("flowchart", text)
        for name in ("ORD1", "ORDENTRY", "PRICECHK", "ORDERS"):
            self.assertIn(name, text)

    def test_missing_nodes_and_inferred_edges_are_visible(self):
        text = self.read(write_flow(self.ws, "NITEBILL"))
        self.assertIn("PRICELIB", text)
        self.assertIn("not found", text)
        self.assertIn("-.->", text)

    def test_incomplete_flow_says_so_first(self):
        text = self.read(write_flow(self.ws, "ORD1"))
        self.assertLess(text.index("Incomplete"), text.index("```mermaid"))
        self.assertIn("MISSCPY", text)

    def test_flow_lists_evidence(self):
        self.assertIn("BILLCALC.cbl", self.read(write_flow(self.ws, "NITEBILL")))

    def test_mermaid_ids_are_safe(self):
        text = self.read(write_flow(self.ws, "NITEBILL"))
        block = text.split("```mermaid")[1].split("```")[0]
        for line in block.splitlines():
            m = re.match(r"\s*(\S+?)[\[\(]", line)
            if m:
                self.assertRegex(m.group(1), r"^n\d+$")

    def test_flow_shows_utility_steps_and_their_data(self):
        text = self.read(write_flow(self.ws, "NITEBILL"))
        block = text.split("```mermaid")[1].split("```")[0]
        for name in ("SORT", "PROD.ORDERS.DAILY", "PROD.ORDERS.SORTED"):
            self.assertIn(name, block)

    def test_flow_lists_logic_outside_programs_with_control_cards(self):
        text = self.read(write_flow(self.ws, "NITEBILL"))
        self.assertIn("Logic outside the programs", text)
        self.assertIn("sort_step", text)
        self.assertIn("jcl_cond", text)
        self.assertIn("SORT FIELDS=(1,5,CH,A)", text)

    def test_quote_setting_removes_control_cards_from_flow(self):
        self.ws.config["quote_source"] = False
        self.ws.save()
        text = self.read(write_flow(self.ws, "NITEBILL"))
        self.assertIn("sort_step", text)
        self.assertNotIn("SORT FIELDS=(1,5,CH,A)", text)

    def test_unknown_entry_gives_plain_error(self):
        with self.assertRaisesRegex(RecordError, "NOPE"):
            write_flow(self.ws, "NOPE")

    def test_flow_from_slice(self):
        self.assertIn("PRICECHK", self.read(write_flow(self.ws, "SLICE-ORD1")))

    def test_huge_flow_is_trimmed_and_says_so(self):
        files = {"ROOT": pgm("ROOT", *["P%d" % i for i in range(80)]), "J": job("J", "ROOT")}
        ws = synthetic(self, files)
        text = self.read(write_flow(ws, "J", max_nodes=20))
        self.assertIn("trimmed", text)
        self.assertLessEqual(len(re.findall(r"^\s*n\d+[\[\(]", text, re.M)), 20)


class FactsTests(unittest.TestCase):
    def setUp(self):
        self.ws, _ = sample_workspace(self)
        run_all(self.ws)

    def test_program_facts_join_callers_and_callees(self):
        facts = program_facts(self.ws, "PRICECHK")
        self.assertIn("program:ORDENTRY", [c["from"] for c in facts["callers"]])
        self.assertEqual(facts["state"], "incomplete")
        self.assertIn("MISSCPY", facts["copybooks"])

    def test_paragraph_flow_is_mermaid(self):
        text = program_facts(self.ws, "BILLCALC")["paragraph_flow"]
        self.assertIn("flowchart", text)
        self.assertIn("3200-APPLY-DISC", text)

    def test_trimmed_paragraph_flow_uses_a_valid_mermaid_comment(self):
        paragraphs = "".join("       P%03d.\n           GOBACK.\n" % i for i in range(70))
        ws = synthetic(self, {"BIGPGM": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. BIGPGM.\n       PROCEDURE DIVISION.\n" + paragraphs})
        last = program_facts(ws, "BIGPGM")["paragraph_flow"].splitlines()[-1]
        self.assertTrue(last.strip().startswith("%%"), last)

    def test_hazards_explained_for_java(self):
        checks = program_facts(self.ws, "BILLCALC")["hidden_behaviour"]
        comp3 = [c for c in checks if c["type"] == "comp3"][0]
        self.assertIn("BigDecimal", comp3["java_note"])
        self.assertIn(21, comp3["lines"])

    def test_jcl_member_lists_steps_and_outside_logic(self):
        facts = program_facts(self.ws, "NITEBILL")
        self.assertEqual(facts["kind"], "jcl_job")
        self.assertIn("sort_step", [c["type"] for c in facts["hidden_behaviour"]])
        self.assertEqual(facts["steps"][1]["program"], "BILLCALC")

    def test_read_paragraph_has_true_line_numbers(self):
        text = read_source(self.ws, "BILLCALC", paragraph="3200-APPLY-DISC")
        self.assertIn("44:", text)
        self.assertIn("COMPUTE WS-TOTAL ROUNDED", text)
        self.assertNotIn("9000-CLOSE", text)

    def test_read_source_is_capped(self):
        ws = synthetic(self, {"BIG": "       PROCEDURE DIVISION.\n" + "       A.\n" * 5000})
        self.assertIn("more lines", read_source(ws, "BIG", limit=100))

    def test_read_source_unknown_paragraph(self):
        with self.assertRaisesRegex(RecordError, "NOPARA"):
            read_source(self.ws, "BILLCALC", paragraph="NOPARA")

    def test_unknown_program_plain_error(self):
        with self.assertRaisesRegex(RecordError, "NOPE"):
            program_facts(self.ws, "NOPE")


class DataDictTests(unittest.TestCase):
    def test_java_types(self):
        cases = [
            ({"pic": "X(5)", "digits": None, "scale": None, "usage": None, "is_group": False, "occurs": None, "alphanumeric": True}, "String"),
            ({"pic": "S9(7)V99", "digits": 9, "scale": 2, "usage": "COMP-3", "is_group": False, "occurs": None, "alphanumeric": False}, "BigDecimal (scale 2)"),
            ({"pic": "9(4)", "digits": 4, "scale": 0, "usage": None, "is_group": False, "occurs": None, "alphanumeric": False}, "Integer"),
            ({"pic": "9(12)", "digits": 12, "scale": 0, "usage": None, "is_group": False, "occurs": None, "alphanumeric": False}, "Long"),
            ({"pic": "9(30)", "digits": 30, "scale": 0, "usage": None, "is_group": False, "occurs": None, "alphanumeric": False}, "BigInteger"),
        ]
        for field, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(java_type(field), expected)

    def test_dictionary_flags_traps(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        data = write_datadict(ws, "CUSTREC")
        fields = {f["name"]: f for f in data["fields"]}
        self.assertEqual(fields["CUST-BAL"]["java_type"], "BigDecimal (scale 2)")
        self.assertTrue(any("REDEFINES" in t for t in fields["CUST-DATE-X"]["traps"]))
        self.assertTrue(any("date" in t.lower() for t in fields["CUST-DATE"]["traps"]))
        self.assertEqual(fields["CUST-RATING"]["conditions"][0]["name"], "CUST-PREFERRED")
        self.assertEqual(fields["CUST-ITEM"]["java_type"], "List<CustItem>")
        with open(ws.path("data", "CUSTREC.md")) as f:
            self.assertIn("CUST-BAL", f.read())

    def test_missing_copybook_plain_error(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        with self.assertRaisesRegex(RecordError, "MISSCPY"):
            write_datadict(ws, "MISSCPY")


class PlanTests(unittest.TestCase):
    def read(self, ws, *parts):
        with open(ws.path(*parts)) as f:
            return f.read()

    def test_dependencies_come_first_in_migration_order(self):
        files = {"JA": job("JA", "A1"), "JB": job("JB", "B1"), "A1": pgm("A1", "B1"), "B1": pgm("B1")}
        ws = synthetic(self, files)
        ws.config["max_slice_programs"] = 1
        ws.save()
        build_slices(ws)
        order = [s["id"] for s in write_plan(ws)["order"]]
        self.assertLess(order.index("SLICE-JB"), order.index("SLICE-JA"))

    def test_cycles_do_not_hang_and_are_reported(self):
        files = {"JA": job("JA", "A1"), "JB": job("JB", "B1"), "A1": pgm("A1", "B1"), "B1": pgm("B1", "A1")}
        ws = synthetic(self, files)
        ws.config["max_slice_programs"] = 1
        ws.save()
        build_slices(ws)
        plan = write_plan(ws)
        self.assertEqual(len(plan["order"]), 2)
        self.assertIn("depend on each other", self.read(ws, "mapping", "migration-order.md"))

    def test_complexity_rises_with_risky_constructs(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        scores = write_plan(ws)["complexity"]
        self.assertGreater(scores["BILLCALC"], scores["ORPHAN"])

    def test_dead_code_labeled_as_candidates_only(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        write_plan(ws)
        text = self.read(ws, "mapping", "dead-code-candidates.md")
        self.assertIn("ORPHAN", text)
        self.assertIn("UNUSED", text)
        self.assertIn("8000-NEVER-USED", text)
        self.assertIn("candidates", text.lower())
        self.assertIn("runtime", text)
        self.assertNotIn("ORDENTRY ", text)

    def test_mapping_is_a_suggestion_with_watch_outs(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        text = self.read(ws, *os.path.relpath(write_mapping(ws, "SLICE-NITEBILL"), ws.out).split(os.sep))
        self.assertIn("Spring Batch", text)
        self.assertIn("suggestion", text.lower())
        self.assertIn("restart", text.lower())
        self.assertIn("NITEBILL", text)

    def test_mapping_covers_utility_steps(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        with open(write_mapping(ws, "SLICE-NITEBILL")) as f:
            text = f.read()
        self.assertIn("SORT step", text)

    def test_mapping_covers_online_flow(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        build_slices(ws)
        with open(write_mapping(ws, "SLICE-ORD1")) as f:
            text = f.read()
        self.assertIn("REST controller", text)
        self.assertIn("COMMAREA", text)


if __name__ == "__main__":
    unittest.main()
