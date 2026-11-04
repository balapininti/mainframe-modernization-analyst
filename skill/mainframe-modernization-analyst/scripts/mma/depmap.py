"""Stage 2: join parsed facts into one dependency map. Every edge carries its evidence."""
import re
import time

from .config import ConfigError, read_json, write_json, write_text
from .inventory import PROGRAM_KINDS, load_catalogue, load_duplicates, load_facts

SYSTEM_PROGRAM_NAMES = {
    "SORT", "DFSORT", "SYNCSORT", "IDCAMS", "IRXJCL", "IEWL", "IGYCRCTL", "CBLTDLI", "AIBTDLI", "AERTDLI", "DSNTIAR",
    "DSNTIAUL", "DSNUTILB", "DSNTEP2", "DSNTEP4", "DSNTIAD", "DSNHLI", "DSNREXX", "DSNALI", "DSNRLI", "DSNULI", "DFSRRC00",
    "MQOPEN", "MQCLOSE", "MQGET", "MQPUT", "MQPUT1", "MQCONN", "MQCONNX", "MQDISC", "MQINQ", "MQSET", "MQCMIT", "MQBACK",
    "FTP", "SDSF",
}
SYSTEM_PROGRAM_PATTERN = re.compile(r"^(?:CEE|ILBO|IGZ|DFH|DFS|IEF|IEB|IEH|IKJEFT|ICE|EZA|BPX|CSQ)")
SYSTEM_COPYBOOKS = {"SQLCA", "SQLDA", "SQLCODES", "DFHEIBLK", "DFHCOMMAREA", "CMQV", "CMQODV", "CMQMDV", "CMQPMOV", "CMQGMOV", "CMQTML"}
SYSTEM_COPYBOOK_PATTERN = re.compile(r"^(?:DFH|CMQ)")
CONTROL_DD = re.compile(r"^(?:SYS\w*IN|CTL\w*|CNTL\w*|PARM\w*|CONTROL\w*|SYMNAMES)$")
CICS_READ = {"READ", "READNEXT", "READPREV", "STARTBR", "RESETBR", "ENDBR"}
CICS_WRITE = {"WRITE"}
CICS_UPDATE = {"REWRITE", "DELETE"}
TECH_KINDS = {"assembler": "assembler", "pli": "pli", "rexx": "rexx", "easytrieve": "easytrieve", "ims_def": "ims"}


class _Builder:
    def __init__(self, ws, catalogue):
        self.ws = ws
        self.edges = {}
        self.dynamic = []
        self.technologies = {}
        extra_programs = set(ws.config["system_programs"])
        extra_copybooks = set(ws.config["system_copybooks"])
        self.is_system_program = lambda n: n in SYSTEM_PROGRAM_NAMES or n in extra_programs or bool(SYSTEM_PROGRAM_PATTERN.match(n))
        self.is_system_copybook = lambda n: n in SYSTEM_COPYBOOKS or n in extra_copybooks or bool(SYSTEM_COPYBOOK_PATTERN.match(n))

    def edge(self, source, edge_type, target, path, line, confidence="confirmed"):
        key = (source, edge_type, target)
        existing = self.edges.get(key)
        rank = {"confirmed": 0, "inferred": 1, "ambiguous": 2}
        if existing is None:
            self.edges[key] = {"from": source, "type": edge_type, "to": target, "file": path, "line": line, "confidence": confidence, "count": 1}
        else:
            existing["count"] += 1
            if rank[confidence] > rank[existing["confidence"]]:
                existing["confidence"] = confidence

    def note_technology(self, tech, path):
        self.technologies.setdefault(tech, set()).add(path)


def _candidates(statement, key):
    """Return ([(target, confidence)], variable) for a CICS option."""
    options = statement["options"]
    if key not in options:
        return [], None
    if key in statement["resolved"]:
        return [(c, "inferred") for c in statement["resolved"][key]], options[key]
    return [(options[key], "confirmed")], None


