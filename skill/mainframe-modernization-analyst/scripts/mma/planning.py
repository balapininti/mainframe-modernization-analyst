"""Complexity, migration order, dead-code candidates and Spring Boot mapping suggestions."""
from .config import write_text
from .depmap import load_map
from .inventory import load_catalogue, load_facts
from .slices import CALL_TYPES, get_slice, load_slices

ENTRY_TYPES = CALL_TYPES | {"runs_program", "starts"}


def _score(facts):
    distinct = {h["type"] for h in facts["hazards"]}
    dynamic = sum(1 for c in facts["calls"] if c["dynamic"])
    value = (
        facts["metrics"]["lines"] / 100 + facts["metrics"]["decisions"] + 3 * len(facts["gotos"]) + 2 * len(distinct)
        + len(facts["calls"]) + 2 * dynamic + len(facts["sql"]) + len(facts["cics"])
    )
    return round(value, 1)


def _band(score):
    return "high" if score >= 100 else "medium" if score >= 30 else "low"


def _owners(slices, edges):
    """A program belongs to the slice that starts it directly; otherwise the smallest slice using it."""
    owner = {}
    entries = {}
    for item in slices:
        for entry in item["entries"]:
            entries[entry] = item["id"]
    for edge in edges:
        if edge["type"] in ("runs_program", "starts") and edge["from"] in entries and edge["to"].startswith("program:"):
            owner.setdefault(edge["to"].partition(":")[2], entries[edge["from"]])
    for item in sorted(slices, key=lambda s: (len(s["programs"]), s["id"])):
        for program in item["programs"]:
            owner.setdefault(program, item["id"])
    return owner


def _migration_order(slices, edges, scores):
    owner = _owners(slices, edges)
    depends = {s["id"]: set() for s in slices}
    shared = set()
    for item in slices:
        for program in item["programs"]:
            if owner[program] != item["id"]:
                depends[item["id"]].add(owner[program])
        shared.update(item["shared_programs"])
    weight = {s["id"]: sum(scores.get(p, 0) for p in s["programs"]) for s in slices}
    remaining = {k: set(v) for k, v in depends.items()}
    order, cycles = [], []
    while remaining:
        ready = sorted((k for k, v in remaining.items() if not v), key=lambda k: (weight[k], k))
        if ready:
            chosen, reason = ready[0], "No unfinished dependencies"
        else:
            chosen = sorted(remaining, key=lambda k: (weight[k], k))[0]
            reason = "These slices depend on each other, so this needs a person's call"
            cycles.append(chosen)
        waits = sorted(depends[chosen])
        order.append({"id": chosen, "score": round(weight[chosen], 1), "depends_on": waits, "reason": reason})
        del remaining[chosen]
        for pending in remaining.values():
            pending.discard(chosen)
    return order, cycles, sorted(shared)


def _unnamed_paragraphs(facts):
    paragraphs = facts["paragraphs"]
    if any(p["is_section"] for p in paragraphs):
        return []
    names = [p["name"] for p in paragraphs]
    named = set()
    for perform in facts["performs"]:
        if perform["target"] in names:
            if perform["thru"] in names:
                named.update(names[names.index(perform["target"]):names.index(perform["thru"]) + 1])
            else:
                named.add(perform["target"])
    named.update(g["target"] for g in facts["gotos"])
    results = []
    for i, name in enumerate(names):
        if i > 0 and name not in named and names[i - 1] in named:
            results.append(name)
    return results


def _write_dead_code(ws, members, facts_by_name, edges, dynamic_count):
    targets = {e["to"] for e in edges}
    lines = [
        "# Dead-code candidates", "",
        "These are candidates only. Static analysis can't prove code is unused: a name may be built at runtime, or used by something outside this source. Confirm with the mainframe team before retiring anything.", "",
    ]
    if dynamic_count:
        lines += ["%d program references are decided at runtime and still unresolved, so any item here could still be in use." % dynamic_count, ""]
    programs = sorted(m["name"] for m in members if m["kind"] == "cobol_program" and "program:" + m["name"] not in targets and "program:" + m.get("program_id", m["name"]) not in targets)
    copybooks = sorted(m["name"] for m in members if m["kind"] == "copybook" and "copybook:" + m["name"] not in targets)
    lines += ["## Programs nothing calls or runs", ""] + ["- %s" % p for p in programs] + [""]
    lines += ["## Copybooks nothing uses", ""] + ["- %s" % c for c in copybooks] + [""]
    lines += ["## Paragraphs nothing names", ""]
    for name in sorted(facts_by_name):
        for paragraph in _unnamed_paragraphs(facts_by_name[name]):
            lines.append("- %s: %s" % (name, paragraph))
    write_text(ws.path("mapping", "dead-code-candidates.md"), "\n".join(lines) + "\n")


