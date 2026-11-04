# Mainframe Modernization Analyst: Copilot Skill Design

**Date:** 2026-11-04
**Status:** Draft for review

Items marked **(my call)** were proposed during design and not separately chosen by the requester. The requester approved the overall scope ("keep all of them, write the design"), but should check these while reading.

## 1. Intent

Java (Spring Boot) developers are being asked to modernize a very large, complex mainframe system they can't read fluently. The knowledge they need is spread across COBOL, copybooks, JCL and CICS, with DB2 and VSAM details where available, and in the heads of a few people.

This GitHub Copilot skill gives those developers what they need to understand the system and specify the rebuild. It works at every level: end-to-end flows, business processes and requirements, and individual programs. It also tells them exactly what information is missing and who to ask for it.

## 2. Goals

- Explain the system to a Spring Boot developer who doesn't know COBOL.
- Produce visual flows, business logic, requirements and program-level detail.
- Work on very large codebases by mapping first and analyzing one slice at a time.
- Identify missing information, request it from the right people, and take it in when it arrives.
- Back every factual claim with evidence, so a reviewer can check it.
- Surface mainframe behaviour that a rebuild could silently lose.

## 3. Non-goals

- Generating Spring Boot code. The skill stops at understanding and specifications.
- Changing mainframe source. The skill treats it as read-only.
- Making architecture decisions. Spring Boot mappings are suggestions for an architect to review.

## 4. Anti-goals

The skill has failed, even if it runs, when:

- A guess about a business rule is presented as fact.
- A partial analysis looks finished.
- A gap is filled silently rather than reported.
- An SME answer that contradicts the code overrides it, or is overridden by it, without being flagged.
- Developers get output so long or so COBOL-heavy that they go back to reading the source.

## 5. Constraints

- **Runtime:** GitHub Copilot in VS Code agent mode and Copilot CLI. Python scripts are allowed on developer machines.
- **No access to client code:** the skill's author can't see the team's or client's code. The skill is exported and handed over, and the receiving team runs it. Everything must work without the author present, and improvements depend on the logs in section 16.
- **Scale:** very large codebase and very complex system. No exact counts are known, so the design must not assume the whole system fits in Copilot's context.
- **Inputs:** COBOL, copybooks, JCL and CICS are expected. DB2 and VSAM details may or may not be available, so every stage must work without them.
- **People:** the mainframe team supplies missing copybooks and other technical artifacts. SMEs answer business questions.

## 6. How it's packaged (my call)

- A standard Copilot agent skill folder: `.github/skills/mainframe-modernization-analyst/`, containing `SKILL.md`, reference files, Python scripts and output templates.
- Built in its own standalone repo, not this Salesforce repo, and released as a versioned zip with install instructions, a `VERSION` file and a changelog.
- A preflight script checks the Python version, write access and that the skill can find the source, and reports problems in plain language.
- It isn't yet known whether the receiving team's Copilot policy allows terminal commands and file writes. Every script must therefore also run by hand from a terminal, with documented commands, and the skill must work from the saved results if Copilot can't run them.
- `SKILL.md` stays short and routes to reference files by task, so only what's needed gets loaded.
- Python uses the standard library only, so it runs on locked-down machines with no package installs.
- Diagrams are Mermaid in Markdown, so they render and can be reviewed in the repo.
- The builder should confirm the current Copilot skill format and how the target Copilot surface loads skills before finalizing the packaging.

## 7. How it works

The skill never tries to read the whole system. It works in four stages.

### Stage 1: Inventory (script)

Scan all provided source and catalogue programs, copybooks, JCL jobs and PROCs, BMS maps, CICS transactions, DB2 objects and VSAM files. Report what's referenced but absent.

Mainframe extracts are often messy, so classification must rely on file content, not extensions. It must also handle fixed-column format, sequence numbers, comment lines and continuation lines. EBCDIC files are decoded using a configurable code page, and anything that still can't be decoded is reported, not skipped silently. **(my call)**

Two more rules protect the map from silent errors **(my call)**:

- **Unrecognized technology:** source in a language or subsystem the scripts don't parse, or an unsupported copy mechanism, is reported as a gap and never treated as absent.
- **Duplicate members:** when the same member name appears in more than one library, the map doesn't pick one. It records a gap until a precedence rule is supplied.

### Stage 2: Dependency map (script)

Extract hard facts deterministically: `CALL`, `COPY`, `EXEC CICS` (`LINK`, `XCTL`, `START`, file commands), `EXEC SQL`, JCL steps, `DD` statements and PROCs. Record who calls whom, which job runs which step, which transaction starts which program, and who reads or writes which data. Dynamic calls whose target can't be resolved become gaps.

