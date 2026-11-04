"""Extract structural facts from a COBOL program. Facts only, with line numbers."""
import re as _plain_re

from .sourcefile import cobol_regex as re, ascii_upper, logical_source, split_lines

WORD = r"[A-Z0-9][A-Z0-9-]*"
KNOWN_CICS = {
    "ABEND", "ADDRESS", "ALLOCATE", "ASKTIME", "ASSIGN", "BIF", "CANCEL", "CONVERSE", "DELAY", "DELETE", "DELETEQ",
    "DEQ", "DOCUMENT", "DUMP", "ENDBR", "ENQ", "ENTER", "FORMATTIME", "FREEMAIN", "GET", "GETMAIN", "HANDLE", "IGNORE",
    "INQUIRE", "ISSUE", "LINK", "LOAD", "POP", "POST", "PURGE", "PUSH", "PUT", "READ", "READNEXT", "READPREV", "READQ",
    "RECEIVE", "RELEASE", "RESETBR", "RESP", "RETRIEVE", "RETURN", "REWRITE", "ROUTE", "SEND", "SET", "SIGNOFF",
    "SIGNON", "START", "STARTBR", "STARTBROWSE", "SUSPEND", "SYNCPOINT", "TRACE", "UNLOCK", "VERIFY", "WAIT", "WEB",
    "WRITE", "WRITEQ", "XCTL",
}
SQL_READ = {"SELECT", "FETCH", "VALUES"}
SQL_WRITE = {"INSERT", "UPDATE", "DELETE", "MERGE"}
SQL_CONTROL = {
    "OPEN", "CLOSE", "COMMIT", "ROLLBACK", "WHENEVER", "SET", "CONNECT", "BEGIN", "END", "LOCK", "SAVEPOINT",
    "RELEASE", "GET", "CALL", "FETCH", "INCLUDE", "DECLARE", "PREPARE", "EXECUTE", "DESCRIBE",
}
IMS_CALLS = {"CBLTDLI", "AIBTDLI", "CEETDLI", "AERTDLI"}
_RESERVED_LABELS = {
    "EXIT", "GOBACK", "CONTINUE", "STOP", "ELSE", "END-IF", "END-EXEC", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-CALL", "END-COMPUTE", "END-WRITE", "END-REWRITE", "END-START", "END-DELETE", "END-SEARCH", "END-STRING",
    "END-UNSTRING", "NEXT", "EJECT", "SKIP1", "SKIP2", "SKIP3",
}
HAZARDS = [
    ("comp3", r"\bCOMP-3\b|\bCOMPUTATIONAL-3\b|\bPACKED-DECIMAL\b"),
    ("redefines", r"\bREDEFINES\b"),
    ("occurs_depending", r"\bOCCURS\b[^.]*?\bDEPENDING\b"),
    ("level88", r"^\s*88\s"),
    ("goto", r"\bGO\s+TO\b"),
    ("perform_thru", r"\bPERFORM\s+" + WORD + r"\s+(?:THRU|THROUGH)\b"),
    ("alter", r"\bALTER\s+" + WORD + r"\s+TO\b"),
    ("next_sentence", r"\bNEXT\s+SENTENCE\b"),
    ("rounded", r"\bROUNDED\b"),
    ("unrounded_compute", r"\bCOMPUTE\s+" + WORD + r"\s*="),
    ("sort_verb", r"\b(?:SORT|MERGE)\s+" + WORD + r"\s+(?:ON|ASCENDING|DESCENDING)\b"),
    ("collating_sequence", r"\bCOLLATING\s+SEQUENCE\b|\bALPHABET\s"),
    ("file_status", r"\bFILE\s+STATUS\b"),
    ("sqlcode", r"\bSQLCODE\b|\bSQLSTATE\b"),
    ("abend", r"\bCEE3ABD\b|\bILBOABN0\b|\bABEND\b"),
    ("return_code", r"\bRETURN-CODE\b"),
    ("checkpoint", r"\bCHKP\b|\bCHECKPOINT\b|\bRERUN\b"),
    ("commit", r"\bEXEC\s+SQL\s+(?:COMMIT|ROLLBACK)\b"),
    ("commarea", r"\bDFHCOMMAREA\b|\bCOMMAREA\s*\("),
    ("syncpoint", r"\bSYNCPOINT\b"),
    ("locking", r"\bEXEC\s+CICS\s+(?:ENQ|DEQ|UNLOCK)\b|\bUPDATE\b(?=[^.]*\bEND-EXEC\b)"),
    ("cics_handle", r"\bHANDLE\s+(?:ABEND|CONDITION|AID)\b"),
    ("date_window", r"\bFROM\s+DATE\b(?!\s+YYYYMMDD)|\bYYMMDD\b|\bWINDOW\b|\bDATE-?YY\b"),
]
_COMPILED_HAZARDS = [(name, re.compile(rx, re.M)) for name, rx in HAZARDS]


