"""Missing information: one file per gap, stable IDs, merged with what people have answered."""
import glob
import hashlib

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
    "duplicate_member": ("Which copy is the right one", "Copies with the same name differ, so links to this name can't be trusted until a rule is set."),
}


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
    unknown = [m["path"] for m in catalogue if m["kind"] == "unknown"]
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


def detect_gaps(ws):
    detected = _detect(ws)
    existing = {g["id"]: g for g in load_gaps(ws)}
    for gid, gap in detected.items():
        old = existing.get(gid)
        if old and old["status"] in ("answered", "conflict"):
            for key in ("status", "answer", "answered_by", "answered_on"):
                if key in old:
                    gap[key] = old[key]
        save_gap(ws, gap)
    for gid, old in existing.items():
        if gid not in detected and old.get("source") == "detected" and old["status"] == "open":
            old["status"] = "resolved"
            old["resolution"] = "found_in_source"
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

