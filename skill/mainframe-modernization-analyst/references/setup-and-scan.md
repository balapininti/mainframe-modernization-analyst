# Setup and scanning

## Set up

```text
mma.py preflight --source <folder>
mma.py init --source <folder>
mma.py scan
```

Repeat `--source` for several folders. Options for `init`:

- `--code-page`: the EBCDIC code page for files not yet converted. The default is `cp037`. Ask the mainframe team if text looks garbled.
- `--record-length`: the record length of EBCDIC files with no line breaks. The default is 80.
- `--no-quotes`: keep quoted source out of outputs, leaving citations only. Use this if outputs reach people without source access.

## What `scan` does

It catalogues all files by content (extensions don't matter), builds the dependency map, detects gaps, proposes slices, writes planning documents and regenerates request lists. Unchanged files are reused, so it's safe to run often.

## Big picture

Run `mma.py summary`, then explain:

1. How big the system is and what it's made of.
2. The main flows, from the slices.
3. What's shared widely across flows.
4. What's missing, starting with what blocks the most.

Then propose business names for slices from their entry points, programs and data, marked as your guess. Save names the developer accepts with `mma.py slice-name <SLICE-ID> "<business name>"`.

## Settings in `modernization/config.json`

- `library_precedence`: which copy wins when members with the same name differ, as path fragments in order, such as `["prod/", "test/"]`. Get this rule from the mainframe team. Never choose yourself.
- `system_programs`, `system_copybooks`: extra names to treat as system-supplied.
- `hub_threshold`: how many callers make a program "shared". The default is 5.
- `max_slice_programs`: the size where a large group is split by entry point. The default is 25.
- `ignore_extensions`: file types to skip.

Run `mma.py scan` after any change.

## What the scripts don't do

Tell the developer about these when they matter:

- `COPY ... REPLACING` isn't applied, so renamed fields keep their copybook names.
- Symbols passed from a job into a PROC aren't applied to the PROC's steps. `SET` and `PROC` defaults are.
- Nested programs in one file are listed together.
- A program name built by more than a plain `MOVE` is reported as an open item, not worked out.
- `inventory/system-references.md` lists names treated as system-supplied. Check it if one might really be yours.
- A file type in `ignore_extensions` is skipped, and the count is shown in `inventory/summary.md`.

## Results folder

`inventory/` catalogue and map, `flows/` flows, `programs/` program detail, `requirements/` rules, requirements, tests and traceability, `data/` data dictionary, `mapping/` mappings and planning, `gaps/` requests and answers, `analysis/` change tracking, `logs/` privacy-safe logs.

The team decides whether this folder goes in version control. `logs/` and caches are ignored by git by default.
