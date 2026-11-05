"""Inputs from the independent review that the parsers got wrong without any warning."""
import unittest

from mma.cobol import parse_cobol
from mma.copybook import parse_copybook, parse_layout
from mma.datadict import java_type
from mma.definitions import parse_definitions
from mma.jcl import parse_jcl
from mma.sourcefile import classify


def src(*lines):
    return "".join("       %s\n" % l for l in lines)


def proc(*lines):
    return src("DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 WS-PGM PIC X(8) VALUE 'DEFPGM'.", "PROCEDURE DIVISION.", "A.", *lines)


def fields(*lines):
    return {f["name"]: f for f in parse_copybook(src(*lines))}


class LayoutTests(unittest.TestCase):
    def test_level_66_changes_nothing(self):
        f = fields("01 REC.", "   05 A PIC X(5).", "   05 B PIC X(10).", "   66 ALT RENAMES A THRU B.")
        self.assertEqual((f["B"]["length"], f["B"]["is_group"], f["REC"]["length"]), (10, False, 15))
        self.assertNotIn("ALT", f)

    def test_level_77_is_independent(self):
        f = fields("01 REC.", "   05 A PIC X(5).", "77 CNT PIC 9(4).")
        self.assertEqual((f["A"]["length"], f["REC"]["length"], f["CNT"]["offset"]), (5, 5, 0))
        self.assertIsNone(f["CNT"]["parent"])

    def test_sign_separate_adds_a_byte(self):
        f = fields("01 REC.", "   05 A PIC S9(5) SIGN LEADING SEPARATE.", "   05 B PIC S9(3) SIGN TRAILING SEPARATE.", "   05 C PIC X.")
        self.assertEqual((f["A"]["length"], f["B"]["length"], f["C"]["offset"]), (6, 4, 10))

    def test_sign_separate_inherited_from_group(self):
        f = fields("01 REC SIGN IS LEADING SEPARATE.", "   05 A PIC S9(3).", "   05 U PIC 9(3).")
        self.assertEqual((f["A"]["length"], f["U"]["length"]), (4, 3))

    def test_usage_inherited_from_group(self):
        f = fields("01 REC.", "   05 G USAGE COMP-3.", "      10 A PIC S9(5).", "      10 B PIC S9(3).", "   05 C PIC X.")
        self.assertEqual((f["A"]["length"], f["B"]["length"], f["G"]["length"], f["C"]["offset"], f["A"]["usage"]), (3, 2, 5, 5, "COMP-3"))

    def test_national_and_dbcs_are_two_bytes_of_text(self):
        f = fields("01 REC.", "   05 A PIC N(5).", "   05 B PIC G(5).", "   05 C PIC N(2) USAGE NATIONAL.")
        self.assertEqual((f["A"]["length"], f["B"]["length"], f["C"]["length"]), (10, 10, 4))
        self.assertEqual(java_type(f["A"], "A"), "String")

    def test_sync_aligns_binary_fields(self):
        f = fields("01 REC.", "   05 A PIC X.", "   05 B PIC S9(9) COMP SYNC.", "   05 C PIC X.")
        self.assertEqual((f["B"]["offset"], f["C"]["offset"]), (4, 8))

    def test_procedure_and_function_pointers(self):
        f = fields("01 REC.", "   05 A USAGE PROCEDURE-POINTER.", "   05 B USAGE FUNCTION-POINTER.")
        self.assertEqual((f["A"]["length"], f["B"]["length"]), (8, 4))

    def test_nested_copy_marks_later_offsets_unverified(self):
        layout = parse_layout(src("01 REC.", "   05 A PIC X(5).", "   COPY INNER.", "   05 B PIC X(2)."))
        by_name = {f["name"]: f for f in layout["fields"]}
        self.assertFalse(by_name["A"]["offset_unverified"])
        self.assertTrue(by_name["B"]["offset_unverified"])
        self.assertTrue(any("INNER" in w for w in layout["warnings"]))

    def test_copy_replacing_warned(self):
        self.assertTrue(any("REPLACING" in w for w in parse_layout(src("01 REC.", "   COPY INNER REPLACING ==A== BY ==B==."))["warnings"]))

    def test_last_entry_without_period_kept_and_warned(self):
        layout = parse_layout(src("01 REC.", "   05 A PIC X(5)"))
        self.assertIn("A", {f["name"] for f in layout["fields"]})
        self.assertEqual({f["name"]: f for f in layout["fields"]}["A"]["length"], 5)
        self.assertTrue(layout["warnings"])

    def test_separators_after_picture(self):
        f = fields("01 REC.", "   05 A PIC X(5), VALUE 'A'.", "   05 B PIC 9(3); VALUE 1.")
        self.assertEqual((f["A"]["length"], f["B"]["length"]), (5, 3))

    def test_field_after_variable_table_is_unverified(self):
        layout = parse_layout(src("01 R.", "   05 N PIC 9(2).", "   05 T OCCURS 1 TO 10 DEPENDING ON N PIC X(4).", "   05 AFTER PIC X."))
        by_name = {f["name"]: f for f in layout["fields"]}
        self.assertTrue(by_name["AFTER"]["offset_unverified"])
        self.assertFalse(by_name["N"]["offset_unverified"])
        self.assertTrue(any("maximum" in w for w in layout["warnings"]))

    def test_edited_pictures_are_text(self):
        f = fields("01 REC.", "   05 A PIC 99/99/99.", "   05 B PIC $$$,$$9.99.")
        self.assertEqual(java_type(f["A"], "A"), "String (edited)")
        self.assertEqual(java_type(f["B"], "B"), "String (edited)")

    def test_comp5_and_packed_integer_types(self):
        f = fields("01 REC.", "   05 A PIC 9(9) COMP-5.", "   05 B PIC 9(18) COMP-5.", "   05 C PIC S9(5) COMP-3.")
        self.assertEqual(java_type(f["A"], "A"), "Long")
        self.assertEqual(java_type(f["B"], "B"), "BigInteger")
        self.assertEqual(java_type(f["C"], "C"), "BigDecimal (scale 0)")

    def test_assumed_decimal_scaling(self):
        self.assertEqual(fields("01 REC.", "   05 A PIC VPP99.")["A"]["scale"], 4)


