"""Inputs from the independent review where the system reported the wrong thing about completeness or links."""
import json
import os
import subprocess
import sys
import unittest

from mma.config import ConfigError, init_workspace
from mma.datadict import write_datadict
from mma.depmap import load_map
from mma.facts import program_facts
from mma.flows import write_flow
from mma.gaps import RecordError, add_sme_question, answer_gap, get_gap, has_cobol_terms, load_gaps, resolve_conflict
from mma.inventory import load_catalogue, member_name, run_inventory
from mma.logs import Logger, LogFieldRejected
from mma.planning import write_mapping, write_plan
from mma.records import add_record, record_analysis, stale, status, validate
from mma.render import render_all
from mma.slices import build_slices

from . import SCRIPTS
from .helpers import sample_workspace
from .test_inventory import run_all
from .test_outputs import job, pgm, synthetic


def cobol(name, *lines, data=()):
    body = "".join("       %s\n" % l for l in lines)
    head = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. %s.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n" % name
    head += "".join("       %s\n" % l for l in data)
    return head + "       PROCEDURE DIVISION.\n       A.\n" + body + "           GOBACK.\n"


def edges(ws):
    return {(e["from"], e["type"], e["to"]) for e in load_map(ws)["edges"]}


def gap_keys(ws, states=("open", "conflict")):
    return {(g["kind"], g["name"]) for g in load_gaps(ws) if g["status"] in states}


