"""Everything a developer or Copilot needs to know about one member, without reading it all."""
from .config import write_json, write_text
from .depmap import load_map
from .gaps import RecordError
from .inventory import load_catalogue, load_facts, read_member_text
from .records import status
from .sourcefile import split_lines

JAVA_NOTES = {
    "comp3": "Packed decimal. Use BigDecimal with the same scale, never double.",
    "redefines": "The same bytes have two meanings. Decide how to model this and which view each record uses.",
    "occurs_depending": "Variable-length table. Check the count field drives the size, including on malformed records.",
    "level88": "Named values. Model as an enum or a boolean method, and keep the literal values.",
    "goto": "Control jumps here. Don't assume a paragraph runs top to bottom when you rebuild it.",
    "perform_thru": "Runs a range of paragraphs, including any between the two names.",
    "alter": "Changes a jump target at runtime. Trace it by hand or ask the mainframe team.",
    "next_sentence": "Jumps past the next period, which is easy to misread. Check the real path.",
    "rounded": "Rounds here. Match the rounding mode exactly with BigDecimal.",
    "unrounded_compute": "No ROUNDED, so extra digits are cut off. Use RoundingMode.DOWN, not HALF_UP.",
    "sort_verb": "Sorting happens in the program. EBCDIC order differs from ASCII: digits sort after letters.",
    "collating_sequence": "A custom sort order. Reproduce it explicitly in Java or the database.",
    "file_status": "Behaviour depends on file status codes. Map each one to an explicit outcome.",
    "sqlcode": "Behaviour depends on SQL return codes. Map each to an explicit outcome or exception.",
    "abend": "Can stop abnormally. Define what the rebuild does at that point, and what gets rolled back.",
    "return_code": "Sets a return code that later job steps may test. Keep that contract.",
    "checkpoint": "Checkpoint or restart logic. Spring Batch chunking and restart must give the same recovery.",
    "commit": "Commits or rolls back here. Match the transaction boundaries with @Transactional.",
    "commarea": "State passed between screens or programs. Decide where it lives in a stateless service.",
    "syncpoint": "A CICS transaction boundary. Match it with Spring transaction boundaries.",
    "locking": "Locks data. Decide between optimistic and pessimistic locking, and test concurrent use.",
    "cics_handle": "CICS error or key handling jumps elsewhere. Map it to explicit exception handling.",
    "date_window": "Two-digit or windowed date. Confirm the century rule before converting to LocalDate.",
    "sort_step": "A job step sorts data outside any program. Its fields and order are business logic.",
    "sort_control_logic": "SORT control cards can filter or reformat records. Read them as business rules.",
    "idcams_step": "IDCAMS manages files here. Check whether a copy or delete step matters to the outcome.",
    "ims_step": "An IMS step. IMS isn't analyzed by this version of the skill.",
    "jcl_cond": "The step runs depending on earlier return codes. Reproduce this in the job flow.",
    "jcl_if": "The job branches on return codes. Reproduce this in the job flow.",
    "gdg": "A generation dataset: each run makes a new version. Decide how versioning and retention work.",
}
MAX_HAZARD_LINES = 20
PARAGRAPH_FLOW_LIMIT = 60
NODE_PREFIX = {"cobol_program": "program:", "copybook": "copybook:", "jcl_job": "job:", "jcl_proc": "proc:", "assembler": "program:", "pli": "program:", "rexx": "program:", "easytrieve": "program:"}
STATUS_KIND = {"copybook": "copybook", "jcl_job": "job", "jcl_proc": "proc"}


def find_member(ws, name):
    name = name.upper()
    fallback = None
    for entry in load_catalogue(ws):
        if not entry.get("selected", True):
            continue
        if entry["name"] == name or entry.get("program_id") == name:
            if entry["kind"] in NODE_PREFIX:
                return entry
            fallback = fallback or entry
    if fallback:
        return fallback
    raise RecordError("%s isn't in the inventory. It may be missing from the source: run python mma.py gaps" % name)


def _hidden_behaviour(hazards):
    grouped = {}
    for hazard in hazards:
        grouped.setdefault(hazard["type"], []).append(hazard["line"])
    return [
        {"type": kind, "count": len(lines), "lines": lines[:MAX_HAZARD_LINES], "java_note": JAVA_NOTES.get(kind, "")}
        for kind, lines in sorted(grouped.items())
    ]


