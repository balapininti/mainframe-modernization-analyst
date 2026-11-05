"""Extract jobs, steps, datasets and control cards from JCL."""
import re

from .sourcefile import ascii_upper, split_lines

KNOWN_OPS = {
    "JOB", "EXEC", "DD", "PROC", "PEND", "IF", "ELSE", "ENDIF", "SET", "INCLUDE", "JCLLIB", "OUTPUT", "CNTL",
    "ENDCNTL", "COMMAND", "XMIT",
}
SORT_PROGRAMS = {"SORT", "ICEMAN", "SYNCSORT", "DFSORT", "ICETOOL", "SYNCTOOL"}
_STATEMENT = re.compile(r"^//(\S*)\s+(\S+)\s*(.*)$")


def _operand_text(text):
    """Operands end at the first blank outside quotes. Anything after is a comment."""
    quote = False
    for i, ch in enumerate(text):
        if ch == "'":
            quote = not quote
        elif ch == " " and not quote:
            return text[:i]
    return text


def _split_operands(text):
    parts, depth, quote, current = [], 0, False, ""
    for ch in text:
        if ch == "'":
            quote = not quote
        if not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(current)
                current = ""
                continue
        current += ch
    if current:
        parts.append(current)
    return parts


def _params(text):
    positional, keyed = [], {}
    for part in _split_operands(text):
        if "=" in part and not part.startswith("'"):
            key, value = part.split("=", 1)
            keyed[ascii_upper(key)] = value
        else:
            positional.append(part)
    return positional, keyed


def _statements(text):
    """Yield (name, op, operands, line, inline_lines, first_inline_line), joining continuations and inline data."""
    lines = split_lines(text)
    i, total = 0, len(lines)
    while i < total:
        raw = lines[i][:71].rstrip()
        number = i + 1
        i += 1
        if raw.startswith("//*") or not raw.startswith("//"):
            continue
        m = _STATEMENT.match(raw)
        if not m:
            continue
        name, op, rest = m.group(1), ascii_upper(m.group(2)), m.group(3)
        if op not in KNOWN_OPS:
            yield name, op, rest, number, None, None
            continue
        operands = _operand_text(rest)
        while operands.endswith(",") and i < total:
            next_line = lines[i][:71].rstrip()
            if next_line.startswith("//*"):
                i += 1
                continue
            if not next_line.startswith("//"):
                break
            operands += _operand_text(next_line[2:].strip())
            i += 1
        inline = None
        inline_start = i + 1
        if op == "DD" and re.match(r"^(\*|DATA)(,|$)", operands):
            inline = []
            while i < total:
                data = lines[i]
                if data.startswith("/*"):
                    i += 1
                    break
                if data.startswith("//"):
                    break
                inline.append(data[:71].rstrip())
                i += 1
        yield name, op, operands, number, inline, inline_start


def parse_jcl(text):
    result = {
        "name": None, "type": "proc", "steps": [], "hazards": [], "unrecognized": [], "includes": [],
        "defined_datasets": [], "line_count": len(split_lines(text)),
    }
    step, last_dd = None, None

    def hazard(kind, line):
        result["hazards"].append({"type": kind, "line": line})

    for name, op, operands, line, inline, inline_start in _statements(text):
        if op not in KNOWN_OPS:
            result["unrecognized"].append((op + " " + operands).strip())
        elif op == "JOB":
            result["name"], result["type"] = ascii_upper(name), "job"
        elif op == "PROC":
            if result["name"] is None:
                result["name"] = ascii_upper(name) or None
            step = None
        elif op == "EXEC":
            positional, keyed = _params(operands)
            step = {
                "name": ascii_upper(name), "line": line, "program": None, "proc": None, "run_program": None, "run_program_line": None,
                "parm": keyed.get("PARM"), "cond": keyed.get("COND"), "dds": [],
            }
            if "PGM" in keyed:
                step["program"] = ascii_upper(keyed["PGM"])
            elif "PROC" in keyed:
                step["proc"] = ascii_upper(keyed["PROC"])
            elif positional:
                step["proc"] = ascii_upper(positional[0])
            result["steps"].append(step)
            last_dd = None
            if step["cond"]:
                hazard("jcl_cond", line)
            if step["program"] in SORT_PROGRAMS:
                hazard("sort_step", line)
            elif step["program"] == "IDCAMS":
                hazard("idcams_step", line)
            elif step["program"] == "DFSRRC00":
                hazard("ims_step", line)
                parts = (step["parm"] or "").strip("'()").split(",")
                if len(parts) > 1:
                    step["run_program"] = ascii_upper(parts[1])
                    step["run_program_line"] = line
        elif op == "DD" and step is not None:
            positional, keyed = _params(operands)
            dd_name = ascii_upper(name) or last_dd
            last_dd = dd_name
            dsn = keyed.get("DSN") or keyed.get("DSNAME")
            member = None
            if dsn:
                dsn = ascii_upper(dsn)
                m = re.match(r"^(.*)\(([A-Z0-9#@$]+)\)$", dsn)
                if m and not m.group(2).isdigit():
                    dsn, member = m.group(1), m.group(2)
                if re.search(r"\([+-]?\d+\)$", dsn):
                    hazard("gdg", line)
            dd = {"name": dd_name, "dsn": dsn, "member": member, "disp": keyed.get("DISP"), "line": line, "inline": None}
            if inline is not None:
                dd["inline"] = "\n".join(inline)
                upper = ascii_upper(dd["inline"])
                run = re.search(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9#@$]+)", upper)
                if run:
                    step["run_program"] = run.group(1)
                    step["run_program_line"] = inline_start + upper.count("\n", 0, run.start())
                for definition in re.finditer(r"\bDEFINE\s+(?:CLUSTER|AIX|ALTERNATEINDEX|PATH)\b[^)]*?\bNAME\s*\(\s*([^)\s]+)", upper):
                    if definition.group(1) not in result["defined_datasets"]:
                        result["defined_datasets"].append(definition.group(1))
                if re.search(r"^\s*(?:SORT|MERGE)\s+FIELDS|^\s*(?:INCLUDE|OMIT)\s+COND", upper, re.M):
                    hazard("sort_control_logic", line)
            step["dds"].append(dd)
        elif op == "IF":
            hazard("jcl_if", line)
        elif op == "INCLUDE":
            _, keyed = _params(operands)
            if "MEMBER" in keyed:
                result["includes"].append({"member": ascii_upper(keyed["MEMBER"]), "line": line})
    return result
