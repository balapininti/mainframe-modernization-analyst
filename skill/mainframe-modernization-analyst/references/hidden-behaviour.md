# Hidden behaviour checklist

A rebuild can silently lose all of these. `mma.py facts <NAME>` flags most of them with line numbers. Check each one for the code you're analyzing, and record what matters as a rule.

## Logic outside COBOL

- **SORT steps:** control cards can filter, reformat or summarize records. Treat them as business rules.
- **IDCAMS steps:** file copies, deletes and repro steps can affect the outcome.
- **JCL conditions:** `COND` and `IF` decide which steps run. Return codes are a contract between steps.
- **Generation datasets:** `(+1)` and `(0)` define versions and retention.
- **Scheduler:** order and dependencies between jobs usually aren't in the source.

## Data

- **COMP-3 (packed decimal):** use `BigDecimal`. Never `double`.
- **REDEFINES:** one area with two meanings. Find what decides which applies.
- **OCCURS DEPENDING ON:** variable-length tables.
- **88-levels:** named values. Often the only record of what a code means.
- **Windowed dates:** two-digit years, and the rule that picks the century.
- **Rounding versus truncation:** `COMPUTE` without `ROUNDED` cuts off digits. Intermediate results follow compiler rules too.
- **Overflow:** a result too big for its field can lose digits unless `ON SIZE ERROR` is used.
- **EBCDIC sort order:** letters sort before digits, unlike ASCII. It changes sort results, range checks and key order.
- **Padding and comparison:** text is space-padded, and shorter values compare as if padded.
- **Spaces in numeric fields:** old data may hold spaces or low values. Validate real data.

## Control flow and failures

- **PERFORM THRU:** runs every paragraph between the two names.
- **GO TO, ALTER, NEXT SENTENCE:** the path isn't top to bottom.
- **Fall-through:** a paragraph runs on into the next unless it's being performed.
- **SQLCODE and file status:** each checked code is behaviour. So is a missing check.
- **Abends:** what stops abnormally, and what gets rolled back.
- **Checkpoint and restart:** how a failed job resumes without double-processing.

## CICS

- **COMMAREA:** state carried between screens or programs.
- **Pseudo-conversational design:** the task ends between screens, so state lives elsewhere.
- **Syncpoints:** where work commits. `SYNCPOINT` and task end are the boundaries.
- **Record locking:** `READ UPDATE`, `ENQ`, and how long locks are held. Note concurrent update behaviour.
- **HANDLE and RESP:** error paths that jump elsewhere.
- **Temporary storage and transient data:** queues that carry data between tasks or trigger others.

## Not visible in code

Ask about batch windows, volumes, response times, retention, audit needs, and manual steps people perform around the system.
