"""Stage 2: join parsed facts into one dependency map. Every edge carries its evidence."""
import glob
import re
import time

from .config import ConfigError, read_json, write_json, write_text
from .inventory import PROGRAM_KINDS, load_catalogue, load_duplicates, load_facts, read_member_text

SYSTEM_PROGRAM_NAMES = {
    "SORT", "DFSORT", "SYNCSORT", "IDCAMS", "IRXJCL", "IEWL", "IGYCRCTL", "CBLTDLI", "AIBTDLI", "AERTDLI", "DSNTIAR",
    "DSNTIAUL", "DSNUTILB", "DSNTEP2", "DSNTEP4", "DSNTIAD", "DSNHLI", "DSNREXX", "DSNALI", "DSNRLI", "DSNULI", "DFSRRC00",
    "MQOPEN", "MQCLOSE", "MQGET", "MQPUT", "MQPUT1", "MQCONN", "MQCONNX", "MQDISC", "MQINQ", "MQSET", "MQCMIT", "MQBACK",
    "FTP", "SDSF", "ICEMAN", "ICETOOL", "ICEGENER", "ICETRK", "SYNCTOOL",
}
SYSTEM_PROGRAM_PATTERN = re.compile(r"^(?:CEE|ILBO|IGZ|DFH|DFS|IEF|IEB|IEH|IKJEFT|EZA|BPX|CSQ)")
SYSTEM_COPYBOOKS = {"SQLCA", "SQLDA", "SQLCODES", "DFHEIBLK", "DFHCOMMAREA", "CMQV", "CMQODV", "CMQMDV", "CMQPMOV", "CMQGMOV", "CMQTML"}
SYSTEM_COPYBOOK_PATTERN = re.compile(r"^(?:DFH|CMQ)")
CONTROL_DD = re.compile(r"^(?:SYS\w*IN|CTL\w*|CNTL\w*|PARM\w*|CONTROL\w*|SYMNAMES|SORTCNTL|DFSPARM)$")
NON_DATA_DD = re.compile(r"^(?:STEPLIB|JOBLIB|DBRMLIB|SYS\w*|CEE\w*|DFSVSAMP|IMS|SORTCNTL|DFSPARM)$")
RUN_PROGRAM = re.compile(r"\bRUN\s+PROG(?:RAM)?\s*\(\s*([^)\s,]+)", re.I)
CICS_READ = {"READ", "READNEXT", "READPREV", "STARTBR", "RESETBR", "ENDBR"}
CICS_WRITE = {"WRITE"}
CICS_UPDATE = {"REWRITE", "DELETE"}
QUEUE_READ = {"READQ"}
QUEUE_WRITE = {"WRITEQ", "DELETEQ"}
TECH_KINDS = {"assembler": "assembler", "pli": "pli", "rexx": "rexx", "easytrieve": "easytrieve", "ims_def": "ims"}
NO_FACTS = ("unknown", "undecodable", "control_card", "assembler", "pli", "rexx", "easytrieve", "ims_def")
RANK = {"confirmed": 0, "inferred": 1, "answered": 2, "ambiguous": 3}


