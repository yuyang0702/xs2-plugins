---
name: story_support
description: Shared plot planning, sourced story context, continuation checks and confirmed archive updates.
type: python
---

`context --chapter 0001` prepares the same story context used by the workbench assistant.
`commit --chapter 0001` confirms the accepted chapter's state from existing observer/arbiter outputs.
`preflight --chapter 0002` checks continuity and outline coverage before continuation.

Original upstream files and pinned versions are retained under `vendor/`. Runtime adapters are in
`upstream.py`; no upstream service, database, credentials or autonomous write loop is started.
