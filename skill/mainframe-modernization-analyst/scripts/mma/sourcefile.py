"""Read mainframe source: decode bytes, classify by content, normalize COBOL."""
import bisect
import os
import re
from collections import namedtuple

DecodeResult = namedtuple("DecodeResult", "ok text encoding reason")

_ASCII_UPPER = {c: c - 32 for c in range(ord("a"), ord("z") + 1)}
_LINE_SPLIT = re.compile(r"\r\n|\n|\r")

EXTENSION_KINDS = {
    ".cbl": "cobol_program", ".cob": "cobol_program", ".cobol": "cobol_program",
    ".cpy": "copybook", ".copy": "copybook", ".jcl": "jcl_job", ".prc": "jcl_proc",
    ".proc": "jcl_proc", ".bms": "bms", ".ddl": "ddl", ".ctl": "control_card",
    ".asm": "assembler", ".mac": "assembler", ".rexx": "rexx", ".pli": "pli",
    ".ca7": "scheduler", ".controlm": "scheduler", ".csd": "csd",
}


class cobol_regex:
    """`re` with word boundaries that treat COBOL's hyphen as part of a word.

    Plain `\\b` would find CALL inside WS-CALL. Use on `LogicalSource.masked` text.
    """

    S, M = re.S, re.M
    _BOUNDARY = r"(?:(?<![A-Z0-9_#@$-])(?=[A-Z0-9_#@$-])|(?<=[A-Z0-9_#@$-])(?![A-Z0-9_#@$-]))"
    _cache = {}
    escape = staticmethod(re.escape)

    @classmethod
    def compile(cls, pattern, flags=0):
        key = (pattern, flags)
        if key not in cls._cache:
            cls._cache[key] = re.compile(pattern.replace(r"\b", cls._BOUNDARY), flags)
        return cls._cache[key]

    @classmethod
    def finditer(cls, pattern, text, flags=0):
        return cls.compile(pattern, flags).finditer(text)

    @classmethod
    def search(cls, pattern, text, flags=0):
        return cls.compile(pattern, flags).search(text)

    @classmethod
    def match(cls, pattern, text, flags=0):
        return cls.compile(pattern, flags).match(text)

    @classmethod
    def findall(cls, pattern, text, flags=0):
        return cls.compile(pattern, flags).findall(text)

    @staticmethod
    def sub(pattern, repl, text):
        return re.sub(pattern, repl, text)


def ascii_upper(text):
    """Uppercase ASCII only, so that string offsets never shift."""
    return text.translate(_ASCII_UPPER)


def split_lines(text):
    """Split on real line endings only, keeping line numbers true to the file."""
    lines = _LINE_SPLIT.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _printable_ratio(text):
    if not text:
        return 1.0
    good = sum(1 for c in text if c.isprintable() or c in "\r\n\t\f\x85")
    return good / len(text)


def decode_bytes(data, code_page="cp037", record_length=80):
    if not data:
        return DecodeResult(True, "", "utf-8", None)
    if b"\x00" not in data:
        try:
            text = data.decode("utf-8-sig")
            if _printable_ratio(text) >= 0.95:
                return DecodeResult(True, text, "utf-8", None)
        except UnicodeDecodeError:
            pass
    if data.count(0x40) > data.count(0x20):
        text = data.decode(code_page, errors="replace").replace("\x85", "\n")
        if _printable_ratio(text) >= 0.9:
            if "\n" not in text and len(text) > record_length:
                text = "\n".join(text[i:i + record_length] for i in range(0, len(text), record_length))
            return DecodeResult(True, text, code_page, None)
    if b"\x00" not in data:
        text = data.decode("latin-1")
        if _printable_ratio(text.replace("\x85", "")) >= 0.95 and data.count(0x20) > 0:
            return DecodeResult(True, text, "latin-1", None)
    return DecodeResult(False, "", None, "binary")


_LEVEL_LINE = re.compile(
    r"^(?:.{6}[ ])?\s*\d{1,2}\s+[A-Z0-9:_-]+\s*(?:PIC\b|PICTURE\b|VALUE\b|REDEFINES\b|OCCURS\b|COMP|USAGE\b|\.)", re.M)
