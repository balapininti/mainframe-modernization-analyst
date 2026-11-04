"""Parse system definitions: CICS CSD, BMS maps, DB2 DDL, IDCAMS and scheduler files."""
import re

from .sourcefile import ascii_upper, split_lines


def _option(body, name):
    m = re.search(r"\b" + name + r"\s*\(\s*([^)\s]+)\s*\)", body)
    return m.group(1) if m else None


def _parse_csd(upper):
    result = {"transactions": [], "programs": [], "files": [], "mapsets": []}
    lines = [("" if l.lstrip().startswith("*") else l) for l in split_lines(upper)]
    text = "\n".join(lines)
    matches = list(re.finditer(r"\bDEFINE\s+([A-Z0-9]+)\s*\(\s*([^)\s]+)\s*\)", text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end]
        kind, name = m.group(1), m.group(2)
        line = text.count("\n", 0, m.start()) + 1
        group = _option(body, "GROUP")
        if kind == "TRANSACTION":
            result["transactions"].append({"id": name, "program": _option(body, "PROGRAM"), "group": group, "line": line})
        elif kind == "PROGRAM":
            result["programs"].append({"name": name, "group": group, "line": line})
        elif kind == "FILE":
            result["files"].append({"name": name, "dsn": _option(body, "DSNAME"), "group": group, "line": line})
        elif kind == "MAPSET":
            result["mapsets"].append({"name": name, "group": group, "line": line})
    return result


def _parse_bms(upper):
    mapset, maps = None, []
    for line in split_lines(upper):
        m = re.match(r"^([A-Z0-9#@$]+)\s+DFHMSD\b", line)
        if m and mapset is None:
            mapset = m.group(1)
        m = re.match(r"^([A-Z0-9#@$]+)\s+DFHMDI\b", line)
        if m:
            maps.append(m.group(1))
    return {"mapset": mapset, "maps": maps}


def _parse_ddl(upper):
    tables, views = [], []
    for m in re.finditer(r"\bCREATE\s+TABLE\s+([A-Z0-9_#@$.\"]+)", upper):
        tables.append(m.group(1).split(".")[-1].strip('"'))
    for m in re.finditer(r"\bCREATE\s+VIEW\s+([A-Z0-9_#@$.\"]+)", upper):
        views.append(m.group(1).split(".")[-1].strip('"'))
    return {"tables": tables, "views": views}


def _parse_idcams(upper):
    datasets = []
    for m in re.finditer(r"\bDEFINE\s+(?:CLUSTER|AIX|ALTERNATEINDEX)\b[^)]*?\bNAME\s*\(\s*([^)\s]+)", upper):
        if m.group(1) not in datasets:
            datasets.append(m.group(1))
    return {"datasets": datasets}


def _parse_scheduler(upper):
    jobs = set(re.findall(r"\bJOBNAME\s*=\s*\"?([A-Z0-9#@$]+)", upper))
    jobs.update(re.findall(r"\bJOB\s*[:=]\s*\"?([A-Z0-9#@$]+)", upper))
    return {"jobs": sorted(jobs)}


def parse_definitions(text, kind):
    upper = ascii_upper(text)
    parser = {
        "csd": _parse_csd, "bms": _parse_bms, "ddl": _parse_ddl, "idcams": _parse_idcams, "scheduler": _parse_scheduler,
    }.get(kind)
    return parser(upper) if parser else {}
