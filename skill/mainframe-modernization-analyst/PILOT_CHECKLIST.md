# Pilot checklist

This skill's maintainer can't see your code, so this pilot is the real test. Start with one flow you know well, so you can tell if the results are right. Allow about half a day.

## Setup

- [ ] Installed in VS Code agent mode or Copilot CLI (note which)
- [ ] `preflight` reports Ready
- [ ] Copilot lists or uses the skill in a new chat
- [ ] Copilot can run the commands. If it can't, note the reason and run them by hand

## Inventory and map

- [ ] "Inventory this system and tell me what's missing" completes. Note how long `scan` took
- [ ] File counts look right, compared with what the mainframe team expects
- [ ] Pick 5 programs you know. Their callers, copybooks and data look right
- [ ] Items reported as missing really are missing
- [ ] Other technology in the source is reported as an open item (such as IMS, Assembler or PL/I)

## Understanding

- [ ] "Explain the end-to-end flow for ..." gives a diagram that renders and is right
- [ ] "Explain ... to a Spring Boot developer" is understandable to someone with no COBOL
- [ ] Open 5 cited line references. They support what's claimed
- [ ] Anything incomplete is clearly marked

## Rules and requirements

- [ ] "Write requirements and rules for ..." finds the rules you know of
- [ ] It doesn't invent reasons. Unknowns are marked "Ask an expert"
- [ ] Requirements read as business language
- [ ] A mainframe colleague and an SME both review a sample

## Missing information

- [ ] The mainframe team can act on the request without a follow-up meeting
- [ ] An SME can answer the questions without seeing code
- [ ] Add a missing file and re-scan: the item closes, and only affected work is listed as stale
- [ ] Record an answer that contradicts the code: it's flagged as a conflict, and not resolved automatically

## Scale

- [ ] Run `scan` on the whole system. Note the time and any problems
- [ ] Copilot stays useful on a large flow rather than running out of context

## Send feedback

- [ ] "Report a problem with this skill" for anything that went wrong
- [ ] `logs export`, then read the preview to confirm nothing sensitive is in it
- [ ] Send the zip to the skill's maintainer, plus notes on anything the logs can't show