def _cobol(builder, entry, facts, node):
    path = entry["path"]
    add = builder.edge
    for tech in facts.get("technologies", []):
        if tech in ("ims", "mq"):
            builder.note_technology(tech, path)
    for copy in facts["copies"]:
        add(node, "copies", "copybook:" + copy["name"], path, copy["line"])
    if entry["kind"] == "copybook":
        return
    for call in facts["calls"]:
        if not call["dynamic"]:
            add(node, "calls", "program:" + call["target"], path, call["line"])
        elif call["candidates"]:
            for candidate in call["candidates"]:
                add(node, "calls", "program:" + candidate, path, call["line"], "inferred")
        else:
            builder.dynamic.append({"from": node, "variable": call["variable"], "file": path, "line": call["line"], "what": "called program"})
    for statement in facts["cics"]:
        verb, line = statement["verb"], statement["line"]
        relation = {"LINK": "links", "XCTL": "transfers_to", "LOAD": "loads"}.get(verb)
        if relation:
            targets, variable = _candidates(statement, "PROGRAM")
            for target, confidence in targets:
                add(node, relation, "program:" + target, path, line, confidence)
            if variable and not targets:
                builder.dynamic.append({"from": node, "variable": variable, "file": path, "line": line, "what": "program in %s" % verb})
        if verb in ("RETURN", "START"):
            targets, variable = _candidates(statement, "TRANSID")
            for target, confidence in targets:
                add(node, "returns_to" if verb == "RETURN" else "starts_transaction", "transaction:" + target, path, line, confidence)
            if variable and not targets:
                builder.dynamic.append({"from": node, "variable": variable, "file": path, "line": line, "what": "transaction"})
        if verb in ("SEND", "RECEIVE"):
            mapset, _ = _candidates(statement, "MAPSET")
            if not mapset:
                mapset, _ = _candidates(statement, "MAP")
            for target, confidence in mapset:
                add(node, "sends_map" if verb == "SEND" else "receives_map", "mapset:" + target, path, line, confidence)
        access = "reads" if verb in CICS_READ else "writes" if verb in CICS_WRITE else "updates" if verb in CICS_UPDATE else None
        if access:
            key = "FILE" if "FILE" in statement["options"] else "DATASET"
            targets, variable = _candidates(statement, key)
            for target, confidence in targets:
                add(node, access, "cics_file:" + target, path, line, confidence)
            if variable and not targets:
                builder.dynamic.append({"from": node, "variable": variable, "file": path, "line": line, "what": "CICS file"})
    for statement in facts["sql"]:
        if statement["access"]:
            relation = "reads" if statement["access"] == "read" else "writes"
            for table in statement["tables"]:
                add(node, relation, "table:" + table, path, statement["line"])


def _jcl(builder, entry, facts, program_facts):
    path = entry["path"]
    owner = ("job:" if facts["type"] == "job" else "proc:") + (facts["name"] or entry["name"])
    controls = []
    for include in facts.get("includes", []):
        builder.edge(owner, "includes", "control:" + include["member"], path, include["line"])
    for step in facts["steps"]:
        programs = [p for p in (step["program"], step["run_program"]) if p]
        for program in programs:
            if "&" in program:
                builder.dynamic.append({"from": owner, "variable": program, "file": path, "line": step["line"], "what": "program in a JCL step"})
                continue
            builder.edge(owner, "runs_program", "program:" + program, path, step["line"])
            for known in program_facts.get(program, {}).get("files", []):
                for dd in step["dds"]:
                    if dd["name"] == known["ddname"] and dd["dsn"] and not dd["dsn"].startswith("&&"):
                        relation = {"read": "reads", "write": "writes", "update": "updates"}.get(known["access"], "uses")
                        builder.edge("program:" + program, relation, "dataset:" + re.sub(r"\([+-]?\d+\)$", "", dd["dsn"]), path, dd["line"])
                        if known["organization"] in ("INDEXED", "RELATIVE"):
                            controls.append((dd["dsn"], path, dd["line"], "program:" + program))
        if step["proc"]:
            builder.edge(owner, "runs_proc", "proc:" + step["proc"], path, step["line"])
        for dd in step["dds"]:
            if dd["member"] and CONTROL_DD.match(dd["name"] or ""):
                builder.edge(owner, "reads_control", "control:" + dd["member"], path, dd["line"])
    return controls


