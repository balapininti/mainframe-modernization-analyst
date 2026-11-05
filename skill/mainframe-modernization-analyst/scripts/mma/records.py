"""Rules, requirements and test scenarios, each checked against the source it cites."""
import glob
import os
import re
import secrets

from .config import read_json, write_json
from .depmap import load_map
from .gaps import RecordError, get_gap, has_cobol_terms, load_gaps, save_gap
from .inventory import load_catalogue, load_facts
from .logs import LogFieldRejected

STATUS_ORDER = ["conflict", "ask_expert", "inferred", "confirmed_sme", "confirmed_code"]
FOLDERS = {"rule": "rules", "requirement": "requirements", "test": "tests"}
PREFIXES = {"rule": "RULE", "requirement": "REQ", "test": "TEST"}
_CITATION = re.compile(r"^([A-Za-z0-9#@$._-]+):([A-Za-z0-9-]*):(\d+)(?:-(\d+))?$")


def _members(ws):
    members = {}
    for entry in load_catalogue(ws):
        if entry.get("selected", True):
            members.setdefault(entry["name"], entry)
            if entry.get("program_id"):
                members.setdefault(entry["program_id"], entry)
    return members


def parse_citation(ws, text, members=None):
    match = _CITATION.match(text.strip())
    if not match:
        raise RecordError("Write each citation as PROGRAM:PARAGRAPH:START-END (leave PARAGRAPH empty for copybooks). Got: %s" % text)
    member, paragraph, start, end = match.group(1).upper(), match.group(2).upper() or None, int(match.group(3)), int(match.group(4) or match.group(3))
    members = members or _members(ws)
    entry = members.get(member)
    if entry is None:
        raise RecordError("The citation names %s, which isn't in the inventory." % member)
    if not 1 <= start <= end <= entry["line_count"]:
        raise RecordError("The citation gives lines %d-%d, but %s has %d lines." % (start, end, member, entry["line_count"]))
    if paragraph:
        paragraphs = {p["name"]: p for p in load_facts(ws, entry).get("paragraphs", [])}
        if paragraph not in paragraphs:
            raise RecordError("The citation names paragraph %s, which isn't in %s." % (paragraph, member))
        found = paragraphs[paragraph]
        if start < found["start_line"] or end > found["end_line"]:
            raise RecordError("The citation gives lines %d-%d, but %s is at lines %d-%d." % (start, end, paragraph, found["start_line"], found["end_line"]))
    return {"member": member, "paragraph": paragraph, "start": start, "end": end, "file": entry["path"], "sha": entry["sha"]}


def _new_id(kind):
    return "%s-%s" % (PREFIXES[kind], secrets.token_hex(4))


def _path(ws, kind, rid):
    return ws.path("requirements", FOLDERS[kind], rid + ".json")


def load_records(ws, kind):
    records = [read_json(p) for p in glob.glob(ws.path("requirements", FOLDERS[kind], PREFIXES[kind] + "-*.json"))]
    return sorted(records, key=lambda r: r["id"])


def _check_rules(ws, rule_ids):
    if not rule_ids:
        raise RecordError("This needs at least one rule to trace back to. Record the rule first.")
    rules = []
    for rid in rule_ids:
        rule = read_json(_path(ws, "rule", rid))
        if rule is None:
            raise RecordError("%s doesn't exist." % rid)
        rules.append(rule)
    return rules


def add_record(ws, kind, **fields):
    if kind == "rule":
        record = _build_rule(ws, **fields)
    elif kind == "requirement":
        record = _build_requirement(ws, **fields)
    elif kind == "test":
        record = _build_test(ws, **fields)
    else:
        raise RecordError("Records can be rule, requirement or test.")
    record["id"] = _new_id(kind)
    write_json(_path(ws, kind, record["id"]), record)
    if kind == "rule" and record["gap"]:
        gap = get_gap(ws, record["gap"])
        gap["blocks"] = sorted(set(gap["blocks"]) | {_member_node(members_entry) for members_entry in _cited_entries(ws, record)})
        save_gap(ws, gap)
    return record


def _cited_entries(ws, rule):
    members = _members(ws)
    return [members[c["member"]] for c in rule["evidence"] if c["member"] in members]


def _member_node(entry):
    prefix = {"copybook": "copybook:", "jcl_job": "job:", "jcl_proc": "proc:"}.get(entry["kind"], "program:")
    return prefix + entry["name"]


