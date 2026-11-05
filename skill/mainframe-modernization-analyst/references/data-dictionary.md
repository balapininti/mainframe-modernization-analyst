# Data dictionary

Run `mma.py datadict <COPYBOOK>`. It writes `data/<COPYBOOK>.md` and `.json`, with each field's level, picture, usage, byte offset, length, suggested Java type, traps and source line.

Then add what the script can't know:

1. Explain what each important field means, marked as your inference unless the source or a person states it. Add these in `data/<COPYBOOK>-notes.md`.
2. Raise SME questions for codes and flags whose meaning isn't clear.
3. Point out fields whose values are defined only by 88-levels or by hardcoded checks in programs.

Offsets assume the copybook is complete. If it has nested `COPY` statements or `REPLACING`, or the layout looks wrong, say the offsets need checking. Java types are suggestions, and the architect decides.

Finish with `mma.py analysis copybook <COPYBOOK> --output data/<COPYBOOK>-notes.md`.
