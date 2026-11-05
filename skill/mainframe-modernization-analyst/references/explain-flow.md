# Explaining an end-to-end flow

1. Log the start, with stage `deep_analysis` and category `explain_flow`.
2. Run `mma.py flow <transaction, job, program or slice>`. Read the file it names.
3. If it's marked incomplete, say so first and list what's missing.
4. For each main program in the flow, run `mma.py facts <NAME>`. Read source only for the parts that decide the path, using `mma.py source <NAME> --paragraph <PARA>`.
5. Write `modernization/flows/<NAME>-explained.md`, following the flow template. Keep the generated Mermaid diagram's links unchanged. You can simplify it, but never add a link that isn't in the map.
6. Finish with `mma.py analysis flow <NAME> --output <file>`.

## What to cover

- The business event in one or two plain sentences.
- Who or what starts it, and when. Scheduling isn't in the code unless scheduler files exist, so don't guess.
- The steps in order, in business terms, with program names in brackets.
- What data is read and changed at each step.
- What happens on failure.
- Where online and batch meet, such as a table written online and read overnight.

Separate what the map proves from what you inferred. Dotted arrows are inferred.
