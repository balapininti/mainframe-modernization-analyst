# Spring Boot mapping

Run `mma.py mapping <SLICE-ID>`. It writes `mapping/<SLICE-ID>.md`, listing what's in the slice, with a suggested equivalent and what to watch out for.

These are suggestions for an architect, not decisions. Do not write any code, classes or configuration.

Add your reasoning where it matters:

- **Boundaries:** programs aren't services. Group by business capability, and say what you'd merge or split, and why.
- **Transactions:** where commit and rollback fall today, and what must stay atomic.
- **State:** where pseudo-conversational state lives between screens, and options for it.
- **Batch:** restart, chunk size, job dependencies and the batch window.
- **Integration:** files, queues and downstream consumers whose format must not change.
- **Sharing data:** tables and files that online and batch both use, including during migration.

Present real trade-offs and open decisions for the architect. Check [hidden-behaviour](hidden-behaviour.md) for each item.