def _paragraph_flow(facts):
    paragraphs = facts["paragraphs"][:PARAGRAPH_FLOW_LIMIT]
    ids = {p["name"]: "p%d" % i for i, p in enumerate(paragraphs)}
    lines = ["flowchart TD"]
    lines += ['  %s["%s"]' % (ids[p["name"]], p["name"]) for p in paragraphs]
    seen = set()
    for kind, items, arrow in (("perform", facts["performs"], "-->"), ("go to", facts["gotos"], "-.->")):
        for item in items:
            source, target = ids.get(item["from"]), ids.get(item["target"])
            if source and target and (source, target, kind) not in seen:
                seen.add((source, target, kind))
                label = "thru " + item["thru"] if item.get("thru") else kind
                lines.append("  %s %s|%s| %s" % (source, arrow, label, target))
    if len(facts["paragraphs"]) > PARAGRAPH_FLOW_LIMIT:
        lines.append("  %% trimmed: %d more paragraphs" % (len(facts["paragraphs"]) - PARAGRAPH_FLOW_LIMIT))
    return "\n".join(lines)


def program_facts(ws, name):
    entry = find_member(ws, name)
    kind = entry["kind"]
    node = NODE_PREFIX.get(kind, "") + entry["name"]
    edges = load_map(ws)["edges"]
    result = {
        "name": entry["name"], "kind": kind, "file": entry["path"], "lines": entry["line_count"],
        "callers": [{"from": e["from"], "type": e["type"], "file": e["file"], "line": e["line"]} for e in edges if e["to"] == node],
        "uses": [{"to": e["to"], "type": e["type"], "line": e["line"], "confidence": e["confidence"]} for e in edges if e["from"] == node],
        "state": "not_analyzed", "blocking": [],
    }
    if kind in NODE_PREFIX:
        current = status(ws, STATUS_KIND.get(kind, "program"), entry["name"])
        result["state"], result["blocking"] = current["state"], current["blocking"]
    facts = load_facts(ws, entry)
    if kind in ("cobol_program", "copybook"):
        result["copybooks"] = sorted({c["name"] for c in facts["copies"]})
        result["hidden_behaviour"] = _hidden_behaviour(facts["hazards"])
        result["unrecognized_statements"] = facts["unrecognized"]
    if kind == "cobol_program":
        result["program_id"] = facts["program_id"]
        result["technologies"] = facts["technologies"]
        result["paragraphs"] = facts["paragraphs"]
        result["paragraph_flow"] = _paragraph_flow(facts)
        result["files"] = facts["files"]
        result["decisions"] = facts["metrics"]["decisions"]
    elif kind in ("jcl_job", "jcl_proc"):
        result["hidden_behaviour"] = _hidden_behaviour(facts["hazards"])
        result["steps"] = [
            {k: s[k] for k in ("name", "line", "program", "proc", "run_program", "parm", "cond")} |
            {"dds": [{k: d[k] for k in ("name", "dsn", "member", "disp", "line")} for d in s["dds"]],
             "control_cards": [d["inline"] for d in s["dds"] if d["inline"]]}
            for s in facts["steps"]
        ]
    _save(ws, result)
    return result


def _save(ws, result):
    write_json(ws.path("programs", result["name"] + ".facts.json"), result)
    lines = [
        "# %s: facts" % result["name"], "",
        "Extracted by script from `%s` (%d lines). The explanation belongs in `%s.md`." % (result["file"], result["lines"], result["name"]), "",
        "**State:** %s" % result["state"], "",
    ]
    if result["blocking"]:
        lines += ["## Blocked by", ""] + ["- %s: %s" % (g["id"], g["name"]) for g in result["blocking"]] + [""]
    if result.get("paragraph_flow"):
        lines += ["## Paragraph flow", "", "```mermaid", result["paragraph_flow"], "```", ""]
    if result.get("hidden_behaviour"):
        lines += ["## Hidden behaviour to carry over", "", "| What | Lines | What to do |", "|------|-------|------------|"]
        lines += ["| %s | %s | %s |" % (h["type"], ", ".join(str(n) for n in h["lines"]), h["java_note"]) for h in result["hidden_behaviour"]]
        lines.append("")
    write_text(ws.path("programs", result["name"] + ".facts.md"), "\n".join(lines))


def read_source(ws, name, paragraph=None, start=None, end=None, limit=400):
    """Return numbered source for just the part being analyzed, to keep Copilot's context small."""
    entry = find_member(ws, name)
    lines = split_lines(read_member_text(ws, entry))
    if paragraph:
        wanted = paragraph.upper()
        found = [p for p in load_facts(ws, entry).get("paragraphs", []) if p["name"] == wanted]
        if not found:
            raise RecordError("%s has no paragraph called %s." % (entry["name"], wanted))
        start, end = found[0]["start_line"], found[0]["end_line"]
    first = max(start or 1, 1)
    last = min(end or len(lines), len(lines))
    shown = lines[first - 1:min(last, first - 1 + limit)]
    output = ["%d: %s" % (first + i, text) for i, text in enumerate(shown)]
    remaining = last - first + 1 - len(shown)
    if remaining > 0:
        output.append("... %d more lines. Ask for a paragraph or a line range." % remaining)
    return "\n".join(output)

