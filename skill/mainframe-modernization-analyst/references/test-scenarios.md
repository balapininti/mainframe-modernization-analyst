# Test scenarios

Derive scenarios from recorded rules, so each traces back to source.

```text
mma.py record test --given "<starting state>" --when "<event>" --then "<expected result>" --rules <RULE-ID> --slice <SLICE-ID>
```

Use business language with real example values. For each rule, cover the normal case, each boundary (exactly 10,000, and just above and below), the failure paths, and any special values such as high values, spaces or zero. Mark any scenario resting on an `inferred` or `ask_expert` rule as needing confirmation.

Expected results for calculations must come from the code's real rounding or truncation, so state which one applies.

## Comparison plan

Tests written from reading code can share its misreadings. Recommend a side-by-side comparison of old and new. In `requirements/comparison-plan-<SLICE-ID>.md`, cover:

- Which inputs to capture, and from which period. They should include month-end and year-end.
- What outputs to compare: files, tables, reports, return codes.
- How to compare despite differences in encoding, sort order, packed decimals and timestamps.
- What differences are acceptable, and who signs off.
- How to protect sensitive production data used in testing.

Ask the mainframe team whether test data and output captures are available.