class CompletenessTests(unittest.TestCase):
    def test_absent_program_is_incomplete(self):
        ws = synthetic(self, {"P1": pgm("P1", "ABSENT"), "J": job("J", "P1")})
        self.assertEqual(status(ws, "program", "ABSENT")["state"], "incomplete")

    def test_nested_copybook_gap_reaches_the_program(self):
        ws = synthetic(self, {"P1": cobol("P1", data=["COPY OUTER."]), "OUTER.cpy": "       COPY INNER.\n       01 R PIC X.\n", "J": job("J", "P1")})
        self.assertIn("INNER", {g["name"] for g in status(ws, "program", "P1")["blocking"]})

    def test_question_with_a_reference_blocks_that_program(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        path = [m["path"] for m in load_catalogue(ws) if m["name"] == "ORPHAN"][0]
        add_sme_question(ws, question="Is this intended?", example="An example.", depends_on="A rule.", references=[{"file": path, "line": 5}])
        self.assertEqual(status(ws, "program", "ORPHAN")["state"], "incomplete")

    def test_rule_in_conflict_or_unanswered_makes_it_incomplete(self):
        for rule_status in ("conflict", "ask_expert"):
            with self.subTest(rule_status=rule_status):
                ws, _ = sample_workspace(self)
                run_all(ws)
                add_record(ws, "rule", text="A rule.", status=rule_status, evidence=["ORPHAN:0000-MAIN:5-5"], by="X", on="2026-11-04")
                self.assertEqual(status(ws, "program", "ORPHAN")["state"], "incomplete")

    def test_flow_header_agrees_with_status_for_unsupported_and_duplicates(self):
        files = {"P1": cobol("P1", "EXEC DLI GU END-EXEC.", "CALL 'P2'."), "J": job("J", "P1")}
        ws = synthetic(self, files)
        with open(write_flow(ws, "J")) as f:
            text = f.read()
        self.assertIn("Incomplete", text)
        self.assertIn("ims", text)
        self.assertNotIn("No open items", text)

    def test_flow_header_lists_nested_copybook_gap(self):
        ws = synthetic(self, {"P1": cobol("P1", data=["COPY OUTER."]), "OUTER.cpy": "       COPY INNER.\n       01 R PIC X.\n", "J": job("J", "P1")})
        with open(write_flow(ws, "J")) as f:
            self.assertIn("INNER", f.read())

    def test_job_without_a_schedule_is_incomplete(self):
        ws = synthetic(self, {"P1": pgm("P1"), "J": job("J", "P1")})
        self.assertIn("ALL-JOBS", {g["name"] for g in status(ws, "job", "J")["blocking"]})


class CopybookLogicTests(unittest.TestCase):
    FILES = {
        "PMAIN": cobol("PMAIN", "COPY PROCCOPY."),
        "PROCCOPY.cpy": "           EXEC CICS LINK PROGRAM('ERRLOG') END-EXEC.\n           EXEC SQL INSERT INTO AUDIT_T (A) VALUES (1) END-EXEC.\n           CALL 'NOTIFY'.\n",
        "J": job("J", "PMAIN"),
    }

    def test_logic_in_a_copybook_is_on_the_map(self):
        found = edges(synthetic(self, self.FILES))
        self.assertIn(("program:PMAIN", "links", "program:ERRLOG"), found)
        self.assertIn(("program:PMAIN", "calls", "program:NOTIFY"), found)
        self.assertIn(("program:PMAIN", "writes", "table:AUDIT_T"), found)

    def test_copybook_logic_cites_the_copybook(self):
        edge = [e for e in load_map(synthetic(self, self.FILES))["edges"] if e["to"] == "program:NOTIFY"][0]
        self.assertTrue(edge["file"].endswith("PROCCOPY.cpy"))
        self.assertEqual(edge["line"], 3)

    def test_gaps_raised_for_what_a_copybook_calls(self):
        self.assertIn(("missing_program", "NOTIFY"), gap_keys(synthetic(self, self.FILES)))

    def test_hazards_in_copied_layouts_reach_the_program(self):
        ws = synthetic(self, {"P1": cobol("P1", data=["COPY REC1."]), "REC1.cpy": "       01 R.\n          05 B PIC S9(5) COMP-3.\n", "J": job("J", "P1")})
        item = [h for h in program_facts(ws, "P1")["hidden_behaviour"] if h["type"] == "comp3"][0]
        self.assertIn(2, item["copybooks"]["REC1"])
        build_slices(ws)
        with open(write_mapping(ws, "SLICE-J")) as f:
            self.assertIn("COMP-3", f.read())

    def test_extensionless_copied_file_is_treated_as_a_copybook(self):
        ws = synthetic(self, {"P1": cobol("P1", "COPY PLAIN."), "PLAIN": "           CALL 'FROMPLAIN'.\n", "J": job("J", "P1")})
        self.assertEqual({m["name"]: m["kind"] for m in load_catalogue(ws)}["PLAIN"], "copybook")
        self.assertIn(("program:P1", "calls", "program:FROMPLAIN"), edges(ws))


class DynamicLinkTests(unittest.TestCase):
    def test_unusable_literal_still_raises_a_gap(self):
        ws = synthetic(self, {"P1": cobol("P1", "MOVE 'TOOLONGNAME' TO WS-L.", "EXEC CICS XCTL PROGRAM(WS-L) END-EXEC.", data=["01 WS-L PIC X(20)."]), "J": job("J", "P1")})
        self.assertIn(("dynamic_reference", "P1:WS-L"), gap_keys(ws))

    def test_variable_mapset_is_not_replaced_by_the_map_name(self):
        ws = synthetic(self, {"P1": cobol("P1", "EXEC CICS SEND MAP('ORDM1') MAPSET(WS-MS) END-EXEC.", data=["01 WS-MS PIC X(8)."]), "J": job("J", "P1")})
        self.assertNotIn(("missing_bms_map", "ORDM1"), gap_keys(ws))
        self.assertIn(("dynamic_reference", "P1:WS-MS"), gap_keys(ws))

    def test_variable_map_raises_a_gap(self):
        ws = synthetic(self, {"P1": cobol("P1", "EXEC CICS RECEIVE MAP(WS-MP) END-EXEC.", data=["01 WS-MP PIC X(8)."]), "J": job("J", "P1")})
        self.assertIn(("dynamic_reference", "P1:WS-MP"), gap_keys(ws))

    def test_dynamic_sql_raises_a_gap(self):
        ws = synthetic(self, {"P1": cobol("P1", "EXEC SQL PREPARE S1 FROM :WS-S END-EXEC."), "J": job("J", "P1")})
        self.assertIn(("dynamic_reference", "P1:DYNAMIC-SQL"), gap_keys(ws))

    def test_stored_procedure_is_a_link_not_a_dynamic_call(self):
        ws = synthetic(self, {"P1": cobol("P1", "EXEC SQL CALL SP1(:A) END-EXEC."), "J": job("J", "P1")})
        self.assertIn(("program:P1", "calls", "program:SP1"), edges(ws))

    def test_insert_select_edges(self):
        found = edges(synthetic(self, {"P1": cobol("P1", "EXEC SQL INSERT INTO T7 SELECT * FROM T8 END-EXEC."), "J": job("J", "P1")}))
        self.assertIn(("program:P1", "writes", "table:T7"), found)
        self.assertIn(("program:P1", "reads", "table:T8"), found)
        self.assertNotIn(("program:P1", "writes", "table:T8"), found)

    def test_handle_abend_and_queues_are_links(self):
        found = edges(synthetic(self, {"P1": cobol("P1", "EXEC CICS HANDLE ABEND PROGRAM('ERRPGM') END-EXEC.", "EXEC CICS WRITEQ TD QUEUE('Q1') FROM(A) END-EXEC."), "J": job("J", "P1")}))
        self.assertIn(("program:P1", "handles_abend", "program:ERRPGM"), found)
        self.assertIn(("program:P1", "writes", "queue:Q1"), found)

    def test_unknown_exec_block_makes_it_incomplete(self):
        ws = synthetic(self, {"P1": cobol("P1", "EXEC ACMEDB GET X END-EXEC."), "J": job("J", "P1")})
        self.assertIn(("unsupported_technology", "acmedb"), gap_keys(ws))
        self.assertEqual(status(ws, "program", "P1")["state"], "incomplete")


class NameTests(unittest.TestCase):
    def test_program_id_different_from_member_joins_up(self):
        ws = synthetic(self, {"MEMB1.cbl": cobol("REALID", "CALL 'SUBX'."), "SUBX.cbl": pgm("SUBX"), "JX": job("JX", "REALID")})
        found = edges(ws)
        self.assertIn(("job:JX", "runs_program", "program:MEMB1"), found)
        self.assertIn(("program:MEMB1", "calls", "program:SUBX"), found)
        self.assertEqual(status(ws, "program", "REALID")["name"], "MEMB1")
        self.assertIn("MEMB1", build_slices(ws)["slices"][0]["programs"])

    def test_client_program_matching_a_system_prefix(self):
        ws = synthetic(self, {"ICEPAY01.cbl": pgm("ICEPAY01"), "P1": pgm("P1", "ICEPAY01"), "J": job("J", "P1")})
        self.assertIn(("program:P1", "calls", "program:ICEPAY01"), edges(ws))

    def test_absent_program_with_a_client_style_ice_name_is_reported(self):
        self.assertIn(("missing_program", "ICEPAY01"), gap_keys(synthetic(self, {"P1": pgm("P1", "ICEPAY01"), "J": job("J", "P1")})))

    def test_system_names_are_listed_for_review(self):
        ws = synthetic(self, {"P1": pgm("P1", "CEEDAYS"), "J": job("J", "P1")})
        with open(ws.path("inventory", "system-references.md")) as f:
            self.assertIn("CEEDAYS", f.read())

    def test_nested_program_and_entry_are_not_missing(self):
        text = cobol("MAINP", "CALL 'INNERP'.", "CALL 'ALT1'.", "ENTRY 'ALT1'.") + "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INNERP.\n       END PROGRAM INNERP.\n"
        keys = gap_keys(synthetic(self, {"MAINP.cbl": text, "J": job("J", "MAINP")}))
        self.assertNotIn(("missing_program", "INNERP"), keys)
        self.assertNotIn(("missing_program", "ALT1"), keys)

    def test_member_names_from_dataset_style_files(self):
        cases = {"PROD.COBOL.ABC": "ABC", "PROD.COBOL.DEF": "DEF", "ABC.cbl": "ABC", "PROD.COBOL.ABC.cbl": "ABC", "CUSTREC": "CUSTREC", "COPY.LIB(MEMB1)": "MEMB1", "REPROCT.ctl": "REPROCT"}
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(member_name(path), expected)

    def test_program_and_job_with_the_same_name_can_both_be_cited(self):
        ws = synthetic(self, {"ORDERS.cbl": pgm("ORDERS"), "ORDERS.jcl": job("ORDERS", "ORDERS") + "//* A\n" * 20})
        rule = add_record(ws, "rule", text="A rule.", status="inferred", evidence=["ORDERS::20-20"])
        self.assertTrue(rule["evidence"][0]["file"].endswith("ORDERS.jcl"))
        with self.assertRaisesRegex(RecordError, "job/ORDERS"):
            add_record(ws, "rule", text="A rule.", status="inferred", evidence=["ORDERS::1-1"])
        self.assertTrue(add_record(ws, "rule", text="A rule.", status="inferred", evidence=["job/ORDERS::1-1"])["evidence"][0]["file"].endswith("ORDERS.jcl"))
        self.assertEqual(validate(ws), [])


class JclLinkTests(unittest.TestCase):
    def test_control_card_member_with_run_program(self):
        files = {"J": "//J JOB\n//S EXEC PGM=IKJEFT1B\n//SYSTSIN DD DSN=CTL.LIB(RUNCARD),DISP=SHR\n", "RUNCARD": " DSN SYSTEM(X)\n RUN PROGRAM(BATCHP)\n"}
        self.assertIn(("job:J", "runs_program", "program:BATCHP"), edges(synthetic(self, files)))

    def test_every_run_program_is_linked(self):
        files = {"J": "//J JOB\n//S EXEC PGM=IKJEFT1B\n//SYSTSIN DD *\n RUN PROG(FIRST)\n RUN PROGRAM(SECOND)\n/*\n"}
        found = edges(synthetic(self, files))
        self.assertIn(("job:J", "runs_program", "program:FIRST"), found)
        self.assertIn(("job:J", "runs_program", "program:SECOND"), found)

    def test_step_override_of_control_card(self):
        self.assertIn(("missing_control_card", "CARD9"), gap_keys(synthetic(self, {"J": "//J JOB\n//S EXEC PGM=P1\n//PS1.SYSIN DD DSN=CTL.LIB(CARD9),DISP=SHR\n", "P1": pgm("P1")})))

    def test_symbolic_control_member_raises_a_gap(self):
        self.assertIn(("dynamic_reference", "J:&M"), gap_keys(synthetic(self, {"J": "//J JOB\n//S EXEC PGM=P1\n//SYSIN DD DSN=CTL.LIB(&M),DISP=SHR\n", "P1": pgm("P1")})))

    def test_control_file_without_member_raises_a_gap(self):
        self.assertIn(("missing_control_card", "CTL.SEQ.FILE"), gap_keys(synthetic(self, {"J": "//J JOB\n//S EXEC PGM=P1\n//SYSIN DD DSN=CTL.SEQ.FILE,DISP=SHR\n", "P1": pgm("P1")})))

    def test_symbolic_dataset_is_inferred_and_no_vsam_request_for_the_literal(self):
        files = {"J": "//J JOB\n//S EXEC PGM=P1\n//DD1 DD DSN=&HLQ..ORDERS,DISP=SHR\n", "P1": cobol("P1").replace("       DATA DIVISION.\n", "       ENVIRONMENT DIVISION.\n       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO DD1 ORGANIZATION INDEXED.\n       DATA DIVISION.\n")}
        ws = synthetic(self, files)
        self.assertEqual([e["confidence"] for e in load_map(ws)["edges"] if e["to"] == "dataset:&HLQ..ORDERS"], ["inferred"])
        self.assertNotIn(("missing_vsam_def", "&HLQ..ORDERS"), gap_keys(ws))
        self.assertIn(("dynamic_reference", "J:&HLQ..ORDERS"), gap_keys(ws))

    def test_instream_proc_links(self):
        found = edges(synthetic(self, {"J": "//J JOB\n//MYP PROC\n//PS EXEC PGM=INNERPGM\n// PEND\n//UNUSED PROC\n//PS EXEC PGM=NEVERRUN\n// PEND\n//S EXEC MYP\n", "INNERPGM": pgm("INNERPGM")}))
        self.assertIn(("job:J", "runs_program", "program:INNERPGM"), found)
        self.assertNotIn(("job:J", "runs_program", "program:NEVERRUN"), found)
        self.assertNotIn(("job:J", "runs_proc", "proc:MYP"), found)

    def test_second_job_in_a_member_keeps_its_own_edges(self):
        found = edges(synthetic(self, {"JJ": "//J1 JOB\n//S1 EXEC PGM=A1\n//J2 JOB\n//S2 EXEC PGM=B1\n"}))
        self.assertIn(("job:J1", "runs_program", "program:A1"), found)
        self.assertIn(("job:J2", "runs_program", "program:B1"), found)


class GapLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        run_all(self.ws)

    def question(self):
        return add_sme_question(self.ws, question="Is it intended?", example="An example.", depends_on="A rule.")

    def named(self, name):
        return [g for g in load_gaps(self.ws) if g["name"] == name][0]

    def test_conflict_cannot_be_overwritten_by_another_answer(self):
        gap = self.question()
        answer_gap(self.ws, gap["id"], by="Ann", answer="No", on="2026-11-04", conflict=True)
        with self.assertRaisesRegex(RecordError, "resolve"):
            answer_gap(self.ws, gap["id"], by="Bob", answer="Fine actually", on="2026-11-05")
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "conflict")

    def test_partial_answer_stays_open_and_keeps_history(self):
        gap = self.question()
        answer_gap(self.ws, gap["id"], by="Ann", answer="I don't know, ask Bob", on="2026-11-04", partial=True)
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "open")
        answer_gap(self.ws, gap["id"], by="Bob", answer="Yes", on="2026-11-05")
        saved = get_gap(self.ws, gap["id"])
        self.assertEqual([a["by"] for a in saved["answers"]], ["Ann", "Bob"])
        render_all(self.ws)
        with open(self.ws.path("gaps", "ANSWERS.md")) as f:
            text = f.read()
        self.assertIn("I don't know", text)
        self.assertIn("Bob", text)

    def test_resolve_only_works_on_a_conflict(self):
        with self.assertRaisesRegex(RecordError, "conflict"):
            resolve_conflict(self.ws, self.named("MISSCPY")["id"], by="Ann", decision="Skip it")

    def test_asking_again_does_not_erase_an_answer(self):
        gap = self.question()
        answer_gap(self.ws, gap["id"], by="Ann", answer="Yes", on="2026-11-04")
        with self.assertRaisesRegex(RecordError, gap["id"]):
            self.question()
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "answered")

    def test_answered_runtime_target_goes_on_the_map(self):
        gap = self.named("BILLCALC:WS-DYN")
        answer_gap(self.ws, gap["id"], by="Max", answer="It is TARGET1", on="2026-11-04", targets=["TARGET1"])
        run_all(self.ws)
        edge = [e for e in load_map(self.ws)["edges"] if e["to"] == "program:TARGET1"][0]
        self.assertEqual((edge["from"], edge["confidence"]), ("program:BILLCALC", "answered"))
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "answered")

    def test_duplicate_cannot_be_settled_by_an_answer(self):
        os_path = os.path.join(self.src, "prod")
        os.makedirs(os_path)
        with open(os.path.join(os_path, "CUSTREC.cpy"), "w") as f:
            f.write("000100 01  OTHER PIC X(9).\n")
        run_all(self.ws)
        with self.assertRaisesRegex(RecordError, "library_precedence"):
            answer_gap(self.ws, self.named("COPYBOOK CUSTREC")["id"], by="Max", answer="Use prod")

    def test_requirement_confidence_follows_its_rules(self):
        gap = self.question()
        rule = add_record(self.ws, "rule", text="A rule.", status="ask_expert", evidence=["ORPHAN:0000-MAIN:5-5"], gap=gap["id"])
        add_record(self.ws, "requirement", text="The system shall do it.", rules=[rule["id"]])
        answer_gap(self.ws, gap["id"], by="Ann", answer="No", on="2026-11-04", conflict=True)
        render_all(self.ws)
        with open(self.ws.path("requirements", "REQUIREMENTS.md")) as f:
            self.assertIn("Conflict", f.read())
        self.assertTrue(any("conflict" in i["problem"].lower() for i in validate(self.ws)))

    def test_answered_gap_reopens_when_new_references_appear(self):
        gap = self.named("MISSCPY")
        answer_gap(self.ws, gap["id"], by="Max", answer="Retired", on="2026-11-04")
        with open(os.path.join(self.src, "cobol", "OTHER1"), "w") as f:
            f.write(cobol("OTHER1", data=["COPY MISSCPY."]))
        run_all(self.ws)
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "open")
        self.assertEqual(get_gap(self.ws, gap["id"])["answers"][0]["by"], "Max")

    def test_gap_closed_by_removing_its_only_reference_says_so(self):
        os.remove(os.path.join(self.src, "cobol", "PRICECHK.cbl"))
        run_all(self.ws)
        self.assertEqual(self.named("MISSCPY")["resolution"], "no_longer_referenced")


class StaleTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        run_all(self.ws)

    def test_new_open_item_marks_analysis_stale(self):
        record_analysis(self.ws, "program", "ORPHAN")
        path = [m["path"] for m in load_catalogue(self.ws) if m["name"] == "ORPHAN"][0]
        add_sme_question(self.ws, question="New?", example="E.", depends_on="D.", references=[{"file": path, "line": 5}])
        self.assertEqual([s["name"] for s in stale(self.ws)], ["ORPHAN"])

    def test_gap_becoming_a_conflict_marks_analysis_stale(self):
        path = [m["path"] for m in load_catalogue(self.ws) if m["name"] == "ORPHAN"][0]
        gap = add_sme_question(self.ws, question="New?", example="E.", depends_on="D.", references=[{"file": path, "line": 5}])
        record_analysis(self.ws, "program", "ORPHAN")
        answer_gap(self.ws, gap["id"], by="Ann", answer="No", on="2026-11-04", conflict=True)
        self.assertEqual([s["name"] for s in stale(self.ws)], ["ORPHAN"])

    def test_vanished_slice_is_reported_not_a_crash(self):
        build_slices(self.ws)
        record_analysis(self.ws, "slice", "SLICE-ORD1")
        os.remove(os.path.join(self.src, "defs", "app.csd"))
        run_all(self.ws)
        build_slices(self.ws)
        self.assertEqual([s["name"] for s in stale(self.ws)], ["SLICE-ORD1"])


