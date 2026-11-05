# Missing information

## How it works

`mma.py scan` detects missing source and definitions, and each becomes an item with an ID. Keep working with what you have. Items are marked with an owner: the **mainframe team** supplies source and definitions, and **SMEs** answer business questions.

## See what's missing

```text
mma.py gaps --top 5
mma.py gaps --focus program:<NAME>
mma.py status program <NAME>
mma.py impact <GAP-ID>
```

Don't list hundreds of items in chat. Raise the one to three most important, saying what's needed, why, and what it blocks. Everything else is in `gaps/REQUEST_LIST.md`.

## Ask an SME

When the code can't answer a business question, add it:

```text
mma.py gap ask --question "<plain question>" --example "<real example>" --depends-on "<what depends on the answer>" --reference <FILE:LINE> --blocks program:<NAME>
```

`--reference` and `--blocks` make the program show as incomplete until the question is answered.

Write in business language, with a concrete example and no program or field names. The command refuses mainframe terms. For example: "Orders from region 07 don't get the 5% discount. Is that still intended, and why?"

Link it to the rule with `--gap <GAP-ID>` on `mma.py record rule`. The program the rule cites then shows as blocked by the question.

To take back a badly worded question, run `mma.py gap withdraw <GAP-ID> --reason "<why>"`, then ask it again.

## Prepare the requests

Run `mma.py render`, then point the developer to:

- `gaps/MAINFRAME_TEAM_REQUEST.md`: exact members, types, referencing lines, and what's blocked.
- `gaps/SME_QUESTIONS.md`: questions with no code references.

The developer sends these. You don't.

## When information arrives

- **Files:** ask the developer to add them to the source folder, then run `mma.py scan`. Matching items close by themselves. Run `mma.py stale`, and redo only what it lists.
- **Answers:** `mma.py gap answer <GAP-ID> --by "<person>" --answer "<their words>"`. Linked rules become `confirmed_sme`.
- **Answers that don't settle it, such as "ask Bob":** add `--partial`. The item stays open and the answer is kept.
- **The value of a runtime name:** add `--target <PROGRAM>`. The link then goes on the map, labeled as coming from an answer.
- **Which duplicate is right:** this can't be answered here. Set `library_precedence` in `modernization/config.json`, then scan.
- **Answers that contradict the code:** add `--conflict`. Tell the developer about the disagreement and show both sides. Don't choose. A person settles it with `mma.py gap resolve <GAP-ID> --by "<person>" --decision "<decision>"`.

Never record an answer on behalf of someone who didn't give it.

## Unsupported technology

IMS, Assembler, PL/I, REXX, Easytrieve and MQ aren't analyzed in this version. They appear as open items and must never be treated as absent. You can read those files by hand, and record anything you find as `inferred`. Tell the developer that part of the map is incomplete.
