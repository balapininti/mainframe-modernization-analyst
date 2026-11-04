import os
import unittest

from mma.gaps import add_sme_question, answer_gap, get_gap, load_gaps, resolve_conflict, top_gaps
from mma.records import RecordError, add_record, impact, load_records, record_analysis, stale, status, validate
from mma.render import render_all

from .helpers import sample_workspace
from .test_inventory import run_all

DISCOUNT = "BILLCALC:3200-APPLY-DISC:44-50"


class RecordBase(unittest.TestCase):
    def setUp(self):
        self.ws, self.src = sample_workspace(self)
        run_all(self.ws)

    def rule(self, **kw):
        kw.setdefault("text", "Preferred customers with orders over 10000 get 5% off.")
        kw.setdefault("status", "confirmed_code")
        kw.setdefault("evidence", [DISCOUNT])
        return add_record(self.ws, "rule", **kw)

    def read(self, *parts):
        with open(self.ws.path(*parts)) as f:
            return f.read()


class EvidenceTests(RecordBase):
    def test_valid_citation_saved_with_source_hash(self):
        rule = self.rule()
        self.assertTrue(rule["id"].startswith("RULE-"))
        self.assertEqual(rule["evidence"][0]["member"], "BILLCALC")
        self.assertEqual(rule["evidence"][0]["start"], 44)
        self.assertTrue(rule["evidence"][0]["sha"])

    def test_unknown_program_rejected(self):
        with self.assertRaisesRegex(RecordError, "NOSUCH"):
            self.rule(evidence=["NOSUCH:A:1-2"])

    def test_unknown_paragraph_rejected(self):
        with self.assertRaisesRegex(RecordError, "NOPARA"):
            self.rule(evidence=["BILLCALC:NOPARA:44-50"])

    def test_lines_outside_paragraph_rejected(self):
        with self.assertRaisesRegex(RecordError, "lines"):
            self.rule(evidence=["BILLCALC:3200-APPLY-DISC:10-20"])

    def test_lines_past_end_of_file_rejected(self):
        with self.assertRaisesRegex(RecordError, "lines"):
            self.rule(evidence=["CUSTREC::1-999"])

    def test_copybook_citation_without_paragraph(self):
        self.assertEqual(self.rule(evidence=["CUSTREC::3-4"])["evidence"][0]["paragraph"], None)

    def test_badly_formed_citation_rejected(self):
        with self.assertRaisesRegex(RecordError, "PROGRAM:PARAGRAPH:START-END"):
            self.rule(evidence=["line 44 of billcalc"])


class StatusRuleTests(RecordBase):
    def test_confirmed_from_code_needs_evidence(self):
        with self.assertRaisesRegex(RecordError, "evidence"):
            self.rule(evidence=[])

    def test_inferred_needs_evidence(self):
        with self.assertRaisesRegex(RecordError, "evidence"):
            self.rule(status="inferred", evidence=[])

    def test_confirmed_by_sme_needs_person_and_date(self):
        with self.assertRaisesRegex(RecordError, "person"):
            self.rule(status="confirmed_sme", evidence=[])
        rule = self.rule(status="confirmed_sme", evidence=[], by="Sam", on="2026-11-04")
        self.assertEqual(rule["by"], "Sam")

    def test_unknown_status_rejected(self):
        with self.assertRaisesRegex(RecordError, "status"):
            self.rule(status="probably")


class RequirementTests(RecordBase):
    def test_requirement_must_cite_a_rule(self):
        with self.assertRaisesRegex(RecordError, "rule"):
            add_record(self.ws, "requirement", text="The system shall discount.", rules=[])

    def test_requirement_cannot_cite_unknown_rule(self):
        with self.assertRaisesRegex(RecordError, "RULE-nope"):
            add_record(self.ws, "requirement", text="The system shall discount.", rules=["RULE-nope"])

    def test_requirement_rejects_cobol_terms(self):
        rule = self.rule()
        for text in ["PERFORM 3200-APPLY-DISC applies it.", "Set WS-TOTAL.", "It is COMP-3."]:
            with self.subTest(text=text), self.assertRaisesRegex(RecordError, "business language"):
                add_record(self.ws, "requirement", text=text, rules=[rule["id"]])

    def test_requirement_inherits_lowest_confidence_from_rules(self):
        firm = self.rule()
        soft = self.rule(status="inferred")
        req = add_record(self.ws, "requirement", text="The system shall discount.", rules=[firm["id"], soft["id"]])
        self.assertEqual(req["confidence"], "inferred")

    def test_test_scenario_links_to_rule(self):
        rule = self.rule()
        scenario = add_record(self.ws, "test", given="A preferred customer", when="An order over 10000 is billed",
                              then="The total is reduced by 5%", rules=[rule["id"]])
        self.assertTrue(scenario["id"].startswith("TEST-"))

    def test_ids_do_not_collide(self):
        self.assertEqual(len({self.rule()["id"] for _ in range(50)}), 50)


