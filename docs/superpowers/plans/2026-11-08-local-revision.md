# Local Revision Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD per interface, one fresh final reviewer. Preserve existing authorized uncommitted work.

**Goal:** all content polishing uses exact local edits and independent expression acceptance; both adviser entries read effective per-book rules.
**Architecture:** reuse draft_guard/revision_patch.py; new plugin-owned local_revision entrypoint for freeze/compose/review/commit; shared expression evidence helper; extend book_contract resolver for pending adviser settings.
**Tech Stack:** Python, JSON workflows, existing WorkflowEngine/AgentNode, configured model transports.
**Spec:** ../specs/2026-11-08-local-revision-design.md

## Global Constraints
- Product changes only in xs2-novel-flywheel. No original manuscript edits, commits, pushes or publishing.
- Preserve author-controlled POV, ornate/plain language, intentional repetition, exposition and narrative pace. No quotas or detector-score gates.
- Continue the current feature checkout; snapshot the delivered baseline before changing it. Prior P0/P1 work is a dependency.
- Content revision uses exact-source patches, protected phrases and current-body evidence; length-only revision remains supported.
- Use only authorized configured providers for five copied-book validation. Keep negative results and all raw output.

## Review Focus
- A manuscript, feedback file, book rule or review changes during a model call; old acceptance must not publish.
- Empty edits, deletion of whole paragraphs, repeated substrings and whole-book restructuring without changed-percentage limits.
- A new book has no formal world/style files, or pending UI values differ from disk; adviser must see effective current choices and declared override precedence.
- A factual pass conceals expression blockers; an allowed stylistic device is mistaken for an exemption or a prohibited form.
- Retry of a changed candidate, stale professional review, crash immediately after atomic publication, and legacy length-only recovery.

## Task 1: Adviser contract propagation
Files: prose_policy/book_contract.py, console_service/assistant.py, workflows/novel-advisor/definition.json, tests/test_advisor_book_contract.py.
Interfaces: resolve(root, project=None), freeze(root, task_id, project=None), adviser input includes the effective object and digest.
- [x] RED pending project vs disk, JSON override, missing formal archives, request freeze/drift and standalone input path.
- [x] Extend the existing resolver and adviser paths; keep proposals optional and existing files intact. GREEN affected assistant/contract tests.

## Task 2: Expression evidence and local polishing
Files: new prose_policy/expression_review.py and local_revision/local_revision.py; polish workflow/roles; reader_review and expression schemas; regression tests and reusable expression eval fixtures.
Interfaces: expression check schema/validation; local prepare → frozen critic → editor input → patch candidate → independent review → atomic commit, all task-bound.
- [x] RED exact unchanged spans, no-change, protected phrases, malformed/stale review, source/feedback/book drift, real source changes, recovery and bounded rejection.
- [x] Require evidence and functional/style reasons for expression checks; preserve legacy reading. Add paired examples from this diagnosis with styles to preserve.
- [x] Wire content polishing to local edits and independent review. Preserve existing length-only route and appropriate model routing. GREEN affected scheduler/quality/output tests.

## Task 3: Final review, sync and five real copy validations
Artifacts: C:/xs2/data/verification/20261108-local-revision-v1.
- [x] Full tests and fresh whole-change review against this turn's frozen baseline; fix material findings RED→GREEN.
- [x] Existing local PluginManager sync; installed/source/runtime resource checks and settings preservation.
- [x] Five copied books: adviser sees rules; actual program content revision and independent reader evaluate generic functional expression issues while preserving each style and hard facts.
- [x] Verify originals and delivered files unchanged; final evidence/assessment report and five linked revised copies. No invented Zhuque result.

## Ledger
Ruling: user explicitly approved the preceding diagnosis and requested these three changes plus copied-book validation; no second design/permission gate. No new scope is inferred.
Ruling: work in the existing feature checkout with a frozen baseline, because a clean checkout would omit the prior authorized P0/P1/contract work; no Git writes.
Ruling: native Python ledger setup substitutes for unavailable Bash helpers, as in the previous task. The ledger is durable; it does not authorize deleting other plans' workspaces.
Pre-flight: adviser resolver changes feed both UI and workflow; expression validation feeds independent reader and local commit; local patch output must remain separate from focused length-only body output.

User steering: the five books are regression samples for one generic pipeline, not per-book repair tasks. Copies start with author world/style intact and old editorial repair requests inactive; all receive the same fresh reader → local revision → fresh reader workflow. No hand-written per-book corrections or title/genre branches.
