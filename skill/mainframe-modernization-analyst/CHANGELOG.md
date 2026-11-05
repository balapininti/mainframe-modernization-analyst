# Changelog

## 0.2.0

Fixes from an independent code review and a test run of the skill.

- Completeness: `status` and flow files now give one answer, following everything reachable, including nested copybooks, absent programs, and rules still needing an answer.
- Copybooks: logic and hidden behaviour inside them now reach the programs that copy them. Offsets handle `SIGN SEPARATE`, inherited `USAGE`, national data, `SYNC`, and levels 66 and 77. Offsets that can't be proven are marked unverified.
- Runtime names: any write the skill can't read keeps the item open.
- JCL: utility steps on the map, symbols from `SET` and `PROC`, in-stream PROCs, several jobs in a member, control cards with `RUN PROGRAM`, `DLM=`, and step overrides.
- SQL: reads and writes separated, aliases, quoted names, `MERGE`, stored procedures, and dynamic SQL raises an open item.
- Answers: conflicts can only be settled by `gap resolve`. Partial answers, full answer history, and runtime targets on the map. Requirement confidence follows its rules.
- Names: dataset-style file names, `PROGRAM-ID` different from the member, `ENTRY`, nested programs, and client programs that look like system names.
- New commands: `record-delete`, `gap withdraw`.
- Privacy: `--no-quotes` also covers facts files, and the salt is ignored by git.

## 0.1.0

First release: inventory, dependency map, slices, flows, program facts, data dictionary, rules and requirements with citation checks, test scenarios, traceability, Spring Boot mapping suggestions, migration order, missing-information loop, and privacy-safe logs.

Not analyzed yet: IMS, Assembler, PL/I, REXX and Easytrieve are reported as open items, not parsed.