class DynamicTargetTests(unittest.TestCase):
    def call(self, *lines):
        return parse_cobol(proc(*lines, "CALL WS-PGM."))["calls"][0]

    def test_writes_other_than_move_leave_it_unresolved(self):
        for statement in ("STRING A B DELIMITED BY SIZE INTO WS-PGM.", "READ F INTO WS-PGM.", "ACCEPT WS-PGM.", "UNSTRING A INTO WS-PGM."):
            with self.subTest(statement=statement):
                self.assertEqual(self.call(statement)["unresolved"], ["WS-PGM"])

    def test_cics_write_into_leaves_it_unresolved(self):
        self.assertEqual(self.call("EXEC CICS READ FILE('F') INTO(WS-PGM) END-EXEC.")["unresolved"], ["WS-PGM"])

    def test_reference_modified_move_is_not_a_name(self):
        call = self.call("MOVE 'AB' TO WS-PGM(1:2).", "MOVE '123456' TO WS-PGM(3:6).")
        self.assertNotIn("AB", call["candidates"])
        self.assertEqual(call["unresolved"], ["WS-PGM"])

    def test_condition_name_set_leaves_it_unresolved(self):
        text = src("DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 WS-PGM PIC X(8).", "   88 PGM-B VALUE 'PGMB'.", "PROCEDURE DIVISION.", "A.",
                   "MOVE 'PGMC' TO WS-PGM.", "SET PGM-B TO TRUE.", "CALL WS-PGM.")
        call = parse_cobol(text)["calls"][0]
        self.assertEqual(call["unresolved"], ["WS-PGM"])


