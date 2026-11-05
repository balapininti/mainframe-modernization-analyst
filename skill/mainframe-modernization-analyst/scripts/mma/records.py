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
_CITATION = re.compile(r"^(?:(program|copybook|job|proc)/)?([A-Za-z0-9#@$._-]+):([A-Za-z0-9#@$_-]*):(\d+)(?:-(\d+))?$")
KIND_PREFIXES = {"program": {"cobol_program", "assembler", "pli", "rexx", "easytrieve"}, "copybook": {"copybook"}, "job": {"jcl_job"}, "proc": {"jcl_proc"}}
KIND_WORDS = {"copybook": "copybook", "jcl_job": "job", "jcl_proc": "proc"}


def _members(ws):
    members = {}
    for entry in load_catalogue(ws):
        if entry.get("selected", True):
            members.setdefault(entry["name"], entry)
    for entry in load_catalogue(ws):
        if entry.get("selected", True):
            for name in [entry.get("program_id")] + entry.get("other_names", []):
                if name:
                    members.setdefault(name, entry)
    return members


def _candidates_for(ws, member, kind):
    wanted = KIND_PREFIXES.get(kind)
    found = []
    for entry in load_catalogue(ws):
        if entry.get("selected", True) and member in (entry["name"], entry.get("program_id")) and (not wanted or entry["kind"] in wanted) and entry not in found:
            found.append(entry)
    return found


def _citation_fits(ws, entry, paragraph, start, end):
    if not 1 <= start <= end <= entry["line_count"]:
        return False
    if paragraph:
        found = [p for p in load_facts(ws, entry).get("paragraphs", []) if p["name"] == paragraph]
        return bool(found) and found[0]["start_line"] <= start and end <= found[0]["end_line"]
    return True