### Stage 3: Slicing

Group the map into business capabilities or transaction flows that one person can work through. Scripts propose entry points and clusters. Copilot proposes business names, and the developer can adjust them.

### Stage 4: Deep analysis (Copilot, on request)

Analyze one slice or program at a time, loading only the source it needs and producing the outputs in section 8.

**Principle:** scripts establish the facts and Copilot explains what they mean. Copilot must not state structural facts that aren't in the script output or the source it read.

## 8. Outputs

### Level 1: End-to-end

- Mermaid flows showing how a business event crosses online, batch and data stores.
- Business process descriptions in plain language.
- External interfaces: inbound and outbound files, reports and downstream consumers.

### Level 2: Business

- Business rules, each with evidence and a status.
- Requirements written without COBOL terms (for example, `REQ-014: The system shall apply...`).
- Test scenarios in Given/When/Then form, drawn from the rules, plus a plan for comparing old and new results side by side.
- Traceability matrix: requirement to rule to source line to test.
- Questions on non-functional needs (batch windows, volumes, response times), which the code can't answer.

### Level 3: Program

- Purpose, paragraph flow, copybooks used, data read and written, failure behaviour, and restart behaviour.
- Paragraph-level Mermaid diagrams where the logic warrants it.
- Data dictionary: each copybook field, its meaning, its suggested Java type and any traps.

### Modernization aids

- Spring Boot mapping table: legacy element, suggested equivalent, and what to watch out for. For example, JCL to Spring Batch, a CICS transaction to a REST controller and service, `COMP-3` to `BigDecimal`.
- Dead-code candidates, labeled as candidates only, since static analysis can't prove code is unused.
- Complexity scores and a suggested migration order based on dependencies.
- Glossary of mainframe terms for Java developers.

## 9. Evidence and status

Every rule and requirement cites program, paragraph or section, and line numbers, and carries exactly one status:

| Status | Meaning |
|--------|---------|
| Confirmed from code | Directly stated by cited source |
| Inferred | A reasonable reading of the code, not proven by it |
| Confirmed by SME | Answered by a named person on a recorded date |
| Ask an expert | The code shows what happens, but not why or whether it's still intended |
| Conflict | An SME answer and the code disagree. Stays open until a person resolves it |

Each flow, program and slice is also marked complete or incomplete, and incomplete items list what's blocking them.

## 10. Missing information

The skill keeps working with what it has, marks affected output as incomplete, and tracks each gap in one running request list.

**It detects:**

- Missing source: a `COPY` member, called program, JCL PROC or BMS map that's referenced but absent.
- Missing system definitions: DB2 table definitions, VSAM file definitions, CICS transaction definitions, job schedules and control cards.
- Things the code can't settle: a program name known only at runtime, an unexplained hardcoded value, or a rule whose reason isn't visible.

**Each item records:** what's needed, why, what it blocks, where it was referenced, urgency, owner (mainframe team or SME), and status.

**It asks the developer in chat** about the most important gaps, not all of them at once. Ranking favours whatever blocks the most flows or the flow being worked on. **(my call)**

**It generates two outputs:**

- **Mainframe team request:** ready to send, with exact member names, types, the referencing program and line, and what's blocked.
- **SME questions:** in business language with no COBOL, each with a real example and what depends on the answer. The code reference stays attached for the developer, not in the question.

**When information arrives:**

- The developer adds the file, or gives the answer in chat.
- The skill reanalyzes only what depended on that item and updates statuses.
- Human answers record who gave them and when.
- Answers that contradict the code are marked as a conflict. The skill doesn't pick a side.

## 11. Hidden behaviour checklist

Deep analysis must explicitly check for each of these and report it, because a rebuild can silently lose it:

- **Logic outside COBOL:** `SORT` steps, `IDCAMS`, and JCL conditions (`COND`, `IF`).
- **Data:** `COMP-3`, `REDEFINES`, `OCCURS DEPENDING ON`, 88-levels, windowed dates, rounding versus truncation, and EBCDIC sort order versus ASCII or Unicode.
- **Control flow and failures:** `PERFORM THRU`, `GO TO`, `SQLCODE` and file status handling, abends, and checkpoint/restart.
- **CICS:** COMMAREA state, syncpoints and record locking.

## 12. Saved results (my call)

Results are saved as files in a `modernization/` folder at the workspace root, kept separate from source and meant to be reviewed in version control. Later sessions build on them rather than starting over. Source files are tracked by content hash so only changed items are reanalyzed.

The receiving team decides whether this folder goes in version control and who can see it. A setting turns off quoted source in outputs, leaving citations only.

To stay safe with several developers on branches, gaps and rules are stored one per file with collision-safe stable IDs, the request list is generated from those files, and script output is deterministic so reruns produce clean diffs.

