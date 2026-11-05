"""Stage 1: catalogue every source member, reusing parsed results for unchanged files."""
import concurrent.futures
import concurrent.futures.process
import hashlib
import os
import re
import time

from .cobol import constants_table, parse_cobol
from .config import SKIP_DIRS, ConfigError, read_json, write_json, write_text
from .definitions import parse_definitions
from .jcl import parse_jcl
from .masking import mask_statement
from .sourcefile import EXTENSION_KINDS, ascii_upper, classify, decode_bytes, split_lines

PARSER_VERSION = 7
PROGRAM_KINDS = {"cobol_program", "assembler", "pli", "rexx", "easytrieve"}
GROUPS = {
    "cobol_program": "program", "assembler": "program", "pli": "program", "rexx": "program", "easytrieve": "program",
    "copybook": "copybook", "jcl_job": "job", "jcl_proc": "proc", "bms": "mapset", "control_card": "control",
}
PARALLEL_THRESHOLD = 200
MAX_WORKERS = 61  # the limit for process pools on Windows
SOURCE_EXTENSIONS = set(EXTENSION_KINDS) | {".txt", ".dat", ".src", ".mem", ".dcl", ".cblle", ".lst"}


def member_name(path):
    """The member name from a file name: ABC.cbl, PROD.COBOL.ABC, PROD.COBOL.ABC.cbl and LIB(ABC) all give ABC."""
    base = os.path.basename(path)
    in_library = re.search(r"\(([^()]+)\)$", base)
    if in_library:
        return in_library.group(1).upper()
    parts = base.split(".")
    if len(parts) > 1 and "." + parts[-1].lower() in SOURCE_EXTENSIONS:
        parts = parts[:-1]
    return parts[-1].upper()


def parse_text(kind, text):
    if kind == "cobol_program":
        return parse_cobol(text)
    if kind == "copybook":
        facts = parse_cobol(text)
        facts["dclgen_tables"] = sorted(set(re.findall(r"EXEC\s+SQL\s+DECLARE\s+(?:[A-Z0-9_#@$]+\.)?([A-Z0-9_#@$]+)\s+TABLE", ascii_upper(text))))
        facts["constants"] = constants_table(text)
        return facts
    if kind in ("jcl_job", "jcl_proc"):
        return parse_jcl(text)
    if kind in ("csd", "bms", "ddl", "idcams", "scheduler"):
        return parse_definitions(text, kind)
    return {}


def _analyze(job):
    """Runs in a worker process and reads its own file, so the parent never holds the whole system in memory."""
    full, name, sha, code_page, record_length = job
    try:
        with open(full, "rb") as f:
            decoded = decode_bytes(f.read(), code_page, record_length)
        if not decoded.ok:
            return sha, {"kind": "undecodable", "encoding": None, "line_count": 0, "facts": {}}
        kind = classify(decoded.text, name)
        return sha, {"kind": kind, "encoding": decoded.encoding, "line_count": len(split_lines(decoded.text)), "facts": parse_text(kind, decoded.text), "parse_error": False}
    except Exception as exc:  # one unparseable member must not stop a run over the whole system
        return sha, {"kind": "unknown", "encoding": None, "line_count": 0, "facts": {}, "parse_error": type(exc).__name__}


def _walk(ws, skipped):
    ignored = set(ws.config["ignore_extensions"])
    for source in ws.source_paths():
        for root, dirs, files in os.walk(source):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                extension = os.path.splitext(name)[1].lower()
                if name.startswith("."):
                    continue
                if extension in ignored:
                    skipped[extension] = skipped.get(extension, 0) + 1
                    continue
                yield os.path.join(root, name), name


def _cache_path(ws, sha):
    return ws.path("inventory", "cache", "%s-%d-%s-%d.json" % (sha[:40], PARSER_VERSION, ws.config["code_page"], ws.config["record_length"]))


def _select_duplicates(ws, entries):
    """One member per name. Differing copies with no precedence rule stay unresolved."""
    groups = {}
    for entry in entries:
        group = GROUPS.get(entry["kind"])
        if group:
            groups.setdefault((group, entry["name"]), []).append(entry)
    duplicates = []
    for (group, name), items in sorted(groups.items()):
        distinct = {e["sha"] for e in items}
        for entry in items:
            entry["selected"] = False
        if len(distinct) == 1:
            items[0]["selected"] = True
            continue
        chosen = None
        for marker in ws.config["library_precedence"]:
            hits = [e for e in items if marker in e["path"]]
            if hits:
                chosen = hits[0]
                break
        if chosen:
            chosen["selected"] = True
            continue
        items[0]["selected"] = True
        for entry in items:
            entry["ambiguous"] = True
        duplicates.append({"group": group, "name": name, "paths": [e["path"] for e in items]})
    return duplicates


