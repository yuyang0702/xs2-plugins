# Plugin performance P0: preserve evidence and literary freedom

User approved three P0 changes: deduplicate per-request context, reuse valid results across tasks, and compact reports with role-local retries. All production code stays in xs2-novel-flywheel. Existing original manuscripts and the paused100k experiment remain untouched. No model downgrade, new literary constraints, audit dimension removal, or restoration of the longrun is authorized.

## Design

1. Add a deterministic model-facing context projection. Canonical source/editor/review inputs remain complete and frozen for all existing validators. Prose is presented once as ordered paragraphs with exact intervening whitespace, reconstructable byte-for-byte; paragraph references remain usable. Remove redundant full-body/paragraph/clause-text copies and the external duplicate contract when it already exists inside the packet. Retain the contract guidance, every rule, every author source, goals, and the complete source and candidate. Apply to local critic/writer/reviewer and independent blind-reader input, all book styles.
2. Reuse only independently approved signed chapter composition plans when all semantic dependencies match: body, report, feedback provenance, author intent/scope, chapter plan, conflict, macro progress, model selection and relevant plugin code/prompts. Operational task ids and refs do not invalidate an otherwise identical plan. A cache hit bypasses planning/review calls, writes a source-guarded P0 reuse receipt and revalidates it at the shared emitter. Changes or tamper cannot obtain old approval. Final body review is never cached across changed prose. Existing native retry/checkpoint and memory-index mechanisms remain.
3. Add local-review v2 as an additive wire format. Model still judges every fact issue, all expression dimensions, every edit's net effect, and every goal. It returns semantic verdicts, reasons and actual evidence refs. The program binds immutable hashes to the actual response and expands edit_index into exact old/replacement evidence; it keeps raw response and expanded audit. Full v1 gates stay authoritative after decoding. v1 compatibility is retained. Missing semantic fields and invented references fail; format failures retry only the reviewer and content failures only the writer.

## Validation

RED/GREEN tests for lossless LF/CRLF/BOM/poetry/empty text projection and model-view tamper; per-book style/rules presence; cache hit and invalidation on every dependency, no changed-body pass reuse; v1/v2 equivalent gate outcomes for fact/cognition/expression/style/goal/partial-deletion defects; real scheduler cache/bypass and responsible-role retry. Full plugin regression and fresh read-only whole-change review.

Freeze pre-change plugin at C:/xs2/data/verification/20261109-performance-p0/baseline-plugin. Paired copy validation uses identical frozen source/candidate and same configured approved analysis model. Compare serialized input/output size, provider-reported tokens/timing, gate outcomes and known-defect detection; reuse test measures skipped planning calls. Never claim universal literary equivalence or a speed multiplier from a small sample. Preserve original and paused-run manifests before/after; no longrun launcher.

## Rulings

- Continue in existing dirty checkout: it contains authorized P0/P1/P2 fixes not committed to Git. A complete independent plugin baseline snapshot provides comparison isolation without losing those changes. No commit/push or worktree creation is needed for this request.
- Conservative P0 reuse covers approved composition plans, not semantic approval of a changed draft. Broader mutable working-draft and parallel-judge designs are outside this P0.
- New benchmark copies are bounded review comparisons using the same previously approved book material, services/models. They do not run the stopped100k controller or generate replacement manuscripts.
