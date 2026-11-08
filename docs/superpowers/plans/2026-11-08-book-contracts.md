# Book Contracts Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; preserve existing uncommitted P0/P1 work. One fresh final whole-change reviewer.

**Goal:** world/style-aware writing, review and local revision across novel types, validated with five real generated stories.
**Architecture:** plugin-owned book contract helper; task-bound propagation through existing context scripts; exact patch/evidence helpers before existing guard adoption.
**Tech Stack:** Python, JSON workflows/roles, pytest, host WorkflowEngine and configured model transport.
**Spec:** ../specs/2026-11-08-book-contracts-design.md

## Global Constraints
- All product changes remain in the plugin. Original manuscripts remain byte-identical.
- Continue the existing feature checkout without reverting prior P0/P1 changes, committing, pushing or publishing.
- Preserve world and style independently of genre. Default to existing voice; do not force limited POV, white-description prose or a transaction sequence.
- Use real model/workflow outputs and retain negative results. Five final samples each <=5000 real words.
- Use existing local install machinery; preserve settings/enabled state. Use only the already authorized configured lingsuan and volcengine providers for generated tests.

## Review Focus
- A world/style file changes while a completed intermediate node is reused.
- Omniscient/variable POV, deliberate refrain, unreliable perception or explanatory prose is wrongly rejected as universal bad writing.
- A patch targets the wrong repeated substring, overlaps another patch or changes protected language.
- Evidence IDs refer to an old body, an invalid range or another payment.
- Blank contracts, legacy plans/reports and stories with no economic transactions remain usable.

## Task 1: Book contract and propagation
Files: new prose_policy/book_contract.py; story_support, multi_scene, draft_guard, reader_review; relevant workflows/configuration; tests/test_book_contract.py.
Interfaces: resolve(root), digest(contract), freeze(root,task_id), public_style(contract). Frozen contract is data, never model-generated policy.
- [x] RED: distinct worlds/styles, default preservation, schema/path validation, public style excludes private world/intent, drift detection and no book-specific shared instructions.
- [x] Implement contract resolution/freeze and common propagation; remove specific transaction/limited-POV assumptions. Preserve declared narrative-led preferences and source projection.
- [x] Bind scene/guard/reader operations and allow functional repetition/variable narration; run affected tests GREEN.

## Task 2: Local expression patches and exact evidence
Files: new draft_guard/revision_patch.py and multi_scene/audit_evidence.py; guard/continuity/review helpers and workflow schemas; tests/test_revision_patch.py and test_audit_evidence.py.
Interfaces: paragraph catalog; apply_patches(source,payload); evidence_catalog(body,units); resolve_report(report,body,units).
- [x] RED: exact substring occurrence/hash/overlap, unchanged source preservation, protected phrase loss, length rejection before audit, references/ranges/stale reports and contextual error messages.
- [x] Implement patch output on the current production expression route, retain legacy body input; include measured length in repair feedback and reject unusable candidates before audit.
- [x] Resolve current-body reference IDs into actual quotes; keep independent semantic checking and all existing arithmetic/order protections. Test actual scheduler recovery GREEN.

## Task 3: Verification, local sync and five real samples
Files: task-scoped harness/artifacts under C:/xs2/data/verification/20261108-book-contracts; plugin docs/evals only where reusable.
- [x] Full plugin suite, fresh final review and one RED→GREEN fix pass for material findings.
- [x] Freeze source and original-book hashes. Sync local plugin with existing PluginManager; verify installed checkout/runtime resources and preserve enabled/settings state.
- [x] Create five independent author fixtures (agent choices, not user-specified plots): 古风/节制叙述，言情/第一人称抒情回环，末日/限知快节奏，科幻/全知与技术说明，玄幻/非现实世界规则与华丽意象. Target2500—3500 real words, absolute max5000.
- [x] Generate via actual program workflows and configured models; review each whole text, preserve attempts and report style/logic/length/closure. Do not manually write prose to force a pass.
- [x] Final hashes/diff checks, reports and five linked manuscripts; explicitly distinguish tested mechanisms, generated-text quality and unperformed Zhuque scanning.

