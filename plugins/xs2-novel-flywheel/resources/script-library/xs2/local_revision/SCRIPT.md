---
name: local_revision
description: Freeze book-specific content revision, apply exact patches and publish only after independent factual and expression acceptance.
type: python
---

`prepare --chapter 0001 --target RANGE` freezes the current manuscript, effective book contract and source/feedback fingerprints. `writer-input --dir DIR --critique PATH` freezes the normalized critic handoff. `candidate --dir DIR` applies exact paragraph edits, preserves untouched bytes/protected phrases and checks length before review.

Workflow `--context`, `--learning-context` and `--feedback` select the current effective runtime inputs; optional feedback overrides the project selector for this task. Current/prior chapter source files, planning, adopted expression settings and selected feedback are fingerprinted. An omitted word target permits revision without a hidden minimum. After a writer retry, commit rebuilds a changed candidate and forces a fresh independent review even when the host retains completed intermediate nodes.

Writer rejection feedback includes the actual previous rejected edits, marked as unpublished diagnostic data. A new writer session can compare its earlier changes without rebasing the frozen original or adopting failed text as book facts/style. Reviewer-only format retries do not receive an unrelated writer packet.

The independent reviewer has five bounded automatic retries across the combined format-fix / writer-change / fresh-audit path; this is workflow recovery capacity, not a literary quota. Every candidate still needs its own matching audit and all acceptance checks.

`commit --dir DIR --review-stdin` requires this task's actual review JSON on stdin and verifies candidate, book and review-input hashes, quoted change effects, unresolved goals and expression evidence. Invalid model outputs retry only the responsible agent; source drift stops. A crash after atomic publication is recoverable without restoring older prose. No lexical quota, detector score or genre preset decides acceptance.