def parse_citation(ws, text):
    match = _CITATION.match(text.strip())
    if not match:
        raise RecordError("Write each citation as PROGRAM:PARAGRAPH:START-END (leave PARAGRAPH empty for copybooks). Got: %s" % text)
    kind, member = match.group(1), match.group(2).upper()
    paragraph, start, end = match.group(3).upper() or None, int(match.group(4)), int(match.group(5) or match.group(4))
    candidates = _candidates_for(ws, member, kind)
    if not candidates:
        raise RecordError("The citation names %s, which isn't in the inventory." % member)
    fitting = [e for e in candidates if _citation_fits(ws, e, paragraph, start, end)]
    if len(fitting) > 1:
        options = ", ".join("%s/%s" % (KIND_WORDS.get(e["kind"], "program"), member) for e in fitting)
        raise RecordError("%s is more than one member. Say which one: %s" % (member, options))
    if not fitting:
        entry = candidates[0]
        if not 1 <= start <= end <= entry["line_count"]:
            raise RecordError("The citation gives lines %d-%d, but %s has %d lines." % (start, end, member, entry["line_count"]))
        paragraphs = {p["name"]: p for p in load_facts(ws, entry).get("paragraphs", [])}
        if paragraph not in paragraphs:
            raise RecordError("The citation names paragraph %s, which isn't in %s." % (paragraph, member))
        found = paragraphs[paragraph]
        raise RecordError("The citation gives lines %d-%d, but %s is at lines %d-%d." % (start, end, paragraph, found["start_line"], found["end_line"]))
    entry = fitting[0]
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
    by_path = {m["path"]: m for m in load_catalogue(ws)}
    return [by_path[c["file"]] for c in rule["evidence"] if c["file"] in by_path]


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
    return {
        "text": text, "status": status, "evidence": [parse_citation(ws, c) for c in evidence],
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
    edges = load_map(ws)["edges"]
    copies = [e for e in edges if e["type"] == "copies"]
    if kind == "program":
        return _follow(["program:" + name], copies)
    if kind == "copybook":
        return _follow(["copybook:" + name], copies)
    if kind not in ("slice", "flow", "job", "proc"):
        raise RecordError("Status can be checked for a program, copybook, job, proc, flow or slice.")
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


MISSING_KINDS = {"program": "missing_program", "copybook": "missing_copybook", "proc": "missing_proc", "mapset": "missing_bms_map", "control": "missing_control_card"}


def blocking_items(ws, nodes):
    """What stops this set of nodes being complete. Every completeness answer in the skill comes from here."""
    members = _members(ws)
    names = {}
    paths = set()
    for node in nodes:
        kind, _, name = node.partition(":")
        names.setdefault(MISSING_KINDS.get(kind), set()).add(name)
        entry = members.get(name)
        if entry and kind in ("program", "copybook", "job", "proc"):
            paths.add(entry["path"])
    has_job = any(n.startswith("job:") for n in nodes)
    blocking = []
    for gap in load_gaps(ws):
        if gap["status"] not in ("open", "conflict"):
            continue
        by_reference = paths & {r["file"] for r in gap["references"] if not r.get("line") or gap.get("source") == "manual"}
        absent = gap["name"] in names.get(gap["kind"], ())
        if set(nodes) & set(gap["blocks"]) or by_reference or absent or (has_job and gap["kind"] == "missing_schedule"):
            blocking.append({"id": gap["id"], "kind": gap["kind"], "name": gap["name"], "what": gap["what"], "owner": gap["owner"], "status": gap["status"]})
    gap_ids = {b["id"] for b in blocking}
    for rule in load_records(ws, "rule"):
        if rule["status"] in ("conflict", "ask_expert") and rule.get("gap") not in gap_ids and paths & {c["file"] for c in rule["evidence"]}:
            blocking.append({"id": rule["id"], "kind": "rule_" + rule["status"], "name": rule["text"], "what": "A rule still needing an answer", "owner": "sme", "status": rule["status"]})
    return blocking


def status(ws, kind, name):
    name = name.upper() if kind != "slice" else name
    if kind in ("program", "flow"):
        entry = _members(ws).get(name)
        if entry and entry["kind"] in KIND_PREFIXES["program"]:
            name = entry["name"]
    nodes = _nodes_for(ws, kind, name)
    if kind != "slice" and not _referenced(ws, nodes) and name not in _members(ws):
        raise RecordError("%s isn't in the inventory." % name)
    blocking = blocking_items(ws, nodes)
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
    for entry in catalogue:
        if entry["kind"] in ("jcl_job", "jcl_proc"):
            facts = load_facts(ws, entry)
            prefix = "job:" if entry["kind"] == "jcl_job" else "proc:"
            for job in facts.get("jobs", []) + [facts.get("name")]:
                if job:
                    by_name[prefix + job] = entry["sha"]
    edges = load_map(ws)["edges"]
    copies = [e for e in edges if e["type"] == "copies"]
    nodes = _follow(_nodes_for(ws, kind, name), copies)
    return {node: by_name.get(node) for node in sorted(nodes) if node.partition(":")[0] in ("program", "copybook", "job", "proc")}


def record_analysis(ws, kind, name, output=None):
    current = status(ws, kind, name)
    name = current["name"]
    gap_states = {g["id"]: g["status"] for g in current["blocking"] if g["id"].startswith("GAP-")}
    saved = {
        "kind": kind, "name": name, "output": output, "dependencies": _dependency_hashes(ws, kind, name),
        "open_gaps": sorted(gap_states), "gap_states": gap_states,
    }
    write_json(ws.path("analysis", "%s-%s.json" % (kind, name)), saved)
    return saved


def stale(ws):
    """Saved analyses that need redoing, and why. Everything else can be reused as is."""
    results = []
    for path in sorted(glob.glob(ws.path("analysis", "*.json"))):
        saved = read_json(path)
        reasons = []
        try:
            current = _dependency_hashes(ws, saved["kind"], saved["name"])
            now = {g["id"]: g["status"] for g in status(ws, saved["kind"], saved["name"])["blocking"] if g["id"].startswith("GAP-")}
        except RecordError:
            results.append({"kind": saved["kind"], "name": saved["name"], "output": saved.get("output"), "reasons": ["it no longer exists in the map"]})
            continue
        changed = sorted(n for n in set(current) | set(saved["dependencies"]) if current.get(n) != saved["dependencies"].get(n))
        if changed:
            reasons.append("source changed: " + ", ".join(changed))
        before = saved.get("gap_states", {g: "open" for g in saved["open_gaps"]})
        closed = sorted(g for g in before if g not in now)
        if closed:
            reasons.append("missing information arrived: " + ", ".join(closed))
        added = sorted(g for g in now if g not in before)
        if added:
            reasons.append("new open items: " + ", ".join(added))
        moved = sorted(g for g in now if g in before and before[g] != now[g])
        if moved:
            reasons.append("items changed status: " + ", ".join(moved))
        if reasons:
            results.append({"kind": saved["kind"], "name": saved["name"], "output": saved.get("output"), "reasons": reasons})
    return results


def requirement_confidence(requirement, rules_by_id):
    """A requirement is only as firm as its weakest rule, as those rules stand now."""
    statuses = [rules_by_id[r]["status"] for r in requirement["rules"] if r in rules_by_id]
    return min(statuses, key=STATUS_ORDER.index) if statuses else "conflict"


def validate(ws):
    """Check every saved record against the current source."""
    issues = []
    by_path = {m["path"]: m for m in load_catalogue(ws)}
    rules = load_records(ws, "rule")
    known = {r["id"] for r in rules}
    by_status = {}
    for rule in rules:
        by_status[rule["status"]] = by_status.get(rule["status"], 0) + 1
        if rule["status"] == "conflict":
            issues.append({"id": rule["id"], "problem": "This is a conflict between the code and an answer. A person needs to settle it."})
        for citation in rule["evidence"]:
            entry = by_path.get(citation["file"])
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