class GapLoopTests(RecordBase):
    def question(self, **kw):
        kw.setdefault("question", "Orders from region 07 get no discount. Is that still intended?")
        kw.setdefault("example", "An order from region 07 for 20000 is billed in full.")
        kw.setdefault("depends_on", "Whether the discount applies to every region.")
        return add_sme_question(self.ws, **kw)

    def test_sme_question_routed_to_sme(self):
        gap = self.question()
        self.assertEqual((gap["kind"], gap["owner"], gap["status"]), ("sme_question", "sme", "open"))

    def test_sme_question_with_cobol_rejected(self):
        with self.assertRaisesRegex(RecordError, "business language"):
            self.question(question="Why does 3200-APPLY-DISC check WS-REGION?")

    def test_answer_records_person_and_date(self):
        gap = self.question()
        answered = answer_gap(self.ws, gap["id"], by="Sam Lee", answer="Yes, by contract.", on="2026-11-04")
        self.assertEqual((answered["status"], answered["answered_by"], answered["answered_on"]), ("answered", "Sam Lee", "2026-11-04"))

    def test_answer_needs_a_person(self):
        gap = self.question()
        with self.assertRaisesRegex(RecordError, "who"):
            answer_gap(self.ws, gap["id"], by="", answer="Yes")

    def test_answer_promotes_linked_rule(self):
        gap = self.question()
        rule = self.rule(status="ask_expert", gap=gap["id"])
        answer_gap(self.ws, gap["id"], by="Sam", answer="Yes", on="2026-11-04")
        saved = [r for r in load_records(self.ws, "rule") if r["id"] == rule["id"]][0]
        self.assertEqual((saved["status"], saved["by"]), ("confirmed_sme", "Sam"))

    def test_conflict_stays_open_and_picks_no_side(self):
        gap = self.question()
        rule = self.rule(status="ask_expert", gap=gap["id"])
        result = answer_gap(self.ws, gap["id"], by="Sam", answer="No, it was removed.", on="2026-11-04", conflict=True)
        self.assertEqual(result["status"], "conflict")
        saved = [r for r in load_records(self.ws, "rule") if r["id"] == rule["id"]][0]
        self.assertEqual(saved["status"], "conflict")
        self.assertIn(gap["id"], {g["id"] for g in top_gaps(self.ws, 100)})

    def test_conflict_resolved_only_by_a_person(self):
        gap = self.question()
        answer_gap(self.ws, gap["id"], by="Sam", answer="No", on="2026-11-04", conflict=True)
        with self.assertRaisesRegex(RecordError, "who"):
            resolve_conflict(self.ws, gap["id"], by="", decision="Follow the code")
        resolved = resolve_conflict(self.ws, gap["id"], by="Ana", decision="Follow the code", on="2026-11-05")
        self.assertEqual((resolved["status"], resolved["resolved_by"]), ("resolved", "Ana"))

    def test_answer_survives_rerun(self):
        gap = [g for g in load_gaps(self.ws) if g["name"] == "MISSCPY"][0]
        answer_gap(self.ws, gap["id"], by="Max", answer="Retired; layout is in NEWCPY.", on="2026-11-04")
        run_all(self.ws)
        self.assertEqual(get_gap(self.ws, gap["id"])["status"], "answered")

    def test_unknown_gap_gives_plain_error(self):
        with self.assertRaisesRegex(RecordError, "GAP-none"):
            answer_gap(self.ws, "GAP-none", by="Sam", answer="x")

    def test_top_gaps_limited_and_ranked_by_what_they_block(self):
        gaps = top_gaps(self.ws, 3)
        self.assertEqual(len(gaps), 3)
        order = {"high": 0, "medium": 1, "low": 2}
        ranks = [order[g["urgency"]] for g in gaps]
        self.assertEqual(ranks, sorted(ranks))

    def test_focus_puts_current_work_first(self):
        gaps = top_gaps(self.ws, 1, focus=["program:PRICECHK"])
        self.assertIn("program:PRICECHK", gaps[0]["blocks"])


