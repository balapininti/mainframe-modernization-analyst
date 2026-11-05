"""Missing information: one file per gap, stable IDs, merged with what people have answered."""
import datetime
import glob
import hashlib
import re

from .config import read_json, write_json
from .depmap import load_map
from .inventory import load_catalogue, load_duplicates

KIND_TEXT = {
    "missing_copybook": ("Copybook source", "Record layouts in the referencing programs can't be read without it."),
    "missing_program": ("Program source", "This program is called or run, but its logic can't be analyzed without its source."),
    "missing_proc": ("JCL PROC source", "The job steps inside this PROC are unknown without it."),
    "missing_bms_map": ("BMS mapset source", "The screen layout and its fields are unknown without it."),
    "missing_db2_ddl": ("DB2 table definition (DDL or DCLGEN)", "Column types and constraints are unknown without it."),
    "missing_vsam_def": ("VSAM file definition (IDCAMS)", "Keys, record size and file type can't be confirmed without it."),
    "missing_cics_def": ("CICS definition (CSD)", "Online entry points and file bindings can't be confirmed without it."),
    "missing_control_card": ("Control card member", "Job behaviour set by this card is unknown without it."),
    "missing_schedule": ("Job scheduler definitions", "Job order, frequency and dependencies aren't in the JCL."),
    "dynamic_reference": ("The runtime value of this name", "The target is decided at runtime, so this path through the system is unknown."),
    "unsupported_technology": ("A decision on how to analyze this technology", "These files aren't parsed by this version of the skill, so anything they do is missing from the map."),
    "undecodable_files": ("Readable copies of these files", "They couldn't be read as text. They may be binary data, or need a different code page."),
    "unrecognized_files": ("Confirmation of what these files are", "They didn't match any known mainframe source type, so they aren't in the analysis."),
    "parse_failures": ("A look at why these files couldn't be parsed", "The skill failed on them, so anything they do is missing from the map. Please report this through a log export."),
    "duplicate_member": ("Which copy is the right one", "Copies with the same name differ, so links to this name can't be trusted until a rule is set."),
}


class RecordError(Exception):
    """Input the skill refuses. The message tells the person what to fix."""


def gap_id(kind, name):
    return "GAP-" + hashlib.sha1((kind + ":" + name).encode()).hexdigest()[:10]


def _urgency(blocks):
    return "high" if len(blocks) >= 5 else "medium" if len(blocks) >= 2 else "low"


def _new(kind, name, references, blocks, owner="mainframe_team", urgency=None):
    what, why = KIND_TEXT[kind]
    refs = sorted(references, key=lambda r: (r["file"], r.get("line") or 0))
    blocks = sorted(set(blocks))
    return {
        "id": gap_id(kind, name), "kind": kind, "name": name, "what": what, "why": why, "owner": owner,
        "references": refs[:50], "reference_count": len(refs), "blocks": blocks,
        "urgency": urgency or _urgency(blocks), "status": "open", "source": "detected",
    }


def _detect(ws):
    data = load_map(ws)
    catalogue = load_catalogue(ws)
    found = {}

    def add(gap):
        found[gap["id"]] = gap

    by_target = {}
    for edge in data["edges"]:
        by_target.setdefault(edge["to"], []).append(edge)

    def refs_blocks(node):
        edges = by_target.get(node, [])
        return [{"file": e["file"], "line": e["line"], "from": e["from"]} for e in edges], [e["from"] for e in edges]

    kinds = {"copybook": "missing_copybook", "program": "missing_program", "proc": "missing_proc", "mapset": "missing_bms_map", "control": "missing_control_card"}
    for node in data["missing"]:
        node_type, _, name = node.partition(":")
        references, blocks = refs_blocks(node)
        add(_new(kinds[node_type], name, references, blocks))
    present = data["present"]
    for node, edges in sorted(by_target.items()):
        node_type, _, name = node.partition(":")
        references, blocks = refs_blocks(node)
        if node_type == "table" and name not in present["table"]:
            add(_new("missing_db2_ddl", name, references, blocks))
        elif node_type == "transaction" and name not in present["transaction"]:
            add(_new("missing_cics_def", "TRANSACTION " + name, references, blocks))
        elif node_type == "cics_file" and name not in present["cics_file"]:
            add(_new("missing_cics_def", "FILE " + name, references, blocks))
    grouped = {}
    for dsn, path, line, source in data["vsam_references"]:
        if dsn not in present["dataset"]:
            grouped.setdefault(dsn, []).append(({"file": path, "line": line, "from": source}, source))
    for dsn, items in sorted(grouped.items()):
        add(_new("missing_vsam_def", dsn, [i[0] for i in items], [i[1] for i in items]))
    if data["job_count"] and not data["has_scheduler"]:
        add(_new("missing_schedule", "ALL-JOBS", [], [], urgency="medium"))
    for dynamic in data["dynamic"]:
        program = dynamic["from"].partition(":")[2]
        name = "%s:%s" % (program, dynamic["variable"])
        gap = _new("dynamic_reference", name, [{"file": dynamic["file"], "line": dynamic["line"], "from": dynamic["from"]}], [dynamic["from"]], urgency="medium")
        gap["detail"] = dynamic["what"]
        if gap["id"] in found:
            found[gap["id"]]["references"] = sorted(found[gap["id"]]["references"] + gap["references"], key=lambda r: (r["file"], r["line"]))
            found[gap["id"]]["reference_count"] = len(found[gap["id"]]["references"])
        else:
            add(gap)
    for tech, paths in data["technologies"].items():
        add(_new("unsupported_technology", tech, [{"file": p, "line": None} for p in paths], [], urgency="high"))
    undecodable = [m["path"] for m in catalogue if m["kind"] == "undecodable"]
    if undecodable:
        add(_new("undecodable_files", "ALL", [{"file": p, "line": None} for p in undecodable], [], urgency="medium"))
    failed = [m["path"] for m in catalogue if m.get("parse_error")]
    if failed:
        add(_new("parse_failures", "ALL", [{"file": p, "line": None} for p in failed], [], urgency="high"))
    unknown = [m["path"] for m in catalogue if m["kind"] == "unknown" and not m.get("parse_error")]
    if unknown:
        add(_new("unrecognized_files", "ALL", [{"file": p, "line": None} for p in unknown], [], urgency="low"))
    for duplicate in load_duplicates(ws):
        name = "%s %s" % (duplicate["group"].upper(), duplicate["name"])
        add(_new("duplicate_member", name, [{"file": p, "line": None} for p in duplicate["paths"]], [], urgency="high"))
    return found


