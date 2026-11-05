# Logs and feedback

The skill's maintainer has no access to this code, so these logs are how the skill improves.

## What's logged

Skill version, Python and OS versions, command durations and results, error types and their location in the skill, file counts, parse coverage, gap counts, and masked patterns of statements the skill couldn't parse, such as `EXEC DLI GU USING PCB ( <NUM> ) INTO ( <ID> ) END-EXEC`.

## What's never logged

Source lines, business rules, requirements, SME names or answers, data values, or paths. Names of programs and data become salted hashes that can be counted but not read. The salt stays here and is never exported.

## Activity logging

```text
mma.py log --activity <activity> --stage <stage> --prompt-category <category> --item <NAME> --surface <surface>
```

- **activity:** `stage_started`, `stage_finished`, `reference_used`, `output_incomplete`
- **stage:** `inventory`, `map`, `slicing`, `deep_analysis`, `requirements`, `data`, `tests`, `mapping`, `gaps`, `planning`
- **prompt-category:** `inventory`, `orient`, `explain_flow`, `explain_program`, `requirements`, `data`, `test_scenarios`, `mapping`, `gaps`, `requests`, `take_in_answers`, `planning`, `other`
- **surface:** `vscode`, `copilot_cli`, `manual`, `unknown`

Log `output_incomplete` when you present incomplete output. Values outside these lists aren't logged, and that's fine: carry on.

## Reporting a problem

When a developer says the skill got something wrong, or says "report a problem with this skill", ask for a rating from 1 to 5 and a short description, then run:

```text
mma.py feedback --rating <1-5> --category <category> --text "<their description>"
```

Categories: `wrong_result`, `missed_something`, `too_long`, `too_technical`, `crash`, `install`, `other`. Remind them not to include sensitive details.

## Exporting logs

```text
mma.py logs export
```

This creates a zip and a preview file in `modernization/logs-export/`. Ask the developer to read the preview. Nothing is sent automatically, and the developer sends the zip themselves.

Feedback text is free-form, so it's left out by default. Include it only if the developer asks, after checking it for sensitive details: `mma.py logs export --include-feedback`.
