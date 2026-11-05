# Planning

`mma.py plan` writes three files in `mapping/`. `scan` refreshes them as well.

- **`complexity.md`:** a rough score per program, from size, decisions, jumps, risky constructs and integrations. Use it to compare, not as an estimate of effort.
- **`migration-order.md`:** slices with dependencies first, then lower complexity. It also lists shared programs to plan first, and slices that depend on each other, which need a person's decision.
- **`dead-code-candidates.md`:** programs, copybooks and paragraphs nothing refers to.

When presenting these:

- Migration order is a suggestion from static links. Business priority, risk and shared data can outweigh it. Ask what the team cares about.
- Dead code is only ever a candidate. Names can be built at runtime, or used from outside this source. Ask the mainframe team to confirm, ideally with usage data.
- Unresolved runtime names and missing source make all of this less certain, so mention how many remain.
