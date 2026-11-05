"""Parse a COBOL record layout into fields with byte offsets and lengths.

Where a layout can't be proven from this file alone, later fields are marked `offset_unverified`
and `parse_layout` explains why, so a wrong offset is never presented as fact.
"""
import re as _plain_re

from .sourcefile import cobol_regex as re, logical_source

_ENTRY = re.compile(r"^\s*(\d{1,2})\s+([A-Z0-9:#@$][A-Z0-9:#@$_-]*)?\s*(.*)$", re.S)
_CLAUSE_WORDS = {"PIC", "PICTURE", "VALUE", "VALUES", "REDEFINES", "OCCURS", "USAGE", "COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-4", "COMP-5",
                 "BINARY", "PACKED-DECIMAL", "DISPLAY", "SIGN", "SYNC", "SYNCHRONIZED", "JUST", "JUSTIFIED", "BLANK"}
_USAGE = (r"\b(COMPUTATIONAL-[1-5]|COMP-[1-5]|COMPUTATIONAL|COMP|BINARY|PACKED-DECIMAL|PROCEDURE-POINTER|FUNCTION-POINTER|POINTER|INDEX"
          r"|NATIONAL|DISPLAY-1)\b")
_EDIT_CHARS = set("Z*B0/,.+-$")


def _expand_pic(pic):
    return _plain_re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), pic)


def _pic_details(pic):
    expanded = _expand_pic(pic)
    signed = expanded.startswith("S") or expanded[:1] in ("+", "-")
    integer, _, fraction = expanded.partition("V")
    if "V" not in expanded and "." in expanded:
        integer, _, fraction = expanded.partition(".")
    digit_chars = "9Z*"
    digits = sum(1 for c in expanded if c in digit_chars)
    scale = sum(1 for c in fraction if c in digit_chars or c == "P")
    text_kind = any(c in expanded for c in "XANG")
    double_byte = any(c in expanded for c in "NG")
    display_length = sum(1 for c in expanded if c not in "VSP")
    edited = not text_kind and (any(c in _EDIT_CHARS for c in expanded[1:] if c != "0") or expanded[:1] in _EDIT_CHARS or expanded.endswith(("CR", "DB")))
    return {"digits": digits, "scale": scale, "signed": signed, "display_length": display_length, "text": text_kind, "double_byte": double_byte, "edited": edited}


def _storage_length(usage, digits, display_length, double_byte):
    if usage == "COMP-3":
        return digits // 2 + 1
    if usage in ("COMP", "COMP-4", "COMP-5", "BINARY"):
        return 2 if digits <= 4 else 4 if digits <= 9 else 8
    if usage in ("COMP-1", "POINTER", "INDEX", "FUNCTION-POINTER"):
        return 4
    if usage in ("COMP-2", "PROCEDURE-POINTER"):
        return 8
    if usage in ("NATIONAL", "DISPLAY-1") or double_byte:
        return display_length * 2
    return display_length


def _normal_usage(text):
    found = re.search(_USAGE, text)
    if not found:
        return None
    return found.group(1).replace("COMPUTATIONAL", "COMP").replace("PACKED-DECIMAL", "COMP-3")


def _statement_entry(statement, offset, src, warnings):
    copied = re.match(r"^\s*COPY\s+([A-Z0-9#@$_-]+)(.*)$", statement, re.S)
    if copied:
        replacing = "REPLACING" in copied.group(2)
        warnings.append("Contains COPY %s%s, which isn't expanded here. Offsets after it are unverified." % (copied.group(1), " REPLACING" if replacing else ""))
        if replacing:
            warnings.append("COPY ... REPLACING can change field names, and this layout doesn't apply it.")
        return {"copy": copied.group(1)}
    parsed = _ENTRY.match(statement)
    if not parsed or not (parsed.group(2) or parsed.group(3).strip()):
        return None
    level = int(parsed.group(1))
    if level == 66:
        return None
    name = parsed.group(2) or "FILLER"
    rest = parsed.group(3)
    if name in _CLAUSE_WORDS:
        rest, name = name + " " + rest, "FILLER"
    leading = len(statement) - len(statement.lstrip())
    line = src.line_at(offset + leading)
    if level == 88:
        value = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(.*)$", rest, re.S)
        raw = ""
        if value:
            start = offset + parsed.start(3) + value.start(1)
            raw = src.text[start:start + len(value.group(1))].strip()
        return {"level": 88, "name": name, "value": raw.strip("'\""), "line": line}
    pic = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest)
    occurs = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?", rest)
    depending = re.search(r"\bDEPENDING\s+(?:ON\s+)?([A-Z0-9#@$_-]+)", rest)
    redefines = re.search(r"\bREDEFINES\s+([A-Z0-9:#@$_-]+)", rest)
    separate = re.search(r"\bSEPARATE\b", rest)
    return {
        "level": level, "name": name, "line": line,
        "pic": pic.group(1).rstrip(".,;") if pic else None,
        "usage": _normal_usage(rest),
        "occurs": (int(occurs.group(2) or occurs.group(1)) if occurs else None),
        "depending_on": depending.group(1) if depending else None,
        "redefines": redefines.group(1) if redefines else None,
        "sign_separate": bool(separate),
        "sign_leading": bool(re.search(r"\bLEADING\b", rest)),
        "sync": bool(re.search(r"\bSYNC(?:HRONIZED)?\b", rest)),
        "has_value": bool(re.search(r"\bVALUES?\b", rest)),
        "conditions": [],
    }


