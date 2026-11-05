"""Stage 3: propose slices of the system one person can work through, from entry points."""
from .config import ConfigError, read_json, write_json, write_text
from .depmap import load_map
from .gaps import RecordError
from .inventory import PROGRAM_KINDS, load_catalogue

CALL_TYPES = {"calls", "links", "transfers_to", "loads"}
STEP_TYPES = CALL_TYPES | {"runs_program", "runs_proc", "runs_utility", "starts", "returns_to", "starts_transaction"}


def _graph(edges):
    graph = {}
    for edge in edges:
        if edge["type"] in STEP_TYPES:
            graph.setdefault(edge["from"], set()).add(edge["to"])
    return graph


def _hubs(edges, threshold):
    callers = {}
    for edge in edges:
        if edge["type"] in CALL_TYPES and edge["to"].startswith("program:"):
            callers.setdefault(edge["to"], set()).add(edge["from"])
    return {node for node, who in callers.items() if len(who) >= threshold}


def _reach(start, graph, hubs):
    """Follow links from an entry point, stopping at shared programs other than the one it starts."""
    own = {t for t in graph.get(start, ()) if t in hubs}
    seen, pending, used_hubs = set(own), [start] + sorted(own), set()
    while pending:
        node = pending.pop()
        for target in graph.get(node, ()):
            if target in hubs and target not in own:
                used_hubs.add(target)
            elif target not in seen:
                seen.add(target)
                pending.append(target)
    return seen, used_hubs


def _describe(id_, entries, nodes, hubs_used, edges_from, names):
    programs = sorted(n.partition(":")[2] for n in nodes if n.startswith("program:"))
    entry_nodes = set(entries)
    tables, datasets, cics_files, mapsets = set(), set(), set(), set()
    for node in nodes | entry_nodes:
        for edge in edges_from.get(node, ()):
            kind, _, name = edge["to"].partition(":")
            if kind == "table":
                tables.add(name)
            elif kind == "dataset":
                datasets.add(name)
            elif kind == "cics_file":
                cics_files.add(name)
                for inner in edges_from.get(edge["to"], ()):
                    if inner["to"].startswith("dataset:"):
                        datasets.add(inner["to"].partition(":")[2])
            elif kind == "mapset":
                mapsets.add(name)
    return {
        "id": id_, "business_name": names.get(id_), "entries": sorted(entries), "programs": programs,
        "shared_programs": sorted(h.partition(":")[2] for h in hubs_used), "tables": sorted(tables),
        "datasets": sorted(datasets), "cics_files": sorted(cics_files), "mapsets": sorted(mapsets),
        "jobs": sorted(n.partition(":")[2] for n in nodes | entry_nodes if n.startswith("job:")),
        "transactions": sorted(n.partition(":")[2] for n in nodes | entry_nodes if n.startswith("transaction:")),
    }


def build_slices(ws):
    data = load_map(ws)
    edges = data["edges"]
    graph = _graph(edges)
    hubs = _hubs(edges, ws.config["hub_threshold"])
    edges_from = {}
    for edge in edges:
        edges_from.setdefault(edge["from"], []).append(edge)
    online = sorted(n for n in graph if n.startswith("transaction:"))
    batch = sorted(n for n in graph if n.startswith("job:"))
    entries = batch + online
    reach, hub_use = {}, {}
    for entry in entries:
        reach[entry], hub_use[entry] = _reach(entry, graph, hubs)
    parent = {e: e for e in entries}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    owner = {}
    for entry in entries:
        for node in reach[entry]:
            if node.startswith(("program:", "transaction:")):
                if node in owner:
                    parent[find(entry)] = find(owner[node])
                else:
                    owner[node] = entry
    clusters = {}
    for entry in entries:
        clusters.setdefault(find(entry), []).append(entry)
    previous = read_json(ws.path("inventory", "slices.json"), {"slices": []})
    names = {s["id"]: s.get("business_name") for s in previous["slices"]}
    slices = []
    limit = ws.config["max_slice_programs"]
    for members in clusters.values():
        nodes = set().union(*(reach[m] for m in members))
        count = sum(1 for n in nodes if n.startswith("program:"))
        groups = [[m] for m in members] if count > limit and len(members) > 1 else [members]
        for group in groups:
            group_nodes = set().union(*(reach[m] for m in group))
            hubs_used = set().union(*(hub_use[m] for m in group))
            id_ = "SLICE-" + sorted(m.partition(":")[2] for m in group)[0]
            slices.append(_describe(id_, group, group_nodes, hubs_used, edges_from, names))
    slices.sort(key=lambda s: s["id"])
    assigned = {p for s in slices for p in s["programs"]}
    hub_names = sorted(h.partition(":")[2] for h in hubs)
    present = {m["name"] for m in load_catalogue(ws) if m["kind"] in PROGRAM_KINDS and m.get("selected", True)}
    unassigned = sorted(present - assigned - set(hub_names))
    result = {"slices": slices, "shared_programs": hub_names, "unassigned": unassigned}
    write_json(ws.path("inventory", "slices.json"), result)
    _write_summary(ws, result)
    return result


def _write_summary(ws, result):
    lines = ["# Proposed slices", "", "| Slice | Business name | Entry points | Programs | Shared | Data stores |", "|-------|---------------|--------------|----------|--------|-------------|"]
    for item in result["slices"]:
        stores = len(item["tables"]) + len(item["datasets"]) + len(item["cics_files"])
        lines.append("| %s | %s | %d | %d | %d | %d |" % (item["id"], item["business_name"] or "(to be named)", len(item["entries"]), len(item["programs"]), len(item["shared_programs"]), stores))
    lines += ["", "Programs shared across many flows: %d" % len(result["shared_programs"]), "Programs with no known entry point: %d" % len(result["unassigned"])]
    write_text(ws.path("inventory", "slices.md"), "\n".join(lines) + "\n")


def load_slices(ws):
    data = read_json(ws.path("inventory", "slices.json"))
    if data is None:
        raise ConfigError("There are no slices yet. Run: python mma.py slices")
    return data


def get_slice(ws, slice_id):
    for item in load_slices(ws)["slices"]:
        if item["id"] == slice_id:
            return item
    raise RecordError("There's no slice called %s. Run: python mma.py slices" % slice_id)


def name_slice(ws, slice_id, business_name):
    data = load_slices(ws)
    get_slice(ws, slice_id)
    for item in data["slices"]:
        if item["id"] == slice_id:
            item["business_name"] = business_name
    write_json(ws.path("inventory", "slices.json"), data)
    _write_summary(ws, data)
