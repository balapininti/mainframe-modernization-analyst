# Commands

All commands can be run by hand in a terminal, from the project's root folder, if Copilot isn't allowed to run them. Paste the output into chat, or open the files in `modernization/`.

Replace `mma.py` with the full path, for example:

```text
python .github/skills/mainframe-modernization-analyst/scripts/mma.py scan
```

## Setting up and refreshing

| Command | What it does |
|---------|--------------|
| `mma.py preflight --source <folder>` | Check the machine and folder are ready |
| `mma.py init --source <folder>` | Set up the analysis |
| `mma.py scan` | Run or refresh everything script-based |
| `mma.py inventory` | Catalogue the source only |
| `mma.py map` | Build the map and detect gaps only |
| `mma.py slices` | Propose slices only |
| `mma.py summary` | Show the big picture |

## Analyzing

| Command | What it does |
|---------|--------------|
| `mma.py flow <entry>` | Draw a flow from a transaction, job, program or slice |
| `mma.py facts <name>` | Show facts for one member |
| `mma.py source <name> --paragraph <para>` | Print a numbered part of the source (or `--start`, `--end`) |
| `mma.py datadict <copybook>` | Build a data dictionary |
| `mma.py mapping <slice>` | Suggest a Spring Boot mapping |
| `mma.py plan` | Write complexity, order and dead-code candidates |
| `mma.py slice-name <slice> "<name>"` | Name a slice |
| `mma.py analysis <kind> <name> --output <file>` | Record that an analysis was done |
| `mma.py stale` | List analyses that need redoing |

## Recording

| Command | What it does |
|---------|--------------|
| `mma.py record rule --text .. --status .. --evidence ..` | Save a rule |
| `mma.py record requirement --text .. --rules ..` | Save a requirement |
| `mma.py record test --given .. --when .. --then .. --rules ..` | Save a test scenario |
| `mma.py record-delete <id>` | Delete a saved record so it can be redone |
| `mma.py validate` | Check records against current source |
| `mma.py render` | Regenerate documents |

## Missing information

| Command | What it does |
|---------|--------------|
| `mma.py gaps --top 5` | List the most important items (or `--all`, `--json`) |
| `mma.py status <kind> <name>` | Show complete or incomplete |
| `mma.py impact <id>` | Show what depends on an item |
| `mma.py gap ask --question .. --example .. --depends-on ..` | Add an SME question |
| `mma.py gap answer <id> --by .. --answer ..` | Record an answer (add `--conflict` if it disagrees with the code, `--partial` if it doesn't settle it, `--target <program>` for a runtime name) |
| `mma.py gap withdraw <id> --reason ..` | Take back a question added by mistake |
| `mma.py gap resolve <id> --by .. --decision ..` | Record a person's decision on a conflict |

## Logs

| Command | What it does |
|---------|--------------|
| `mma.py log --activity ..` | Record activity through the allowlist |
| `mma.py feedback --rating .. --category .. --text ..` | Report a problem |
| `mma.py logs export` | Create a zip and preview to review and send |