def _parse_entries(text, warnings):
    src = logical_source(text)
    entries = []
    position = 0
    for m in re.finditer(r"\.(?:\s|$)", src.masked):
        entry = _statement_entry(src.masked[position:m.start()], position, src, warnings)
        if entry:
            entries.append(entry)
        position = m.end()
    tail = src.masked[position:]
    if tail.strip():
        entry = _statement_entry(tail.rstrip(), position, src, warnings)
        if entry:
            entries.append(entry)
            warnings.append("The last entry has no closing period, so the source may be cut off.")
    return entries


def _details(entry, inherited):
    usage = entry["usage"] or inherited["usage"]
    separate = entry["sign_separate"] or inherited["sign_separate"]
    sync = entry["sync"] or inherited["sync"]
    leading = entry["sign_leading"] or inherited["sign_leading"]
    entry["usage"], entry["sign_separate"], entry["sync"], entry["sign_leading"] = usage, separate, sync, leading
    entry["digits"], entry["scale"], entry["signed"], entry["alphanumeric"], entry["edited"] = None, None, False, False, False
    if entry["pic"]:
        pic = _pic_details(entry["pic"])
        entry["signed"], entry["alphanumeric"], entry["edited"] = pic["signed"], pic["text"], pic["edited"]
        if not pic["text"]:
            entry["digits"], entry["scale"] = pic["digits"], pic["scale"]
        length = _storage_length(usage, pic["digits"], pic["display_length"], pic["double_byte"])
        if separate and pic["signed"] and pic["display_length"] and usage not in ("COMP-3", "COMP", "COMP-4", "COMP-5", "BINARY"):
            length += 1
        entry["element_length"] = length
    elif usage and not entry["children"]:
        entry["element_length"] = _storage_length(usage, 0, 0, False)
    else:
        entry["element_length"] = 0
    down = {"usage": usage, "sign_separate": separate, "sync": sync, "sign_leading": leading}
    for child in entry["children"]:
        _details(child, down)


def _align(cursor, field):
    """SYNC moves binary fields to a boundary of their own size, relative to the start of the record."""
    if field["sync"] and not field["children"] and field["element_length"] in (2, 4, 8):
        width = field["element_length"]
        return (cursor + width - 1) // width * width
    return cursor


def _layout(node, offset):
    node["offset"] = offset
    if not node["children"]:
        size = node["element_length"]
    else:
        cursor, furthest, variable = offset, offset, False
        by_name = {}
        for child in node["children"]:
            start = by_name[child["redefines"]]["offset"] if child["redefines"] in by_name else _align(cursor, child)
            child_size = _layout(child, start)
            by_name[child["name"]] = child
            variable = variable or child["variable_length"]
            if not child["redefines"]:
                cursor = start + child_size
            furthest = max(furthest, start + child_size)
        size = furthest - offset
        node["variable_length"] = node["variable_length"] or variable
    node["length"] = size
    if node["occurs"]:
        size = size * node["occurs"]
    if node["depending_on"]:
        node["variable_length"] = True
    return size


_ROOT = {"usage": None, "sign_separate": False, "sync": False, "sign_leading": False}


def parse_layout(text):
    warnings = []
    entries = _parse_entries(text, warnings)
    fields, roots, stack, previous = [], [], [], None
    unverified, depending_level = False, None
    for entry in entries:
        if "copy" in entry:
            unverified = True
            continue
        if entry["level"] == 88:
            if previous is not None:
                previous["conditions"].append({"name": entry["name"], "value": entry["value"]})
            continue
        if entry["level"] in (1, 77):
            unverified, depending_level = False, None
        elif depending_level is not None and entry["level"] <= depending_level:
            unverified = True
            depending_level = None
        entry["children"], entry["variable_length"] = [], False
        entry["offset_unverified"] = unverified
        if entry["depending_on"]:
            depending_level = entry["level"]
            warnings.append("%s has a variable size (it depends on %s). Offsets after it assume the maximum, so they aren't fixed." % (entry["name"], entry["depending_on"]))
        if entry["level"] == 77:
            stack = []
        while stack and stack[-1]["level"] >= entry["level"]:
            stack.pop()
        entry["parent"] = stack[-1]["name"] if stack else None
        (stack[-1]["children"] if stack else roots).append(entry)
        stack.append(entry)
        fields.append(entry)
        previous = entry
    for root in roots:
        _details(root, _ROOT)
        _layout(root, 0)
    for field in fields:
        field["is_group"] = bool(field["children"])
        field.pop("children")
        field.pop("element_length")
    return {"fields": fields, "warnings": warnings}


def parse_copybook(text):
    return parse_layout(text)["fields"]
