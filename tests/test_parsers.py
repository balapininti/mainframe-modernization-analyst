import os
import unittest

from mma.cobol import parse_cobol
from mma.copybook import parse_copybook
from mma.definitions import parse_definitions
from mma.jcl import parse_jcl

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample")


def read(*parts):
    with open(os.path.join(FIX, *parts)) as f:
        return f.read()


class CobolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bill = parse_cobol(read("cobol", "BILLCALC.cbl"))
        cls.order = parse_cobol(read("cobol", "ORDENTRY"))

    def test_program_id(self):
        self.assertEqual(self.bill["program_id"], "BILLCALC")

    def test_static_call_with_line(self):
        call = [c for c in self.bill["calls"] if c["target"] == "PRICELIB"][0]
        self.assertEqual(call["line"], 41)
        self.assertFalse(call["dynamic"])

    def test_dynamic_call_resolved_from_value(self):
        call = [c for c in self.bill["calls"] if c.get("variable") == "WS-PGM"][0]
        self.assertTrue(call["dynamic"])
        self.assertEqual(call["candidates"], ["AUDITLOG"])

    def test_dynamic_call_with_no_candidates(self):
        call = [c for c in self.bill["calls"] if c.get("variable") == "WS-DYN"][0]
        self.assertEqual(call["candidates"], [])

    def test_comment_and_literal_create_no_calls(self):
        self.assertEqual(self.order["calls"], [])

    def test_copies_cover_copy_and_sql_include(self):
        names = {(c["name"], c["mechanism"]) for c in self.order["copies"]}
        self.assertIn(("ORDREC", "COPY"), names)
        self.assertIn(("SQLCA", "SQL_INCLUDE"), names)

    def test_library_tool_include(self):
        parsed = parse_cobol(read("cobol", "IMSPGM.cbl"))
        self.assertIn(("LIBMEMB", "++INCLUDE"), {(c["name"], c["mechanism"]) for c in parsed["copies"]})

    def test_cics_link_and_transid(self):
        link = [c for c in self.order["cics"] if c["verb"] == "LINK"][0]
        self.assertEqual(link["options"]["PROGRAM"], "PRICECHK")
        self.assertEqual(link["line"], 13)
        self.assertEqual(self.order["cics"][-1]["options"]["TRANSID"], "ORD1")

    def test_cics_file_resolved_from_variable(self):
        parsed = parse_cobol(read("cobol", "PRICECHK.cbl"))
        read_stmt = [c for c in parsed["cics"] if c["verb"] == "READ"][0]
        self.assertEqual(read_stmt["resolved"]["FILE"], ["PRICEFL"])

    def test_sql_access(self):
        insert = [s for s in self.order["sql"] if s["verb"] == "INSERT"][0]
        self.assertEqual((insert["tables"], insert["access"]), (["ORDERS"], "write"))
        cursor = [s for s in self.bill["sql"] if s["verb"] == "DECLARE"][0]
        self.assertEqual((cursor["tables"], cursor["access"]), (["ORDERS"], "read"))

    def test_select_into_is_not_a_table(self):
        text = "       PROCEDURE DIVISION.\n       A.\n           EXEC SQL SELECT X INTO :Y FROM T1, S.T2 END-EXEC.\n"
        self.assertEqual(parse_cobol(text)["sql"][0]["tables"], ["T1", "T2"])

    def test_files_and_access(self):
        files = {f["logical"]: f for f in self.bill["files"]}
        self.assertEqual(files["CUST-FILE"]["ddname"], "CUSTMAST")
        self.assertEqual(files["CUST-FILE"]["organization"], "INDEXED")
        self.assertEqual(files["BILL-OUT"]["ddname"], "BILLOUT")
        self.assertEqual(files["CUST-FILE"]["access"], "update")
        self.assertEqual(files["BILL-OUT"]["access"], "write")

    def test_paragraph_ranges(self):
        paras = {p["name"]: p for p in self.bill["paragraphs"]}
        self.assertEqual((paras["3200-APPLY-DISC"]["start_line"], paras["3200-APPLY-DISC"]["end_line"]), (44, 50))
        self.assertNotIn("GOBACK", paras)
        self.assertNotIn("EXIT", paras)

    def test_perform_thru_and_goto(self):
        thru = [p for p in self.bill["performs"] if p["thru"]][0]
        self.assertEqual((thru["from"], thru["target"], thru["thru"]), ("0000-MAIN", "2000-READ", "2000-EXIT"))
        self.assertEqual(self.bill["gotos"][0]["target"], "2000-EXIT")

    def test_hazards_found_with_lines(self):
        found = {(h["type"], h["line"]) for h in self.bill["hazards"]}
        for expected in [("goto", 36), ("perform_thru", 25), ("comp3", 21), ("rounded", 46), ("file_status", 9)]:
            self.assertIn(expected, found)
        self.assertIn(("commarea", 14), {(h["type"], h["line"]) for h in self.order["hazards"]})
        self.assertIn("syncpoint", {h["type"] for h in self.order["hazards"]})

    def test_unknown_exec_block_reported(self):
        parsed = parse_cobol(read("cobol", "IMSPGM.cbl"))
        self.assertTrue(any(u.startswith("EXEC DLI GU") for u in parsed["unrecognized"]))
        self.assertIn("ims", parsed["technologies"])

    def test_empty_input_does_not_fail(self):
        self.assertEqual(parse_cobol("")["paragraphs"], [])

    def test_hyphenated_names_are_not_keywords(self):
        text = (
            "       DATA DIVISION.\n       01 WS-COMP-3 PIC X.\n       01 WS-ABEND-FLAG PIC X.\n"
            "       PROCEDURE DIVISION.\n       A.\n           MOVE WS-CALL TO X.\n"
            "           MOVE WS-GO TO TO-Y.\n           MOVE A-PERFORM TO B.\n"
        )
        parsed = parse_cobol(text)
        self.assertEqual(parsed["calls"], [])
        self.assertEqual(parsed["performs"], [])
        self.assertEqual(parsed["gotos"], [])
        self.assertEqual(parsed["hazards"], [])

    def test_select_for_update_of_is_not_a_table(self):
        text = "       PROCEDURE DIVISION.\n       A.\n           EXEC SQL DECLARE C CURSOR FOR SELECT X\n           FROM T9 FOR UPDATE OF X END-EXEC.\n"
        self.assertEqual(parse_cobol(text)["sql"][0]["tables"], ["T9"])

    DYN = (
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 WS-CONST PIC X(8) VALUE 'REALPGM'.\n       01 WS-MSG PIC X(30) VALUE 'NOT A PROGRAM NAME'.\n"
        "       01 WS-PGM PIC X(8).\n       01 WS-OTHER PIC X(8).\n       01 WS-TEXT PIC X(30).\n"
        "       PROCEDURE DIVISION.\n       A.\n"
        "           IF X = 1\n              MOVE 'NOPE' TO WS-OTHER\n"
        "              MOVE 'BAD WORDS HERE' TO WS-PGM\n"
        "              MOVE WS-CONST TO WS-PGM\n              MOVE 'LIT2' TO WS-OTHER WS-PGM\n"
        "              DISPLAY WS-PGM\n           END-IF\n"
        "           EXEC CICS XCTL PROGRAM(WS-PGM) END-EXEC.\n"
    )

    def test_move_only_reaches_its_own_targets(self):
        stmt = parse_cobol(self.DYN)["cics"][0]
        self.assertNotIn("NOPE", stmt["resolved"]["PROGRAM"])

    def test_move_with_several_targets_and_constant_hop(self):
        self.assertEqual(sorted(parse_cobol(self.DYN)["cics"][0]["resolved"]["PROGRAM"]), ["LIT2", "REALPGM"])

    def test_values_that_cannot_be_names_are_ignored(self):
        self.assertNotIn("BAD WORDS HERE", parse_cobol(self.DYN)["cics"][0]["resolved"]["PROGRAM"])

    def test_decisions_counted(self):
        self.assertEqual(self.bill["metrics"]["decisions"], 4)


class JclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = parse_jcl(read("jcl", "NITEBILL.jcl"))
        cls.steps = {s["name"]: s for s in cls.job["steps"]}

    def test_job_name_and_steps(self):
        self.assertEqual(self.job["name"], "NITEBILL")
        self.assertEqual(self.job["type"], "job")
        self.assertEqual(len(self.job["steps"]), 6)

    def test_program_step_and_cond(self):
        self.assertEqual(self.steps["STEP020"]["program"], "BILLCALC")
        self.assertEqual(self.steps["STEP020"]["cond"], "(4,LT)")
        self.assertEqual(self.steps["STEP020"]["line"], 10)

    def test_proc_step(self):
        self.assertEqual(self.steps["STEP030"]["proc"], "BILLPROC")

    def test_continued_dd(self):
        dd = [d for d in self.steps["STEP010"]["dds"] if d["name"] == "SORTOUT"][0]
        self.assertEqual(dd["dsn"], "PROD.ORDERS.SORTED(+1)")
        self.assertEqual(dd["disp"], "(NEW,CATLG,DELETE)")

    def test_control_member(self):
        dd = [d for d in self.steps["STEP020"]["dds"] if d["name"] == "SYSIN"][0]
        self.assertEqual((dd["dsn"], dd["member"]), ("PROD.CTL", "BILLPARM"))

    def test_inline_sort_card_kept(self):
        dd = [d for d in self.steps["STEP010"]["dds"] if d["name"] == "SYSIN"][0]
        self.assertIn("SORT FIELDS=(1,5,CH,A)", dd["inline"])

    def test_db2_batch_program(self):
        self.assertEqual(self.steps["STEP040"]["run_program"], "ORPHANX")

    def test_db2_batch_program_cites_its_own_line(self):
        self.assertEqual(self.steps["STEP040"]["run_program_line"], 18)

    def test_hazards(self):
        types = {h["type"] for h in self.job["hazards"]}
        self.assertTrue({"sort_step", "jcl_cond", "jcl_if", "gdg"} <= types)

    def test_proc_and_inline_define(self):
        proc = parse_jcl(read("jcl", "BILLPROC.proc"))
        self.assertEqual((proc["name"], proc["type"]), ("BILLPROC", "proc"))
        self.assertIn("PROD.INLINE.KSDS", proc["defined_datasets"])
        self.assertIn("idcams_step", {h["type"] for h in proc["hazards"]})

    def test_unknown_statement_reported(self):
        self.assertEqual(parse_jcl("//A JOB\n//B WIDGET X=1\n")["unrecognized"], ["WIDGET X=1"])

    def test_commas_in_quoted_parm_do_not_split(self):
        step = parse_jcl("//A JOB\n//S EXEC PGM=X,PARM='A,B=C'\n")["steps"][0]
        self.assertEqual((step["program"], step["parm"]), ("X", "'A,B=C'"))