class SliceIdTests(unittest.TestCase):
    def test_adding_an_earlier_named_entry_keeps_the_slice_and_its_name(self):
        from mma.slices import load_slices, name_slice
        files = {"JS": job("JS", "P1"), "P1": pgm("P1")}
        ws = synthetic(self, files)
        build_slices(ws)
        name_slice(ws, "SLICE-JS", "Night billing")
        with open(os.path.join(ws.root, "src", "AAA"), "w") as f:
            f.write(job("AAA", "P1"))
        run_all(ws)
        build_slices(ws)
        slices = {s["id"]: s for s in load_slices(ws)["slices"]}
        self.assertEqual(slices["SLICE-JS"]["business_name"], "Night billing")
        self.assertEqual(len(slices), 1)

    def test_job_and_transaction_with_the_same_name_do_not_collide(self):
        ws = synthetic(self, {"AB12": job("AB12", "P1"), "P1": pgm("P1"), "P2": pgm("P2"), "A.csd": " DEFINE TRANSACTION(AB12) GROUP(G) PROGRAM(P2)\n"})
        ids = [s["id"] for s in build_slices(ws)["slices"]]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)


class InventoryRobustnessTests(unittest.TestCase):
    def test_parse_failure_does_not_take_down_the_scan_and_raises_a_gap(self):
        from unittest import mock
        import mma.inventory as inventory
        ws, _ = sample_workspace(self)
        real = inventory.parse_text

        def failing(kind, text):
            if "BILLCALC" in text:
                raise ValueError("boom")
            return real(kind, text)
        with mock.patch.object(inventory, "parse_text", side_effect=failing):
            run_all(ws)
        self.assertIn(("parse_failures", "ALL"), gap_keys(ws))
        self.assertEqual(status(ws, "program", "BILLCALC")["state"], "incomplete")
        build_slices(ws)
        write_plan(ws)
        write_flow(ws, "NITEBILL")
        with self.assertRaisesRegex(RecordError, "parsed"):
            program_facts(ws, "BILLCALC")
        run_all(ws)
        self.assertNotIn(("parse_failures", "ALL"), gap_keys(ws))

    def test_skipped_files_are_counted_and_archives_are_reported(self):
        ws, src = sample_workspace(self)
        for name in ("notes.json", "missing.zip"):
            with open(os.path.join(src, name), "wb") as f:
                f.write(b"PK\x03\x04\x00\x00")
        run_all(ws)
        with open(ws.path("inventory", "summary.md")) as f:
            self.assertIn(".json", f.read())
        self.assertIn("missing.zip", {m["path"].rsplit("/", 1)[-1] for m in load_catalogue(ws)})

    def test_record_length_change_is_not_served_from_the_old_cache(self):
        ws, src = sample_workspace(self)
        rec = "//JJJ JOB (A)".ljust(40) + "//S1 EXEC PGM=ABC".ljust(40)
        with open(os.path.join(src, "EBCJOB"), "wb") as f:
            f.write(rec.encode("cp037"))
        ws.config["record_length"] = 80
        ws.save()
        run_inventory(ws)
        ws.config["record_length"] = 40
        ws.save()
        run_inventory(ws)
        self.assertEqual({m["name"]: m["line_count"] for m in load_catalogue(ws)}["EBCJOB"], 2)

    def test_bad_code_page_rejected_at_setup(self):
        ws, _ = sample_workspace(self)
        with self.assertRaisesRegex(ConfigError, "code page"):
            init_workspace(ws.root, ["src"], code_page="cp99999")

    def test_salt_is_ignored_by_git(self):
        ws, _ = sample_workspace(self)
        with open(ws.path(".gitignore")) as f:
            self.assertIn(".salt", f.read())