class StatementTests(unittest.TestCase):
    def test_sql_call_is_not_a_cobol_call(self):
        parsed = parse_cobol(proc("EXEC SQL CALL SP1(:A) END-EXEC."))
        self.assertEqual(parsed["calls"], [])
        self.assertEqual(parsed["sql"][0]["procedure"], "SP1")

    def test_execute_cics_recognized(self):
        self.assertEqual(parse_cobol(proc("EXECUTE CICS LINK PROGRAM('HIDN') END-EXEC."))["cics"][0]["options"]["PROGRAM"], "HIDN")

    def test_unknown_exec_block_is_a_technology(self):
        self.assertIn("acmedb", parse_cobol(proc("EXEC ACMEDB GET X END-EXEC."))["technologies"])

    def test_nested_programs_and_entries_listed(self):
        text = src("IDENTIFICATION DIVISION.", "PROGRAM-ID. MAINP.", "PROCEDURE DIVISION.", "A.", "ENTRY 'ALT1'.", "CALL 'DEEP'.", "GOBACK.",
                   "IDENTIFICATION DIVISION.", "PROGRAM-ID. INNERP.", "END PROGRAM INNERP.", "END PROGRAM MAINP.")
        parsed = parse_cobol(text)
        self.assertEqual(parsed["program_id"], "MAINP")
        self.assertEqual(sorted(parsed["other_names"]), ["ALT1", "INNERP"])
        self.assertIn("nested_program", {h["type"] for h in parsed["hazards"]})

    def test_paragraph_with_code_on_the_same_line(self):
        parsed = parse_cobol(proc("1000-A. MOVE 1 TO X."))
        self.assertIn("1000-A", {p["name"] for p in parsed["paragraphs"]})

    def test_go_to_depending_records_every_target(self):
        parsed = parse_cobol(proc("GO TO 3000-C 4000-D DEPENDING ON X."))
        self.assertEqual([g["target"] for g in parsed["gotos"]], ["3000-C", "4000-D"])

    def test_sort_procedures_count_as_references(self):
        parsed = parse_cobol(proc("SORT F ON ASCENDING KEY K", "  INPUT PROCEDURE IS 5000-I", "  OUTPUT PROCEDURE 6000-O."))
        self.assertEqual({p["target"] for p in parsed["performs"]}, {"5000-I", "6000-O"})

    def test_perform_times_is_not_a_paragraph(self):
        self.assertEqual(parse_cobol(proc("PERFORM WS-CNT TIMES", "  MOVE 1 TO X", "END-PERFORM."))["performs"], [])

    def test_abend_routines_flagged_from_call_literals(self):
        for name, hazard in (("ILBOABN0", "abend"), ("CEE3ABD", "abend"), ("CKPT", "checkpoint")):
            with self.subTest(name=name):
                self.assertIn(hazard, {h["type"] for h in parse_cobol(proc("CALL '%s'." % name))["hazards"]})

    def test_truncation_flagged_for_more_forms(self):
        for statement in ("COMPUTE A(I) = 1.", "COMPUTE A OF G = 1.", "COMPUTE A B = 1.", "ADD A TO B GIVING C.", "DIVIDE A BY B GIVING C."):
            with self.subTest(statement=statement):
                self.assertIn("unrounded_compute", {h["type"] for h in parse_cobol(proc(statement))["hazards"]})

    def test_rounded_not_flagged_as_truncation(self):
        self.assertNotIn("unrounded_compute", {h["type"] for h in parse_cobol(proc("COMPUTE A ROUNDED = 1."))["hazards"]})

    def test_names_with_special_characters_kept_whole(self):
        parsed = parse_cobol(src("COPY AB_CD.", "EXEC SQL INCLUDE DCL#CUST END-EXEC."))
        self.assertEqual({c["name"] for c in parsed["copies"]}, {"AB_CD", "DCL#CUST"})

    def test_assign_clause_forms(self):
        cases = {"DA-S-INFILE": "INFILE", "UR-S-PRT": "PRT", "SYS010-UT-2400-S-TAPE": "TAPE", "DA-R-RELF": "RELF", "CUST-FILE": "CUST-FILE", "UT-S-X1": "X1"}
        for assign, expected in cases.items():
            with self.subTest(assign=assign):
                parsed = parse_cobol(src("INPUT-OUTPUT SECTION.", "FILE-CONTROL.", "    SELECT F1 ASSIGN TO %s." % assign))
                self.assertEqual(parsed["files"][0]["ddname"], expected)

    def test_open_with_commas(self):
        text = src("FILE-CONTROL.", "    SELECT F1 ASSIGN TO D1.", "    SELECT F2 ASSIGN TO D2.", "PROCEDURE DIVISION.", "A.", "OPEN INPUT F1, F2.")
        self.assertEqual({f["logical"]: f["access"] for f in parse_cobol(text)["files"]}, {"F1": "read", "F2": "read"})


