"""Turn saved records into the documents people read and send. Generated, so never hand-edited."""
from .config import write_text
from .gaps import load_gaps, top_gaps
from .inventory import load_catalogue, read_member_text
from .records import load_records
from .sourcefile import split_lines

STATUS_WORDS = {
    "confirmed_code": "Confirmed from code", "inferred": "Inferred", "confirmed_sme": "Confirmed by SME",
    "ask_expert": "Ask an expert", "conflict": "Conflict",
}
MAX_QUOTED_LINES = 12
MAX_LISTED_REFERENCES = 5


def _citation_text(citation):
    where = citation["member"]
    if citation["paragraph"]:
        where += " " + citation["paragraph"]
    return "%s, lines %d-%d" % (where, citation["start"], citation["end"])


def _reference_text(reference):
    text = reference["file"]
    if reference.get("line"):
        text += " line %d" % reference["line"]
    return text


def _references_line(gap):
    references = gap["references"]
    shown = ", ".join(_reference_text(r) for r in references[:MAX_LISTED_REFERENCES])
    extra = gap.get("reference_count", len(references)) - min(len(references), MAX_LISTED_REFERENCES)
    if extra > 0:
        shown += " and %d more" % extra
    return shown or "the whole system"


def _render_request_list(ws, gaps):
    ranked = top_gaps(ws, len(gaps) or 1)
    lines = ["# Missing information", "", "Open items, most important first.", ""]
    if not ranked:
        lines.append("Nothing is open.")
    for gap in ranked:
        lines += [
            "## %s: %s" % (gap["id"], gap["what"]), "",
            "- **Item:** %s" % gap["name"],
            "- **Owner:** %s" % ("SME" if gap["owner"] == "sme" else "Mainframe team"),
            "- **Urgency:** %s" % gap["urgency"],
            "- **Status:** %s" % gap["status"],
            "- **Why it matters:** %s" % gap["why"],
            "- **Blocks:** %s" % (", ".join(gap["blocks"][:10]) or "not specific to one program"),
            "- **Referenced at:** %s" % _references_line(gap), "",
        ]
    write_text(ws.path("gaps", "REQUEST_LIST.md"), "\n".join(lines))


def _render_mainframe_request(ws, gaps):
    open_items = [g for g in gaps if g["owner"] == "mainframe_team" and g["status"] == "open"]
    lines = [
        "# Request to the mainframe team", "",
        "We're analyzing this system for modernization and need the items below. Each one lists where it was referenced and what it's holding up.", "",
    ]
    if not open_items:
        lines.append("Nothing is needed right now.")
    kinds = sorted({g["kind"] for g in open_items})
    for kind in kinds:
        group = sorted((g for g in open_items if g["kind"] == kind), key=lambda g: (-len(g["blocks"]), g["name"]))
        lines += ["## %s" % group[0]["what"], "", group[0]["why"], ""]
        for gap in group:
            lines.append("- **%s** (%s urgency, ref %s): referenced by %s" % (gap["name"], gap["urgency"], gap["id"], _references_line(gap)))
        lines.append("")
    write_text(ws.path("gaps", "MAINFRAME_TEAM_REQUEST.md"), "\n".join(lines))


def _render_sme_questions(ws, gaps):
    questions = [g for g in gaps if g["owner"] == "sme" and g["status"] == "open"]
    lines = ["# Questions for subject matter experts", "", "Please answer in your own words. It's fine to say you don't know or to point us to someone else.", ""]
    if not questions:
        lines.append("There are no open questions.")
    for number, gap in enumerate(questions, 1):
        lines += [
            "## Question %d" % number, "", gap["what"], "",
            "- **Example:** %s" % gap.get("example", ""),
            "- **What depends on your answer:** %s" % gap["why"],
            "- **Reference:** %s" % gap["id"], "",
        ]
    write_text(ws.path("gaps", "SME_QUESTIONS.md"), "\n".join(lines))


def _render_answers(ws, gaps):
    answered = [g for g in gaps if g.get("answered_by")]
    lines = ["# Answers log", ""]
    if not answered:
        lines.append("No answers recorded yet.")
    for gap in answered:
        lines += [
            "## %s" % gap["id"], "", "- **Item:** %s" % gap["name"],
            "- **Answer:** %s" % gap["answer"],
            "- **From:** %s on %s" % (gap["answered_by"], gap["answered_on"]),
            "- **Status:** %s" % gap["status"],
        ]
        if gap.get("resolved_by"):
            lines.append("- **Decision:** %s (%s on %s)" % (gap["decision"], gap["resolved_by"], gap["resolved_on"]))
        lines.append("")
    write_text(ws.path("gaps", "ANSWERS.md"), "\n".join(lines))