def run_inventory(ws):
    started = time.time()
    entries, jobs, results = [], [], {}
    cached = 0
    max_bytes = ws.config["max_file_mb"] * 1024 * 1024
    skipped = {}
    for full, name in _walk(ws, skipped):
        relative = ws.rel(full)
        try:
            size = os.path.getsize(full)
            if size > max_bytes:
                entries.append({"name": member_name(name), "path": relative, "sha": "size-%d" % size, "kind": "unknown",
                                "encoding": None, "line_count": 0, "reason": "too_large"})
                continue
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            entries.append({"name": member_name(name), "path": relative, "sha": "unreadable", "kind": "undecodable",
                            "encoding": None, "line_count": 0, "reason": "unreadable"})
            continue
        sha = hashlib.sha256(data).hexdigest()
        entries.append({"name": member_name(name), "path": relative, "sha": sha})
        if sha in results:
            continue
        saved = read_json(_cache_path(ws, sha))
        if saved is not None:
            results[sha] = saved
            cached += 1
        else:
            results[sha] = None
            jobs.append((full, name, sha, ws.config["code_page"], ws.config["record_length"]))
    if not entries:
        raise ConfigError(
            "I didn't find any files in %s. Check that the folder holds the mainframe code, then run it again."
            % ", ".join(ws.config["source_roots"]))
    workers = min(ws.config["jobs"] or (os.cpu_count() or 1), MAX_WORKERS)
    if len(jobs) >= PARALLEL_THRESHOLD and workers > 1:
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
                analyzed = list(pool.map(_analyze, jobs, chunksize=64))
        except (OSError, RuntimeError, concurrent.futures.process.BrokenProcessPool):
            analyzed = [_analyze(job) for job in jobs]
    else:
        analyzed = [_analyze(job) for job in jobs]
    for sha, result in analyzed:
        results[sha] = result
        if not result.get("parse_error"):
            write_json(_cache_path(ws, sha), result)
    for entry in entries:
        result = results.get(entry["sha"])
        if result is None:
            continue
        entry.update(kind=result["kind"], encoding=result["encoding"], line_count=result["line_count"])
        if result.get("parse_error"):
            entry["parse_error"] = True
        program_id = result["facts"].get("program_id") if result["kind"] == "cobol_program" else None
        if program_id:
            entry["program_id"] = program_id
        if result["kind"] == "cobol_program" and result["facts"].get("other_names"):
            entry["other_names"] = result["facts"]["other_names"]
    entries.sort(key=lambda e: e["path"])
    _reclassify_copied(entries, results)
    duplicates = _select_duplicates(ws, entries)
    write_json(ws.path("inventory", "catalogue.json"), {"members": entries, "duplicates": duplicates, "skipped": skipped})
    counts = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    _write_summary(ws, entries, counts, duplicates, skipped)
    _log_coverage(ws, entries, counts, results, started, len(jobs), cached)
    return {"file_counts": counts, "total_files": len(entries), "cached_files": cached, "parsed_files": len(jobs), "duplicates": len(duplicates)}


def _reclassify_copied(entries, results):
    """A file programs COPY is a copybook, even if nothing in it looked like one."""
    copied = set()
    for result in results.values():
        if result and result["kind"] in ("cobol_program", "copybook"):
            copied.update(c["name"] for c in result["facts"].get("copies", []))
    for entry in entries:
        if entry.get("kind") == "unknown" and entry["name"] in copied and not entry.get("parse_error") and not entry.get("reason"):
            entry["kind"] = "copybook"


def _write_summary(ws, entries, counts, duplicates, skipped):
    lines = ["# Source inventory", "", "| Kind | Files |", "|------|-------|"]
    lines += ["| %s | %d |" % (k, counts[k]) for k in sorted(counts)]
    lines += ["", "Total files: %d" % len(entries), "Total lines: %d" % sum(e["line_count"] for e in entries)]
    if duplicates:
        lines += ["", "Members with differing copies: %d (see the gaps list)" % len(duplicates)]
    if skipped:
        lines += ["", "Skipped by file type (see `ignore_extensions`): " + ", ".join("%s: %d" % (k, skipped[k]) for k in sorted(skipped))]
    write_text(ws.path("inventory", "summary.md"), "\n".join(lines) + "\n")


def _log_coverage(ws, entries, counts, results, started, parsed, cached):
    encodings = {}
    patterns = {}
    for entry in entries:
        encoding = entry["encoding"]
        if encoding:
            bucket = encoding if encoding in ("utf-8", "latin-1") else "ebcdic"
            encodings[bucket] = encodings.get(bucket, 0) + 1
    programs_parsed = 0
    for entry in entries:
        result = results.get(entry["sha"])
        if entry["kind"] == "cobol_program" and result and not result.get("parse_error"):
            programs_parsed += 1
        if result:
            for statement in result["facts"].get("unrecognized", []):
                key = (entry["kind"], mask_statement(statement))
                patterns[key] = patterns.get(key, 0) + 1
    total_unrecognized = sum(patterns.values())
    ws.logger.event(
        "coverage", file_counts=counts, encodings=encodings, unrecognized_count=total_unrecognized,
        programs=counts.get("cobol_program", 0), programs_parsed=programs_parsed, total_files=len(entries))
    for (kind, pattern), count in sorted(patterns.items()):
        ws.logger.event("unrecognized", source_kind=kind, pattern=pattern, count=count)
    ws.logger.event("script_run", command="inventory", duration_ms=int((time.time() - started) * 1000), result="ok",
                    files_processed=parsed + cached, cached_files=cached)


def load_catalogue(ws):
    data = read_json(ws.path("inventory", "catalogue.json"))
    if data is None:
        raise ConfigError("There's no inventory yet. Run: python mma.py inventory")
    return data["members"]


def load_duplicates(ws):
    return read_json(ws.path("inventory", "catalogue.json"), {"duplicates": []})["duplicates"]


def load_facts(ws, entry):
    """Parsed facts for one member, reparsing if another developer's checkout has no cache."""
    if entry.get("parse_error"):
        return {}
    saved = read_json(_cache_path(ws, entry["sha"]))
    if saved is None:
        full = ws.abs(entry["path"])
        _, saved = _analyze((full, os.path.basename(full), entry["sha"], ws.config["code_page"], ws.config["record_length"]))
        if not saved.get("parse_error"):
            write_json(_cache_path(ws, entry["sha"]), saved)
    if entry["kind"] == "copybook" and saved["kind"] != "copybook":
        return parse_text("copybook", read_member_text(ws, entry))
    return saved["facts"]


def read_member_text(ws, entry):
    with open(ws.abs(entry["path"]), "rb") as f:
        return decode_bytes(f.read(), ws.config["code_page"], ws.config["record_length"]).text