class SqlTests(unittest.TestCase):
    def sql(self, body):
        statements = []
        words = body.split()
        line = ""
        lines = []
        for word in words:
            if len(line) + len(word) > 55:
                lines.append(line)
                line = ""
            line += word + " "
        lines.append(line)
        return parse_cobol(proc("EXEC SQL", *lines, "END-EXEC."))["sql"][0]

    def test_aliased_table_list(self):
        self.assertEqual(self.sql("SELECT A INTO :B FROM T4 AS X, T5 AS Y")["reads"], ["T4", "T5"])

    def test_fetch_names_no_table(self):
        self.assertEqual(self.sql("FETCH NEXT FROM C1 INTO :A")["tables"], [])

    def test_functions_with_from_name_no_table(self):
        self.assertEqual(self.sql("SELECT EXTRACT(HOUR FROM TS1), TRIM(LEADING ' ' FROM COL1) INTO :A FROM T1")["tables"], ["T1"])

    def test_table_function_is_not_a_table(self):
        self.assertEqual(self.sql("SELECT A INTO :B FROM TABLE(F1(:X)) AS T")["tables"], [])

    def test_insert_select_writes_target_and_reads_source(self):
        s = self.sql("INSERT INTO T7 SELECT * FROM T8")
        self.assertEqual((s["writes"], s["reads"]), (["T7"], ["T8"]))

    def test_update_subquery_reads_it(self):
        s = self.sql("UPDATE T15 SET A = (SELECT MAX(B) FROM T16)")
        self.assertEqual((s["writes"], s["reads"]), (["T15"], ["T16"]))

    def test_merge_using(self):
        s = self.sql("MERGE INTO T9 USING T10 ON A = B WHEN MATCHED THEN UPDATE SET C = 1")
        self.assertEqual((s["writes"], s["reads"]), (["T9"], ["T10"]))

    def test_set_subquery_and_lock(self):
        self.assertEqual(self.sql("SET :H = (SELECT MAX(A) FROM T11)")["reads"], ["T11"])
        self.assertEqual(self.sql("LOCK TABLE T14 IN EXCLUSIVE MODE")["reads"], ["T14"])

    def test_quoted_names(self):
        self.assertEqual(self.sql('SELECT A INTO :B FROM "S1"."T13"')["reads"], ["T13"])

    def test_common_table_expression(self):
        s = self.sql("WITH C AS (SELECT A FROM T20) SELECT A INTO :B FROM C")
        self.assertEqual(s["reads"], ["T20"])

    def test_dynamic_sql_flagged(self):
        self.assertTrue(self.sql("PREPARE S1 FROM :WS-STMT")["dynamic"])
        self.assertTrue(self.sql("EXECUTE IMMEDIATE :WS-STMT")["dynamic"])