def write_plan(ws):
    data = load_map(ws)
    slices = load_slices(ws)["slices"]
    members = [m for m in load_catalogue(ws) if m.get("selected", True)]
    facts_by_name = {m["name"]: load_facts(ws, m) for m in members if m["kind"] == "cobol_program"}
    scores = {name: _score(facts) for name, facts in facts_by_name.items()}
    order, cycles, shared = _migration_order(slices, data["edges"], scores)
    lines = ["# Complexity", "", "A rough guide for planning. Higher means more to untangle.", "", "| Program | Score | Band |", "|---------|-------|------|"]
    lines += ["| %s | %s | %s |" % (n, scores[n], _band(scores[n])) for n in sorted(scores, key=lambda n: (-scores[n], n))]
    write_text(ws.path("mapping", "complexity.md"), "\n".join(lines) + "\n")
    lines = ["# Suggested migration order", "", "A suggestion for planning. Dependencies come first, then lower complexity.", ""]
    if shared:
        lines += ["Shared programs to plan first, because many flows use them: %s" % ", ".join(shared), ""]
    if cycles:
        lines += ["**Some slices depend on each other:** %s. A person needs to decide where to break the loop." % ", ".join(cycles), ""]
    lines += ["| # | Slice | Score | Depends on | Why here |", "|---|-------|-------|------------|----------|"]
    for number, item in enumerate(order, 1):
        lines.append("| %d | %s | %s | %s | %s |" % (number, item["id"], item["score"], ", ".join(item["depends_on"]) or "nothing", item["reason"]))
    write_text(ws.path("mapping", "migration-order.md"), "\n".join(lines) + "\n")
    _write_dead_code(ws, members, facts_by_name, data["edges"], len(data["dynamic"]))
    return {"order": order, "cycles": cycles, "complexity": scores, "shared": shared}


def write_mapping(ws, slice_id):
    item = get_slice(ws, slice_id)
    members = {m["name"]: m for m in load_catalogue(ws) if m.get("selected", True)}
    hazards = set()
    for program in item["programs"]:
        entry = members.get(program)
        if entry and entry["kind"] == "cobol_program":
            hazards.update(h["type"] for h in load_facts(ws, entry)["hazards"])
    rows = []
    for txn in item["transactions"]:
        rows.append(("CICS transaction %s" % txn, "REST controller and service", "One transaction can span several screens. Model each step explicitly."))
    for mapset in item["mapsets"]:
        rows.append(("BMS screen %s" % mapset, "UI view with request and response DTOs", "Screen field lengths often act as validation rules."))
    for job in item["jobs"]:
        rows.append(("JCL job %s" % job, "Spring Batch job", "Keep step order, return-code branching, and restart behaviour."))
    for program in item["programs"]:
        rows.append(("Program %s" % program, "Service class", "Plan one service per business capability, not one per program, if they differ."))
    for program in item["shared_programs"]:
        rows.append(("Shared program %s" % program, "Shared library or internal service", "Many flows use it, so build and test it first."))
    for table in item["tables"]:
        rows.append(("DB2 table %s" % table, "JPA entity and repository", "Match decimal scale, nullable columns and isolation level."))
    for name in item["cics_files"] + item["datasets"]:
        rows.append(("File %s" % name, "Relational table, or Spring Batch reader/writer for flat files", "Key order and EBCDIC sort order can change results."))
    if "commarea" in hazards:
        rows.append(("COMMAREA state", "Request DTO, or session or database state", "Decide where state lives between steps, and what happens if a user abandons them."))
    if "comp3" in hazards:
        rows.append(("Packed decimals (COMP-3)", "BigDecimal", "Never double. Match rounding and truncation."))
    if hazards & {"syncpoint", "commit"}:
        rows.append(("Syncpoints and commits", "@Transactional boundaries", "Commit at the same business points."))
    if hazards & {"checkpoint"}:
        rows.append(("Checkpoint and restart", "Spring Batch chunking and restart", "Prove recovery after a failure mid-run."))
    lines = [
        "# Spring Boot mapping: %s" % slice_id, "",
        "These are suggestions for an architect to review, not decisions.", "",
        "| Legacy | Suggested equivalent | Watch out for |", "|--------|----------------------|---------------|",
    ]
    lines += ["| %s | %s | %s |" % row for row in rows]
    path = ws.path("mapping", slice_id + ".md")
    write_text(path, "\n".join(lines) + "\n")
    return path