def _item_path(ws, gid):
    return ws.path("gaps", "items", gid + ".json")


def load_gaps(ws):
    gaps = [read_json(path) for path in glob.glob(ws.path("gaps", "items", "GAP-*.json"))]
    return sorted(gaps, key=lambda g: g["id"])


def get_gap(ws, gid):
    return read_json(_item_path(ws, gid))


def save_gap(ws, gap):
    write_json(_item_path(ws, gap["id"]), gap)


PRESERVED = ("status", "answer", "answered_by", "answered_on", "answers", "targets", "resolution", "resolved_by", "decision", "resolved_on")


def _where(gap):
    return sorted((r["file"], r.get("line") or 0) for r in gap["references"])


def detect_gaps(ws):
    detected = _detect(ws)
    existing = {g["id"]: g for g in load_gaps(ws)}
    present = {m["name"] for m in load_catalogue(ws)}
    for gid, gap in detected.items():
        old = existing.get(gid)
        if old and (old["status"] in ("answered", "conflict") or old.get("resolved_by")):
            for key in PRESERVED:
                if key in old:
                    gap[key] = old[key]
            if gap["status"] == "answered" and set(_where(gap)) - set(_where(old)):
                gap["status"] = "open"  # new places need it, so the old answer may no longer cover this
        elif old and old.get("answers"):
            gap["answers"] = old["answers"]
        save_gap(ws, gap)
    for gid, old in existing.items():
        if gid not in detected and old.get("source") == "detected" and old["status"] == "open":
            old["status"] = "resolved"
            if not old["kind"].startswith("missing_"):
                old["resolution"] = "no_longer_detected"
            elif old["name"] in present:
                old["resolution"] = "found_in_source"
            else:
                old["resolution"] = "no_longer_referenced"
            save_gap(ws, old)
    gaps = load_gaps(ws)
    by_kind, by_owner = {}, {}
    open_count = resolved = 0
    for gap in gaps:
        if gap["status"] in ("open", "conflict"):
            open_count += 1
            by_kind[gap["kind"]] = by_kind.get(gap["kind"], 0) + 1
            by_owner[gap["owner"]] = by_owner.get(gap["owner"], 0) + 1
        else:
            resolved += 1
    ws.logger.event("gaps", by_kind=by_kind, by_owner=by_owner, open=open_count, resolved=resolved)
    return {"open": open_count, "resolved": resolved, "by_kind": by_kind, "by_owner": by_owner}



COBOL_TERMS = re.compile(r"\b\d{3,4}-[A-Z]|\bPERFORM\b|\bPIC\b|\bMOVE\b|\bGO TO\b")  # uppercase only: these are also English words
MAINFRAME_TERMS = re.compile(
    r"\bWS-[A-Z]|\bCOMP-3\b|\bCOPYBOOK\b|\bEXEC\s+(?:CICS|SQL)\b|\bJCL\b|\bVSAM\b|\bCOBOL\b|\bREDEFINES\b|\bSQLCODE\b|\bDFH[A-Z]|\bCOMMAREA\b",
    re.I)


def has_cobol_terms(text):
    return bool(COBOL_TERMS.search(text or "") or MAINFRAME_TERMS.search(text or ""))


