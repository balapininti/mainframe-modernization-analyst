"""Parse a COBOL record layout into fields with byte offsets and lengths."""
from .sourcefile import cobol_regex as re, ascii_upper, logical_source

_ENTRY = re.compile(r"^\s*(\d{1,2})\s+([A-Z0-9:#@$][A-Z0-9:#@$_-]*)?\s*(.*)$", re.S)


def _expand_pic(pic):
    return re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), pic)


def _pic_details(pic):
    expanded = _expand_pic(pic)
    signed = expanded.startswith("S") or expanded[:1] in "+-"
    integer, _, fraction = expanded.partition("V")
    if "V" not in expanded and "." in expanded:
        integer, _, fraction = expanded.partition(".")
    digit_chars = "9Z*"
    digits = sum(1 for c in expanded if c in digit_chars)
    scale = sum(1 for c in fraction if c in digit_chars)
    display_length = sum(1 for c in expanded if c not in "VSP")
    alphanumeric = any(c in expanded for c in "XA")
    return digits, scale, signed, display_length, alphanumeric


def _storage_length(usage, digits, display_length):
    if usage == "COMP-3":
        return digits // 2 + 1
    if usage in ("COMP", "COMP-4", "COMP-5", "BINARY"):
        return 2 if digits <= 4 else 4 if digits <= 9 else 8
    if usage in ("COMP-1", "POINTER", "INDEX"):
        return 4
    if usage == "COMP-2":
        return 8
    return display_length


def _parse_entries(text):
    src = logical_source(text)
    entries = []
    position = 0
    for m in re.finditer(r"\.(?:\s|$)", src.masked):
        statement = src.masked[position:m.start()]
        offset = position
        position = m.end()
        parsed = _ENTRY.match(statement)
        if not parsed or not parsed.group(2) and not parsed.group(3):
            continue
        level = int(parsed.group(1))
        name = parsed.group(2) or "FILLER"
        rest = parsed.group(3)
        if name in ("PIC", "PICTURE", "VALUE", "REDEFINES", "OCCURS"):
            rest, name = name + " " + rest, "FILLER"
        leading = len(statement) - len(statement.lstrip())
        line = src.line_at(offset + leading)
        if level == 88:
            value = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(.*)$", rest, re.S)
            raw = ""
            if value:
                start = offset + parsed.start(3) + value.start(1)
                raw = src.text[start:start + len(value.group(1))].strip()
            entries.append({"level": 88, "name": name, "value": raw.strip("'\""), "line": line})
            continue
        pic = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest)
        usage = re.search(r"\b(COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL|POINTER|INDEX)\b", rest)
        usage_name = None
        if usage:
            usage_name = usage.group(1).replace("COMPUTATIONAL", "COMP").replace("PACKED-DECIMAL", "COMP-3")
        occurs = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?", rest)
        depending = re.search(r"\bDEPENDING\s+(?:ON\s+)?([A-Z0-9-]+)", rest)
        redefines = re.search(r"\bREDEFINES\s+([A-Z0-9:_-]+)", rest)
        entries.append({
            "level": level, "name": name, "line": line,
            "pic": pic.group(1).rstrip(".") if pic else None,
            "usage": usage_name,
            "occurs": (int(occurs.group(2) or occurs.group(1)) if occurs else None),
            "depending_on": depending.group(1) if depending else None,
            "redefines": redefines.group(1) if redefines else None,
            "conditions": [],
        })
    return entries


def _layout(node, offset):
    node["offset"] = offset
    if not node["children"]:
        size = node.get("element_length", 0)
    else:
        size, cursor, variable = 0, offset, False
        by_name = {}
        for child in node["children"]:
            start = by_name[child["redefines"]]["offset"] if child["redefines"] in by_name else cursor
            child_size = _layout(child, start)
            by_name[child["name"]] = child
            variable = variable or child["variable_length"]
            if not child["redefines"]:
                cursor = start + child_size
                size += child_size
        node["variable_length"] = node["variable_length"] or variable
    node["length"] = size
    if node["occurs"]:
        size = size * node["occurs"]
    if node["depending_on"]:
        node["variable_length"] = True
    return size


def parse_copybook(text):
    entries = _parse_entries(text)
    fields, roots, stack, previous = [], [], [], None
    for entry in entries:
        if entry["level"] == 88:
            if previous is not None:
                previous["conditions"].append({"name": entry["name"], "value": entry["value"]})
            continue
        entry["children"] = []
        entry["variable_length"] = False
        entry["digits"], entry["scale"], entry["signed"], entry["element_length"] = None, None, False, 0
        if entry["pic"]:
            digits, scale, signed, display_length, alphanumeric = _pic_details(entry["pic"])
            entry["digits"], entry["scale"], entry["signed"] = (None if alphanumeric else digits), (None if alphanumeric else scale), signed
            entry["alphanumeric"] = alphanumeric
            entry["element_length"] = _storage_length(entry["usage"], digits, display_length)
        else:
            entry["alphanumeric"] = False
            if entry["usage"]:
                entry["element_length"] = _storage_length(entry["usage"], 0, 0)
        while stack and stack[-1]["level"] >= entry["level"]:
            stack.pop()
        entry["parent"] = stack[-1]["name"] if stack else None
        (stack[-1]["children"] if stack else roots).append(entry)
        stack.append(entry)
        fields.append(entry)
        previous = entry
    for root in roots:
        _layout(root, 0)
    for field in fields:
        field["is_group"] = bool(field["children"])
        field.pop("children")
        field.pop("element_length")
    return fields
