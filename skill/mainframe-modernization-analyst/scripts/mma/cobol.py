"""Extract structural facts from a COBOL program. Facts only, with line numbers."""
import re as _plain_re

from .sourcefile import ascii_upper, cobol_regex as re, logical_source, split_lines

WORD = r"[A-Z0-9#@$][A-Z0-9#@$_-]*"
LITERAL = r"['\"]_*['\"]"
KNOWN_CICS = {
    "ABEND", "ADDRESS", "ALLOCATE", "ASKTIME", "ASSIGN", "BIF", "CANCEL", "CONVERSE", "DELAY", "DELETE", "DELETEQ",
    "DEQ", "DOCUMENT", "DUMP", "ENDBR", "ENQ", "ENTER", "FORMATTIME", "FREEMAIN", "GET", "GETMAIN", "HANDLE", "IGNORE",
    "INQUIRE", "ISSUE", "LINK", "LOAD", "POP", "POST", "PURGE", "PUSH", "PUT", "READ", "READNEXT", "READPREV", "READQ",
    "RECEIVE", "RELEASE", "RESETBR", "RESP", "RETRIEVE", "RETURN", "REWRITE", "ROUTE", "SEND", "SET", "SIGNOFF",
    "SIGNON", "START", "STARTBR", "STARTBROWSE", "SUSPEND", "SYNCPOINT", "TRACE", "UNLOCK", "VERIFY", "WAIT", "WEB",
    "WRITE", "WRITEQ", "XCTL",
}
SQL_WRITE = {"INSERT", "UPDATE", "DELETE", "MERGE"}
SQL_WITH_TABLES = SQL_WRITE | {"SELECT", "WITH", "VALUES", "SET", "DECLARE"}
SQL_CONTROL = {
    "OPEN", "CLOSE", "COMMIT", "ROLLBACK", "WHENEVER", "CONNECT", "BEGIN", "END", "SAVEPOINT", "RELEASE", "GET", "FETCH",
    "INCLUDE", "PREPARE", "EXECUTE", "DESCRIBE", "LOCK", "CALL", "SET",
}
SQL_ALIAS_STOP = {
    "WHERE", "GROUP", "ORDER", "HAVING", "FETCH", "FOR", "WITH", "INNER", "LEFT", "RIGHT", "FULL", "JOIN", "ON", "UNION",
    "EXCEPT", "INTERSECT", "SET", "WHEN", "CROSS", "OPTIMIZE", "QUERYNO", "END", "USING", "AS", "INTO", "SELECT", "VALUES",
}
_SQL_NAME = r"[A-Z0-9_#@$][A-Z0-9_#@$.]*"
_SQL_ITEM = _plain_re.compile(r"\s*(" + _SQL_NAME + r")(\s*\()?(?:\s+AS)?(?:\s+(" + _SQL_NAME + r"))?\s*(,)?")
IMS_CALLS = {"CBLTDLI", "AIBTDLI", "CEETDLI", "AERTDLI"}
ABEND_ROUTINES = {"CEE3ABD", "CEE3AB2", "ILBOABN0", "ILBOABN", "ABEND", "ABENDPGM"}
CHECKPOINT_ROUTINES = {"CKPT", "CHKP"}
ASSIGN_CLASSES = {"S", "D", "R", "I", "AS", "DA", "UT", "UR"}
_RESERVED_LABELS = {
    "EXIT", "GOBACK", "CONTINUE", "STOP", "ELSE", "END-IF", "END-EXEC", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-CALL", "END-COMPUTE", "END-WRITE", "END-REWRITE", "END-START", "END-DELETE", "END-SEARCH", "END-STRING",
    "END-UNSTRING", "NEXT", "EJECT", "SKIP1", "SKIP2", "SKIP3",
}
_NON_TARGET_WORDS = {
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE", "ELSE",
    "END-EVALUATE", "END-EXEC", "END-IF", "END-PERFORM", "END-READ", "END-STRING", "END-UNSTRING", "EVALUATE", "EXEC",
    "EXECUTE", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MOVE", "MULTIPLY", "NEXT", "OPEN", "PERFORM",
    "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "START", "STOP", "STRING", "SUBTRACT", "UNSTRING",
    "WHEN", "WRITE", "AT", "NOT", "INVALID", "ON", "TALLYING", "DELIMITED", "COUNT", "WITH", "POINTER", "OVERFLOW",
}
_NAME_VALUE = _plain_re.compile(r"[A-Z0-9#@$]{1,8}")
_TARGET = _plain_re.compile(r"(" + WORD + r")\s*(\([^)]*\)\s*)?(?:(?:OF|IN)\s+" + WORD + r"\s*)?,?\s*")
_OPTION_NAME = _plain_re.compile(WORD + r"\s*\(")
_BASE_NAME = _plain_re.compile(WORD)
_RESOLVED_OPTIONS = {"PROGRAM", "TRANSID", "FILE", "DATASET", "MAP", "MAPSET", "QUEUE", "QNAME"}
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
    ("unrounded_compute", r"\bCOMPUTE\b(?![^=.]*\bROUNDED\b)[^=.]*=|\b(?:ADD|SUBTRACT|MULTIPLY|DIVIDE)\b(?![^.]{0,200}?\bROUNDED\b)[^.]{0,200}?\bGIVING\b"),
    ("sort_verb", r"\b(?:SORT|MERGE)\s+" + WORD + r"\s+(?:ON|ASCENDING|DESCENDING)\b"),
    ("collating_sequence", r"\bCOLLATING\s+SEQUENCE\b|\bALPHABET\s"),
    ("file_status", r"\bFILE\s+STATUS\b"),
    ("sqlcode", r"\bSQLCODE\b|\bSQLSTATE\b"),
    ("abend", r"\bABEND\b"),
    ("return_code", r"\bRETURN-CODE\b"),
    ("checkpoint", r"\bCHKP\b|\bCHECKPOINT\b|\bRERUN\b"),
    ("commit", r"\bEXEC\s+SQL\s+(?:COMMIT|ROLLBACK)\b"),
    ("commarea", r"\bDFHCOMMAREA\b|\bCOMMAREA\s*\("),
    ("syncpoint", r"\bSYNCPOINT\b"),
    ("locking", r"\bEXEC\s+CICS\s+(?:ENQ|DEQ|UNLOCK)\b|\bUPDATE\b(?=[^.]*\bEND-EXEC\b)"),
    ("cics_handle", r"\bHANDLE\s+(?:ABEND|CONDITION|AID)\b"),
    ("date_window", r"\bFROM\s+DATE\b(?!\s+YYYYMMDD)|\bYYMMDD\b|\bWINDOW\b|\bDATE-?YY\b"),
    ("copy_replacing", r"\bCOPY\s+" + WORD + r"\b[^.]*?\bREPLACING\b"),
]
_COMPILED_HAZARDS = [(name, re.compile(rx, re.M)) for name, rx in HAZARDS]