## Execution ledger

Ruling: continue in the existing feature checkout — this is the user's ongoing work with substantial uncommitted prerequisites; a clean checkout would omit authorized P0/P1 changes. No branch integration or remote write is included.
Ruling: the user already approved this architecture in the preceding exchange and explicitly requested implementation; do not add another design/permission stop.
Pre-flight: task1 contract feeds task2 contexts and task3 fixtures; helper schema/public style and digest are the shared interfaces. Task2 references bind actual candidate SHA before any resolution. Source snapshots must be final before live generation.

Task1 core:11 new contract tests RED→GREEN; affected story/prose/reader/scene/guard/handoff suite147 passed108.46s. Author-facing narrator_scope/style_intent settings added after their own RED→GREEN case. Optional meta/narrative_contract.json overrides values and includes intentional devices/protected phrases; existing effective style/world archives are included. Genre never supplies hidden style defaults.
Task2 core:14 patch/reference tests RED→GREEN, early-length regression GREEN. Two integration name-shadowing mistakes were identified from stack traces and fixed (evidence/feedback locals), with existing math tests preserved. Production workflow expression output now uses patches; new report schemas support current-body IDs/ranges and book-contract hashes. Affected workflow/resource/reader/guard suite78 passed18.62s, including real scheduler retry of changed candidates.
Ruling: nonfinancial physical stocks need separate dimensions, not fake currency conversion. Added optional resource_ledgers with grounded opening, transfer/event and balance checks; two regressions RED→GREEN and40 quantity/reference cases passed. Resources are applicable declared ledgers, not mandatory transactions for every story. World semantics remain model-reviewed under the book contract.
Ruling: no Bash executable was available for the skill workspace helper; created equivalent ignored .superpowers/sdd/2026-11-08-book-contracts with a plan-scoped ledger using native Python. Original366-file baseline frozen under C:/xs2/data/verification/20261108-book-contracts.

Full pre-review suite1040 passed273.62s. Fresh reviewer review_book_contracts found5 material gaps: default single writer bypass; task freeze mismatch on downstream prepare; alternate focused-length writer missing contract/binding; replaced-scene assembly losing profile; reader schemas rejecting promised references. All reproduced as failing tests (single route plus6 recovery tests), then fixed GREEN19. Single and multi now share frozen planning and join at the same guard. Focused writer execution and both commit checkers bind the book digest; source drift is blocked. Added a separate RED→GREEN binding for existing prose-preference mode/instructions.
Final full run exposed2 regressions: the older polish_post commit checker needed the added digest, and a route assertion assumed the old direct plan→multi edge. Corrected the checker and updated the intended graph assertion;35 focused/recovery/scene tests passed5.06s. Final full suite reruns. No validation gate was relaxed.
Five controlled author fixtures are saved in verification/author-cases.json; plugin world/character preparation created five new book workspaces. No story prose has been manually authored. Two single-writer and three multi-writer cases cover the complete production paths.