def delete_record(ws, rid):
    """Remove a saved rule, requirement or test so it can be recorded again correctly."""
    prefix = rid.partition("-")[0]
    kinds = {v: k for k, v in PREFIXES.items()}
    kind = kinds.get(prefix)
    if kind is None or read_json(_path(ws, kind, rid)) is None:
        raise RecordError("There's no record called %s." % rid)
    if kind == "rule":
        users = sorted(r["id"] for k in ("requirement", "test") for r in load_records(ws, k) if rid in r["rules"])
        if users:
            raise RecordError("%s is used by %s. Delete those first." % (rid, ", ".join(users)))
    os.remove(_path(ws, kind, rid))


def _build_rule(ws, text, status, evidence=None, slice=None, gap=None, by=None, on=None):
    if status not in STATUS_ORDER:
        raise RecordError("The status must be one of: %s." % ", ".join(STATUS_ORDER))
    if not text:
        raise RecordError("The rule text is empty.")
    evidence = evidence or []
    if status in ("confirmed_code", "inferred", "ask_expert") and not evidence:
        raise RecordError("A rule with status %s needs evidence: cite the source lines." % status)
    if status == "confirmed_sme" and not (by and on):
        raise RecordError("A rule confirmed by an SME needs the person's name and the date.")
    if gap and get_gap(ws, gap) is None:
        raise RecordError("%s doesn't exist." % gap)
    members = _members(ws)
    return {
        "text": text, "status": status, "evidence": [parse_citation(ws, c, members) for c in evidence],
        "slice": slice, "gap": gap, "by": by, "on": on,
    }


def _build_requirement(ws, text, rules=None, slice=None):
    if not text:
        raise RecordError("The requirement text is empty.")
    if has_cobol_terms(text):
        raise RecordError("Write requirements in business language, with no program, field or mainframe terms.")
    found = _check_rules(ws, rules)
    confidence = min((r["status"] for r in found), key=STATUS_ORDER.index)
    return {"text": text, "rules": sorted(rules), "slice": slice, "confidence": confidence}


def _build_test(ws, given, when, then, rules=None, slice=None):
    if not (given and when and then):
        raise RecordError("A test scenario needs given, when and then.")
    _check_rules(ws, rules)
    return {"given": given, "when": when, "then": then, "rules": sorted(rules), "slice": slice}


def _follow(start, edges):
    """Everything reachable from the start nodes. A flow is only complete if all of this is."""
    by_source = {}
    for edge in edges:
        by_source.setdefault(edge["from"], []).append(edge["to"])
    seen, pending = set(start), list(start)
    while pending:
        for target in by_source.get(pending.pop(), ()):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return seen


def _flow_start(name, edges):
    known = {e["from"] for e in edges} | {e["to"] for e in edges}
    for prefix in ("transaction", "job", "proc", "program"):
        node = "%s:%s" % (prefix, name)
        if node in known:
            return [node]
    raise RecordError("%s isn't a known transaction, job or program." % name)


def _nodes_for(ws, kind, name):
    if kind == "program":
        return {"program:" + name}
    if kind == "copybook":
        return {"copybook:" + name}
    if kind not in ("slice", "flow", "job", "proc"):
        raise RecordError("Status can be checked for a program, copybook, job, proc, flow or slice.")
    edges = load_map(ws)["edges"]
    if kind == "slice":
        data = read_json(ws.path("inventory", "slices.json"), {"slices": []})
        found = [s for s in data["slices"] if s["id"] == name]
        if not found:
            raise RecordError("There's no slice called %s. Run: python mma.py slices" % name)
        start = found[0]["entries"] + ["program:" + p for p in found[0]["programs"] + found[0]["shared_programs"]]
    elif kind == "flow":
        start = _flow_start(name, edges)
    else:
        start = ["%s:%s" % (kind, name)]
    return _follow(start, edges)


def status(ws, kind, name):
    name = name.upper() if kind != "slice" else name
    nodes = _nodes_for(ws, kind, name)
    members = _members(ws)
    paths = set()
    for node in nodes:
        entry = members.get(node.partition(":")[2])
        if entry:
            paths.add(entry["path"])
    if kind != "slice" and not paths and not _referenced(ws, nodes):
        raise RecordError("%s isn't in the inventory." % name)
    blocking = []
    for gap in load_gaps(ws):
        if gap["status"] not in ("open", "conflict"):
            continue
        if nodes & set(gap["blocks"]) or paths & {r["file"] for r in gap["references"] if not r.get("line")}:
            blocking.append({"id": gap["id"], "kind": gap["kind"], "name": gap["name"], "owner": gap["owner"], "status": gap["status"]})
    return {"kind": kind, "name": name, "state": "incomplete" if blocking else "complete", "blocking": blocking}


