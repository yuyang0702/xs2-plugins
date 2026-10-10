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
`upstream.py`; no upstream service, database, credentials or autonomous write loop is started.