class _Builder:
    def __init__(self, ws, known_programs, known_copybooks, members):
        self.ws = ws
        self.edges = {}
        self.dynamic = []
        self.technologies = {}
        self.known_programs = known_programs
        self.known_copybooks = known_copybooks
        self.members = members
        self.extra_programs = set(ws.config["system_programs"])
        self.extra_copybooks = set(ws.config["system_copybooks"])
        self.system_references = {}

    def is_system_program(self, name):
        """A name in the source is the client's, even if it looks like a system name."""
        if name in self.known_programs:
            return False
        return name in SYSTEM_PROGRAM_NAMES or name in self.extra_programs or bool(SYSTEM_PROGRAM_PATTERN.match(name))

    def is_system_copybook(self, name):
        if name in self.known_copybooks:
            return False
        return name in SYSTEM_COPYBOOKS or name in self.extra_copybooks or bool(SYSTEM_COPYBOOK_PATTERN.match(name))

    def is_system(self, node):
        kind, _, name = node.partition(":")
        return (kind == "program" and self.is_system_program(name)) or (kind == "copybook" and self.is_system_copybook(name))

    def edge(self, source, edge_type, target, path, line, confidence="confirmed"):
        if self.is_system(target):
            self.system_references[target] = self.system_references.get(target, 0) + 1
            return
        key = (source, edge_type, target)
        existing = self.edges.get(key)
        if existing is None:
            self.edges[key] = {"from": source, "type": edge_type, "to": target, "file": path, "line": line, "confidence": confidence, "count": 1}
        else:
            existing["count"] += 1
            if RANK[confidence] > RANK[existing["confidence"]]:
                existing["confidence"] = confidence

    def note_technology(self, tech, path):
        self.technologies.setdefault(tech, set()).add(path)

    def add_dynamic(self, source, variable, path, line, what):
        self.dynamic.append({"from": source, "variable": variable, "file": path, "line": line, "what": what})


def _settle(candidates, unresolved, constants):
    """Add values from copied copybooks. Return ([(target, confidence)], items still unknown)."""
    found, remaining = set(candidates), []
    for name in unresolved:
        if name in constants:
            found.update(constants[name])
        else:
            remaining.append(name)
    return [(c, "inferred") for c in sorted(found)], remaining


def _candidates(statement, key, constants):
    """Return ([(target, confidence)], variable if any part of the value is unknown) for a CICS option."""
    options = statement["options"]
    if key not in options:
        return [], None
    if key in statement["resolved"]:
        targets, remaining = _settle(statement["resolved"][key], statement["unresolved"].get(key, []), constants)
        return targets, options[key] if remaining or not targets else None
    return [(options[key], "confirmed")], None


def _links(builder, node, path, facts, constants):
    """Calls, transfers and data access found in one source file, attributed to the program that runs them."""
    add = builder.edge

    def dynamic(variable, line, what):
        builder.add_dynamic(node, variable, path, line, what)

    for tech in facts.get("technologies", []):
        if tech not in ("cics", "db2"):
            builder.note_technology(tech, path)
    for call in facts["calls"]:
        if not call["dynamic"]:
            add(node, "calls", "program:" + call["target"], path, call["line"])
            continue
        targets, remaining = _settle(call["candidates"], call["unresolved"], constants)
        for target, confidence in targets:
            add(node, "calls", "program:" + target, path, call["line"], confidence)
        if remaining or not targets:
            dynamic(call["variable"], call["line"], "called program")
    for statement in facts["cics"]:
        _cics_links(builder, node, path, statement, constants, dynamic)
    for statement in facts["sql"]:
        line = statement["line"]
        for table in statement["reads"]:
            add(node, "reads", "table:" + table, path, line)
        for table in statement["writes"]:
            add(node, "writes", "table:" + table, path, line)
        if statement["procedure"]:
            add(node, "calls", "program:" + statement["procedure"], path, line, "inferred")
        if statement["dynamic"]:
            dynamic("DYNAMIC-SQL", line, "SQL built at runtime")