def _referenced(ws, nodes):
    edges = load_map(ws)["edges"]
    return any(e["to"] in nodes or e["from"] in nodes for e in edges)


def impact(ws, gid):
    gap = get_gap(ws, gid)
    if gap is None:
        raise RecordError("There's no item called %s. Run: python mma.py gaps" % gid)
    members = sorted(gap["blocks"])
    names = {m.partition(":")[2] for m in members}
    rules = [r["id"] for r in load_records(ws, "rule") if r.get("gap") == gid or names & {e["member"] for e in r["evidence"]}]
    analyses = []
    for path in sorted(glob.glob(ws.path("analysis", "*.json"))):
        saved = read_json(path)
        if gid in saved["open_gaps"]:
            analyses.append("%s %s" % (saved["kind"], saved["name"]))
    return {"gap": gid, "members": members, "rules": rules, "analyses": analyses}


def _dependency_hashes(ws, kind, name):
    catalogue = [m for m in load_catalogue(ws) if m.get("selected", True)]
    by_name = {}
    for entry in catalogue:
        by_name[_member_node(entry)] = entry["sha"]
        if entry["kind"] in ("jcl_job", "jcl_proc"):
            by_name[("job:" if entry["kind"] == "jcl_job" else "proc:") + entry["name"]] = entry["sha"]
    edges = load_map(ws)["edges"]
    copies = [e for e in edges if e["type"] == "copies"]
    nodes = _follow(_nodes_for(ws, kind, name), copies)
    return {node: by_name.get(node) for node in sorted(nodes) if node.partition(":")[0] in ("program", "copybook", "job", "proc")}


def record_analysis(ws, kind, name, output=None):
    name = name.upper() if kind != "slice" else name
    saved = {
        "kind": kind, "name": name, "output": output, "dependencies": _dependency_hashes(ws, kind, name),
        "open_gaps": sorted(g["id"] for g in status(ws, kind, name)["blocking"]),
    }
    write_json(ws.path("analysis", "%s-%s.json" % (kind, name)), saved)
    return saved


def stale(ws):
    """Saved analyses that need redoing, and why. Everything else can be reused as is."""
    results = []
    open_now = {g["id"] for g in load_gaps(ws) if g["status"] in ("open", "conflict")}
    for path in sorted(glob.glob(ws.path("analysis", "*.json"))):
        saved = read_json(path)
        reasons = []
        current = _dependency_hashes(ws, saved["kind"], saved["name"])
        changed = sorted(n for n in set(current) | set(saved["dependencies"]) if current.get(n) != saved["dependencies"].get(n))
        if changed:
            reasons.append("source changed: " + ", ".join(changed))
        closed = sorted(g for g in saved["open_gaps"] if g not in open_now)
        if closed:
            reasons.append("missing information arrived: " + ", ".join(closed))
        if reasons:
            results.append({"kind": saved["kind"], "name": saved["name"], "output": saved.get("output"), "reasons": reasons})
    return results


def validate(ws):
    """Check every saved record against the current source."""
    issues = []
    members = _members(ws)
    rules = load_records(ws, "rule")
    known = {r["id"] for r in rules}
    by_status = {}
    for rule in rules:
        by_status[rule["status"]] = by_status.get(rule["status"], 0) + 1
        for citation in rule["evidence"]:
            entry = members.get(citation["member"])
            if entry is None:
                issues.append({"id": rule["id"], "problem": "%s is no longer in the source." % citation["member"]})
            elif entry["sha"] != citation["sha"]:
                issues.append({"id": rule["id"], "problem": "%s changed since this was cited. Recheck lines %d-%d." % (citation["member"], citation["start"], citation["end"])})
    requirements = load_records(ws, "requirement")
    tests = load_records(ws, "test")
    for record in requirements + tests:
        for rid in record["rules"]:
            if rid not in known:
                issues.append({"id": record["id"], "problem": "It cites %s, which no longer exists." % rid})
    try:
        ws.logger.event("validation", issues=len(issues), by_status=by_status, rules=len(rules), requirements=len(requirements), tests=len(tests))
    except LogFieldRejected:
        pass
    return issues

