---
name: story_support
description: Shared plot planning, sourced story context, continuation checks and confirmed archive updates.
type: python
---

`context --chapter 0001` prepares the same story context used by the workbench assistant.
`commit --chapter 0001` confirms the accepted chapter's state from existing observer/arbiter outputs.
`preflight --chapter 0002` checks continuity and outline coverage before continuation.
Deleted chapters are recorded under `archive/chapter_resets/`. Preflight blocks
continuation across a deleted chapter until its body and confirmed archive are
rebuilt. `refresh` rebuilds shared archive views from valid chapter snapshots,
including clearing obsolete hook/debt indexes when no confirmed chapters remain.
`begin-reader` / `commit-reader --chapter 0001` bind the evaluation to the
reviewed body and save it under `story/0001/reader_report.json`. The shared
`quality/reader_report.json` remains a compatibility copy of the latest report;
it is never used to revise a different chapter.

Confirmed characters, world facts, hooks and debts require `evidence`: one
continuous quotation as a string, or a nonempty array of independent continuous
quotations. Every quotation is checked against the reviewed chapter. Whitespace
formatting may differ; invented or changed wording is rejected. Legacy strings
containing separate sentences/lines are checked passage by passage and saved as
an array. Chapter and source hashes must still match the review snapshot.

Original upstream files and pinned versions are retained under `vendor/`. Runtime adapters are in
`upstream.py`; no upstream service, credentials or autonomous write loop is started.

Plugin-owned `archive/longform.sqlite3` stores durable publication intents and run
receipts. `recover` replays compatible pending commits; `abandon-commit --chapter
0001` explicitly preserves and abandons a conflicting intent before fresh review.
See the plugin's `docs/longform-p0.md`. No command changes novel prose or style.

P1 adds `recall --chapter 0201 --query "..."` and `impact`. Shared context
automatically includes sourced distant passages, explicit alias ambiguities,
separate character cognition, correction chains and temporal boundaries.
The disposable SQLite memory index is rebuildable; canonical evidence stays
in P0 snapshots. See `docs/longform-p1.md` for optional registry/event schemas.

P2 adds `serial --serial-action status --chapter 0031` and the outline workflow's
rolling branch. It plans only unwritten chapters within the book's declared
volume scope, validates actual handoff/progress, and publishes through P0.
`serial --serial-action approve` adopts an unchanged author-reviewed candidate
for the current TASK_ID. Continuous dispatch budgets and task reservations are
durable across restarts. See `docs/longform-p2.md` for book-owned configuration
and the limits of offline verification.