def _cics_links(builder, node, path, statement, constants, dynamic):
    add = builder.edge
    verb, line = statement["verb"], statement["line"]
    relation = {"LINK": "links", "XCTL": "transfers_to", "LOAD": "loads", "HANDLE": "handles_abend"}.get(verb)
    if relation and "PROGRAM" in statement["options"]:
        targets, variable = _candidates(statement, "PROGRAM", constants)
        for target, confidence in targets:
            add(node, relation, "program:" + target, path, line, confidence)
        if variable:
            dynamic(variable, line, "program in %s" % verb)
    if verb in ("RETURN", "START"):
        targets, variable = _candidates(statement, "TRANSID", constants)
        for target, confidence in targets:
            add(node, "returns_to" if verb == "RETURN" else "starts_transaction", "transaction:" + target, path, line, confidence)
        if variable:
            dynamic(variable, line, "transaction")
    if verb in ("SEND", "RECEIVE") and ("MAP" in statement["options"] or "MAPSET" in statement["options"]):
        key = "MAPSET" if "MAPSET" in statement["options"] else "MAP"
        targets, variable = _candidates(statement, key, constants)
        for target, confidence in targets:
            add(node, "sends_map" if verb == "SEND" else "receives_map", "mapset:" + target, path, line, confidence)
        if variable:
            dynamic(variable, line, "screen map")
    access = "reads" if verb in CICS_READ else "writes" if verb in CICS_WRITE else "updates" if verb in CICS_UPDATE else None
    if access:
        key = "FILE" if "FILE" in statement["options"] else "DATASET"
        targets, variable = _candidates(statement, key, constants)
        for target, confidence in targets:
            add(node, access, "cics_file:" + target, path, line, confidence)
        if variable:
            dynamic(variable, line, "CICS file")
    if verb in QUEUE_READ or verb in QUEUE_WRITE:
        key = "QUEUE" if "QUEUE" in statement["options"] else "QNAME"
        targets, variable = _candidates(statement, key, constants)
        for target, confidence in targets:
            add(node, "reads" if verb in QUEUE_READ else "writes", "queue:" + target, path, line, confidence)
        if variable:
            dynamic(variable, line, "queue")


def _copied(name, copybook_facts, seen=None):
    """Copybooks a program pulls in, directly or through other copybooks."""
    seen = set() if seen is None else seen
    for copy in copybook_facts.get(name, (None, {}))[1].get("copies", []):
        if copy["name"] not in seen:
            seen.add(copy["name"])
            _copied(copy["name"], copybook_facts, seen)
    return seen


def _cobol(builder, entry, facts, copybook_facts):
    node = ("copybook:" if entry["kind"] == "copybook" else "program:") + entry["name"]
    path = entry["path"]
    for copy in facts["copies"]:
        builder.edge(node, "copies", "copybook:" + copy["name"], path, copy["line"])
    if entry["kind"] == "copybook":
        return
    included = set()
    for copy in facts["copies"]:
        included.add(copy["name"])
        _copied(copy["name"], copybook_facts, included)
    constants = {}
    for name in sorted(included):
        constants.update(copybook_facts.get(name, (None, {}))[1].get("constants", {}))
    _links(builder, node, path, facts, constants)
    for name in sorted(included):
        copy_entry, copy_data = copybook_facts.get(name, (None, None))
        if copy_data:
            _links(builder, node, copy_entry["path"], copy_data, constants)
            for tech in copy_data.get("technologies", []):
                if tech not in ("cics", "db2"):
                    builder.note_technology(tech, path)


def _is_data_dd(dd):
    return bool(dd["dsn"]) and not dd["dsn"].startswith("&&") and not NON_DATA_DD.match(dd["name"] or "") and not dd["member"]


def _base_dsn(dd):
    return re.sub(r"\([+-]?\d+\)$", "", dd["dsn"])


def _dd_relation(dd):
    disposition = (dd["disp"] or "").strip("()").split(",")[0].upper()
    return {"SHR": "reads", "OLD": "reads", "NEW": "writes", "MOD": "writes"}.get(disposition, "uses")


def _dd_confidence(dd, default="confirmed"):
    return "inferred" if dd["symbolic"] else default


def _control_programs(builder, member):
    """RUN PROGRAM inside a control card member names the real batch program behind IKJEFT01."""
    entry = builder.members.get(member)
    if entry is None:
        return []
    try:
        lines = read_member_text(builder.ws, entry).split("\n")
    except OSError:
        return []
    found = []
    for number, line in enumerate(lines, 1):
        for match in RUN_PROGRAM.finditer(line):
            found.append({"name": match.group(1).upper(), "line": number, "file": entry["path"]})
    return found


