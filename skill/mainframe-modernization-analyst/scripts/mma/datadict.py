"""Data dictionary: each copybook field with its layout, suggested Java type and traps."""
import re

from .config import write_json, write_text
from .copybook import parse_layout
from .facts import find_member
from .gaps import RecordError
from .inventory import read_member_text

DATE_NAME = re.compile(r"(?:^|-)(?:DATE|DT|YY|YYMMDD|YYYYMMDD|CCYYMMDD|MMDDYY)(?:-|$)")


def _class_name(name):
    return "".join(part.capitalize() for part in re.split(r"[-:]+", name) if part)


def java_type(field, name=""):
    usage, digits, scale = field.get("usage"), field.get("digits"), field.get("scale")
    if field.get("is_group"):
        base = _class_name(name) or "Group"
    elif usage == "COMP-1":
        base = "Float"
    elif usage == "COMP-2":
        base = "Double"
    elif usage in ("POINTER", "INDEX", "PROCEDURE-POINTER", "FUNCTION-POINTER"):
        base = "(no Java equivalent: review)"
    elif not field.get("pic"):
        base = "(unknown: review)"
    elif field.get("edited"):
        base = "String (edited)"
    elif field.get("alphanumeric") or digits is None:
        base = "String"
    elif usage == "COMP-3" or scale:
        base = "BigDecimal (scale %d)" % (scale or 0)
    elif usage == "COMP-5" and not field.get("signed"):
        base = "Integer" if digits <= 4 else "Long" if digits <= 9 else "BigInteger"
    elif digits <= 9:
        base = "Integer"
    elif digits <= 18:
        base = "Long"
    else:
        base = "BigInteger"
    return "List<%s>" % base if field.get("occurs") else base


def _sign_trap(field):
    if not field.get("signed") or field.get("usage") or not field.get("digits") or field.get("edited"):
        return None
    if field.get("sign_separate"):
        return "The sign is its own byte (%s the digits)." % ("before" if field.get("sign_leading") else "after")
    where = "first" if field.get("sign_leading") else "last"
    return "Signed display: the sign is overpunched in the %s digit, so plain parsing fails." % where


def _traps(field):
    traps = []
    usage, name = field.get("usage"), field["name"]
    if usage == "COMP-3":
        traps.append("Packed decimal on disk: convert the bytes properly, and don't use double.")
    if usage in ("COMP", "COMP-4", "BINARY"):
        traps.append("Binary: the compiler's TRUNC setting can change the largest value it holds.")
    if usage in ("COMP-1", "COMP-2"):
        traps.append("Mainframe floating point isn't the same format as Java's: compare values carefully.")
    sign = _sign_trap(field)
    if sign:
        traps.append(sign)
    if field.get("edited"):
        traps.append("Formatted for display, such as a date with slashes or currency. It isn't a number until parsed.")
    if field.get("redefines"):
        traps.append("REDEFINES %s: the same bytes have another meaning. Decide which view applies when." % field["redefines"])
    if field.get("depending_on"):
        traps.append("Size depends on %s, so the record length varies." % field["depending_on"])
    if field.get("sync"):
        traps.append("SYNC: the compiler adds slack bytes for alignment, which matter when reading raw records.")
    if field.get("offset_unverified"):
        traps.append("Offset unverified: see the warnings at the top.")
    if field.get("conditions"):
        traps.append("Named values: keep them as an enum or boolean methods.")
    if DATE_NAME.search(name):
        traps.append("Looks like a date stored as text or a number. Confirm its format and century rule before using LocalDate.")
    if name == "FILLER":
        if field.get("has_value"):
            traps.append("Holds a constant. This pattern often builds a lookup table read through a REDEFINES, so check before dropping it.")
        else:
            traps.append("Unused bytes, but they still count if the file format must stay the same.")
    if field.get("alphanumeric"):
        traps.append("Mainframe text is space-padded. Decide whether to trim, and keep comparison rules the same.")
    return traps


def write_datadict(ws, copybook):
    entry = find_member(ws, copybook)
    if entry["kind"] != "copybook":
        raise RecordError("%s is a %s, not a copybook." % (entry["name"], entry["kind"]))
    fields = []
    layout = parse_layout(read_member_text(ws, entry))
    for field in layout["fields"]:
        item = {key: field.get(key) for key in (
            "level", "name", "pic", "usage", "offset", "length", "occurs", "depending_on", "redefines", "conditions", "line", "parent", "is_group",
            "variable_length", "offset_unverified")}
        item["java_type"] = java_type(field, field["name"])
        item["traps"] = _traps(field)
        item["meaning"] = None
        fields.append(item)
    data = {"copybook": entry["name"], "file": entry["path"], "fields": fields, "warnings": layout["warnings"]}
    write_json(ws.path("data", entry["name"] + ".json"), data)
    lines = [
        "# Data dictionary: %s" % entry["name"], "", "Layout extracted by script from `%s`. Java types are suggestions." % entry["path"], "",
    ] + (["**Check before relying on these offsets:**", ""] + ["- %s" % w for w in layout["warnings"]] + [""] if layout["warnings"] else []) + [
        "| Field | Level | Picture | Usage | Offset | Length | Suggested Java | Traps | Line |",
        "|-------|-------|---------|-------|--------|--------|----------------|-------|------|",
    ]
    for f in fields:
        lines.append("| %s%s | %02d | %s | %s | %s | %s | %s | %s | %d |" % (
            "&nbsp;" * (2 * min(f["level"], 10) // 5), f["name"], f["level"], f["pic"] or "", f["usage"] or "", ("%s (unverified)" % f["offset"] if f["offset_unverified"] else f["offset"]), f["length"], f["java_type"], "<br/>".join(f["traps"]), f["line"]))
    write_text(ws.path("data", entry["name"] + ".md"), "\n".join(lines) + "\n")
    return data