class DefinitionTests(unittest.TestCase):
    def test_csd(self):
        d = parse_definitions(read("defs", "app.csd"), "csd")
        self.assertEqual(d["transactions"], [{"id": "ORD1", "program": "ORDENTRY", "group": "ORDERS", "line": 1}])
        self.assertEqual(d["files"][0]["dsn"], "PROD.PRICE.KSDS")
        self.assertEqual(d["programs"][0]["name"], "ORDENTRY")

    def test_bms(self):
        d = parse_definitions(read("defs", "ORDSET.bms"), "bms")
        self.assertEqual((d["mapset"], d["maps"]), ("ORDSET", ["ORDMAP"]))

    def test_ddl_drops_schema(self):
        self.assertEqual(parse_definitions(read("defs", "orders.ddl"), "ddl")["tables"], ["ORDERS"])

    def test_idcams_path_is_a_definition(self):
        text = "  DEFINE PATH (NAME(A.B.PATH) PATHENTRY(A.B.AIX))\n"
        self.assertEqual(parse_definitions(text, "idcams")["datasets"], ["A.B.PATH"])
        job = "//J JOB\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n" + text + "/*\n"
        self.assertIn("A.B.PATH", parse_jcl(job)["defined_datasets"])

    def test_idcams(self):
        self.assertEqual(parse_definitions(read("defs", "price.idcams"), "idcams")["datasets"], ["PROD.PRICE.KSDS"])


class CopybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields = {f["name"]: f for f in parse_copybook(read("copy", "CUSTREC"))}

    def test_offsets_and_lengths(self):
        self.assertEqual((self.fields["CUST-ID"]["offset"], self.fields["CUST-ID"]["length"]), (0, 5))
        self.assertEqual((self.fields["CUST-BAL"]["offset"], self.fields["CUST-BAL"]["length"]), (6, 5))

    def test_redefines_shares_offset(self):
        self.assertEqual(self.fields["CUST-DATE-X"]["offset"], self.fields["CUST-DATE"]["offset"])
        self.assertEqual(self.fields["CUST-DATE-X"]["redefines"], "CUST-DATE")
        self.assertEqual(self.fields["CUST-COUNT"]["offset"], 17)

    def test_binary_length(self):
        self.assertEqual(self.fields["CUST-COUNT"]["length"], 2)

    def test_occurs_multiplies_group(self):
        self.assertEqual(self.fields["CUST-ITEM"]["occurs"], 3)
        self.assertEqual(self.fields["CUST-REC"]["length"], 25)

    def test_condition_names_attached(self):
        self.assertEqual(self.fields["CUST-RATING"]["conditions"], [{"name": "CUST-PREFERRED", "value": "A"}])
        self.assertNotIn("CUST-PREFERRED", self.fields)

    def test_decimal_details(self):
        bal = self.fields["CUST-BAL"]
        self.assertEqual((bal["digits"], bal["scale"], bal["signed"], bal["usage"]), (9, 2, True, "COMP-3"))

    def test_odo_marked_variable(self):
        text = "       01 R.\n          05 N PIC 9(2).\n          05 T OCCURS 1 TO 5 TIMES DEPENDING ON N PIC X.\n"
        fields = {f["name"]: f for f in parse_copybook(text)}
        self.assertEqual(fields["T"]["depending_on"], "N")
        self.assertEqual(fields["T"]["occurs"], 5)
        self.assertTrue(fields["R"]["variable_length"])


if __name__ == "__main__":
    unittest.main()
