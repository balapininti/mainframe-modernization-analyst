import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from .helpers import FIXTURE
from . import SCRIPTS

CLI = os.path.join(SCRIPTS, "mma.py")


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "my project")
        os.makedirs(self.root)
        shutil.copytree(FIXTURE, os.path.join(self.root, "src"))

    def run_cli(self, *args, ok=True):
        done = subprocess.run([sys.executable, CLI] + list(args), cwd=self.root, capture_output=True, text=True)
        if ok:
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        return done

    def scan(self):
        self.run_cli("init", "--source", "src")
        return self.run_cli("scan")

    def out(self, *parts):
        return os.path.join(self.root, "modernization", *parts)


class PlainErrorTests(CliBase):
    def assertPlain(self, done):
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn("Traceback", done.stderr + done.stdout)

    def test_no_setup(self):
        done = self.run_cli("inventory", ok=False)
        self.assertPlain(done)
        self.assertIn("mma.py init", done.stderr)

    def test_wrong_source_path(self):
        done = self.run_cli("init", "--source", "nope", ok=False)
        self.assertPlain(done)
        self.assertIn("nope", done.stderr)

    def test_empty_source_folder(self):
        os.makedirs(os.path.join(self.root, "empty"))
        self.run_cli("init", "--source", "empty")
        done = self.run_cli("scan", ok=False)
        self.assertPlain(done)
        self.assertIn("didn't find any files", done.stderr)

    def test_unwritable_output(self):
        os.chmod(self.root, 0o555)
        self.addCleanup(os.chmod, self.root, 0o755)
        done = self.run_cli("init", "--source", "src", ok=False)
        self.assertPlain(done)
        self.assertIn("write", done.stderr)

    def test_unknown_program(self):
        self.scan()
        done = self.run_cli("facts", "NOPE", ok=False)
        self.assertPlain(done)
        self.assertIn("NOPE", done.stderr)

    def test_unexpected_failure_is_logged_without_traceback(self):
        self.scan()
        with open(self.out("inventory", "dependencies.json"), "w") as f:
            f.write('{"edges": 5}')
        done = self.run_cli("flow", "ORD1", ok=False)
        self.assertPlain(done)
        self.assertIn("logs export", done.stderr)
        logged = "".join(open(p).read() for p in glob.glob(self.out("logs", "events-*.jsonl")))
        self.assertIn('"type": "error"', logged)


class PreflightTests(CliBase):
    def test_good_setup_passes(self):
        done = self.run_cli("preflight", "--source", "src")
        self.assertIn("Ready", done.stdout)

    def test_bad_source_explained(self):
        done = self.run_cli("preflight", "--source", "nope", ok=False)
        self.assertIn("nope", done.stdout)
        self.assertNotIn("Traceback", done.stderr)

    def test_python_version_reported(self):
        self.assertIn("Python", self.run_cli("preflight", "--source", "src").stdout)