class JclTests(unittest.TestCase):
    def step(self, text, name=None):
        steps = parse_jcl(text)["steps"]
        return steps[0] if name is None else {s["name"]: s for s in steps}[name]

    def test_run_prog_abbreviation_and_several_runs(self):
        step = self.step("//J JOB\n//S EXEC PGM=IKJEFT1B\n//SYSTSIN DD *\n DSN SYSTEM(X)\n RUN PROG(FIRST)\n RUN PROGRAM(SECOND)\n/*\n")
        self.assertEqual([p["name"] for p in step["run_programs"]], ["FIRST", "SECOND"])
        self.assertEqual([p["line"] for p in step["run_programs"]], [5, 6])

    def test_step_override_dd_name_split(self):
        dd = self.step("//J JOB\n//S EXEC MYPROC\n//PS1.SYSIN DD DSN=CTL.LIB(CARD),DISP=SHR\n")["dds"][0]
        self.assertEqual((dd["name"], dd["override_step"], dd["member"]), ("SYSIN", "PS1", "CARD"))

    def test_symbolic_member_kept(self):
        dd = self.step("//J JOB\n//S EXEC PGM=X\n//SYSIN DD DSN=CTL.LIB(&M),DISP=SHR\n")["dds"][0]
        self.assertEqual(dd["member"], "&M")

    def test_symbols_from_set_and_proc_defaults(self):
        job = "//J JOB\n// SET PG=REALPGM,HLQ=PROD\n//S EXEC PGM=&PG\n//IN DD DSN=&HLQ..ORDERS,DISP=SHR\n"
        step = self.step(job)
        self.assertEqual((step["program"], step["dds"][0]["dsn"], step["dds"][0]["symbolic"]), ("REALPGM", "PROD.ORDERS", True))
        self.assertEqual(self.step("//P PROC PROG=DEFPGM\n//S EXEC PGM=&PROG\n")["program"], "DEFPGM")

    def test_unresolved_symbol_is_marked(self):
        dd = self.step("//J JOB\n//S EXEC PGM=X\n//IN DD DSN=&HLQ..ORDERS,DISP=SHR\n")["dds"][0]
        self.assertEqual((dd["dsn"], dd["symbolic"]), ("&HLQ..ORDERS", True))

    def test_conditions_on_proc_exec_and_job(self):
        self.assertIn("jcl_cond", {h["type"] for h in parse_jcl("//J JOB\n//S EXEC MYP,COND.PS1=(4,LT)\n")["hazards"]})
        self.assertIn("jcl_cond", {h["type"] for h in parse_jcl("//J JOB (A),COND=(4,LT)\n//S EXEC PGM=X\n")["hazards"]})

    def test_quoted_parm_continued_over_lines(self):
        step = self.step("//J JOB\n//S EXEC PGM=X,PARM='AAA\n//             BBB',COND=(0,NE)\n")
        self.assertEqual(step["cond"], "(0,NE)")
        self.assertEqual(parse_jcl("//J JOB\n//S EXEC PGM=X,PARM='AAA\n//             BBB',COND=(0,NE)\n")["unrecognized"], [])

    def test_instream_proc_runs_only_when_invoked(self):
        parsed = parse_jcl("//J JOB\n//MYP PROC\n//PS EXEC PGM=INNERPGM\n// PEND\n//UNUSED PROC\n//PS EXEC PGM=NEVERRUN\n// PEND\n//S EXEC MYP\n")
        self.assertEqual([s["name"] for s in parsed["steps"]], ["S"])
        self.assertEqual(parsed["instream_procs"]["MYP"][0]["program"], "INNERPGM")
        self.assertEqual(parsed["name"], "J")

    def test_two_jobs_in_one_member_keep_their_steps(self):
        parsed = parse_jcl("//J1 JOB\n//S1 EXEC PGM=A\n//J2 JOB\n//S2 EXEC PGM=B\n")
        self.assertEqual({s["name"]: s["job"] for s in parsed["steps"]}, {"S1": "J1", "S2": "J2"})
        self.assertEqual(parsed["jobs"], ["J1", "J2"])

    def test_data_delimiter_honoured(self):
        parsed = parse_jcl("//J JOB\n//S EXEC PGM=A\n//SYSUT1 DD DATA,DLM=ZZ\n//CHILD JOB\n//X EXEC PGM=CHILDPGM\nZZ\n//S2 EXEC PGM=B\n")
        self.assertEqual(parsed["name"], "J")
        self.assertEqual([s["name"] for s in parsed["steps"]], ["S", "S2"])

    def test_dd_data_does_not_stop_at_slashes(self):
        parsed = parse_jcl("//J JOB\n//S EXEC PGM=A\n//SYSUT1 DD DATA\n//X EXEC PGM=CHILD\n/*\n//S2 EXEC PGM=B\n")
        self.assertEqual([s["name"] for s in parsed["steps"]], ["S", "S2"])


class ClassifyTests(unittest.TestCase):
    def test_comments_do_not_decide_the_kind(self):
        self.assertEqual(classify("      * USED BY PROGRAM-ID ABC\n       01 R.\n          05 A PIC X.\n", "C.cpy"), "copybook")
        self.assertEqual(classify("      * MAP DEFINED WITH DFHMDI\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n", "P.cbl"), "cobol_program")
        self.assertEqual(classify("//P1 PROC\n//* JOB RUNS NIGHTLY\n//S EXEC PGM=A\n", "X"), "jcl_proc")

    def test_jobparm_before_job(self):
        self.assertEqual(classify("/*JOBPARM S=A\n//J JOB (A)\n//S EXEC PGM=A\n", "X"), "jcl_job")

    def test_abbreviated_csd(self):
        self.assertEqual(classify(" DEFINE TRANS(T001) GROUP(G) PROG(P1)\n", "X"), "csd")


class CsdTests(unittest.TestCase):
    def test_abbreviated_keywords(self):
        d = parse_definitions(" DEFINE TRANS(T001) GROUP(G) PROG(P1)\n DEFINE PROG(P1) GROUP(G)\n", "csd")
        self.assertEqual(d["transactions"][0]["program"], "P1")
        self.assertEqual(d["programs"][0]["name"], "P1")


if __name__ == "__main__":
    unittest.main()
