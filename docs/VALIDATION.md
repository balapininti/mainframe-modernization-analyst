# Validation results

Version 0.1.0, run 2026-11-04 on macOS with Python 3.14.

## What was tested

| Check | Result |
|-------|--------|
| Automated tests, including all real-code checks | See the final count in the release notes |
| AWS CardDemo inventory, compared with independent line scans | Every `.cbl` is a program, every `.jcl` is JCL, and `COPY`, `CALL`, `EXEC CICS` and `EXEC PGM=` match |
| Every confirmed citation in CardDemo | The cited line mentions its target |
| Every `LINK` and `XCTL` in CardDemo | Gives a link or an open item |
| Same system as CRLF, with no extensions, as EBCDIC, and as EBCDIC fixed records with no line breaks | Same map, including line numbers |
| Copybooks removed from CardDemo, then restored | Reported with the right lines, owner and blocks; items close when restored |
| Privacy sweep of a real log export | 245 program, table and data names checked; none found |
| Mermaid diagrams generated from CardDemo | All 40 parsed by Mermaid 11 |
| Generated system: 20,000 programs, 5.3 million lines | First scan 22 seconds, rescan 7.5 seconds, flow 0.1 seconds, 311 MB of output (mostly a cache git ignores) |

## Bugs real code found that fixture tests hadn't

- Hyphenated names treated as keywords, such as `WS-CALL`.
- Unrelated literals treated as program names (158 false gaps on CardDemo before the fix, 5 real ones after).
- Partly known `XCTL` targets reported as settled.
- `XCTL PROGRAM(TABLE(IDX))` dropped silently.
- A shared first program leaving a slice empty.
- An invalid Mermaid comment on long programs.

## What this doesn't prove

- **Copilot itself.** Nothing here ran in VS Code or Copilot CLI. `SKILL.md` follows the published format, but real loading and agent behaviour need the pilot.
- **Your code.** CardDemo is a clean, purpose-built sample. Real extracts have other dialects, library tools and damage.
- **Scale in Copilot.** The scripts handle millions of lines. How well Copilot works over a large map needs the pilot.
- **Windows and older Python.** Syntax is checked against Python 3.9 and file encoding against an ASCII locale, but nothing has run on Windows or on Python 3.9.
- **Non-COBOL logic.** IMS, Assembler, PL/I, REXX and Easytrieve are reported, not parsed.

`PILOT_CHECKLIST.md` in the skill covers these with the receiving team.

## Running the checks

```text
python3 -m unittest discover -s tests -t .
MMA_CARDDEMO=<path to CardDemo app folder> python3 -m unittest tests.test_carddemo
MMA_SCALE=20000 python3 -m unittest tests.test_scale
```