def _step(builder, owner, path, step, program_facts, instream, vsam, depth=0):
    if step["program"] and builder.is_system_program(step["program"]) and not step["run_programs"]:
        job_name = owner.partition(":")[2]
        utility = "utility:%s.%s.%s" % (job_name, step["name"] or "STEP", step["program"])
        builder.edge(owner, "runs_utility", utility, path, step["line"])
        for dd in step["dds"]:
            if _is_data_dd(dd):
                builder.edge(utility, _dd_relation(dd), "dataset:" + _base_dsn(dd), path, dd["line"], "inferred")
    programs = [{"name": p["name"], "line": p["line"], "file": path} for p in step["run_programs"]]
    for dd in step["dds"]:
        if dd["member"] and CONTROL_DD.match(dd["name"] or ""):
            if "&" in dd["member"]:
                builder.add_dynamic(owner, "&" + dd["member"].lstrip("&"), path, dd["line"], "control card member")
            else:
                builder.edge(owner, "reads_control", "control:" + dd["member"], path, dd["line"], _dd_confidence(dd))
                programs += _control_programs(builder, dd["member"])
        elif dd["dsn"] and not dd["member"] and CONTROL_DD.match(dd["name"] or "") and not dd["dsn"].startswith("&&") and dd["dsn"] != "NULLFILE":
            builder.edge(owner, "reads_control", "control:" + _base_dsn(dd), path, dd["line"], _dd_confidence(dd))
        if dd["override_step"] and _is_data_dd(dd):
            builder.edge(owner, "overrides_to", "dataset:" + _base_dsn(dd), path, dd["line"], "inferred")
    if step["program"]:
        programs.append({"name": step["program"], "line": step["line"], "file": path})
    for item in programs:
        program = item["name"]
        if "&" in program or "*" in program:
            builder.add_dynamic(owner, program, path, item["line"], "program in a JCL step")
            continue
        builder.edge(owner, "runs_program", "program:" + program, item["file"], item["line"])
        if program not in program_facts and not builder.is_system_program(program):
            for dd in step["dds"]:
                if _is_data_dd(dd):
                    builder.edge("program:" + program, "uses", "dataset:" + _base_dsn(dd), path, dd["line"], "inferred")
        for known in program_facts.get(program, {}).get("files", []):
            for dd in step["dds"]:
                if dd["name"] == known["ddname"] and dd["dsn"] and not dd["dsn"].startswith("&&"):
                    relation = {"read": "reads", "write": "writes", "update": "updates"}.get(known["access"], "uses")
                    builder.edge("program:" + program, relation, "dataset:" + _base_dsn(dd), path, dd["line"], _dd_confidence(dd))
                    if known["organization"] in ("INDEXED", "RELATIVE"):
                        if "&" in dd["dsn"]:
                            builder.add_dynamic(owner, dd["dsn"], path, dd["line"], "dataset name set by a JCL symbol")
                        else:
                            vsam.append((dd["dsn"], path, dd["line"], "program:" + program))
    if step["proc"]:
        if "&" in step["proc"]:
            builder.add_dynamic(owner, step["proc"], path, step["line"], "PROC in a JCL step")
        elif step["proc"] in instream and depth < 5:
            for inner in instream[step["proc"]]:
                _step(builder, owner, path, inner, program_facts, instream, vsam, depth + 1)
        else:
            builder.edge(owner, "runs_proc", "proc:" + step["proc"], path, step["line"])


def _jcl(builder, entry, facts, program_facts, vsam):
    path = entry["path"]
    base = ("job:" if facts["type"] == "job" else "proc:") + (facts["name"] or entry["name"])
    for include in facts.get("includes", []):
        builder.edge(base, "includes", "control:" + include["member"], path, include["line"])
    for step in facts["steps"]:
        owner = "job:" + step["job"] if step.get("job") else base
        _step(builder, owner, path, step, program_facts, facts.get("instream_procs", {}), vsam)


