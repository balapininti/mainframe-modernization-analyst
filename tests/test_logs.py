import json
import os
import tempfile
import unittest
import zipfile

from mma.logs import Logger, LogFieldRejected, add_feedback, export_logs
from mma.masking import is_masked, mask_statement

SECRETS = ["SECRETPGM", "SECRETSEG", "ACME-CORP", "Jane Doe", "/Users/x/client/src", "4111111111111111"]


class MaskingTests(unittest.TestCase):
    def test_keywords_kept_and_names_masked(self):
        self.assertEqual(
            mask_statement("EXEC DLI GU USING PCB(1) INTO(SECRETSEG) END-EXEC"),
            "EXEC DLI GU USING PCB ( <NUM> ) INTO ( <ID> ) END-EXEC",
        )

    def test_literals_masked(self):
        self.assertEqual(mask_statement("CALL 'SECRETPGM' USING X"), "CALL <LIT> USING <ID>")

    def test_unterminated_literal_masked(self):
        self.assertNotIn("SECRET", mask_statement("MOVE 'SECRET VALUE"))

    def test_length_capped(self):
        self.assertLessEqual(len(mask_statement("A " * 1000)), 300)

    def test_is_masked_rejects_real_names(self):
        self.assertTrue(is_masked("EXEC DLI GU <ID>"))
        self.assertFalse(is_masked("EXEC DLI GU SECRETSEG"))


class LoggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logger = Logger(self.tmp.name)

    def events(self):
        path = os.path.join(self.tmp.name, "logs")
        out = []
        for name in os.listdir(path):
            if name.startswith("events"):
                with open(os.path.join(path, name)) as f:
                    out += [json.loads(l) for l in f]
        return out

    def test_valid_event_written(self):
        self.logger.event("script_run", command="inventory", duration_ms=12, result="ok", files_processed=3, cached_files=0)
        event = self.events()[0]
        self.assertEqual(event["type"], "script_run")
        self.assertEqual(event["files_processed"], 3)
        self.assertIn("skill_version", event)

    def test_unknown_field_rejected(self):
        with self.assertRaises(LogFieldRejected):
            self.logger.event("script_run", command="inventory", path="/secret")

    def test_unknown_event_type_rejected(self):
        with self.assertRaises(LogFieldRejected):
            self.logger.event("anything", command="inventory")

    def test_free_text_in_enum_field_rejected(self):
        with self.assertRaises(LogFieldRejected):
            self.logger.event("script_run", command="SECRETPGM failed")

    def test_exception_message_cannot_be_logged(self):
        with self.assertRaises(LogFieldRejected):
            self.logger.event("error", command="inventory", error_type="cannot open /Users/x/SECRETPGM")

    def test_exception_recorded_without_its_message(self):
        try:
            open("/nonexistent/SECRETPGM")
        except OSError as exc:
            self.logger.exception("inventory", exc)
        event = self.events()[0]
        self.assertEqual(event["error_type"], "FileNotFoundError")
        self.assertNotIn("SECRETPGM", json.dumps(event))

    def test_name_hash_is_stable_salted_and_case_blind(self):
        first = self.logger.name_hash("SECRETPGM")
        self.assertEqual(first, Logger(self.tmp.name).name_hash("secretpgm"))
        self.assertNotIn("SECRET", first)
        with tempfile.TemporaryDirectory() as other:
            self.assertNotEqual(first, Logger(other).name_hash("SECRETPGM"))

    def test_item_field_only_accepts_hashes(self):
        with self.assertRaises(LogFieldRejected):
            self.logger.event("activity", activity="stage_started", item="SECRETPGM")
        self.logger.event("activity", activity="stage_started", item=self.logger.name_hash("SECRETPGM"))

    def test_logging_failure_never_stops_work(self):
        blocked = os.path.join(self.tmp.name, "file")
        open(blocked, "w").close()
        Logger(blocked).event("script_run", command="inventory", result="ok")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logger = Logger(self.tmp.name)
        self.logger.event("script_run", command="inventory", result="ok", files_processed=1)
        self.logger.event("unrecognized", source_kind="cobol_program", pattern=mask_statement("EXEC DLI GU INTO(SECRETSEG)"), count=2)

    def zip_text(self, path):
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n).decode() for n in z.namelist()}

    def test_export_contains_events_and_preview(self):
        result = export_logs(self.tmp.name)
        contents = self.zip_text(result["zip"])
        self.assertIn("events.jsonl", contents)
        self.assertIn("preview.md", contents)
        self.assertTrue(os.path.exists(result["preview"]))
        self.assertIn("EXEC DLI GU", contents["events.jsonl"])

    def test_salt_never_exported(self):
        self.logger.name_hash("SOMETHING")
        salt = open(os.path.join(self.tmp.name, ".salt")).read().strip()
        joined = "".join(self.zip_text(export_logs(self.tmp.name)["zip"]).values())
        self.assertNotIn(salt, joined)
        self.assertNotIn(".salt", self.zip_text(export_logs(self.tmp.name)["zip"]))

    def test_tampered_log_line_is_dropped_from_export(self):
        path = [n for n in os.listdir(os.path.join(self.tmp.name, "logs")) if n.startswith("events")][0]
        with open(os.path.join(self.tmp.name, "logs", path), "a") as f:
            f.write(json.dumps({"type": "script_run", "command": "inventory", "note": SECRETS[0]}) + "\n")
            f.write("not json " + SECRETS[1] + "\n")
        result = export_logs(self.tmp.name)
        joined = "".join(self.zip_text(result["zip"]).values())
        self.assertNotIn(SECRETS[0], joined)
        self.assertNotIn(SECRETS[1], joined)
        self.assertEqual(result["dropped"], 2)

    def test_feedback_excluded_unless_confirmed(self):
        add_feedback(self.tmp.name, rating=2, category="wrong_result", text="Jane Doe saw an error")
        self.assertNotIn("Jane Doe", "".join(self.zip_text(export_logs(self.tmp.name)["zip"]).values()))
        included = self.zip_text(export_logs(self.tmp.name, include_feedback=True)["zip"])
        self.assertIn("Jane Doe", included["feedback.jsonl"])
        self.assertIn("Jane Doe", included["preview.md"])

    def test_no_events_gives_empty_but_valid_export(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.zip_text(export_logs(empty)["zip"])["events.jsonl"], "")


if __name__ == "__main__":
    unittest.main()
