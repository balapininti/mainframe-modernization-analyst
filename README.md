# Mainframe Modernization Analyst

A GitHub Copilot skill that helps Spring Boot developers understand and specify the modernization of large mainframe systems. It stops at understanding and specifications, and generates no code.

- The skill: `skill/mainframe-modernization-analyst/`
- Design: `docs/superpowers/specs/2026-11-04-mainframe-modernization-skill-design.md`
- Test results and limits: `docs/VALIDATION.md`

## Build the handover zip

```text
python3 tools/build_release.py
```

This creates `dist/mainframe-modernization-analyst-<version>.zip`. Give it to the team with `INSTALL.md` and `PILOT_CHECKLIST.md`, which are inside it.

## Improving it from the team's logs

The team sends a zip from `mma.py logs export`. In it, `preview.md` is readable and `events.jsonl` holds:

- `unrecognized`: masked statements the parser doesn't handle yet, with counts
- `coverage`: file kinds, encodings and parse rates
- `error`: exception type and skill location
- `gaps`: open items by kind and owner
- `script_run`, `activity`: what ran, how long it took, and which jobs were used

Reproduce a parser problem from its masked pattern in `tests/fixtures/`, add a failing test, fix it, and bump `VERSION` and `CHANGELOG.md`.
