# Manuscript quality

Plugin-owned deterministic prose length evidence. Uses the same sibling console-service length policy as automatic production; no provider or user configuration is changed.

- `guidance --chapter 0001 --target 4800-5200`: measures the current body and publishes `length_context_file` with a concrete addition/deletion budget.
- `gate-reader --chapter 0001 --target 4800-5200`: requires a current hash-bound reader report, records actual length, and prevents a model pass from overriding the author's length range. Keeps the legacy report alias in sync only when bound to the same body.

Counts Chinese characters and Latin/numeric words, excluding titles, punctuation and whitespace. Blank targets preserve unspecified legacy books. Checks do not modify chapter text. Automatic production keeps original drafts and prior feedback during bounded correction attempts.
