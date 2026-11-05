# Installing the Mainframe Modernization Analyst

## What you need

- GitHub Copilot, in VS Code agent mode or Copilot CLI, with agent skills available
- Python 3.9 or newer. No packages are needed
- The mainframe source in a folder you can open: COBOL, copybooks, JCL and CICS, plus DB2 and VSAM details if available

The skill makes no network calls of its own. Copilot sends what it reads to its model as usual, so check that your organization's Copilot policy covers this source.

## Install

Unzip so that this folder sits in one of these places:

- **For one project:** `.github/skills/mainframe-modernization-analyst/`
- **For just you, in all projects:** `~/.copilot/skills/mainframe-modernization-analyst/`

The folder name must stay exactly as it is, or the skill won't load.

## Check it

From the project's root folder:

```text
python .github/skills/mainframe-modernization-analyst/scripts/mma.py preflight --source <folder with the mainframe code>
```

Then open a new Copilot chat in agent mode, or start Copilot CLI, and ask:

> Inventory this system and tell me what's missing.

Copilot may ask for approval to run terminal commands. If your policy blocks commands or file writes, you can run every command by hand: see `references/cli.md`.

## Update

Replace the skill's folder with the new version. Your results in `modernization/` aren't touched.

## Next

Run through `PILOT_CHECKLIST.md`, then send the log export to the skill's maintainer.