class StatusAndImpactTests(RecordBase):
    def test_program_with_open_gap_is_incomplete(self):
        result = status(self.ws, "program", "PRICECHK")
        self.assertEqual(result["state"], "incomplete")
        self.assertIn("MISSCPY", [g["name"] for g in result["blocking"]])

    def test_program_with_no_gaps_is_complete(self):
        self.assertEqual(status(self.ws, "program", "ORPHAN")["state"], "complete")

    def test_status_clears_when_gap_resolved(self):
        with open(os.path.join(self.src, "copy", "MISSCPY"), "w") as f:
            f.write("000100 01  M PIC X.\n")
        run_all(self.ws)
        self.assertEqual(status(self.ws, "program", "PRICECHK")["state"], "complete")

    def test_impact_lists_only_dependents(self):
        gap = [g for g in load_gaps(self.ws) if g["name"] == "MISSCPY"][0]
        rule = add_record(self.ws, "rule", text="Price lookup.", status="inferred", evidence=["PRICECHK:0000-MAIN:11-12"])
        other = add_record(self.ws, "rule", text="Discount.", status="confirmed_code", evidence=[DISCOUNT])
        result = impact(self.ws, gap["id"])
        self.assertEqual(result["members"], ["program:PRICECHK"])
        self.assertIn(rule["id"], result["rules"])
        self.assertNotIn(other["id"], result["rules"])

    def test_nothing_stale_right_after_analysis(self):
        record_analysis(self.ws, "program", "BILLCALC")
        self.assertEqual(stale(self.ws), [])

    def test_source_change_marks_only_that_analysis_stale(self):
        record_analysis(self.ws, "program", "BILLCALC")
        record_analysis(self.ws, "program", "ORPHAN")
        with open(os.path.join(self.src, "cobol", "ORPHAN.cbl"), "a") as f:
            f.write("000600*    CHANGED\n")
        run_all(self.ws)
        self.assertEqual([s["name"] for s in stale(self.ws)], ["ORPHAN"])

    def test_copybook_change_marks_its_users_stale(self):
        record_analysis(self.ws, "program", "BILLCALC")
        record_analysis(self.ws, "program", "ORPHAN")
        with open(os.path.join(self.src, "copy", "CUSTREC"), "a") as f:
            f.write("001300*    CHANGED\n")
        run_all(self.ws)
        self.assertEqual([s["name"] for s in stale(self.ws)], ["BILLCALC"])

    def test_resolved_gap_marks_analysis_stale(self):
        record_analysis(self.ws, "program", "PRICECHK")
        with open(os.path.join(self.src, "copy", "MISSCPY"), "w") as f:
            f.write("000100 01  M PIC X.\n")
        run_all(self.ws)
        self.assertEqual([s["name"] for s in stale(self.ws)], ["PRICECHK"])


class ValidateTests(RecordBase):
    def test_clean_records_have_no_issues(self):
        self.rule()
        self.assertEqual(validate(self.ws), [])

    def test_changed_source_flags_evidence(self):
        rule = self.rule()
        path = os.path.join(self.src, "cobol", "BILLCALC.cbl")
        with open(path, "a") as f:
            f.write("005500*    CHANGED\n")
        run_all(self.ws)
        issues = validate(self.ws)
        self.assertEqual(issues[0]["id"], rule["id"])
        self.assertIn("changed", issues[0]["problem"])

    def test_requirement_with_deleted_rule_flagged(self):
        rule = self.rule()
        req = add_record(self.ws, "requirement", text="The system shall discount.", rules=[rule["id"]])
        os.remove(self.ws.path("requirements", "rules", rule["id"] + ".json"))
        self.assertIn(req["id"], {i["id"] for i in validate(self.ws)})


class RenderTests(RecordBase):
    def test_mainframe_request_has_exact_members_and_lines(self):
        render_all(self.ws)
        text = self.read("gaps", "MAINFRAME_TEAM_REQUEST.md")
        self.assertIn("MISSCPY", text)
        self.assertIn("PRICECHK.cbl", text)
        self.assertIn("line 5", text)
        self.assertNotIn("sme_question", text)

    def test_sme_questions_hide_code_references(self):
        add_sme_question(self.ws, question="Orders from region 07 get no discount. Is that intended?",
                         example="A region 07 order for 20000 is billed in full.",
                         depends_on="Whether the discount applies everywhere.",
                         references=[{"file": "src/cobol/BILLCALC.cbl", "line": 48}])
        render_all(self.ws)
        text = self.read("gaps", "SME_QUESTIONS.md")
        self.assertIn("region 07", text)
        self.assertNotIn("BILLCALC", text)
        self.assertNotIn("MISSCPY", text)
        self.assertIn("BILLCALC", self.read("gaps", "REQUEST_LIST.md"))

    def test_traceability_links_requirement_rule_source_and_test(self):
        rule = self.rule()
        req = add_record(self.ws, "requirement", text="The system shall discount.", rules=[rule["id"]])
        test = add_record(self.ws, "test", given="g", when="w", then="t", rules=[rule["id"]])
        render_all(self.ws)
        text = self.read("requirements", "TRACEABILITY.md")
        for token in (req["id"], rule["id"], test["id"], "BILLCALC", "44-50"):
            self.assertIn(token, text)

    def test_quote_setting_controls_source_in_rules(self):
        self.rule()
        render_all(self.ws)
        self.assertIn("COMPUTE WS-TOTAL ROUNDED", self.read("requirements", "RULES.md"))
        self.ws.config["quote_source"] = False
        self.ws.save()
        render_all(self.ws)
        text = self.read("requirements", "RULES.md")
        self.assertNotIn("COMPUTE WS-TOTAL ROUNDED", text)
        self.assertIn("44-50", text)

    def test_status_is_shown_in_plain_words(self):
        self.rule(status="inferred")
        render_all(self.ws)
        self.assertIn("Inferred", self.read("requirements", "RULES.md"))

    def test_render_is_deterministic(self):
        self.rule()
        render_all(self.ws)
        first = self.read("requirements", "RULES.md"), self.read("gaps", "REQUEST_LIST.md")
        render_all(self.ws)
        self.assertEqual(first, (self.read("requirements", "RULES.md"), self.read("gaps", "REQUEST_LIST.md")))


if __name__ == "__main__":
    unittest.main()