def build_map(ws):
    started = time.time()
    catalogue = load_catalogue(ws)
    selected = [m for m in catalogue if m.get("selected", True)]
    builder = _Builder(ws, catalogue)
    facts_by_path = {m["path"]: load_facts(ws, m) for m in selected if m["kind"] not in ("unknown", "undecodable", "control_card", "assembler", "pli", "rexx", "easytrieve", "ims_def")}
    program_facts = {}
    for entry in selected:
        if entry["kind"] == "cobol_program":
            facts = facts_by_path[entry["path"]]
            program_facts[entry["name"]] = facts
            if entry.get("program_id"):
                program_facts.setdefault(entry["program_id"], facts)
    present = {"program": set(), "copybook": set(), "proc": set(), "job": set(), "mapset": set(), "control": set(),
               "table": set(), "dataset": set(), "cics_file": set(), "transaction": set()}
    vsam_refs = []
    has_scheduler = False
    for entry in selected:
        kind, name, path = entry["kind"], entry["name"], entry["path"]
        facts = facts_by_path.get(path, {})
        present["control"].add(name)
        if kind in PROGRAM_KINDS:
            present["program"].add(name)
            if entry.get("program_id"):
                present["program"].add(entry["program_id"])
        if kind in ("copybook", "unknown"):
            present["copybook"].add(name)
        if kind in TECH_KINDS:
            builder.note_technology(TECH_KINDS[kind], path)
        if kind == "scheduler":
            has_scheduler = True
        if kind == "cobol_program":
            _cobol(builder, entry, facts, "program:" + name)
        elif kind == "copybook":
            _cobol(builder, entry, facts, "copybook:" + name)
            present["table"].update(facts.get("dclgen_tables", []))
        elif kind in ("jcl_job", "jcl_proc"):
            present["job" if facts["type"] == "job" else "proc"].add(facts["name"] or name)
            if facts["type"] != "job":
                present["proc"].add(name)
            vsam_refs += _jcl(builder, entry, facts, program_facts)
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
    ambiguous_nodes = set()
    for duplicate in load_duplicates(ws):
        ambiguous_nodes.add(duplicate["group"] + ":" + duplicate["name"])
    for edge in builder.edges.values():
        if edge["to"] in ambiguous_nodes or edge["from"] in ambiguous_nodes:
            edge["confidence"] = "ambiguous"
    missing = set()
    for edge in builder.edges.values():
        for node in (edge["from"], edge["to"]):
            node_type, _, name = node.partition(":")
            if node_type == "program" and name not in present["program"] and not builder.is_system_program(name):
                missing.add(node)
            elif node_type == "copybook" and name not in present["copybook"] and not builder.is_system_copybook(name):
                missing.add(node)
            elif node_type in ("proc", "mapset", "control") and name not in present[node_type]:
                missing.add(node)
    edges = [e for e in builder.edges.values() if not _is_system(builder, e["to"])]
    edges.sort(key=lambda e: (e["from"], e["type"], e["to"]))
    write_json(ws.path("inventory", "dependencies.json"), {
        "edges": edges,
        "missing": sorted(missing),
        "present": {k: sorted(v) for k, v in present.items() if k in ("table", "dataset", "cics_file", "transaction")},
        "dynamic": sorted(builder.dynamic, key=lambda d: (d["from"], d["variable"], d["line"])),
        "technologies": {k: sorted(v) for k, v in sorted(builder.technologies.items())},
        "vsam_references": sorted(set(vsam_refs)),
        "has_scheduler": has_scheduler,
        "job_count": sum(1 for m in selected if m["kind"] == "jcl_job"),
    })
    write_text(ws.path("inventory", "dependencies-summary.md"), _summary(edges, missing))
    ws.logger.event("script_run", command="map", duration_ms=int((time.time() - started) * 1000), result="ok", files_processed=len(selected))
    ws.logger.event("coverage", edges=len(edges))
    return {"edges": len(edges), "missing": len(missing), "dynamic": len(builder.dynamic)}


def _is_system(builder, node):
    node_type, _, name = node.partition(":")
    return (node_type == "program" and builder.is_system_program(name)) or (node_type == "copybook" and builder.is_system_copybook(name))


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