def _answered_targets(ws, builder):
    """Runtime names a person has told us go on the map, labeled as coming from an answer."""
    for path in glob.glob(ws.path("gaps", "items", "GAP-*.json")):
        gap = read_json(path)
        if gap.get("kind") == "dynamic_reference" and gap.get("status") == "answered" and gap.get("targets"):
            relation = "calls" if gap.get("detail") == "called program" else "transfers_to"
            for reference in gap["references"]:
                for target in gap["targets"]:
                    builder.edge(reference["from"], relation, "program:" + target, reference["file"], reference["line"], "answered")


def _apply_aliases(builder, aliases):
    """Link a PROGRAM-ID or ENTRY name back to the member that holds it."""
    merged = {}

    def real(node):
        kind, _, name = node.partition(":")
        return "program:" + aliases[name] if kind == "program" and name in aliases else node

    for edge in builder.edges.values():
        edge["from"], edge["to"] = real(edge["from"]), real(edge["to"])
        key = (edge["from"], edge["type"], edge["to"])
        if key in merged:
            merged[key]["count"] += edge["count"]
            if RANK[edge["confidence"]] > RANK[merged[key]["confidence"]]:
                merged[key]["confidence"] = edge["confidence"]
        else:
            merged[key] = edge
    builder.edges = merged
    builder.dynamic = [dict(d, **{"from": real(d["from"])}) for d in builder.dynamic]