def _quote(ws, citation, members, cache):
    entry = members.get(citation["file"])
    if entry is None:
        return None
    if citation["file"] not in cache:
        try:
            cache[citation["file"]] = split_lines(read_member_text(ws, entry))
        except OSError:
            cache[citation["file"]] = []
    lines = cache[citation["file"]][citation["start"] - 1:citation["end"]]
    return lines[:MAX_QUOTED_LINES]


def _render_rules(ws, rules):
    members = {m["path"]: m for m in load_catalogue(ws)}
    cache = {}
    lines = ["# Business rules", ""]
    if not rules:
        lines.append("No rules recorded yet.")
    for rule in rules:
        lines += ["## %s" % rule["id"], "", rule["text"], "", "- **Status:** %s" % STATUS_WORDS[rule["status"]]]
        if rule.get("by"):
            lines.append("- **Confirmed by:** %s on %s" % (rule["by"], rule["on"]))
        if rule.get("decision"):
            lines.append("- **Decision:** %s" % rule["decision"])
        if rule.get("gap"):
            lines.append("- **Open item:** %s" % rule["gap"])
        for citation in rule["evidence"]:
            lines.append("- **Evidence:** %s (`%s`)" % (_citation_text(citation), citation["file"]))
            quoted = _quote(ws, citation, members, cache) if ws.config["quote_source"] else None
            if quoted:
                lines += ["", "```cobol"] + quoted + ["```"]
        lines.append("")
    write_text(ws.path("requirements", "RULES.md"), "\n".join(lines))


def _render_requirements(ws, requirements):
    lines = ["# Requirements", ""]
    if not requirements:
        lines.append("No requirements recorded yet.")
    for req in requirements:
        lines += ["## %s" % req["id"], "", req["text"], "", "- **Confidence:** %s" % STATUS_WORDS[req["confidence"]], "- **Rules:** %s" % ", ".join(req["rules"]), ""]
    write_text(ws.path("requirements", "REQUIREMENTS.md"), "\n".join(lines))


def _render_tests(ws, tests):
    lines = ["# Test scenarios", ""]
    if not tests:
        lines.append("No test scenarios recorded yet.")
    for test in tests:
        lines += ["## %s" % test["id"], "", "- **Given** %s" % test["given"], "- **When** %s" % test["when"], "- **Then** %s" % test["then"], "- **Rules:** %s" % ", ".join(test["rules"]), ""]
    write_text(ws.path("requirements", "TEST_SCENARIOS.md"), "\n".join(lines))


def _render_traceability(ws, rules, requirements, tests):
    by_id = {r["id"]: r for r in rules}
    lines = ["# Traceability", "", "| Requirement | Rule | Status | Source | Tests |", "|-------------|------|--------|--------|-------|"]
    covered = set()
    for req in requirements:
        for rid in req["rules"]:
            covered.add(rid)
            rule = by_id.get(rid)
            source = "; ".join(_citation_text(c) for c in rule["evidence"]) if rule else "missing"
            state = STATUS_WORDS[rule["status"]] if rule else "missing"
            linked = ", ".join(t["id"] for t in tests if rid in t["rules"]) or "none"
            lines.append("| %s | %s | %s | %s | %s |" % (req["id"], rid, state, source, linked))
    for rule in rules:
        if rule["id"] not in covered:
            source = "; ".join(_citation_text(c) for c in rule["evidence"])
            linked = ", ".join(t["id"] for t in tests if rule["id"] in t["rules"]) or "none"
            lines.append("| none | %s | %s | %s | %s |" % (rule["id"], STATUS_WORDS[rule["status"]], source, linked))
    write_text(ws.path("requirements", "TRACEABILITY.md"), "\n".join(lines) + "\n")


def render_all(ws):
    gaps = load_gaps(ws)
    _render_request_list(ws, [g for g in gaps if g["status"] in ("open", "conflict")])
    _render_mainframe_request(ws, gaps)
    _render_sme_questions(ws, gaps)
    _render_answers(ws, gaps)
    rules = load_records(ws, "rule")
    requirements = load_records(ws, "requirement")
    tests = load_records(ws, "test")
    _render_rules(ws, rules)
    _render_requirements(ws, requirements)
    _render_tests(ws, tests)
    _render_traceability(ws, rules, requirements, tests)
