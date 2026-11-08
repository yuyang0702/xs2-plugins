# Draft Consistency Implementation Plan

> **For agentic workers:** use superpowers:executing-plans; preserve existing uncommitted P0/P1 work.

**Goal:** source-bound money/fact/state checks and ordered hard-fact then expression repair in the plugin.
**Architecture:** multi_scene contract plus prefix handoffs; plugin draft_guard CLI and independent audit/repair nodes before rendering.
**Tech Stack:** Python, JSON workflow/role resources, pytest, existing host scheduler and configured model transport.
**Spec:** ../specs/2026-11-07-draft-consistency-design.md

## Global Constraints
- No host product changes, original-book writes, publication, commits or pushes.
- New verification directory; freeze all original hashes and resources.
- Honor existing model selections and authorized destinations.
- Deterministic checks use declared units and exact grounded spans; do not encode this novel in product code.

## Review Focus
- Audit omits a planned transfer or names a correct amount beside an incorrect quote.
- Duplicate/unordered handoff events, prior/future scene leakage and wrong canonical aliases.
- Repaired candidate changes while its intermediate audit node remains completed.
- Expression repair regresses approved money/facts/POV/handoff.
- Historical plans, source/contract drift, malformed numeric values and empty financial stories.

## Task 1: Grounded contracts and evidence checks
Files: resources/script-library/xs2/multi_scene/continuity_contract.py; tests/test_continuity_contract.py.
Interfaces: validate_contract(data, sources, scene_count); amount(text, units); audit_issues(report, candidate, contract, phase).
- [x] Tests RED for incorrect payment arithmetic, balances, ordering, source grounding, fact observations, POV/repetition findings, missing/stale audit proof.
- [x] Implement exact integer arithmetic, strict evidence/schema checks and priority ordering; GREEN.

## Task 2: Writer continuity and ordered guard pipeline
Files: multi_scene.py, scene_allocation.py, new draft_guard CLI; mvp workflow; prompts/agents; production model selection; tests/test_draft_guard.py and real scheduler coverage.
- [x] Contract in current planner; canonical per-scene briefs; preceding prose handoffs that exclude later scenes on recovery.
- [x] Hard-fact repair/audit/commit, then expression repair/audit/commit before SI/render; fail closed on hard regression and stale proof.
- [x] Observe recovery failures RED, implement GREEN, run plugin suite and existing host graph tests; one fresh final code review and regression fixes.

## Task 3: Copy model verification
- [x] Freeze new copy, original baseline and resources; feed actual previous failed P1 output into the post-assembly guard.
- [x] Run real repair/audit nodes; preserve all failed replies and distinguish quality results from mechanism checks. P0 two-stage reader was not entered because expression never obtained valid approval; this is a negative copy result, not a passing final manuscript.
- [x] Original hashes unchanged; write evidence and final limitations.

## Execution ledger
- User directly requested these fixes and copy revalidation following the concrete findings. Continue within that approved scope without another design/permission round; implementation choices above are agent decisions.
- Continue in the existing feature checkout; do not revert or commit the uncommitted P0/P1 changes. Use task-scoped checkpoints under C:/xs2/data/verification.

- Task1: exact arithmetic and grounded observations tests observed RED then GREEN. Shared contract, source SHA, prefix handoff and expression-stage hard regression coverage added. Real scheduler verifies fact-before-expression and refreshes the completed auditor after a writer retry.
- Fresh review found five material gaps: unsupported opening balances, underconstrained unit factors, unrelated/overlapping change, balances at wrong narrative times, and trailing half-unit truncation. Six regression tests observed RED for all gaps; fixed with grounded nonzero openings, full-rank exact unit equations, same-event disjoint amounts/change, temporal balances and trailing-half support. All25 money/contract tests GREEN. No review findings deferred.
- Integration initially exposed direct condition convergence escaping a branch stop; fixed with executable guard_finish join and fail-closed unprepared path. Existing host plus guard scheduler suite29 passed. Earlier full suite3 failures included a concurrently updated route assertion, new script inventory and missing recognition of frozen story context; corrected source/context coverage rather than injecting an unbound duplicate. Final full suite in progress.

- Final post-review plugin suite:1002 passed in247.93s. Host graph plus guard integration:29 passed in14.76s. Source changes stay in plugin. New copy and resources frozen at C:/xs2/data/verification/20261107-draft-consistency; original366 files untouched. Actual plan/contract generation is running via the already authorized lingsuan service.

- Live planning pressure tests exposed two prompt-delivery defects: the model emitted parts arrays without seeing its full schema, and then mixed long narrative rules into the literal name table. Both replies were rejected, preserved, and source task messages corrected. Version21 now shows the exact output schema and restricts facts to sourced names; broader semantics remain in source_constraints/events/transfers. Fresh copy v3 planned successfully in182.45s with the four cash flows6000/1200/1000/20 and final balance3780; no accepted artifact or raw output was manually edited. Final affected resource/guard suite101 passed in23.59s. Baseline negative replay underway.

- v3 negative replay completed with a real independent audit (421.23s). Script recomputation found actual paper payment1020 versus required1200; audit also found inconsistent shop name, ambiguous repeated receipt/handover, missing batch acceptance, invented tail total/background and POV overreach. No manuscript was published. Live output also reproduced two false positives: ordinary document references treated as renamed entities, and a post-payment balance inside a broader event quote treated as early. Two tests observed RED→GREEN. Version22 adds name/referent matching modes with explicit semantic same-referent evidence and anchors balances to actual paid/change spans; name drift and early/skipped balances remain blocked. Audit instructions now request distinct name variants/minimal action clauses, reducing redundant evidence. Fresh copy v4 plans the final snapshot; it will run the repair pipeline on the same imported failed P1 body, while v3 retains the negative proof.

