"""Command line for the skill. Works the same from Copilot or by hand in a terminal."""
import argparse
import json
import os
import shutil
import sys
import time
import traceback

from . import preflight as preflight_module
from .config import ConfigError, Workspace, init_workspace
from .datadict import write_datadict
from .depmap import build_map
from .facts import program_facts, read_source
from .flows import write_flow
from .gaps import RecordError, add_sme_question, answer_gap, detect_gaps, load_gaps, resolve_conflict, top_gaps, withdraw_question
from .inventory import run_inventory
from .logs import LogFieldRejected, Logger, add_feedback, export_logs
from .planning import write_mapping, write_plan
from .records import add_record, delete_record, impact, record_analysis, stale, status, validate
from .render import render_all
from .slices import build_slices, load_slices, name_slice

ROOT_DIR = "."
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ws():
    return Workspace.load(ROOT_DIR)


def _gap_line(gap):
    owner = "SME" if gap["owner"] == "sme" else "Mainframe team"
    detail = gap["name"] if gap["kind"] == "sme_question" else "%s: %s" % (gap["name"], gap["what"])
    return "%s [%s, %s, %s] %s (blocks %d)" % (gap["id"], gap["status"], gap["urgency"], owner, detail, len(gap["blocks"]))


def _print_top(ws, limit=5):
    gaps = top_gaps(ws, limit)
    total = sum(1 for g in load_gaps(ws) if g["status"] in ("open", "conflict"))
    print("\nOpen items: %d. Most important first:" % total)
    for gap in gaps:
        print("  " + _gap_line(gap))


def _copy_glossary(ws):
    source = os.path.join(SKILL_DIR, "references", "glossary.md")
    if os.path.exists(source):
        shutil.copyfile(source, ws.path("glossary.md"))


def cmd_init(args):
    ws = init_workspace(ROOT_DIR, args.source, args.code_page, args.record_length, False if args.no_quotes else None)
    ws.logger.environment(os.environ.get("MMA_SURFACE", "manual"))
    print("Set up. Results will be saved in %s" % ws.out)
    print("Next: python mma.py scan")


def cmd_preflight(args):
    return preflight_module.run(ROOT_DIR, args.source)


def cmd_scan(_):
    ws = _ws()
    inventory = run_inventory(ws)
    print("Files found:")
    for kind in sorted(inventory["file_counts"]):
        print("  %s: %d" % (kind, inventory["file_counts"][kind]))
    print("Reused %d unchanged files, parsed %d." % (inventory["cached_files"], inventory["parsed_files"]))
    mapped = build_map(ws)
    print("Links found: %d. Referenced but not found: %d. Decided at runtime and unresolved: %d." % (mapped["edges"], mapped["missing"], mapped["dynamic"]))
    detect_gaps(ws)
    result = build_slices(ws)
    print("Slices proposed: %d. Shared programs: %d. Programs with no known entry point: %d." % (len(result["slices"]), len(result["shared_programs"]), len(result["unassigned"])))
    write_plan(ws)
    render_all(ws)
    _copy_glossary(ws)
    _print_top(ws)
    print("\nSaved to %s" % ws.out)


def cmd_inventory(_):
    ws = _ws()
    print(json.dumps(run_inventory(ws), indent=1, sort_keys=True))


def cmd_map(_):
    ws = _ws()
    print(json.dumps(build_map(ws), indent=1, sort_keys=True))
    detect_gaps(ws)


def cmd_slices(_):
    result = build_slices(_ws())
    for item in result["slices"]:
        print("%s %s: %d entries, %d programs" % (item["id"], item["business_name"] or "(to be named)", len(item["entries"]), len(item["programs"])))


def cmd_slice_name(args):
    name_slice(_ws(), args.slice, args.business_name)
    print("Named %s." % args.slice)


def cmd_summary(_):
    ws = _ws()
    with open(ws.path("inventory", "summary.md"), encoding="utf-8") as f:
        print(f.read())
    slices = load_slices(ws)
    print("Slices: %d" % len(slices["slices"]))
    for item in slices["slices"][:30]:
        print("  %s %s: %d programs" % (item["id"], item["business_name"] or "(to be named)", len(item["programs"])))
    if len(slices["slices"]) > 30:
        print("  ...and %d more. See inventory/slices.md" % (len(slices["slices"]) - 30))
    _print_top(ws)


