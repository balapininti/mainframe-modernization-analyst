# Explaining one program

1. Log the start, with category `explain_program` and `--item <NAME>`.
2. Run `mma.py facts <NAME>`. This gives callers, what it uses, paragraphs, a paragraph flow and hidden behaviour, and saves `programs/<NAME>.facts.md`.
3. If it's incomplete, say so first.
4. Read one paragraph at a time with `mma.py source <NAME> --paragraph <PARA>`, starting at the first. Copybook layouts come from `mma.py datadict <COPYBOOK>`.
5. Check [hidden-behaviour](hidden-behaviour.md).
6. Write `modernization/programs/<NAME>.md`, following the program template.
7. Record rules with `mma.py record rule` as you find them. See [requirements](requirements.md).
8. Finish with `mma.py analysis program <NAME> --output <file>`.

## How to explain it

- Start with what it does for the business, in two or three sentences.
- Explain behaviour, not statements. Say "applies a 5% discount to orders over 10,000 for preferred customers (lines 45-47)", not "IF CUST-RATING = 'A' AND...".
- Compare to Java only where it helps, such as "this paragraph works like a private method, but the next one runs next unless control jumps".
- Follow the real path. `PERFORM THRU` and `GO TO` mean paragraphs don't always behave like methods.
- For hardcoded values, state the value and where it is, and raise an SME question if the reason isn't visible. Don't invent one.