Live trial v29 exposed a general quantity bug: ordinal 第二枚 was parsed as cardinal two. Added two RED→GREEN cases, kept the failed planning replies, and froze v30. Its full suite1050 passed281.88s. The same apocalypse story then exposed omitted-unit zero (可用模块，零) and auditor misuse of nonnumeric possession as a numeric balance. Added two more RED→GREEN cases, exact diagnostics and numeric-only observation instructions; nonnumeric possession remains a semantic check. Frozen v31 full suite1052 passed284.23s. Re-audited the unchanged v30 facts candidate with freshly rebuilt v31 evidence and a new actual model audit, then completed expression review and publication; no approval or prose was fabricated.
Late whole-resource review found26 old universal POV paragraphs across7 workflows, conflicting with the newly appended book contract. A new failing regression reproduced this. Removed the obsolete constraints, retaining human-selected scope and separating narrator access from character knowledge. Character workflow version increased11→12; its strict version regression was updated after observing the sole expected failure in the first v32 full suite (1052 other cases passed). Two focused regressions GREEN. Final v32 full suite running.
Frozen final v32 resources150 files. PluginManager install and ExtensionManager cold load match source byte-for-byte; MVP32, installed content b4641eece43550345dbe7de3f786f58a53f339b591dd27ffb3ef241030f122c5. User settings/enabled state unchanged. No configured UI server was reachable; no claim of reloading a running UI process.
Five actual MVP stories completed: ancient2722, romance2601, apocalypse2609, scifi2904, fantasy2718 real words. Initial deterministic guards pass, including a final-validator replay that first resolves each old audit using its own frozen catalog algorithm. Independent P0 readers passed ancient/romance/apocalypse with low optional expression notes; fantasy and scifi correctly requested repair for missing causal preparation and repeated interpretation. Running their existing plugin polish and fresh independent reader workflows rather than calling the initial drafts final passes. Preserve all initial texts, failed trials, replies and versions. Model transport adapter now explicitly includes the exact native completion schema to prevent scalar-versus-array output mistakes.
Final v32 full1053 passed286.72s. Both scifi/fantasy completed2 actual polish rounds, not manual prose edits. The scifi author fixture explicitly supplemented a compatible volatile-cache/power-budget mechanism; fantasy author feedback clarified voluntary choice among other valid memories without inventing a universal most-precious-memory rule. Final lengths3014/2788. P0 still reports specific redundant explanations; a valid revise is an honest quality outcome, not a failed generation or permission to fabricate pass.
Later P0 scrutiny distinguished genuine core causal support from optional algorithm thresholds. Added a genre-neutral minimum-necessary-detail policy for science, magic, institutions and crafts; it retains real contradictions and unsupported costs/choices. A final fantasy report also exposed malformed context issue IDs and blind revise-with-no-blocking-issue responses. Added stable required context IDs and report-only feedback/bounded rejection to each responsible auditor. Four cases distinguish malformed model reports from changed source data: RED→GREEN, originals never rewritten; source drift still stops. Final reader16/source snapshot34. The actual fantasy v34 run exercised a blind report rejection, retried the real model, accepted a valid second report, and continued to context review. Final full1057 suite running.
Final local sync uses content d3934fd4a7922b99249d00afab362fa71fc335b9db50f3f6307d53acb7eb462a:150 source/installed resources equal, cold-loaded MVP32, reader16; settings unchanged. v33 full test run was superseded and stopped using its exact dedicated process command, not counted as passing.
Completion: the first v34 full run1055 passed/2 failed because the accepted context-report fixture lacked the newly required stable id. Updated that fixture (no validation relaxation). Final complete suite1057 passed282.67s; log C:/xs2/tmp/book-contract-v34-final2.log. Re-synced the test-fixture update too: final installed content1097c8e5ef3cee448aca7f34759bfcae692c70e6c577d732b9a3519c80c11eef, all150 runtime resources match final snapshot34 and source, settings unchanged.
Completion: scifi's third real polish round only removed three specific redundant explanations, preserving the mechanism and clocks; final2859 words and new independent P0 pass. Fantasy final2788 and new independent P0 pass, including actual blind-report retry. Final five lengths2722/2601/2609/2859/2788, all P0 pass. Full-text reads and exact manuscript hashes are in manual-assessment.json; low-priority expression observations remain visible. All initial deterministic reports were replayed with the final validator after matching-version reference resolution; revised stories use fresh independent reports bound to the final bodies and current book contracts. The final report builder asserts these bindings, original366-file equality, source/installed resources and1057 test evidence before writing verification-result.txt and verification-status.json. git diff --check clean. No Zhuque rerun, commits, pushes or original edits.