def build_map(ws):
    started = time.time()
    catalogue = load_catalogue(ws)
    selected = [m for m in catalogue if m.get("selected", True)]
    usable = [m for m in selected if not m.get("parse_error")]
    facts_by_path = {m["path"]: load_facts(ws, m) for m in usable if m["kind"] not in NO_FACTS}
    aliases, known_programs, known_copybooks, members = {}, set(), set(), {}
    for entry in selected:
        members.setdefault(entry["name"], entry)
        if entry["kind"] in PROGRAM_KINDS:
            known_programs.add(entry["name"])
        if entry["kind"] in ("copybook", "unknown"):
            known_copybooks.add(entry["name"])
    for entry in selected:
        if entry["kind"] == "cobol_program":
            for name in [entry.get("program_id")] + entry.get("other_names", []):
                if name and name not in known_programs and name != entry["name"]:
                    aliases.setdefault(name, entry["name"])
    known_programs.update(aliases)
    builder = _Builder(ws, known_programs, known_copybooks, members)
    program_facts, copybook_facts = {}, {}
    for entry in usable:
        if entry["kind"] == "cobol_program":
            facts = facts_by_path[entry["path"]]
            program_facts[entry["name"]] = facts
            for name, member in aliases.items():
                if member == entry["name"]:
                    program_facts[name] = facts
        elif entry["kind"] == "copybook":
            copybook_facts[entry["name"]] = (entry, facts_by_path[entry["path"]])
    present = {"program": set(known_programs), "copybook": set(known_copybooks), "proc": set(), "job": set(), "mapset": set(), "control": set(),
               "table": set(), "dataset": set(), "cics_file": set(), "transaction": set()}
    vsam_refs = []
    has_scheduler = False
    for entry in selected:
        kind, name, path = entry["kind"], entry["name"], entry["path"]
        present["control"].add(name)
        if kind in TECH_KINDS:
            builder.note_technology(TECH_KINDS[kind], path)
        if kind == "scheduler":
            has_scheduler = True
        if path not in facts_by_path:
            continue
        facts = facts_by_path[path]
        if kind == "cobol_program":
            _cobol(builder, entry, facts, copybook_facts)
        elif kind == "copybook":
            _cobol(builder, entry, facts, copybook_facts)
            present["table"].update(facts.get("dclgen_tables", []))
        elif kind in ("jcl_job", "jcl_proc"):
            present["job"].update(facts.get("jobs", []))
            if facts["type"] != "job":
                present["proc"].add(facts["name"] or name)
                present["proc"].add(name)
            _jcl(builder, entry, facts, program_facts, vsam_refs)
            present["dataset"].update(facts["defined_datasets"])
        elif kind == "bms":
            present["mapset"].add(facts.get("mapset") or name)
            present["mapset"].add(name)
        elif kind == "ddl":
            present["table"].update(facts["tables"])
            present["table"].update(facts["views"])
        elif kind == "idcams":
            present["dataset"].update(facts["datasets"])
        elif kind == "csd":
            for txn in facts["transactions"]:
                present["transaction"].add(txn["id"])
                if txn["program"]:
                    builder.edge("transaction:" + txn["id"], "starts", "program:" + txn["program"], path, txn["line"])
            for cics_file in facts["files"]:
                present["cics_file"].add(cics_file["name"])
                if cics_file["dsn"]:
                    builder.edge("cics_file:" + cics_file["name"], "defined_as", "dataset:" + cics_file["dsn"], path, cics_file["line"])
                    vsam_refs.append((cics_file["dsn"], path, cics_file["line"], "cics_file:" + cics_file["name"]))
    _answered_targets(ws, builder)
    _apply_aliases(builder, aliases)
    ambiguous_nodes = {d["group"] + ":" + d["name"] for d in load_duplicates(ws)}
    for edge in builder.edges.values():
        if edge["to"] in ambiguous_nodes or edge["from"] in ambiguous_nodes:
            edge["confidence"] = "ambiguous"
    missing = set()
    for edge in builder.edges.values():
        for node in (edge["from"], edge["to"]):
            node_type, _, name = node.partition(":")
            if node_type in ("program", "copybook", "proc", "mapset", "control") and name not in present[node_type]:
                missing.add(node)
    edges = sorted(builder.edges.values(), key=lambda e: (e["from"], e["type"], e["to"]))
    write_json(ws.path("inventory", "dependencies.json"), {
        "edges": edges,
        "missing": sorted(missing),
        "present": {k: sorted(v) for k, v in present.items() if k in ("table", "dataset", "cics_file", "transaction")},
        "dynamic": sorted(builder.dynamic, key=lambda d: (d["from"], d["variable"], d["line"])),
        "technologies": {k: sorted(v) for k, v in sorted(builder.technologies.items())},
        "vsam_references": sorted(set(vsam_refs)),
        "aliases": aliases,
        "has_scheduler": has_scheduler,
        "job_count": sum(1 for m in selected if m["kind"] == "jcl_job"),
    })
    write_text(ws.path("inventory", "dependencies-summary.md"), _summary(edges, missing))
    lines = ["# Names treated as system-supplied", "", "These aren't in the source and match system naming, so they're left off the map. If one is really yours, remove any doubt by adding its source.", "", "| Name | References |", "|------|------------|"]
    lines += ["| %s | %d |" % (n.partition(":")[2], c) for n, c in sorted(builder.system_references.items())]
    write_text(ws.path("inventory", "system-references.md"), "\n".join(lines) + "\n")
    ws.logger.event("script_run", command="map", duration_ms=int((time.time() - started) * 1000), result="ok", files_processed=len(selected))
    ws.logger.event("coverage", edges=len(edges))
    return {"edges": len(edges), "missing": len(missing), "dynamic": len(builder.dynamic)}


def _summary(edges, missing):
    counts = {}
    for edge in edges:
        counts[edge["type"]] = counts.get(edge["type"], 0) + 1
    lines = ["# Dependency map", "", "| Relationship | Count |", "|--------------|-------|"]
    lines += ["| %s | %d |" % (k, counts[k]) for k in sorted(counts)]
    lines += ["", "Referenced but not found: %d" % len(missing)]
    return "\n".join(lines) + "\n"


def load_map(ws):
    data = read_json(ws.path("inventory", "dependencies.json"))
    if data is None:
        raise ConfigError("There's no dependency map yet. Run: python mma.py map")
    return data
