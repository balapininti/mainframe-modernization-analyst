"""Mermaid end-to-end flows drawn from the dependency map, so diagrams only show proven links."""
import re

from .config import read_json, write_text
from .depmap import load_map
from .gaps import RecordError, load_gaps

SHAPES = {
    "transaction": ('(["', '"])'), "job": ('[["', '"]]'), "proc": ('[["', '"]]'), "table": ('[("', '")]'),
    "dataset": ('[("', '")]'), "cics_file": ('[("', '")]'), "mapset": ('[/"', '"/]'), "control": ('["', '"]'), "program": ('["', '"]'),
}
TYPE_WORDS = {"cics_file": "CICS file", "table": "DB2 table", "dataset": "dataset", "mapset": "screen map", "control": "control card", "transaction": "transaction", "job": "JCL job", "proc": "JCL proc", "program": "program"}
DEFAULT_MAX_NODES = 60
SKIPPED_EDGES = {"copies"}


def _starts(ws, entry, edges):
    if entry.startswith("SLICE-"):
        data = read_json(ws.path("inventory", "slices.json"), {"slices": []})
        for item in data["slices"]:
            if item["id"] == entry:
                return item["entries"]
        raise RecordError("There's no slice called %s. Run: python mma.py slices" % entry)
    name = entry.upper()
    known = {e["from"] for e in edges} | {e["to"] for e in edges}
    for prefix in ("transaction", "job", "proc", "program"):
        if "%s:%s" % (prefix, name) in known:
            return ["%s:%s" % (prefix, name)]
    raise RecordError("%s isn't a known transaction, job or program. Try: python mma.py summary" % name)


def _collect(starts, by_source, max_nodes):
    order, seen = [], set()
    queue = list(starts)
    trimmed = False
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        if len(order) >= max_nodes:
            trimmed = True
            continue
        seen.add(node)
        order.append(node)
        for edge in by_source.get(node, ()):
            if edge["to"] not in seen:
                queue.append(edge["to"])
    return order, seen, trimmed


def _safe_label(text):
    return re.sub(r'["<>\[\]{}|]', " ", text)


def write_flow(ws, entry, max_nodes=DEFAULT_MAX_NODES):
    data = load_map(ws)
    edges = [e for e in data["edges"] if e["type"] not in SKIPPED_EDGES]
    by_source = {}
    for edge in edges:
        by_source.setdefault(edge["from"], []).append(edge)
    starts = _starts(ws, entry, edges)
    order, included, trimmed = _collect(starts, by_source, max_nodes)
    ids = {node: "n%d" % i for i, node in enumerate(order)}
    missing = set(data["missing"])
    lines = ["flowchart LR"]
    for node in order:
        kind, _, name = node.partition(":")
        left, right = SHAPES.get(kind, ('["', '"]'))
        note = "<br/>not found" if node in missing else ""
        lines.append('  %s%s%s<br/>%s%s%s' % (ids[node], left, _safe_label(name), TYPE_WORDS.get(kind, kind), note, right))
    drawn = []
    for node in order:
        for edge in by_source.get(node, ()):
            if edge["to"] in included:
                arrow = "-->" if edge["confidence"] == "confirmed" else "-.->"
                lines.append("  %s %s|%s| %s" % (ids[node], arrow, edge["type"], ids[edge["to"]]))
                drawn.append(edge)
    lines.append("  classDef missing stroke-dasharray: 5 5,stroke:#c0392b")
    absent = [ids[n] for n in order if n in missing]
    if absent:
        lines.append("  class %s missing" % ",".join(absent))
    blocking = [g for g in load_gaps(ws) if g["status"] in ("open", "conflict") and included & set(g["blocks"])]
    title = entry.upper() if not entry.startswith("SLICE-") else entry
    doc = ["# Flow: %s" % title, ""]
    if blocking:
        doc += ["**Incomplete.** This flow can't be treated as finished until these items are settled:", ""]
        doc += ["- %s: %s (%s)" % (g["id"], g["name"], g["what"]) for g in sorted(blocking, key=lambda g: g["id"])]
    else:
        doc.append("No open items block this flow. This covers static links only, so review it with someone who knows the system.")
    doc.append("")
    if trimmed:
        doc += ["**This diagram was trimmed** at %d nodes. Use a smaller slice or start from a program further down." % max_nodes, ""]
    doc += ["```mermaid"] + lines + ["```", "",
            "Dashed boxes weren't found in the source. Dotted arrows were inferred from values in the code, not stated directly.", "",
            "## Evidence", "", "| From | Relationship | To | Where | Confidence |", "|------|--------------|----|-------|------------|"]
    for edge in drawn:
        doc.append("| %s | %s | %s | `%s` line %s | %s |" % (edge["from"], edge["type"], edge["to"], edge["file"], edge["line"], edge["confidence"]))
    path = ws.path("flows", re.sub(r"[^A-Za-z0-9._-]", "_", title) + ".md")
    write_text(path, "\n".join(doc) + "\n")
    return path

