# Business rules and requirements

## Rules come first

A rule is one business behaviour, tied to evidence. Save each one:

```text
mma.py record rule --text "<plain description>" --status <status> --evidence PROGRAM:PARAGRAPH:START-END --slice <SLICE-ID>
```

Leave the paragraph empty for copybooks and JCL: `CUSTREC::44-44`, `NITEBILL::3-8`. Give several citations after `--evidence` if needed. The command checks that citations exist and refuses bad ones. Fix them by reading the source, never by loosening them.

## Choosing a status

| Status | Use when |
|--------|----------|
| `confirmed_code` | The cited code directly states the behaviour. |
| `inferred` | It's a reasonable reading, but the code doesn't prove the meaning, such as "rating A means preferred". |
| `ask_expert` | The code shows what happens, but not why, or whether it's still intended. Create an SME question and link it with `--gap`. |
| `confirmed_sme` | A named person confirmed it. Needs `--by` and `--on`. Usually set automatically when an answer is recorded. |
| `conflict` | A person's answer and the code disagree. Set automatically by `gap answer --conflict`. |

When in doubt, choose the weaker status.

## Requirements come from rules

```text
mma.py record requirement --text "The system shall ..." --rules <RULE-ID> --slice <SLICE-ID>
```

Give one or more rule IDs after `--rules`. Requirements must be in business language, with no program, paragraph or field names. The command refuses mainframe terms. A requirement's confidence is that of its weakest rule, so make it clear when a requirement rests on `inferred` or `ask_expert` rules.

Include non-functional needs too: batch windows, volumes, response times, retention. The code rarely shows them, so raise them as SME or mainframe team questions. See [missing-information](missing-information.md).

## Finish

```text
mma.py validate
mma.py render
```

This produces `requirements/RULES.md`, `REQUIREMENTS.md`, `TEST_SCENARIOS.md` and `TRACEABILITY.md`. Save the document for the slice as `requirements/<SLICE-ID>-requirements.md`.

To correct a saved record, delete it with `mma.py record-delete <ID>` and record it again. A rule in use must have its requirements and tests removed first.

To avoid missing rules, go through decisions in order: each `IF`, `EVALUATE`, validation, calculation, hardcoded value and error path, plus JCL conditions and SORT control cards.
