"""Privacy-safe logs. A field is written only if the allowlist below permits its value.

Never add a field here that can carry source text, business rules, people's names,
data values or paths. Names go through `Logger.name_hash`.
"""
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import secrets
import sys
import traceback
import zipfile

from .masking import is_masked

FILE_KINDS = {
    "cobol_program", "copybook", "jcl_job", "jcl_proc", "bms", "csd", "ddl", "idcams", "control_card", "assembler",
    "pli", "rexx", "easytrieve", "ims_def", "scheduler", "unknown", "undecodable",
}
GAP_KINDS = {
    "missing_copybook", "missing_program", "missing_proc", "missing_bms_map", "missing_db2_ddl", "missing_vsam_def",
    "missing_cics_def", "missing_control_card", "missing_schedule", "dynamic_reference", "unsupported_technology",
    "undecodable_files", "unrecognized_files", "duplicate_member", "sme_question",
}
OWNERS = {"mainframe_team", "sme"}
STATUSES = {"confirmed_code", "inferred", "confirmed_sme", "ask_expert", "conflict"}
COMMANDS = {
    "init", "preflight", "inventory", "map", "slices", "flow", "facts", "source", "datadict", "plan", "gaps", "gap",
    "record", "validate", "render", "status", "stale", "impact", "log", "feedback", "logs", "slice", "analysis",
    "summary", "scan", "mapping", "usage", "uncaught",
}
STAGES = {"inventory", "map", "slicing", "deep_analysis", "requirements", "data", "tests", "mapping", "gaps", "planning"}
PROMPTS = {
    "inventory", "orient", "explain_flow", "explain_program", "requirements", "data", "test_scenarios", "mapping",
    "gaps", "requests", "take_in_answers", "planning", "other",
}
FEEDBACK_CATEGORIES = {"wrong_result", "missed_something", "too_long", "too_technical", "crash", "install", "other"}
SCHEMA_VERSION = 1


def _enum(*groups):
    allowed = set().union(*groups)
    return lambda v: isinstance(v, str) and v in allowed


def _matches(pattern):
    compiled = re.compile(pattern)
    return lambda v: isinstance(v, str) and compiled.fullmatch(v) is not None


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _boolean(v):
    return isinstance(v, bool)


def _counts(allowed):
    return lambda v: isinstance(v, dict) and all(k in allowed and _number(n) for k, n in v.items())


_HASH = _matches(r"n_[0-9a-f]{12}")
_COMMAND = _enum(COMMANDS)