class WorkflowTests(CliBase):
    def test_scan_reports_counts_and_gaps(self):
        done = self.scan()
        self.assertIn("cobol_program", done.stdout)
        self.assertIn("Open items", done.stdout)
        with open(self.out("gaps", "MAINFRAME_TEAM_REQUEST.md")) as f:
            self.assertIn("MISSCPY", f.read())
        for path in ("gaps/MAINFRAME_TEAM_REQUEST.md", "inventory/slices.md", "mapping/migration-order.md", "glossary.md"):
            self.assertTrue(os.path.exists(self.out(*path.split("/"))), path)

    def test_source_is_never_modified(self):
        before = {}
        for root, _, files in os.walk(os.path.join(self.root, "src")):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    before[path] = f.read()
        self.scan()
        self.run_cli("flow", "ORD1")
        for path, data in before.items():
            with open(path, "rb") as f:
                self.assertEqual(f.read(), data)

    def test_full_missing_information_loop(self):
        self.scan()
        gaps = json.loads(self.run_cli("gaps", "--json", "--top", "100").stdout)
        gap = [g for g in gaps if g["name"] == "MISSCPY"][0]
        self.assertIn("MISSCPY", self.run_cli("status", "program", "PRICECHK").stdout)
        self.run_cli("analysis", "program", "PRICECHK")
        with open(os.path.join(self.root, "src", "copy", "MISSCPY"), "w") as f:
            f.write("000100 01  M PIC X.\n")
        self.run_cli("scan")
        self.assertIn("PRICECHK", self.run_cli("stale").stdout)
        self.assertIn("complete", self.run_cli("status", "program", "PRICECHK").stdout)
        self.assertIn(gap["id"], self.run_cli("gaps", "--all").stdout)

    def test_rule_to_trace(self):
        self.scan()
        rule = json.loads(self.run_cli("record", "rule", "--text", "Preferred customers get 5% off.", "--status", "confirmed_code",
                                       "--evidence", "BILLCALC:3200-APPLY-DISC:44-50", "--json").stdout)
        self.run_cli("record", "requirement", "--text", "The system shall discount preferred customers.", "--rules", rule["id"])
        self.run_cli("record", "test", "--given", "g", "--when", "w", "--then", "t", "--rules", rule["id"])
        self.assertIn("No problems", self.run_cli("validate").stdout)
        self.run_cli("render")
        with open(self.out("requirements", "TRACEABILITY.md")) as f:
            self.assertIn(rule["id"], f.read())

    def test_bad_rule_gets_plain_refusal(self):
        self.scan()
        done = self.run_cli("record", "rule", "--text", "x", "--status", "confirmed_code", "--evidence", "BILLCALC:NOPARA:1-2", ok=False)
        self.assertIn("NOPARA", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_sme_question_answer_conflict(self):
        self.scan()
        gap = json.loads(self.run_cli("gap", "ask", "--question", "Is region 07 excluded on purpose?", "--example", "A region 07 order pays full price.",
                                      "--depends-on", "The discount rule.", "--json").stdout)
        self.run_cli("gap", "answer", gap["id"], "--by", "Sam", "--answer", "No", "--conflict")
        self.assertIn("conflict", self.run_cli("gaps", "--all").stdout)
        self.run_cli("gap", "resolve", gap["id"], "--by", "Ana", "--decision", "Follow the code")

    def test_outputs_commands(self):
        self.scan()
        self.assertIn("ORD1", self.run_cli("flow", "ORD1").stdout)
        self.assertIn("PRICECHK", self.run_cli("facts", "PRICECHK").stdout)
        self.assertIn("COMPUTE", self.run_cli("source", "BILLCALC", "--paragraph", "3200-APPLY-DISC").stdout)
        self.assertIn("CUSTREC", self.run_cli("datadict", "CUSTREC").stdout)
        self.assertIn("SLICE-ORD1", self.run_cli("mapping", "SLICE-ORD1").stdout)
        self.run_cli("slice-name", "SLICE-ORD1", "Order entry")
        self.assertIn("Order entry", open(self.out("inventory", "slices.md")).read())
        self.assertIn("SLICE-", self.run_cli("summary").stdout)


class EncodingTests(CliBase):
    def test_non_ascii_source_works_on_a_machine_with_an_ascii_locale(self):
        path = os.path.join(self.root, "src", "cobol", "BILLCALC.cbl")
        with open(path, "rb") as f:
            data = f.read().replace(b"3200-APPLY-DISC.\n", b"3200-APPLY-DISC.\n", 1)
        lines = data.split(b"\n")
        lines[44] = "004500*    caf\u00e9 discount note".encode("utf-8")
        with open(path, "wb") as f:
            f.write(b"\n".join(lines))
        env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", PYTHONIOENCODING="ascii")

        def run(*args):
            done = subprocess.run([sys.executable, CLI] + list(args), cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done

        run("init", "--source", "src")
        run("scan")
        run("record", "rule", "--text", "Caf\u00e9 rule", "--status", "confirmed_code", "--evidence", "BILLCALC:3200-APPLY-DISC:44-50")
        run("render")
        run("source", "BILLCALC", "--paragraph", "3200-APPLY-DISC")
        with open(self.out("requirements", "RULES.md"), encoding="utf-8") as f:
            self.assertIn("caf\u00e9", f.read())


class LogFlowTests(CliBase):
    def test_copilot_activity_logged_through_allowlist(self):
        self.scan()
        self.run_cli("log", "--activity", "stage_started", "--stage", "deep_analysis", "--prompt-category", "explain_program", "--item", "BILLCALC", "--surface", "vscode")
        logged = "".join(open(p).read() for p in glob.glob(self.out("logs", "events-*.jsonl")))
        self.assertIn("stage_started", logged)
        self.assertNotIn("BILLCALC", logged)

    def test_bad_log_call_refused_plainly_and_never_blocks(self):
        self.scan()
        done = self.run_cli("log", "--activity", "free text with BILLCALC")
        self.assertIn("not logged", done.stdout + done.stderr)

    def test_export_has_no_source_or_names(self):
        self.scan()
        self.run_cli("facts", "BILLCALC")
        self.run_cli("feedback", "--rating", "2", "--category", "wrong_result", "--text", "Jane Doe says BILLCALC is wrong")
        done = self.run_cli("logs", "export")
        self.assertIn("Review", done.stdout)
        path = glob.glob(self.out("logs-export", "*.zip"))[0]
        with zipfile.ZipFile(path) as z:
            text = "".join(z.read(n).decode() for n in z.namelist())
        for secret in ("BILLCALC", "ORDENTRY", "MISSCPY", "PROD.CUST", "SECRETSEG", "SECRETWORD", "Jane Doe", self.root, "COMPUTE WS-TOTAL"):
            self.assertNotIn(secret, text)
        self.assertIn("EXEC DLI GU", text)

    def test_feedback_exported_only_when_asked(self):
        self.scan()
        self.run_cli("feedback", "--rating", "2", "--category", "other", "--text", "Jane Doe note")
        self.run_cli("logs", "export", "--include-feedback")
        path = sorted(glob.glob(self.out("logs-export", "*.zip")))[-1]
        with zipfile.ZipFile(path) as z:
            self.assertIn("Jane Doe", z.read("feedback.jsonl").decode())


if __name__ == "__main__":
    unittest.main()