def _strip_literal(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        return raw[1:-1].strip()
    return None


def _without_exec_blocks(masked):
    """The text with EXEC ... END-EXEC blanked at the same offsets, so `CALL` in SQL isn't a COBOL CALL."""
    def blank(match):
        return "".join(c if c == "\n" else " " for c in match.group(0))
    return re.compile(r"\bEXEC(?:UTE)?\s+[A-Z0-9]+\b.*?\bEND-EXEC\b", re.S).sub(blank, masked)


def _find_includes(raw_text, src):
    copies = []
    for m in re.finditer(r"\bCOPY\s+(" + WORD + r"|" + LITERAL + r")(?:\s+(?:OF|IN)\s+(" + WORD + r"))?", src.masked):
        token = m.group(1)
        name = (_strip_literal(src.text[m.start(1):m.end(1)]) or "") if token[0] in "'\"" else token
        copies.append({"name": ascii_upper(name), "mechanism": "COPY", "library": m.group(2), "line": src.line_at(m.start())})
    for m in re.finditer(r"\bEXEC\s+SQL\s+INCLUDE\s+(" + WORD + r")", src.masked):
        copies.append({"name": m.group(1), "mechanism": "SQL_INCLUDE", "library": None, "line": src.line_at(m.start())})
    for number, line in enumerate(split_lines(raw_text), 1):
        if len(line) > 6 and line[6] in "*/":
            continue
        m = _plain_re.match(r"^(?:.{0,7})\s*(\+\+INCLUDE|-INC)\s+([A-Za-z0-9#@$-]+)", line)
        if m:
            copies.append({"name": ascii_upper(m.group(2)), "mechanism": ascii_upper(m.group(1)), "library": None, "line": number})
    return sorted(copies, key=lambda c: (c["line"], c["name"]))


def _value_table(src, plain):
    """Build, once per program, what each data item can receive. Writes we can't read make an item opaque."""
    values, moves, opaque = {}, {}, set()
    proc_start = re.search(r"\bPROCEDURE\s+DIVISION\b", src.masked)
    data_start = re.search(r"\bDATA\s+DIVISION\b", src.masked)
    begin = data_start.end() if data_start else 0
    end = proc_start.start() if proc_start else len(src.masked)
    data = src.masked[begin:end]
    for m in re.finditer(r"\b\d{1,2}\s+(" + WORD + r")\b[^.]*?\bVALUE\s+(?:IS\s+)?(" + LITERAL + r")", data):
        values.setdefault(m.group(1), set()).add(_strip_literal(src.text[begin + m.start(2):begin + m.end(2)]))
    parents, last = {}, None
    for m in re.finditer(r"^\s*(\d{1,2})\s+(" + WORD + r")", data, re.M):
        if m.group(1) == "88":
            parents[m.group(2)] = last
        else:
            last = m.group(2)
    scan_start = proc_start.start() if proc_start else 0
    scan = src.masked[scan_start:]
    plain_scan = plain[scan_start:]

    def targets_after(position, on_target):
        while True:
            word = _TARGET.match(plain_scan, position)
            if not word or word.group(1) in _NON_TARGET_WORDS:
                return
            on_target(word.group(1), word.group(2) or "")
            position = word.end()

    for m in re.finditer(r"\bMOVE\s+(" + LITERAL + r"|" + WORD + r")(?:\s*\([^)]*\))?(?:\s+(?:OF|IN)\s+" + WORD + r")?(?:\s*\([^)]*\))?\s+TO\s+", plain_scan):
        token = m.group(1)
        literal = _strip_literal(src.text[scan_start + m.start(1):scan_start + m.end(1)]) if token[0] in "'\"" else None
        source = None if token[0] in "'\"" else token

        def record(name, subscript, literal=literal, source=source):
            if ":" in subscript:
                opaque.add(name)
                return
            entry = moves.setdefault(name, {"literals": set(), "sources": set()})
            if literal is not None:
                entry["literals"].add(literal)
            elif source:
                entry["sources"].add(source)

        targets_after(m.end(), record)
    for m in re.finditer(r"\b(?:INTO|ACCEPT)\s+", plain_scan):
        targets_after(m.end(), lambda name, _: opaque.add(name))
    for m in re.finditer(r"\bINTO\s*\(\s*(" + WORD + r")|\bINTO\s+:(" + WORD + r")", scan):
        opaque.add(m.group(1) or m.group(2))
    for m in re.finditer(r"\bSET\s+(" + WORD + r")\s+TO\s+TRUE\b", plain_scan):
        opaque.add(parents.get(m.group(1), m.group(1)))
    return values, moves, opaque


def _value_candidates(variable, src, cache):
    """Return (name-shaped literals the item can hold, items feeding it whose values aren't visible here)."""
    if "__table__" not in cache:
        cache["__table__"] = _value_table(src, cache["__plain__"])
    values, moves, opaque = cache["__table__"]
    found, seen, pending, unresolved = set(), set(), [variable], set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        entry = moves.get(name)
        if name in opaque or (name not in values and not entry):
            unresolved.add(name)
        found.update(values.get(name, ()))
        if entry:
            found.update(entry["literals"])
            pending.extend(entry["sources"])
    return sorted(v for v in (ascii_upper(f or "") for f in found) if _NAME_VALUE.fullmatch(v)), sorted(unresolved)


def constants_table(text):
    """Literal VALUEs declared in a copybook, so programs that copy it can resolve names through it."""
    src = logical_source(text)
    values = {}
    for m in re.finditer(r"\b\d{1,2}\s+(" + WORD + r")\b[^.]*?\bVALUE\s+(?:IS\s+)?(" + LITERAL + r")", src.masked):
        literal = ascii_upper(_strip_literal(src.text[m.start(2):m.end(2)]) or "")
        if m.group(1) != "FILLER" and _NAME_VALUE.fullmatch(literal):
            values.setdefault(m.group(1), []).append(literal)
    return {k: sorted(set(v)) for k, v in values.items()}


def _calls(src, plain, cache):
    calls = []
    for m in re.finditer(r"\bCALL\s+(" + LITERAL + r"|" + WORD + r")", plain):
        token = m.group(1)
        line = src.line_at(m.start())
        if token[0] in "'\"":
            calls.append({"target": ascii_upper(_strip_literal(src.text[m.start(1):m.end(1)]) or ""), "dynamic": False, "line": line})
        else:
            candidates, unresolved = _value_candidates(token, src, cache)
            calls.append({"target": None, "dynamic": True, "variable": token, "candidates": candidates, "unresolved": unresolved, "line": line})
    return calls


def _option_spans(body):
    """Yield (option, start, end) for top-level OPTION(value), allowing nested parentheses in the value."""
    position = 0
    while True:
        found = _OPTION_NAME.search(body, position)
        if not found:
            return
        depth, index = 1, found.end()
        while index < len(body) and depth:
            depth += {"(": 1, ")": -1}.get(body[index], 0)
            index += 1
        if depth:
            return
        yield found.group(0).rstrip(" (\n\t"), found.end(), index - 1
        position = index


def _cics(src, cache, unrecognized):
    statements = []
    for m in re.finditer(r"\bEXEC(?:UTE)?\s+CICS\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        body = m.group(1)
        words = body.split()
        verb = _plain_re.match(r"[A-Z0-9-]*", words[0]).group(0) if words else ""
        if verb not in KNOWN_CICS:
            unrecognized.append(" ".join(("EXEC CICS " + body).split()))
        options, resolved, partly = {}, {}, {}
        for key, inner_start, inner_end in _option_spans(body):
            start = m.start(1) + inner_start
            literal = _strip_literal(src.text[start:m.start(1) + inner_end])
            if literal is not None:
                options[key] = ascii_upper(literal)
                continue
            value = body[inner_start:inner_end].strip()
            base = _BASE_NAME.match(value)
            options[key] = base.group(0) if base else value
            if key in _RESOLVED_OPTIONS:
                resolved[key], partly[key] = _value_candidates(options[key], src, cache)
        statements.append({"verb": verb, "line": src.line_at(m.start()), "options": options, "resolved": resolved, "unresolved": partly, "words": words[:2]})
    return statements


def _sql_list_after(body, start, names):
    """Read `name [AS] [alias], name ...` from a position, stopping at anything else."""
    position = start
    while True:
        item = _SQL_ITEM.match(body, position)
        if not item:
            return
        name = item.group(1)
        if item.group(2) or name in ("TABLE", "SELECT"):
            return
        names.append(name.split(".")[-1])
        alias = item.group(3)
        if alias in SQL_ALIAS_STOP or not item.group(4):
            return
        position = item.end()


def _sql_tables(verb, body):
    """Return (tables read, tables written)."""
    clean = body
    for _ in range(3):
        clean = _plain_re.sub(r"\b(?:EXTRACT|TRIM|SUBSTRING|POSITION|OVERLAY)\s*\([^()]*\)", " ", clean)
    writes = []
    target = {
        "INSERT": r"^INSERT\s+INTO\s+", "UPDATE": r"^UPDATE\s+", "DELETE": r"^DELETE\s+FROM\s+", "MERGE": r"^MERGE\s+INTO\s+",
    }.get(verb)
    reads_from = 0
    if target:
        found = _plain_re.match(target, clean)
        if found:
            name = _plain_re.match(_SQL_NAME, clean[found.end():])
            if name:
                writes.append(name.group(0).split(".")[-1])
                reads_from = found.end() + name.end()
    reads = []
    for m in _plain_re.finditer(r"(?:^|[\s(,])(?:FROM|JOIN)\s+", clean[reads_from:]):
        _sql_list_after(clean, reads_from + m.end(), reads)
    if verb == "MERGE":
        using = _plain_re.search(r"\bUSING\s+", clean)
        if using:
            _sql_list_after(clean, using.end(), reads)
    if verb == "WITH":
        local = set(_plain_re.findall(r"(?:WITH|,)\s*(" + _SQL_NAME + r")\s+AS\s*\(", clean))
        reads = [r for r in reads if r not in local]
    keep = []
    for name in reads:
        if name != "SYSDUMMY1" and not name.isdigit() and name not in keep:
            keep.append(name)
    return keep, writes


def _sql(src, unrecognized):
    statements = []
    for m in re.finditer(r"\bEXEC\s+SQL\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        raw = ascii_upper(src.text[m.start(1):m.end(1)])
        body = " ".join(_plain_re.sub(r"'[^']*'", "''", raw).replace('"', "").split())
        words = body.split()
        verb = words[0] if words else ""
        line = src.line_at(m.start())
        if verb == "DECLARE" and " TABLE" in body and "CURSOR" not in body:
            continue
        reads, writes, procedure, dynamic = [], [], None, False
        if verb in SQL_WITH_TABLES:
            reads, writes = _sql_tables(verb, body)
        elif verb == "LOCK" and len(words) > 2:
            reads = [words[2].split(".")[-1]]
        elif verb == "CALL" and len(words) > 1:
            procedure = words[1].split("(")[0].split(".")[-1]
        if verb == "PREPARE" or body.startswith("EXECUTE IMMEDIATE"):
            dynamic = True
        if verb not in SQL_WITH_TABLES and verb not in SQL_CONTROL:
            unrecognized.append("EXEC SQL " + body)
        tables = writes + [r for r in reads if r not in writes]
        access = "write" if writes else "read" if reads else None
        statements.append({"verb": verb, "tables": tables, "reads": reads, "writes": writes, "access": access,
                           "procedure": procedure, "dynamic": dynamic, "line": line})
    return statements


def _dd_from_assign(name):
    tokens = name.split("-")
    if len(tokens) > 1 and set(tokens[:-1]) & ASSIGN_CLASSES:
        return tokens[-1]
    return name


def _files(src, plain):
    files = []
    for m in re.finditer(r"\bSELECT\s+(?:OPTIONAL\s+)?(" + WORD + r")\s+ASSIGN\s+(?:TO\s+)?(" + LITERAL + r"|" + WORD + r")([^.]*)\.", plain):
        token = m.group(2)
        dd = ascii_upper(_strip_literal(src.text[m.start(2):m.end(2)]) or "") if token[0] in "'\"" else token
        org = re.search(r"\bORGANIZATION\s+(?:IS\s+)?([A-Z]+)", m.group(3))
        files.append({
            "logical": m.group(1), "ddname": _dd_from_assign(dd), "organization": org.group(1) if org else "SEQUENTIAL",
            "access": None, "line": src.line_at(m.start()),
        })
    by_name = {f["logical"]: f for f in files}
    rank = {None: 0, "read": 1, "write": 2, "update": 3}
    for m in re.finditer(r"\bOPEN\b([^.]*)", plain):
        mode = None
        for token in m.group(1).replace(",", " ").split():
            if token in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = {"INPUT": "read", "OUTPUT": "write", "I-O": "update", "EXTEND": "write"}[token]
            elif token in by_name and mode and rank[mode] > rank[by_name[token]["access"]]:
                by_name[token]["access"] = mode
    return files


def _paragraphs(src, plain):
    start = re.search(r"\bPROCEDURE\s+DIVISION\b[^.]*\.", plain)
    if not start:
        return [], None
    paragraphs = []
    offset = start.end()
    lines = plain[offset:].split("\n")
    # Area A labels have at most 3 leading spaces in fixed format. Free format may indent freely.
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    free_indent = bool(indents) and min(indents) >= 4
    position = offset
    for line in lines:
        m = _plain_re.match(r"^(\s*)(" + WORD + r")(\s+SECTION)?\s*\.(?:\s|$)", line)
        if m and m.group(2) not in _RESERVED_LABELS and (free_indent or len(m.group(1)) < 4):
            paragraphs.append({
                "name": m.group(2), "is_section": bool(m.group(3)),
                "start_line": src.line_at(position + len(m.group(1))), "end_line": None,
            })
        position += len(line) + 1
    return paragraphs, start.end()


def _hazards(src, calls, nested):
    found = []
    for name, pattern in _COMPILED_HAZARDS:
        for m in pattern.finditer(src.masked):
            found.append({"type": name, "line": src.line_at(m.start() + len(m.group(0)) - len(m.group(0).lstrip()))})
    for call in calls:
        if call["target"] in ABEND_ROUTINES:
            found.append({"type": "abend", "line": call["line"]})
        elif call["target"] in CHECKPOINT_ROUTINES:
            found.append({"type": "checkpoint", "line": call["line"]})
    for line in nested:
        found.append({"type": "nested_program", "line": line})
    return sorted(found, key=lambda h: (h["line"], h["type"]))


def _control_flow(src, plain, proc_start, enclosing):
    performs, gotos = [], []
    if proc_start is None:
        return performs, gotos
    body = plain[proc_start:]
    for m in re.finditer(r"\bPERFORM\s+(?!UNTIL\b|VARYING\b|WITH\b|TEST\b|FOREVER\b|\d+\s+TIMES)(" + WORD + r")\b(?!\s+TIMES\b)(?:\s+(?:THRU|THROUGH)\s+(" + WORD + r"))?", body):
        line = src.line_at(proc_start + m.start())
        performs.append({"from": enclosing(line), "target": m.group(1), "thru": m.group(2), "line": line})
    for m in re.finditer(r"\b(?:INPUT|OUTPUT)\s+PROCEDURE\s+(?:IS\s+)?(" + WORD + r")(?:\s+(?:THRU|THROUGH)\s+(" + WORD + r"))?", body):
        line = src.line_at(proc_start + m.start())
        performs.append({"from": enclosing(line), "target": m.group(1), "thru": m.group(2), "line": line})
    for m in re.finditer(r"\bGO\s+(?:TO\s+)?((?:" + WORD + r"\s+)+)DEPENDING\b|\bGO\s+(?:TO\s+)?(" + WORD + r")", body):
        line = src.line_at(proc_start + m.start())
        for target in (m.group(1).split() if m.group(1) else [m.group(2)]):
            gotos.append({"from": enclosing(line), "target": target, "line": line})
    return performs, gotos


def parse_cobol(text):
    src = logical_source(text)
    plain = _without_exec_blocks(src.masked)
    cache = {"__plain__": plain}
    unrecognized = []
    technologies = set()
    names, nested = [], []
    for pid in re.finditer(r"\bPROGRAM-ID\s*\.?\s*(" + LITERAL + r"|" + WORD + r")", src.masked):
        token = pid.group(1)
        names.append(ascii_upper(_strip_literal(src.text[pid.start(1):pid.end(1)]) or "") if token[0] in "'\"" else token)
        if len(names) > 1:
            nested.append(src.line_at(pid.start()))
    other_names = names[1:]
    for m in re.finditer(r"\bENTRY\s+(" + LITERAL + r")", plain):
        other_names.append(ascii_upper(_strip_literal(src.text[m.start(1):m.end(1)]) or ""))
    for m in re.finditer(r"\bEXEC\s+(?!CICS\b|SQL\b)([A-Z0-9]+)\b(.*?)\bEND-EXEC\b", src.masked, re.S):
        unrecognized.append(" ".join(("EXEC " + m.group(1) + m.group(2)).split()))
        technologies.add("ims" if m.group(1) in ("DLI", "SQLIMS") else m.group(1).lower())
    calls = _calls(src, plain, cache)
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
    paragraphs, proc_start = _paragraphs(src, plain)
    last_line = src.line_at(len(src.text))
    for i, para in enumerate(paragraphs):
        para["end_line"] = paragraphs[i + 1]["start_line"] - 1 if i + 1 < len(paragraphs) else last_line

    def enclosing(line):
        for para in reversed(paragraphs):
            if para["start_line"] <= line:
                return para["name"]
        return None

    performs, gotos = _control_flow(src, plain, proc_start, enclosing)
    procedure = plain[proc_start:] if proc_start is not None else ""
    decisions = sum(len(re.findall(rx, procedure)) for rx in (r"\bIF\b", r"\bEVALUATE\b", r"\bWHEN\b", r"\bUNTIL\b"))
    return {
        "program_id": names[0] if names else None,
        "other_names": sorted(set(other_names)),
        "copies": _find_includes(text, src),
        "calls": calls,
        "cics": cics,
        "sql": sql,
        "files": _files(src, plain),
        "paragraphs": paragraphs,
        "performs": performs,
        "gotos": gotos,
        "hazards": _hazards(src, calls, nested),
        "unrecognized": unrecognized,
        "technologies": sorted(technologies),
        "metrics": {"lines": len(split_lines(text)), "decisions": decisions},
    }
