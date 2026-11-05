"""Extract jobs, steps, datasets and control cards from JCL."""
import re

from .definitions import defined_datasets
from .sourcefile import ascii_upper, split_lines

KNOWN_OPS = {
    "JOB", "EXEC", "DD", "PROC", "PEND", "IF", "ELSE", "ENDIF", "SET", "INCLUDE", "JCLLIB", "OUTPUT", "CNTL",
    "ENDCNTL", "COMMAND", "XMIT",
}
SORT_PROGRAMS = {"SORT", "ICEMAN", "SYNCSORT", "DFSORT", "ICETOOL", "SYNCTOOL"}
_STATEMENT = re.compile(r"^//(\S*)\s+(\S+)\s*(.*)$")
_SYMBOL = re.compile(r"&([A-Z0-9#@$]+)\.?")


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


def _read_inline(lines, start, operands):
    """Return (data lines, index after them), honouring DLM= and the DATA form that may hold // lines."""
    delimiter = re.search(r"\bDLM=(?:'([^']+)'|([^,\s]+))", operands)
    end_mark = (delimiter.group(1) or delimiter.group(2)) if delimiter else None
    is_data = operands.startswith("DATA")
    data, i = [], start
    while i < len(lines):
        line = lines[i]
        if end_mark:
            if line.startswith(end_mark):
                return data, i + 1
        else:
            if line.startswith("/*"):
                return data, i + 1
            if line.startswith("//") and not is_data:
                return data, i
        data.append(line[:71].rstrip())
        i += 1
    return data, i


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
        while (operands.endswith(",") or operands.count("'") % 2) and i < total:
            next_line = lines[i][:71].rstrip()
            if next_line.startswith("//*"):
                i += 1
                continue
            if not next_line.startswith("//"):
                break
            operands = _operand_text(operands + next_line[2:].strip())
            i += 1
        inline = None
        inline_start = i + 1
        if op == "DD" and re.match(r"^(\*|DATA)(,|$)", operands):
            inline, i = _read_inline(lines, i, operands)
        yield name, op, operands, number, inline, inline_start


def _apply_symbols(value, symbols):
    """Substitute known symbols. Returns (text, whether a symbol was involved). && marks temporary datasets."""
    if value is None or "&" not in value or value.startswith("&&"):
        return value, False
    return _SYMBOL.sub(lambda m: symbols.get(m.group(1), m.group(0)), ascii_upper(value)), True


def _remember_symbols(operands, symbols):
    _, keyed = _params(operands)
    for key, value in keyed.items():
        if value:
            symbols[key] = value.strip("'")


def parse_jcl(text):
    result = {
        "name": None, "type": "proc", "steps": [], "hazards": [], "unrecognized": [], "includes": [],
        "defined_datasets": [], "line_count": len(split_lines(text)), "jobs": [], "instream_procs": {},
    }
    step, last_dd, current_job, instream = None, None, None, None
    symbols = {}

    def hazard(kind, line):
        result["hazards"].append({"type": kind, "line": line})

    for name, op, operands, line, inline, inline_start in _statements(text):
        if op not in KNOWN_OPS:
            result["unrecognized"].append((op + " " + operands).strip())
        elif op == "JOB":
            current_job = ascii_upper(name)
            result["jobs"].append(current_job)
            if result["type"] != "job":
                result["name"], result["type"] = current_job, "job"
            if any(k.startswith("COND") for k in _params(operands)[1]):
                hazard("jcl_cond", line)
        elif op == "PROC":
            _remember_symbols(operands, symbols)
            if result["type"] == "job":
                instream = ascii_upper(name)
                result["instream_procs"][instream] = []
            elif result["name"] is None:
                result["name"] = ascii_upper(name) or None
            step = None
        elif op == "PEND":
            instream, step = None, None
        elif op == "SET":
            _remember_symbols(operands, symbols)
        elif op == "EXEC":
            positional, keyed = _params(operands)
            cond = keyed.get("COND") or next((v for k, v in keyed.items() if k.startswith("COND.")), None)
            step = {
                "name": ascii_upper(name), "line": line, "program": None, "proc": None, "run_program": None,
                "run_program_line": None, "run_programs": [], "parm": keyed.get("PARM"), "cond": cond, "dds": [], "job": current_job,
            }
            if "PGM" in keyed:
                step["program"] = ascii_upper(_apply_symbols(keyed["PGM"], symbols)[0])
            elif "PROC" in keyed:
                step["proc"] = ascii_upper(_apply_symbols(keyed["PROC"], symbols)[0])
            elif positional:
                step["proc"] = ascii_upper(_apply_symbols(positional[0], symbols)[0])
            (result["instream_procs"][instream] if instream else result["steps"]).append(step)
            last_dd = None
            if cond:
                hazard("jcl_cond", line)
            if step["program"] in SORT_PROGRAMS:
                hazard("sort_step", line)
            elif step["program"] == "IDCAMS":
                hazard("idcams_step", line)
            elif step["program"] == "DFSRRC00":
                hazard("ims_step", line)
                parts = (step["parm"] or "").strip("'()").split(",")
                if len(parts) > 1:
                    step["run_programs"].append({"name": ascii_upper(parts[1]), "line": line})
                    step["run_program"], step["run_program_line"] = ascii_upper(parts[1]), line
        elif op == "DD" and step is not None:
            positional, keyed = _params(operands)
            full_name = ascii_upper(name)
            override = None
            if "." in full_name:
                override, full_name = full_name.rsplit(".", 1)
                hazard("dd_override", line)
            dd_name = full_name or last_dd
            last_dd = dd_name
            dsn, symbolic = _apply_symbols(keyed.get("DSN") or keyed.get("DSNAME"), symbols)
            member = None
            if dsn:
                dsn = ascii_upper(dsn)
                m = re.match(r"^(.*)\((&?[A-Z0-9#@$]+)\)$", dsn)
                if m and not m.group(2).isdigit():
                    dsn, member = m.group(1), m.group(2)
                if re.search(r"\([+-]?\d+\)$", dsn):
                    hazard("gdg", line)
            dd = {
                "name": dd_name, "dsn": dsn, "member": member, "disp": keyed.get("DISP"), "line": line, "inline": None,
                "override_step": override, "symbolic": symbolic,
            }
            if inline is not None:
                dd["inline"] = "\n".join(inline)
                upper = ascii_upper(dd["inline"])
                for run in re.finditer(r"\bRUN\s+PROG(?:RAM)?\s*\(\s*([^)\s,]+)", upper):
                    program = run.group(1)
                    run_line = inline_start + upper.count("\n", 0, run.start())
                    step["run_programs"].append({"name": program, "line": run_line})
                    if step["run_program"] is None:
                        step["run_program"], step["run_program_line"] = program, run_line
                for dataset in defined_datasets(upper):
                    if dataset not in result["defined_datasets"]:
                        result["defined_datasets"].append(dataset)
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