- v4 writer left paper underpayment and handoff/POV faults, which its actual auditor and script rejected. The real audit also exposed ordinary descriptions of named parties (旧铺/中年男子) being treated as renames, and nested event quotes falsely proving reverse order. Two further tests RED→GREEN; v23 adds per-occurrence is_name classification and treats overlapping event proof as invalid audit input to be narrowed, rather than automatically rewriting correct actions. Money/contract suite29 passed. v5 uses a fresh source snapshot, exactly revalidates/reuses unchanged actual v4 planning input/output, and carries the body-hash/quote-bound real v3 critique as editing feedback (not approval) into actual model repair. Current full suite in progress.

- v5 actual writer fixed paper amount but still left duplicated silver transfer, POV overreach, and state inconsistency (accepted batch later called unknown); independent audit rejected it, expression never ran. Based on this real failure, v24 routes hard-fact repair to the configured analysis model while expression retains body writer. Public model_overrides regression observed RED→GREEN. Fresh copy v6 replays only identical actual planning and same-body actual critique, then makes new real repair/audit calls. The previous successful full suite was1006 passed in247.45s; final v24 suite is running.

- v24 full suite1007 passed in246.35s. v6 analysis-model repair produced5099 real words; its independent audit found no semantic issues, but the script rejected an overlapping change/balance quote and title/short-form name classifications. These were evidence errors, not an instruction to rewrite correct payments. A focused overlap regression observed RED→GREEN: overlapping balance/payment evidence now returns to the auditor for narrower proof while genuinely early balances remain blocked. v25 additionally tells both auditors to distinguish established short references and surname/title addresses from formal new names. Existing name-drift protection remains intact. All30 contract tests pass. v7 freezes a fresh resource snapshot and imports the unedited actual v6 model JSON as candidate, with source hash/provenance, for a new independent audit; this is neither a new writer call nor a reused approval. Final full regression and live validation are running.

- v25 full suite1008 passed in278.57s using an explicit workspace basetemp. The first default-temp run had WinError5 setup failures at the inaccessible pytest-of-yuyan directory; no product failure was hidden. v7's actual audit accepted names/POV/order but treated remaining silver as the entire mixed-cash balance and incorrectly estimated the5099-word candidate above5300. v26 adds exact disjoint balance components, allowing only amounts within the balance claim or that transaction's retained change, rejecting duplicates and unrelated cash (two regressions RED→GREEN). Audit inputs now include program-measured actual_word_count; auditors do not classify guessed word counts as hard facts, and final expression commit still enforces the actual bound. All32 contract tests pass. Fresh v8 freezes this snapshot and independently re-audits the unedited actual v6 candidate before expression; no approval or prose was fabricated.

- v8 facts audit completed178.73s with no semantic issues; the exact program checks accepted all money/fact/order observations, including disjoint3700 silver plus80 retained change. facts-approved bodySHA=c6160bcc4ed25d381ef888c72679840cad13a2f70b569dea311234e0ecee9e53 (5099 real words). The workflow has now entered the real configured expression writer; final approval and P0 reader remain pending.

- Final v26 full plugin suite1010 passed in252.45s, explicit workspace basetemp; git diff --check clean. First actual expression writer returned3375 real words and changed the past persuader from陆 to沈. Its real independent audit detected that actor regression, and the guard rejected it before adoption. Preserved the complete first guard/task/result snapshot under v8/expression-attempt-1. One bounded writer retry receives the genuine actor finding plus an explicitly recorded verification-harness reminder of measured3375 versus5000—5300 and source5099 (editing input, never approval); all new proof must still be generated and checked. No prose or accepted receipts edited.

- The second actual expression writer completed145.46s and returned4996 real words. Actual host recovery kept the intermediate auditor completed; commit correctly refreshed candidate context and rejected the stale auditor, never approving the new body with its old report. Resumed the same task solely for a new independent audit. The4-word lower-bound shortfall remains unresolved and is not silently tolerated.

- Closing result: the second expression auditor completed561.97s but provided one non-current event quote (protect-sample paragraph); the guard rejected its invalid proof. Its semantic issues array was empty, which is not treated as approval. The4996-word expression draft remains unapproved and under the configured lower bound; no final adoption or P0 reader run claimed. The5099-word fact-approved candidate and both expression attempts/raw replies are preserved. Final reports: C:/xs2/data/verification/20261107-draft-consistency-v8/verification-result.txt and verification-status.json. All366 original files remain byte-identical.
- One final narrow arithmetic edge was reproduced RED→GREEN: incoming-payment change belongs to the other payer and cannot supplement the receiver's claimed cash balance. Added the direction condition; final affected contract/guard/real-scheduler/handoff suite46 passed in14.01s. Actual-model runtime snapshot remains immutable; final-resources separately freezes current source, and the final validator recomputed the same real body/contract/audit proof. The novel's retained change is from an outgoing purchase, so facts approval remains valid. Last full suite1010 passed before this one-line stricter check; final affected suite covers the change. No manuscript/proof was manually repaired to force approval.
