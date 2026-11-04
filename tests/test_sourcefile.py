import unittest

from mma.sourcefile import classify, decode_bytes, logical_source, split_lines


def fixed(*code):
    return "\n".join("000100 " + c for c in code)


class DecodeTests(unittest.TestCase):
    def test_utf8_is_decoded(self):
        r = decode_bytes(b"       IDENTIFICATION DIVISION.\n")
        self.assertTrue(r.ok)
        self.assertEqual(r.encoding, "utf-8")

    def test_ebcdic_with_newlines_is_decoded(self):
        data = "       PROGRAM-ID. ABC.\n       DATA DIVISION.\n".encode("cp037")
        r = decode_bytes(data, "cp037")
        self.assertTrue(r.ok)
        self.assertEqual(r.encoding, "cp037")
        self.assertIn("PROGRAM-ID. ABC.", r.text)
        self.assertEqual(len(split_lines(r.text.rstrip("\n"))), 2)

    def test_ebcdic_without_newlines_splits_on_record_length(self):
        rec = "//JOB1 JOB".ljust(80) + "//S1 EXEC PGM=ABC".ljust(80)
        r = decode_bytes(rec.encode("cp037"), "cp037", 80)
        lines = split_lines(r.text)
        self.assertEqual(lines[1].rstrip(), "//S1 EXEC PGM=ABC")

    def test_binary_is_reported_not_decoded(self):
        r = decode_bytes(bytes(range(256)) * 4)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "binary")

    def test_latin1_fallback(self):
        r = decode_bytes("       * café note\n".encode("latin-1"))
        self.assertTrue(r.ok)
        self.assertEqual(r.encoding, "latin-1")

    def test_bom_is_removed(self):
        self.assertTrue(decode_bytes(b"\xef\xbb\xbf//A JOB").text.startswith("//A"))


class ClassifyTests(unittest.TestCase):
    def test_kinds_by_content_with_no_extension(self):
        cases = {
            "cobol_program": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n",
            "copybook": "       01 CUST-REC.\n          05 CUST-ID PIC X(5).\n",
            "jcl_job": "//* note\n//J1 JOB (A),'X'\n//S EXEC PGM=A\n",
            "jcl_proc": "//P1 PROC\n//S EXEC PGM=A\n",
            "bms": "M1 DFHMSD TYPE=&SYSPARM\nA DFHMDI SIZE=(24,80)\n",
            "csd": " DEFINE TRANSACTION(ABC1) GROUP(G) PROGRAM(X)\n",
            "ddl": "CREATE TABLE ORDERS (ID INT);\n",
            "idcams": " DELETE X\n DEFINE CLUSTER (NAME(A.B) INDEXED)\n",
            "control_card": " SORT FIELDS=(1,5,CH,A)\n",
            "assembler": "MOD1 CSECT\n USING *,15\n",
            "pli": " MAIN: PROCEDURE OPTIONS(MAIN);\n",
            "rexx": "/* REXX */\nSAY 'HI'\n",
            "easytrieve": "FILE IN1\nJOB INPUT IN1\n",
            "ims_def": " PCB TYPE=DB,DBDNAME=X\n PSBGEN LANG=COBOL,PSBNAME=Y\n",
        }
        for kind, text in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(classify(text, "NOEXT"), kind)

    def test_extension_breaks_tie_only_when_content_is_unclear(self):
        self.assertEqual(classify("       MOVE A TO B.\n", "PARA.cpy"), "copybook")
        self.assertEqual(classify("random words here\n", "NOTES"), "unknown")

    def test_jcl_with_mostly_inline_data_stays_jcl(self):
        text = "//J1 JOB (A)\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n" + " DEFINE CLUSTER (NAME(A))\n" * 9 + "/*\n"
        self.assertEqual(classify(text, "X"), "jcl_job")

    def test_proc_with_mostly_inline_data_stays_jcl(self):
        text = "//P1 PROC\n//S EXEC PGM=IDCAMS\n//SYSIN DD *\n" + " DEFINE CLUSTER (NAME(A))\n" * 9 + "/*\n"
        self.assertEqual(classify(text, "X"), "jcl_proc")

    def test_dclgen_is_a_copybook(self):
        self.assertEqual(classify(" EXEC SQL DECLARE T1 TABLE (A INT) END-EXEC.\n", "D"), "copybook")


class LogicalSourceTests(unittest.TestCase):
    def test_fixed_format_drops_comments_and_right_margin(self):
        src = logical_source(fixed("IDENTIFICATION DIVISION.", "*CALL 'NO'.", "    MOVE A TO B.".ljust(65) + "IGNORED"))
        self.assertNotIn("NO", src.masked)
        self.assertNotIn("IGNORED", src.masked)
        self.assertIn("MOVE A TO B.", src.masked)

    def test_line_numbers_survive_comments(self):
        src = logical_source(fixed("A.", "*C", "*C", "    CALL 'X'."))
        self.assertEqual(src.line_at(src.masked.index("CALL")), 4)

    def test_keywords_in_literals_are_masked(self):
        src = logical_source(fixed("    DISPLAY 'CALL FOO'."))
        self.assertNotIn("CALL", src.masked)
        offset = src.masked.index("'")
        self.assertEqual(src.text[offset:offset + 10], "'CALL FOO'")

    def test_lowercase_matches_uppercase(self):
        self.assertIn("CALL", logical_source(fixed("    call 'x'.")).masked)

    def test_crlf_and_tabs_parse_as_fixed(self):
        src = logical_source("000100\tMOVE A TO B.\r\n000200*C\r\n")
        self.assertIn("MOVE A TO B.", src.masked)

    def test_stripped_sequence_columns_are_treated_as_free(self):
        src = logical_source("IDENTIFICATION DIVISION.\nPROGRAM-ID. ABC.\n")
        self.assertIn("IDENTIFICATION DIVISION", src.masked)
        self.assertIn("PROGRAM-ID. ABC", src.masked)

    def test_continued_literal_is_joined(self):
        text = "000100     MOVE 'ABC\n000200-    'DEF' TO X.\n"
        src = logical_source(text)
        self.assertIn("'ABCDEF'", src.text)

    def test_inline_comment_removed_but_not_inside_literal(self):
        src = logical_source(fixed("    MOVE '*>' TO X. *> CALL 'NO'"))
        self.assertNotIn("CALL", src.masked)
        self.assertIn("'*>'", src.text)


if __name__ == "__main__":
    unittest.main()