```text
modernization/
  inventory/      catalogue and dependency map (machine-readable + summary)
  flows/          end-to-end flows and process descriptions
  programs/       program-level detail
  requirements/   rules, requirements, test scenarios, traceability
  data/           data dictionary
  mapping/        Spring Boot mappings, complexity, migration order
  gaps/           request list, mainframe team request, SME questions, answers log
  glossary.md
```

## 13. Starter prompts

Include ready-to-use prompts in the skill, each mapped to a task:

| Job | Example prompt |
|-----|----------------|
| Inventory | "Inventory this system and tell me what's missing." |
| Orient | "Give me the big picture and the main business flows." |
| Explain a flow | "Explain the end-to-end flow for `<transaction or job>`." |
| Explain a program | "Explain `<program>` to a Spring Boot developer." |
| Requirements | "Write requirements and rules for `<slice>`." |
| Data | "Build the data dictionary for `<copybook>`." |
| Test scenarios | "Write test scenarios for `<slice>`." |
| Mapping | "Suggest a Spring Boot mapping for `<slice>`." |
| Gaps | "What's still missing, and who do I ask?" |
| Requests | "Prepare the mainframe team request and SME questions." |
| Take in answers | "Here's the answer or file for `<item>`. Update the analysis." |
| Planning | "Suggest a migration order and explain why." |

The skill instructions also act as the core prompt. They set the role (expert mainframe programmer explaining to a Spring Boot developer) and the rules in sections 7, 9, 10 and 11.

## 14. What success looks like

- A Spring Boot developer with no COBOL background can explain a flow and start specifying its rebuild from the outputs alone.
- A reviewer can trace any rule to its source lines.
- Gaps reach the mainframe team and SMEs as requests they can act on without a follow-up meeting.
- A later session picks up from saved results without redoing the analysis.

## 15. Left to the builder

- Parsing approach and internal data formats for the scripts.
- Slice-clustering method and the complexity scoring formula.
- Exact templates, provided they carry the content above.
- Test fixtures. **My suggestion:** use AWS's open-source CardDemo mainframe sample, plus deliberately removed copybooks to exercise the missing-information loop. Passing on a sample doesn't prove the skill handles a real extract, so the plan must include an early pilot on real source. The receiving team runs that pilot from a written checklist and returns the exported logs.

## 16. Logs and feedback

The requester needs logs from the receiving team to improve the skill without seeing client code. The requester asked for the logs; the privacy rules below are **(my call)**.

**What gets logged** (in `modernization/logs/`, as JSON lines):

- **Environment:** skill version, Copilot surface if known, Python version and OS.
- **Script runs:** stage, duration, files processed, result, and errors with their type and skill code location.
- **Coverage:** file counts by type, percentage parsed, and unrecognized statements.
- **Gaps:** counts by type and owner, and how many were resolved.
- **Skill activity:** stage started or finished, reference files used, prompt category, and whether output was marked incomplete.
- **Feedback:** a developer's rating or correction, recorded through a "report a problem with this skill" prompt.

**How unsupported code is reported:** parser failures are logged as a masked pattern. Mainframe keywords are kept, and every name and literal is replaced, for example `EXEC DLI GU USING PCB(<NUM>) INTO(<ID>)`. This shows what the parser needs to support without exposing the code.

**What must never be logged:** source lines, business rules, requirements, SME names or answers, data values, or paths. Program, copybook, table and field names are replaced with salted hashes, so items can be counted and tracked across runs but not read. The salt stays with the team and is never exported.

**How the rules are enforced:** the log writer accepts only allowlisted fields and rejects anything else, so a new log call can't leak free text by accident. Feedback text is free-form, so it's kept separate and included only after the developer confirms it.

**How logs reach the requester:**

- A prompt or script creates one zip file, plus a readable preview of exactly what's in it.
- The team reviews the preview and sends the zip themselves.
- The skill never sends anything over the network.

**Limitation:** script logs are reliable, because code writes them. Skill activity logs depend on Copilot following the instruction to call the logging script, so they may have gaps.

**Testing:** the test suite must plant known secrets in sample source and fail if any of them appear in an export.

## 17. Unknowns the design handles by default

These apply to the receiving team and can't be answered in advance. The skill handles each case and reports what it finds in the logs:

- Whether Copilot can run commands and write files: scripts can also be run by hand (section 6).
- Other languages or copy mechanisms in the source: reported as gaps (section 7).
- EBCDIC files and code page: configurable decoding (section 7).
- Duplicate members and library layout: reported until a precedence rule is supplied (section 7).
- Whether outputs can be committed, and who can see them: the team's decision (section 12).