_RULES = [
    ("bms", re.compile(r"\bDFHM(?:SD|DI)\b")),
    ("cobol_program", re.compile(r"\bPROGRAM-ID\b|\bIDENTIFICATION\s+DIVISION\b|^\s*\S{0,6}\s*ID\s+DIVISION\b", re.M)),
    ("csd", re.compile(r"\bDEFINE\s+(?:TRANS(?:ACTION)?|PROG(?:RAM)?|FILE|MAPSET|TDQUEUE|TSMODEL|PROFILE|DB2CONN|DB2ENTRY)\s*\(")),
    ("idcams", re.compile(r"\bDEFINE\s+(?:CLUSTER|ALTERNATEINDEX|AIX|PATH|GDG|NONVSAM)\b|\bREPRO\s")),
    ("ims_def", re.compile(r"\b(?:PSBGEN|DBDGEN)\b")),
    ("pli", re.compile(r"\bPROCEDURE\s+OPTIONS\s*\(")),
    ("assembler", re.compile(r"^\S*\s+(?:CSECT|DSECT|AMODE|RMODE)\b|^\s+MACRO\s*$", re.M)),
    ("easytrieve", re.compile(r"^\s*JOB\s+INPUT\b", re.M)),
    ("copybook", re.compile(r"\bEXEC\s+SQL\s+DECLARE\s+\S+\s+TABLE\b")),
    ("ddl", re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|VIEW|TABLESPACE)\b", re.M)),
    ("copybook", _LEVEL_LINE),
    ("control_card", re.compile(r"^\s*(?:SORT|MERGE)\s+FIELDS\s*=|^\s*(?:INCLUDE|OMIT)\s+COND\s*=|^\s*(?:INREC|OUTREC)\s+", re.M)),
    ("scheduler", re.compile(r"\bDEFTABLE\b|<JOB\s")),
]


def _without_comments(upper):
    """Comments must never decide what a file is."""
    kept = []
    for line in split_lines(upper):
        if line.startswith(("//*", "*")):
            continue
        if not line.startswith("//") and len(line) > 6 and line[6] in "*/":
            continue
        kept.append(line)
    return kept


def classify(text, name=""):
    upper = ascii_upper(text)
    if re.match(r"\A\s*/\*.*REXX", upper):
        return "rexx"
    lines = _without_comments(upper)
    significant = [l for l in lines if l.strip() and not l.startswith("/*")]
    body = "\n".join(lines)
    if significant and significant[0].startswith("//"):
        return "jcl_job" if re.search(r"^//\S*\s+JOB\b", body, re.M) else "jcl_proc"
    for kind, pattern in _RULES:
        if pattern.search(body):
            return kind
    return EXTENSION_KINDS.get(os.path.splitext(name)[1].lower(), "unknown")


def _scan_line(code, open_quote):
    """Return (code without inline comment, quote still open at the end of the line)."""
    i, quote = 0, open_quote
    while i < len(code):
        ch = code[i]
        if quote:
            if ch == quote:
                if i + 1 < len(code) and code[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch
        elif code.startswith("*>", i):
            return code[:i].rstrip(), None
        i += 1
    return code, quote


def _is_fixed(lines):
    good = total = 0
    for line in lines:
        if not line.strip():
            continue
        if ">>SOURCE" in ascii_upper(line) and "FREE" in ascii_upper(line):
            return False
        total += 1
        if len(line) < 7:
            good += 1 if line.strip().isalnum() and len(line.strip()) <= 6 and line.strip().isdigit() else 0
        elif line[6] in " *-/dD$":
            good += 1
    return total == 0 or good / total >= 0.95


def _code_lines(text):
    lines = [l.expandtabs(8) for l in split_lines(text)]
    if _is_fixed(lines):
        for number, line in enumerate(lines, 1):
            if len(line) < 7:
                continue
            indicator = line[6]
            if indicator in "*/dD$":
                continue
            yield number, line[7:72].rstrip(), indicator == "-"
    else:
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("*") or stripped.startswith(">>"):
                continue
            if stripped.startswith("-"):
                yield number, stripped[1:], True
            else:
                yield number, line.rstrip(), False


def _mask(text):
    out = []
    quote = None
    for ch in text:
        if quote:
            if ch == "\n":
                quote = None
                out.append(ch)
            elif ch == quote:
                quote = None
                out.append(ch)
            else:
                out.append("_")
        else:
            if ch in "'\"":
                quote = ch
            out.append(ch)
    return ascii_upper("".join(out))


class LogicalSource:
    """COBOL code with comments removed. `masked` and `text` share offsets."""

    def __init__(self, text, starts, numbers):
        self.text = text
        self.masked = _mask(text)
        self._starts = starts
        self._numbers = numbers

    def line_at(self, offset):
        if not self._starts:
            return 0
        return self._numbers[max(0, bisect.bisect_right(self._starts, offset) - 1)]


def logical_source(text):
    parts, starts, numbers = [], [], []
    offset = 0
    quote = None
    for number, code, continued in _code_lines(text):
        if continued and parts:
            piece = code.lstrip()
            if quote and piece.startswith(quote):
                piece = piece[1:]
                start_quote = quote
            else:
                start_quote = None
            parts[-1] = parts[-1][:-1]
            offset -= 1
            code, quote = _scan_line(piece, start_quote)
        else:
            code, quote = _scan_line(code, None)
        starts.append(offset)
        numbers.append(number)
        parts.append(code + "\n")
        offset += len(code) + 1
    return LogicalSource("".join(parts), starts, numbers)