def cmd_flow(args):
    print(write_flow(_ws(), args.entry))


def cmd_facts(args):
    ws = _ws()
    result = program_facts(ws, args.name)
    print(json.dumps(result, indent=1, sort_keys=True))


def cmd_source(args):
    print(read_source(_ws(), args.name, args.paragraph, args.start, args.end))


def cmd_datadict(args):
    ws = _ws()
    data = write_datadict(ws, args.copybook)
    print("%s: %d fields. Saved to %s" % (data["copybook"], len(data["fields"]), ws.path("data", data["copybook"] + ".md")))


def cmd_plan(_):
    ws = _ws()
    plan = write_plan(ws)
    print("Migration order saved to %s" % ws.path("mapping", "migration-order.md"))
    for number, item in enumerate(plan["order"][:20], 1):
        print("  %d. %s" % (number, item["id"]))


def cmd_mapping(args):
    print("%s: %s" % (args.slice, write_mapping(_ws(), args.slice)))


def cmd_gaps(args):
    ws = _ws()
    gaps = load_gaps(ws) if args.all else top_gaps(ws, args.top, args.focus)
    if args.json:
        print(json.dumps(gaps, indent=1, sort_keys=True))
        return
    if not gaps:
        print("Nothing is open.")
    for gap in gaps:
        print(_gap_line(gap))


def cmd_gap(args):
    ws = _ws()
    if args.action == "ask":
        references = []
        for reference in args.reference or []:
            path, _, line = reference.rpartition(":")
            references.append({"file": path, "line": int(line)} if line.isdigit() else {"file": reference, "line": None})
        gap = add_sme_question(ws, args.question, args.example, args.depends_on, references, args.blocks)
    elif args.action == "withdraw":
        gap = withdraw_question(ws, args.id, args.reason)
    elif args.action == "answer":
        gap = answer_gap(ws, args.id, args.by, args.answer, args.on, args.conflict)
    else:
        gap = resolve_conflict(ws, args.id, args.by, args.decision, args.on)
    render_all(ws)
    print(json.dumps(gap, indent=1, sort_keys=True) if getattr(args, "json", False) else _gap_line(gap))


def cmd_impact(args):
    print(json.dumps(impact(_ws(), args.id), indent=1, sort_keys=True))


def cmd_status(args):
    result = status(_ws(), args.kind, args.name)
    print("%s %s: %s" % (args.kind, result["name"], result["state"]))
    for gap in result["blocking"]:
        print("  %s %s (%s)" % (gap["id"], gap["name"], gap["kind"]))


def cmd_analysis(args):
    saved = record_analysis(_ws(), args.kind, args.name, args.output)
    print("Recorded the analysis of %s %s against the current source." % (saved["kind"], saved["name"]))


def cmd_stale(_):
    results = stale(_ws())
    if not results:
        print("Every saved analysis is up to date.")
    for item in results:
        print("%s %s: %s" % (item["kind"], item["name"], "; ".join(item["reasons"])))


def cmd_record(args):
    ws = _ws()
    if args.kind == "rule":
        fields = dict(text=args.text, status=args.status, evidence=args.evidence, slice=args.slice, gap=args.gap, by=args.by, on=args.on)
    elif args.kind == "requirement":
        fields = dict(text=args.text, rules=args.rules, slice=args.slice)
    else:
        fields = dict(given=args.given, when=args.when, then=args.then, rules=args.rules, slice=args.slice)
    record = add_record(ws, args.kind, **fields)
    print(json.dumps(record, indent=1, sort_keys=True) if args.json else record["id"])


def cmd_record_delete(args):
    ws = _ws()
    delete_record(ws, args.id)
    render_all(ws)
    print("Deleted %s." % args.id)


def cmd_validate(_):
    issues = validate(_ws())
    if not issues:
        print("No problems found.")
        return 0
    for issue in issues:
        print("%s: %s" % (issue["id"], issue["problem"]))
    return 1


def cmd_render(_):
    ws = _ws()
    render_all(ws)
    _copy_glossary(ws)
    print("Documents updated in %s" % ws.out)