class PrivacyTests(unittest.TestCase):
    def test_no_quotes_also_covers_facts_files(self):
        ws, _ = sample_workspace(self)
        ws.config["quote_source"] = False
        ws.save()
        run_all(ws)
        program_facts(ws, "NITEBILL")
        program_facts(ws, "IMSPGM")
        for name in ("NITEBILL", "IMSPGM"):
            with open(ws.path("programs", name + ".facts.json")) as f:
                text = f.read()
            self.assertNotIn("SORT FIELDS", text)
            self.assertNotIn("SECRETSEG", text)

    def test_only_real_reference_names_can_be_logged(self):
        ws, _ = sample_workspace(self)
        with self.assertRaises(LogFieldRejected):
            ws.logger.event("activity", activity="reference_used", reference="references/acme_bank_payroll_rules.md")
        ws.logger.event("activity", activity="reference_used", reference="references/planning.md")

    def test_lowercase_mainframe_terms_refused_in_sme_questions(self):
        self.assertTrue(has_cobol_terms("What does the comp-3 field in copybook custrec hold?"))
        self.assertFalse(has_cobol_terms("Should we move this order to the next step?"))


class DictionaryOutputTests(unittest.TestCase):
    def test_warnings_and_unverified_offsets_in_output(self):
        ws = synthetic(self, {"REC1.cpy": "       01 R.\n          05 A PIC X.\n          COPY INNER.\n          05 B PIC X.\n"})
        data = write_datadict(ws, "REC1")
        self.assertTrue(data["warnings"])
        self.assertTrue({f["name"]: f for f in data["fields"]}["B"]["offset_unverified"])
        with open(ws.path("data", "REC1.md")) as f:
            text = f.read()
        self.assertIn("Check before relying", text)
        self.assertIn("(unverified)", text)


class CliFlagTests(unittest.TestCase):
    def test_partial_and_target_flags(self):
        ws, _ = sample_workspace(self)
        run_all(ws)
        gap = [g for g in load_gaps(ws) if g["name"] == "BILLCALC:WS-DYN"][0]
        cli = os.path.join(SCRIPTS, "mma.py")

        def run(*args):
            done = subprocess.run([sys.executable, cli] + list(args), cwd=ws.root, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
        run("gap", "answer", gap["id"], "--by", "Max", "--answer", "Not sure", "--partial")
        self.assertEqual(get_gap(ws, gap["id"])["status"], "open")
        run("gap", "answer", gap["id"], "--by", "Max", "--answer", "It's T1", "--target", "T1")
        self.assertEqual(get_gap(ws, gap["id"])["targets"], ["T1"])


if __name__ == "__main__":
    unittest.main()