def _strip_literal(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        return raw[1:-1].strip()
    return None


def _find_includes(raw_text, src):
    copies = []
    for m in re.finditer(r"\bCOPY\s+(" + WORD + r"|['\"]_*['\"])(?:\s+(?:OF|IN)\s+(" + WORD + r"))?", src.masked):
        token = m.group(1)
        if token[0] in "'\"":
            name = _strip_literal(src.text[m.start(1):m.end(1)]) or ""
        else:
            name = token
        copies.append({"name": ascii_upper(name), "mechanism": "COPY", "library": m.group(2), "line": src.line_at(m.start())})
    for m in re.finditer(r"\bEXEC\s+SQL\s+INCLUDE\s+(" + WORD + r")", src.masked):
        copies.append({"name": m.group(1), "mechanism": "SQL_INCLUDE", "library": None, "line": src.line_at(m.start())})
    for number, line in enumerate(split_lines(raw_text), 1):
        if len(line) > 6 and line[6] in "*/":
            continue
        m = re.match(r"^(?:.{0,7})\s*(\+\+INCLUDE|-INC)\s+([A-Za-z0-9#@$-]+)", line)
        if m:
            copies.append({"name": ascii_upper(m.group(2)), "mechanism": ascii_upper(m.group(1)), "library": None, "line": number})
    return sorted(copies, key=lambda c: (c["line"], c["name"]))


_NON_TARGET_WORDS = {
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE", "ELSE",
    "END-EVALUATE", "END-EXEC", "END-IF", "END-PERFORM", "END-READ", "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF",
    "INITIALIZE", "INSPECT", "MOVE", "MULTIPLY", "NEXT", "OPEN", "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE",
    "SEARCH", "SET", "SORT", "START", "STOP", "STRING", "SUBTRACT", "UNSTRING", "WHEN", "WRITE", "AT", "NOT", "INVALID",
}
_NAME_VALUE = _plain_re.compile(r"[A-Z0-9#@$]{1,8}")
_TARGET = _plain_re.compile(r"(" + WORD + r")\s*(?:\([^)]*\)\s*)?(?:(?:OF|IN)\s+" + WORD + r"\s*)?,?\s*")


def _value_table(src):
    """Build, once per program, the literals and other items that each data item can receive."""
    values, moves = {}, {}
    data_start = re.search(r"\bDATA\s+DIVISION\b", src.masked)
    proc_start = re.search(r"\bPROCEDURE\s+DIVISION\b", src.masked)
    begin = data_start.end() if data_start else 0
    end = proc_start.start() if proc_start else len(src.masked)
    for m in re.finditer(r"\b\d{1,2}\s+(" + WORD + r")\b[^.]*?\bVALUE\s+(?:IS\s+)?(['\"]_*['\"])", src.masked[begin:end]):
        literal = _strip_literal(src.text[begin + m.start(2):begin + m.end(2)])
        values.setdefault(m.group(1), set()).add(literal)
    scan = src.masked[end:]
    for m in re.finditer(r"\bMOVE\s+(['\"]_*['\"]|" + WORD + r")\s+TO\s+", scan):
        token = m.group(1)
        source = None
        if token[0] in "'\"":
            literal = _strip_literal(src.text[end + m.start(1):end + m.end(1)])
        else:
            literal, source = None, token
        position = m.end()
        while True:
            word = _TARGET.match(scan, position)
            if not word or word.group(1) in _NON_TARGET_WORDS:
                break
            entry = moves.setdefault(word.group(1), {"literals": set(), "sources": set()})
            if literal is not None:
                entry["literals"].add(literal)
            else:
                entry["sources"].add(source)
            position = word.end()
    return values, moves


def _value_candidates(variable, src, cache):
    """Program-name-shaped literals a data item can hold, from its VALUE and the MOVEs into it."""
    if "__table__" not in cache:
        cache["__table__"] = _value_table(src)
    values, moves = cache["__table__"]
    found, seen, pending = set(), set(), [variable]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        found.update(values.get(name, ()))
        entry = moves.get(name)
        if entry:
            found.update(entry["literals"])
            pending.extend(entry["sources"])
    return sorted(v for v in (ascii_upper(f or "") for f in found) if _NAME_VALUE.fullmatch(v))


def _calls(src, cache):
    calls = []
    for m in re.finditer(r"\bCALL\s+(['\"]_*['\"]|" + WORD + r")", src.masked):
        token = m.group(1)
        line = src.line_at(m.start())
        if token[0] in "'\"":
            calls.append({"target": ascii_upper(_strip_literal(src.text[m.start(1):m.end(1)]) or ""), "dynamic": False, "line": line})
        else:
            calls.append({"target": None, "dynamic": True, "variable": token, "candidates": _value_candidates(token, src, cache), "line": line})
    return calls


def _cics(src, cache, unrecognized):
    statements = []
    for m in re.finditer(r"\bEXEC\s+CICS\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        body = m.group(1)
        words = body.split()
        verb = re.match(r"[A-Z0-9-]*", words[0]).group(0) if words else ""
        if verb not in KNOWN_CICS:
            unrecognized.append(" ".join(("EXEC CICS " + body).split()))
        options, resolved = {}, {}
        for opt in re.finditer(r"\b(" + WORD + r")\s*\(\s*([^()]*?)\s*\)", body):
            start = m.start(1) + opt.start(2)
            raw = src.text[start:m.start(1) + opt.end(2)]
            literal = _strip_literal(raw)
            key = opt.group(1)
            if literal is not None:
                options[key] = ascii_upper(literal)
            else:
                options[key] = opt.group(2)
                if key in ("PROGRAM", "TRANSID", "FILE", "DATASET", "MAP", "MAPSET"):
                    resolved[key] = _value_candidates(opt.group(2), src, cache)
        statements.append({"verb": verb, "line": src.line_at(m.start()), "options": options, "resolved": resolved, "words": words[:2]})
    return statements


def _sql(src, unrecognized):
    statements = []
    for m in re.finditer(r"\bEXEC\s+SQL\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        body = " ".join(m.group(1).split())
        words = body.split()
        verb = words[0] if words else ""
        tables, access = [], None
        if verb == "DECLARE" and " TABLE" in body and "CURSOR" not in body:
            continue
        if verb in SQL_WRITE or verb in SQL_READ or (verb == "DECLARE" and "CURSOR" in body):
            for t in re.finditer(r"(?<!YEAR )(?<!MONTH )(?<!DAY )\b(?:FROM|JOIN|UPDATE|INSERT\s+INTO|MERGE\s+INTO)\s+((?:[A-Z0-9_#@$.]+\s*(?:[A-Z0-9_]+\s*)?,\s*)*[A-Z0-9_#@$.]+)", body):
                for part in t.group(1).split(","):
                    name = part.split()[0].split(".")[-1]
                    if name and name not in ("SYSDUMMY1", "SELECT", "SET", "OF") and not name.isdigit() and name not in tables:
                        tables.append(name)
            access = "write" if verb in SQL_WRITE else "read"
        elif verb not in SQL_CONTROL:
            unrecognized.append("EXEC SQL " + body)
        statements.append({"verb": verb, "tables": tables, "access": access, "line": src.line_at(m.start())})
    return statements


def _files(src):
    files = []
    for m in re.finditer(r"\bSELECT\s+(?:OPTIONAL\s+)?(" + WORD + r")\s+ASSIGN\s+(?:TO\s+)?(['\"]_*['\"]|" + WORD + r")([^.]*)\.", src.masked):
        token = m.group(2)
        if token[0] in "'\"":
            dd = ascii_upper(_strip_literal(src.text[m.start(2):m.end(2)]) or "")
        else:
            dd = token
        dd = re.sub(r"^(?:UT-)?(?:[SDI]|AS|DA)-", "", dd)
        org = re.search(r"\bORGANIZATION\s+(?:IS\s+)?([A-Z]+)", m.group(3))
        files.append({
            "logical": m.group(1), "ddname": dd, "organization": org.group(1) if org else "SEQUENTIAL",
            "access": None, "line": src.line_at(m.start()),
        })
    by_name = {f["logical"]: f for f in files}
    rank = {None: 0, "read": 1, "write": 2, "update": 3}
    for m in re.finditer(r"\bOPEN\b([^.]*)", src.masked):
        mode = None
        for token in m.group(1).split():
            if token in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = {"INPUT": "read", "OUTPUT": "write", "I-O": "update", "EXTEND": "write"}[token]
            elif token in by_name and mode and rank[mode] > rank[by_name[token]["access"]]:
                by_name[token]["access"] = mode
    return files


def _paragraphs(src):
    start = re.search(r"\bPROCEDURE\s+DIVISION\b[^.]*\.", src.masked)
    if not start:
        return [], None
    area_b_seen = False
    paragraphs = []
    offset = start.end()
    lines = src.masked[offset:].split("\n")
    # Area A labels have at most 3 leading spaces in fixed format. Free format may indent freely.
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    area_b_seen = bool(indents) and min(indents) >= 4
    position = offset
    for line in lines:
        m = re.match(r"^(\s*)(" + WORD + r")(\s+SECTION)?\s*\.\s*$", line)
        if m and m.group(2) not in _RESERVED_LABELS and (area_b_seen or len(m.group(1)) < 4):
            paragraphs.append({
                "name": m.group(2), "is_section": bool(m.group(3)),
                "start_line": src.line_at(position + len(m.group(1))), "end_line": None,
            })
        position += len(line) + 1
    return paragraphs, start.end()


def _hazards(src):
    found = []
    for name, pattern in _COMPILED_HAZARDS:
        for m in pattern.finditer(src.masked):
            found.append({"type": name, "line": src.line_at(m.start() + len(m.group(0)) - len(m.group(0).lstrip()))})
    return sorted(found, key=lambda h: (h["line"], h["type"]))


def parse_cobol(text):
    src = logical_source(text)
    cache = {}
    unrecognized = []
    technologies = set()
    pid = re.search(r"\bPROGRAM-ID\s*\.?\s*(['\"]_*['\"]|" + WORD + r")", src.masked)
    program_id = None
    if pid:
        token = pid.group(1)
        program_id = ascii_upper(_strip_literal(src.text[pid.start(1):pid.end(1)]) or "") if token[0] in "'\"" else token
    for m in re.finditer(r"\bEXEC\s+(?!CICS\b|SQL\b)([A-Z0-9]+)\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        unrecognized.append(" ".join(("EXEC " + m.group(1) + m.group(2)).split()))
        if m.group(1) in ("DLI", "SQLIMS"):
            technologies.add("ims")
    calls = _calls(src, cache)
    for call in calls:
        if call["target"] in IMS_CALLS:
            technologies.add("ims")
        elif call["target"] and call["target"].startswith("MQ"):
            technologies.add("mq")
    cics = _cics(src, cache, unrecognized)
    sql = _sql(src, unrecognized)
    if cics:
        technologies.add("cics")
    if sql:
        technologies.add("db2")
    paragraphs, proc_start = _paragraphs(src)
    last_line = src.line_at(len(src.text))
    for i, para in enumerate(paragraphs):
        para["end_line"] = paragraphs[i + 1]["start_line"] - 1 if i + 1 < len(paragraphs) else last_line

    def enclosing(line):
        for para in reversed(paragraphs):
            if para["start_line"] <= line:
                return para["name"]
        return None

    performs, gotos = [], []
    if proc_start is not None:
        body = src.masked[proc_start:]
        for m in re.finditer(r"\bPERFORM\s+(?!UNTIL\b|VARYING\b|WITH\b|TEST\b|FOREVER\b|\d+\s+TIMES)(" + WORD + r")(?:\s+(?:THRU|THROUGH)\s+(" + WORD + r"))?", body):
            line = src.line_at(proc_start + m.start())
            performs.append({"from": enclosing(line), "target": m.group(1), "thru": m.group(2), "line": line})
        for m in re.finditer(r"\bGO\s+(?:TO\s+)?(" + WORD + r")", body):
            line = src.line_at(proc_start + m.start())
            gotos.append({"from": enclosing(line), "target": m.group(1), "line": line})
    procedure = src.masked[proc_start:] if proc_start is not None else ""
    decisions = sum(len(re.findall(rx, procedure)) for rx in (r"\bIF\b", r"\bEVALUATE\b", r"\bWHEN\b", r"\bUNTIL\b"))
    return {
        "program_id": program_id,
        "copies": _find_includes(text, src),
        "calls": calls,
        "cics": cics,
        "sql": sql,
        "files": _files(src),
        "paragraphs": paragraphs,
        "performs": performs,
        "gotos": gotos,
        "hazards": _hazards(src),
        "unrecognized": unrecognized,
        "technologies": sorted(technologies),
        "metrics": {"lines": len(split_lines(text)), "decisions": decisions},
    }