def add_sme_question(ws, question, example, depends_on, references=None, blocks=None):
    """A business question for an SME. The code reference is kept for the developer, not the SME."""
    if not question or not example or not depends_on:
        raise RecordError("An SME question needs the question, a real example, and what depends on the answer.")
    if any(has_cobol_terms(t) for t in (question, example, depends_on)):
        raise RecordError("Write SME questions in business language, with no program, field or mainframe terms.")
    existing = get_gap(ws, gap_id("sme_question", question))
    if existing and existing["status"] in ("answered", "conflict", "resolved"):
        raise RecordError("This was already asked as %s, and its status is %s. Its answer is kept." % (existing["id"], existing["status"]))
    if existing and existing["status"] == "open":
        existing["blocks"] = sorted(set(existing["blocks"]) | set(blocks or []))
        existing["references"] += [r for r in references or [] if r not in existing["references"]]
        existing["reference_count"] = len(existing["references"])
        save_gap(ws, existing)
        return existing
    gap = {
        "id": gap_id("sme_question", question), "kind": "sme_question", "name": question, "what": question,
        "why": depends_on, "example": example, "owner": "sme", "references": references or [],
        "reference_count": len(references or []), "blocks": sorted(blocks or []), "urgency": "medium",
        "status": "open", "source": "manual",
    }
    save_gap(ws, gap)
    return gap


def _require_gap(ws, gid):
    gap = get_gap(ws, gid)
    if gap is None:
        raise RecordError("There's no item called %s. Run: python mma.py gaps" % gid)
    return gap


def _update_linked_rules(ws, gid, **changes):
    for path in glob.glob(ws.path("requirements", "rules", "RULE-*.json")):
        rule = read_json(path)
        if rule.get("gap") == gid:
            rule.update(changes)
            write_json(path, rule)


def answer_gap(ws, gid, by, answer, on=None, conflict=False, partial=False, targets=None):
    """Record what a person said. `partial` keeps the item open; `targets` puts a runtime name on the map."""
    gap = _require_gap(ws, gid)
    if not by:
        raise RecordError("Say who gave this answer, so it can be traced back to them.")
    if not answer:
        raise RecordError("The answer is empty.")
    if gap["status"] == "conflict":
        raise RecordError("%s is a conflict between the code and an earlier answer. Only `gap resolve` can settle it." % gid)
    if gap["kind"] == "duplicate_member":
        raise RecordError("Set the rule in `library_precedence` in modernization/config.json, then scan again. That way the map uses the right copy.")
    on = on or datetime.date.today().isoformat()
    gap.setdefault("answers", []).append({"by": by, "on": on, "answer": answer, "kind": "conflict" if conflict else "partial" if partial else "answer"})
    if partial:
        save_gap(ws, gap)
        return gap
    gap.update(status="conflict" if conflict else "answered", answer=answer, answered_by=by, answered_on=on)
    if targets:
        gap["targets"] = sorted(t.upper() for t in targets)
    save_gap(ws, gap)
    _update_linked_rules(ws, gid, status="conflict" if conflict else "confirmed_sme", by=by, on=on)
    return gap


def resolve_conflict(ws, gid, by, decision, on=None):
    gap = _require_gap(ws, gid)
    if gap["status"] != "conflict":
        raise RecordError("%s isn't a conflict. Only a conflict between the code and an answer can be resolved here." % gid)
    if not by:
        raise RecordError("Say who made this decision. Only a person can settle a conflict between the code and an answer.")
    if not decision:
        raise RecordError("The decision is empty.")
    on = on or datetime.date.today().isoformat()
    gap.update(status="resolved", resolution="decided_by_person", resolved_by=by, decision=decision, resolved_on=on)
    save_gap(ws, gap)
    _update_linked_rules(ws, gid, status="confirmed_sme", by=by, on=on, decision=decision)
    return gap


def top_gaps(ws, limit=5, focus=None):
    """The items most worth asking about now: current work first, then what blocks the most."""
    focus = set(focus or [])
    order = {"high": 0, "medium": 1, "low": 2}
    gaps = [g for g in load_gaps(ws) if g["status"] in ("open", "conflict")]
    gaps.sort(key=lambda g: (
        0 if focus & set(g["blocks"]) else 1, order[g["urgency"]], 0 if g["status"] == "conflict" else 1,
        -len(g["blocks"]), g["id"]))
    return gaps[:limit]


def withdraw_question(ws, gid, reason):
    """Take back a question the skill or a developer added. Detected items close only through a scan."""
    gap = _require_gap(ws, gid)
    if gap.get("source") != "manual":
        raise RecordError("%s was found by the scan, so it closes when the next scan finds the item. It can't be withdrawn." % gid)
    if not reason:
        raise RecordError("Say why this is being withdrawn.")
    linked = sorted(read_json(p)["id"] for p in glob.glob(ws.path("requirements", "rules", "RULE-*.json")) if read_json(p).get("gap") == gid)
    if linked:
        raise RecordError("%s is linked to %s. Delete or re-record those first." % (gid, ", ".join(linked)))
    gap.update(status="withdrawn", resolution=reason)
    save_gap(ws, gap)
    return gap
