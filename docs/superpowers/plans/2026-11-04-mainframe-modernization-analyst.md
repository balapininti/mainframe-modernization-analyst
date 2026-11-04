# Mainframe Modernization Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, test and package a Copilot skill that maps very large mainframe systems and turns them into evidence-backed specs for Spring Boot developers.

**Architecture:** A `SKILL.md` routes Copilot to focused reference files. A stdlib-only Python CLI (`scripts/mma.py`, package `scripts/mma/`) establishes all structural facts and saves results to `modernization/`. Copilot explains the facts and records rules through the CLI, which validates citations against source.

**Tech Stack:** Python 3.9+ standard library only, `unittest`, Mermaid in Markdown, GitHub Copilot agent skill format.

**Spec:** `docs/superpowers/specs/2026-11-04-mainframe-modernization-skill-design.md`

## Global Constraints

- No third-party Python packages, no network calls anywhere in the skill.
- Source is read-only. All writes go under `modernization/`.
- Rule and evidence statuses: `confirmed_code`, `inferred`, `confirmed_sme`, `ask_expert`, `conflict`.
- Logs: allowlisted fields only; no source lines, rules, SME names, data values or paths; names as salted hashes; salt never exported.
- Every script runs by hand from a terminal; script output is deterministic.
- No code generation. Spring Boot mappings are suggestions.

## Review Focus

1. CRLF, tabs, lowercase COBOL, stripped sequence columns: parse the same as canonical fixed format.
2. Keywords inside comments and literals (`DISPLAY 'CALL FOO'`): must not create dependencies.
3. Empty source folder, wrong path, unwritable output: a plain-language message, not a traceback.
4. Rerun with no changes: byte-identical outputs and no duplicated gaps.
5. Paths with spaces and files with no extension: found and classified by content.

---

### Task 1: Source reading

**Files:** Create `skill/mainframe-modernization-analyst/scripts/mma/sourcefile.py`; Test `tests/test_sourcefile.py`

**Interfaces:** Produces `decode_bytes(data, code_page, record_length) -> DecodeResult`, `classify(text, name) -> kind`, `normalize_cobol(text) -> list[CodeLine]`, `mask_literals(text) -> str`.

- [ ] Write tests for UTF-8, CRLF, EBCDIC with and without newlines, binary rejection, classification by content, fixed and free-format normalization, continuation, comment removal and literal masking (Review Focus 1, 2, 5)
- [ ] Run and watch fail: `python3 -m unittest tests.test_sourcefile`
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 2: Parsers

**Files:** Create `scripts/mma/cobol.py`, `jcl.py`, `definitions.py`, `copybook.py`; Test `tests/test_parsers.py`, fixtures in `tests/fixtures/sample/`

**Interfaces:** Consumes Task 1. Produces `parse_cobol(text) -> dict`, `parse_jcl(text) -> dict`, `parse_definitions(text, kind) -> dict`, `parse_copybook(text) -> list[field]`.

- [ ] Write tests: `CALL` static and dynamic, `COPY`, `++INCLUDE`, `EXEC CICS` and `EXEC SQL` extraction, paragraphs, performs, hazards, JCL steps, continuation, inline SYSIN, `RUN PROGRAM`, CSD, BMS, DDL, IDCAMS, copybook layout and byte offsets
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 3: Logging and export

**Files:** Create `scripts/mma/logs.py`, `masking.py`; Test `tests/test_logs.py`

**Interfaces:** Produces `Logger(outdir)`, `Logger.event(type, **fields)`, `Logger.name_hash(name)`, `mask_statement(text) -> str`, `export_logs(outdir, include_feedback) -> paths`.

- [ ] Write tests: unknown fields rejected, free text rejected, masked pattern keeps only keywords and placeholders, planted secrets absent from export, salt absent, feedback excluded unless confirmed
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 4: Inventory, dependency map and gap detection

**Files:** Create `scripts/mma/config.py`, `inventory.py`, `depmap.py`, `gaps.py`; Test `tests/test_inventory.py`

**Interfaces:** Consumes Tasks 1 to 3. Produces `run_inventory(ws) -> summary`, `build_map(ws) -> summary`, `detect_gaps(ws)`, `load_map(ws)`.

- [ ] Write tests: catalogue counts, edges, all gap kinds with owner and referencing line, system members not flagged, duplicate handling and precedence, unknown technology, cache reuse, byte-identical rerun (Review Focus 4), stable gap IDs, auto-resolution when the file arrives
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 5: Records, validation and the missing-information loop

**Files:** Create `scripts/mma/records.py`, `render.py`; extend `gaps.py`; Test `tests/test_records.py`

**Interfaces:** Consumes Task 4. Produces `add_record(ws, kind, ...)`, `validate(ws) -> issues`, `answer_gap(ws, id, by, answer, conflict)`, `impact(ws, gap_id)`, `stale(ws)`, `status(ws, kind, name)`, `render_all(ws)`.

- [ ] Write tests: bad citations rejected, `confirmed_code` needs evidence, `confirmed_sme` needs person and date, conflict stays open, SME questions contain no COBOL, requests carry exact members and lines, incomplete status, only dependents listed as stale
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 6: Analysis outputs

**Files:** Create `scripts/mma/slices.py`, `flows.py`, `planning.py`, `datadict.py`, `facts.py`; Test `tests/test_outputs.py`

**Interfaces:** Consumes Tasks 2 and 4. Produces `build_slices(ws)`, `write_flow(ws, entry)`, `write_plan(ws)`, `write_datadict(ws, copybook)`, `program_facts(ws, name)`, `read_source(ws, name, paragraph)`.

- [ ] Write tests: slices keep hubs out of clusters, valid Mermaid with missing nodes marked, migration order puts dependencies first and survives cycles, Java type mapping for `COMP-3` and `REDEFINES`, hazards listed, dead-code labeled as candidates
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 7: CLI, skill content and release

**Files:** Create `scripts/mma.py`, `scripts/mma/cli.py`, `preflight.py`, `SKILL.md`, `VERSION`, `INSTALL.md`, `references/*.md`, `templates/*.md`, `tools/build_release.py`; Test `tests/test_cli.py`, `tests/test_skill_package.py`

- [ ] Write tests: end-to-end CLI on fixture, Review Focus 3 and 5 messages, `SKILL.md` frontmatter valid, every referenced file exists, every documented CLI command exists, every section 13 prompt present, stdlib-only imports, release zip contents
- [ ] Run and watch fail
- [ ] Implement; run; expect PASS
- [ ] Commit

### Task 8: Validation against real sample code

**Files:** Create `tests/test_carddemo.py` (skipped unless `MMA_CARDDEMO` is set), `tests/test_scale.py`, `docs/VALIDATION.md`, `PILOT_CHECKLIST.md`

- [ ] Compare inventory and calls against independent `grep` counts on CardDemo
- [ ] Remove copybooks and confirm the full gap loop
- [ ] Run a generated large system and record timing
- [ ] Write results and limits in `docs/VALIDATION.md`
- [ ] Commit