def cmd_log(args):
    try:
        ws = _ws()
    except ConfigError:
        print("not logged: analysis isn't set up yet")
        return 0
    fields = {}
    for key in ("stage", "reference", "surface"):
        if getattr(args, key):
            fields[key] = getattr(args, key)
    if args.prompt_category:
        fields["prompt_category"] = args.prompt_category
    if args.item:
        fields["item"] = ws.logger.name_hash(args.item)
    try:
        ws.logger.event("activity", activity=args.activity, **fields)
    except LogFieldRejected:
        print("not logged: that value isn't allowed in the logs")
    return 0


def cmd_feedback(args):
    ws = _ws()
    add_feedback(ws.out, args.rating, args.category, args.text or "")
    print("Saved. It's only sent if you choose to include it in a log export.")


def cmd_logs(args):
    ws = _ws()
    result = export_logs(ws.out, args.include_feedback)
    print("Created %s" % result["zip"])
    print("Review what's in it first: %s" % result["preview"])
    print("%d events included, %d lines dropped by the privacy check." % (result["events"], result["dropped"]))
    print("Nothing was sent. If you're happy with it, send the zip to the skill's maintainer.")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        """Wrong usage can show a gap in the instructions, so log that it happened. Its text may hold names."""
        if os.path.isdir(os.path.join(ROOT_DIR, "modernization")):
            try:
                _safe_logger().event("error", command="usage", error_type="UsageError", skill_file="cli.py", skill_line=0)
            except (OSError, LogFieldRejected):
                pass
        super().error(message)


def build_parser():
    parser = _Parser(prog="mma.py", description="Mainframe modernization analysis. Read-only on source; results go to modernization/.")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    def add(name, handler, help_text):
        item = sub.add_parser(name, help=help_text, description=help_text)
        item.set_defaults(handler=handler)
        return item

    item = add("init", cmd_init, "Set up the analysis for a source folder")
    item.add_argument("--source", action="append", required=True)
    item.add_argument("--code-page")
    item.add_argument("--record-length", type=int)
    item.add_argument("--no-quotes", action="store_true", help="Leave quoted source out of outputs; keep citations")
    item = add("preflight", cmd_preflight, "Check this machine and folder are ready")
    item.add_argument("--source", action="append")
    add("scan", cmd_scan, "Run or refresh the inventory, map, gaps, slices, plan and documents")
    add("inventory", cmd_inventory, "Catalogue the source")
    add("map", cmd_map, "Build the dependency map and detect gaps")
    add("slices", cmd_slices, "Propose slices")
    item = add("slice-name", cmd_slice_name, "Give a slice a business name")
    item.add_argument("slice")
    item.add_argument("business_name")
    add("summary", cmd_summary, "Show the big picture")
    item = add("flow", cmd_flow, "Draw the end-to-end flow from a transaction, job, program or slice")
    item.add_argument("entry")
    item = add("facts", cmd_facts, "Show script-extracted facts for one member")
    item.add_argument("name")
    item = add("source", cmd_source, "Print numbered source for a member, paragraph or line range")
    item.add_argument("name")
    item.add_argument("--paragraph")
    item.add_argument("--start", type=int)
    item.add_argument("--end", type=int)
    item = add("datadict", cmd_datadict, "Build the data dictionary for a copybook")
    item.add_argument("copybook")
    add("plan", cmd_plan, "Write complexity, migration order and dead-code candidates")
    item = add("mapping", cmd_mapping, "Suggest a Spring Boot mapping for a slice")
    item.add_argument("slice")
    item = add("gaps", cmd_gaps, "List missing information, most important first")
    item.add_argument("--top", type=int, default=10)
    item.add_argument("--focus", action="append", help="A node to prioritize, such as program:BILLCALC")
    item.add_argument("--all", action="store_true")
    item.add_argument("--json", action="store_true")
    item = add("gap", cmd_gap, "Ask an SME question, record an answer, or settle a conflict")
    actions = item.add_subparsers(dest="action", metavar="action")
    actions.required = True
    ask = actions.add_parser("ask", help="Add an SME question")
    ask.add_argument("--question", required=True)
    ask.add_argument("--example", required=True)
    ask.add_argument("--depends-on", required=True)
    ask.add_argument("--reference", action="append", help="FILE:LINE, kept for the developer only")
    ask.add_argument("--blocks", action="append")
    ask.add_argument("--json", action="store_true")
    answer = actions.add_parser("answer", help="Record an answer from a person")
    answer.add_argument("id")
    answer.add_argument("--by", required=True)
    answer.add_argument("--answer", required=True)
    answer.add_argument("--on")
    answer.add_argument("--conflict", action="store_true", help="The answer disagrees with the code")
    answer.add_argument("--json", action="store_true")
    withdraw = actions.add_parser("withdraw", help="Take back a question that was added by mistake")
    withdraw.add_argument("id")
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--json", action="store_true")
    resolve = actions.add_parser("resolve", help="Record a person's decision on a conflict")
    resolve.add_argument("id")
    resolve.add_argument("--by", required=True)
    resolve.add_argument("--decision", required=True)
    resolve.add_argument("--on")
    resolve.add_argument("--json", action="store_true")
    item = add("impact", cmd_impact, "Show what depends on a gap")
    item.add_argument("id")
    item = add("status", cmd_status, "Show whether something is complete or incomplete")
    item.add_argument("kind", choices=["program", "copybook", "job", "proc", "flow", "slice"])
    item.add_argument("name")
    item = add("analysis", cmd_analysis, "Record that an analysis was done, so changes can be detected")
    item.add_argument("kind", choices=["program", "copybook", "job", "proc", "flow", "slice"])
    item.add_argument("name")
    item.add_argument("--output")
    add("stale", cmd_stale, "List saved analyses that need redoing, and why")
    item = add("record", cmd_record, "Save a rule, requirement or test scenario")
    item.add_argument("kind", choices=["rule", "requirement", "test"])
    for flag in ("--text", "--status", "--slice", "--gap", "--by", "--on", "--given", "--when", "--then"):
        item.add_argument(flag)
    item.add_argument("--evidence", action="extend", nargs="+", help="PROGRAM:PARAGRAPH:START-END. Give one or more")
    item.add_argument("--rules", action="extend", nargs="+", help="One or more rule IDs")
    item.add_argument("--json", action="store_true")
    item = add("record-delete", cmd_record_delete, "Delete a saved rule, requirement or test so it can be recorded again")
    item.add_argument("id")
    add("validate", cmd_validate, "Check saved records against the current source")
    add("render", cmd_render, "Regenerate request lists, rules, requirements and traceability")
    item = add("log", cmd_log, "Record skill activity through the privacy allowlist")
    item.add_argument("--activity", required=True)
    item.add_argument("--stage")
    item.add_argument("--prompt-category")
    item.add_argument("--reference")
    item.add_argument("--item", help="A name. Only a salted hash is stored")
    item.add_argument("--surface")
    item = add("feedback", cmd_feedback, "Report a problem with this skill")
    item.add_argument("--rating", type=int, required=True)
    item.add_argument("--category", required=True)
    item.add_argument("--text")
    item = add("logs", cmd_logs, "Create a log export for the skill's maintainer")
    item.add_argument("action", choices=["export"])
    item.add_argument("--include-feedback", action="store_true", help="Include free-text feedback. Check the preview first")
    return parser