COMMON = {
    "type": _enum({"environment", "script_run", "error", "coverage", "unrecognized", "gaps", "activity", "validation", "export"}),
    "ts": _matches(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"),
    "run": _matches(r"[0-9a-f]{8}"),
    "schema_version": _number,
    "skill_version": _matches(r"\d+\.\d+\.\d+|unknown"),
}
SCHEMA = {
    "environment": {
        "python_version": _matches(r"\d+\.\d+\.\d+"),
        "os": _enum({"darwin", "linux", "windows", "other"}),
        "surface": _enum({"vscode", "copilot_cli", "manual", "unknown"}),
    },
    "script_run": {
        "command": _COMMAND, "duration_ms": _number, "result": _enum({"ok", "error", "blocked"}),
        "files_processed": _number, "cached_files": _number,
    },
    "error": {
        "command": _COMMAND, "error_type": _matches(r"[A-Z][A-Za-z0-9]*"),
        "skill_file": _matches(r"[a-z_]+\.py"), "skill_line": _number,
    },
    "coverage": {
        "file_counts": _counts(FILE_KINDS), "encodings": _counts({"utf-8", "latin-1", "ebcdic"}),
        "unrecognized_count": _number, "programs": _number, "programs_parsed": _number, "total_files": _number,
        "edges": _number,
    },
    "unrecognized": {"source_kind": _enum(FILE_KINDS), "pattern": is_masked, "count": _number},
    "gaps": {"by_kind": _counts(GAP_KINDS), "by_owner": _counts(OWNERS), "open": _number, "resolved": _number},
    "activity": {
        "activity": _enum({"stage_started", "stage_finished", "reference_used", "output_incomplete"}),
        "stage": _enum(STAGES), "prompt_category": _enum(PROMPTS),
        "reference": _matches(r"references/[a-z0-9_-]+\.md"), "item": _HASH, "surface": _enum({"vscode", "copilot_cli", "manual", "unknown"}),
    },
    "validation": {"issues": _number, "by_status": _counts(STATUSES), "rules": _number, "requirements": _number, "tests": _number},
    "export": {"events": _number, "dropped": _number, "included_feedback": _boolean},
}


class LogFieldRejected(ValueError):
    """A log call tried to write something the allowlist does not permit."""


def skill_version():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VERSION")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def validate_event(event):
    if not isinstance(event, dict) or not COMMON["type"](event.get("type")):
        return False
    allowed = SCHEMA[event["type"]]
    for key, value in event.items():
        check = COMMON.get(key) or allowed.get(key)
        if check is None or not check(value):
            return False
    return True


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Logger:
    def __init__(self, outdir):
        self.outdir = outdir
        self.run = secrets.token_hex(4)
        self.path = os.path.join(outdir, "logs", "events-%s-%s.jsonl" % (_now()[:10].replace("-", ""), self.run))
        self._salt = None

    def _load_salt(self):
        path = os.path.join(self.outdir, ".salt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        salt = secrets.token_hex(16)
        os.makedirs(self.outdir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(salt + "\n")
        return salt

    def name_hash(self, name):
        if self._salt is None:
            self._salt = self._load_salt()
        digest = hashlib.sha256((self._salt + ":" + name.upper()).encode()).hexdigest()
        return "n_" + digest[:12]

    def event(self, event_type, **fields):
        """Write one event. Rejected content raises. A disk problem never stops the real work."""
        event = dict(type=event_type, ts=_now(), run=self.run, schema_version=SCHEMA_VERSION, skill_version=skill_version())
        event.update(fields)
        if not validate_event(event):
            raise LogFieldRejected("log event refused by the allowlist: %s" % event_type)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError:
            pass

    def exception(self, command, exc):
        """Record where a failure happened in the skill. The message is dropped: it can hold paths or names."""
        skill_dir = os.path.dirname(os.path.abspath(__file__))
        skill_file, skill_line = "unknown.py", 0
        for frame in traceback.extract_tb(exc.__traceback__):
            if os.path.dirname(os.path.abspath(frame.filename)) == skill_dir:
                skill_file, skill_line = os.path.basename(frame.filename), frame.lineno
        self.event("error", command=command, error_type=type(exc).__name__, skill_file=skill_file, skill_line=skill_line)

    def environment(self, surface="unknown"):
        system = platform.system().lower()
        self.event("environment", python_version=".".join(str(n) for n in sys.version_info[:3]),
                   os=system if system in ("darwin", "linux", "windows") else "other", surface=surface)


def add_feedback(outdir, rating, category, text):
    """Feedback text is free-form, so it stays separate and is only exported after confirmation."""
    if category not in FEEDBACK_CATEGORIES:
        raise LogFieldRejected("unknown feedback category")
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise LogFieldRejected("rating must be 1 to 5")
    os.makedirs(os.path.join(outdir, "logs"), exist_ok=True)
    with open(os.path.join(outdir, "logs", "feedback.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), "rating": rating, "category": category, "text": text, "skill_version": skill_version()}, sort_keys=True) + "\n")


def _read_events(outdir):
    kept, dropped = [], 0
    for path in sorted(glob.glob(os.path.join(outdir, "logs", "events-*.jsonl"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except ValueError:
                    dropped += 1
                    continue
                if validate_event(event):
                    kept.append(event)
                else:
                    dropped += 1
    kept.sort(key=lambda e: (e["ts"], e["run"]))
    return kept, dropped


def _preview(events, dropped, feedback_lines, included):
    by_type = {}
    for event in events:
        by_type[event["type"]] = by_type.get(event["type"], 0) + 1
    lines = [
        "# Log export preview", "",
        "This is everything in the zip. Review it before sending it to the skill's maintainer. Nothing is sent automatically.", "",
        "- Events: %d" % len(events),
        "- Lines dropped by the privacy check: %d" % dropped,
        "- Feedback text included: %s" % ("yes" if included else "no"), "",
    ]
    lines += ["- `%s`: %d" % (k, by_type[k]) for k in sorted(by_type)]
    lines += ["", "## Events", "", "```json"] + [json.dumps(e, sort_keys=True) for e in events] + ["```"]
    if included:
        lines += ["", "## Feedback (free text: check for names and sensitive details)", "", "```json"] + feedback_lines + ["```"]
    return "\n".join(lines) + "\n"


def export_logs(outdir, include_feedback=False):
    events, dropped = _read_events(outdir)
    feedback_lines = []
    feedback_path = os.path.join(outdir, "logs", "feedback.jsonl")
    if include_feedback and os.path.exists(feedback_path):
        with open(feedback_path, encoding="utf-8") as f:
            feedback_lines = [l.rstrip("\n") for l in f if l.strip()]
    target = os.path.join(outdir, "logs-export")
    os.makedirs(target, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(target, "mma-logs-%s.zip" % stamp)
    preview_path = os.path.join(target, "mma-logs-%s-preview.md" % stamp)
    preview = _preview(events, dropped, feedback_lines, include_feedback)
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(preview)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("events.jsonl", "".join(json.dumps(e, sort_keys=True) + "\n" for e in events))
        z.writestr("preview.md", preview)
        if include_feedback:
            z.writestr("feedback.jsonl", "".join(l + "\n" for l in feedback_lines))
    return {"zip": zip_path, "preview": preview_path, "events": len(events), "dropped": dropped}