def _log_name(command):
    return {"slice-name": "slice", "record-delete": "record"}.get(command, command)


def _safe_logger():
    return Logger(os.path.join(os.path.abspath(ROOT_DIR), "modernization"))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    started = time.time()
    has_output = os.path.isdir(os.path.join(ROOT_DIR, "modernization"))
    try:
        code = args.handler(args) or 0
    except (ConfigError, RecordError, LogFieldRejected) as exc:
        print("Problem: %s" % exc, file=sys.stderr)
        code = 2
    except PermissionError:
        print("Problem: I don't have permission to read or write a file here. Check access to the source folder and to modernization/.", file=sys.stderr)
        code = 2
    except Exception as exc:  # the person gets a clean message; the maintainer gets the logged location
        frames = traceback.extract_tb(exc.__traceback__)
        where = "%s:%d" % (os.path.basename(frames[-1].filename), frames[-1].lineno) if frames else "unknown"
        print("Problem: something went wrong inside the skill (%s at %s). It's been logged. To report it, run: python mma.py logs export" % (type(exc).__name__, where), file=sys.stderr)
        if has_output:
            try:
                _safe_logger().exception(_log_name(args.command), exc)
            except (OSError, LogFieldRejected):
                pass
        code = 1
    if has_output and args.command not in ("log", "scan", "inventory", "map"):
        try:
            _safe_logger().event("script_run", command=_log_name(args.command), duration_ms=int((time.time() - started) * 1000), result="ok" if code == 0 else "error")
        except (OSError, LogFieldRejected):
            pass
    return code

