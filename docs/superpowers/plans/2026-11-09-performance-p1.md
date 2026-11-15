# Performance P1 Implementation Plan

> Execute inline with superpowers:executing-plans and test-driven-development; one fresh whole-change reviewer. No commit/push requested. Preserve prior changes.

**Goal:** Retain verified useful patches and overlap independent reviews without weakening quality or imposing style.
**Architecture:** Original-anchored signed pending edits; parallel reader branches with conditional dependent reconciliation.
**Tech Stack:** Existing Python, P0 signed derived views, native workflow parallel/converge gateways; no new host code or dependencies.
**Spec:** docs/superpowers/specs/2026-11-09-performance-p1-design.md

## Global constraints

Plugin only; original and paused100k book byte-identical; same approved models/routes for bounded copy review; no longrun/writer launcher. All quality gates and retry limits unchanged. No uniform literary constraints.

## Review focus

- A fact-rejected draft cannot become a pending baseline.
- A valid retained patch cannot vanish because a fresh writer omitted it.
- Mutated pending material, source or prompts cannot inherit old judgment.
- Blind findings and restricted/unclear author scope still get dependent reconciliation.
- Parallel branch errors cannot publish a partial report or rerun a healthy model branch.

## Tasks

- [x] 1. Add pending_revision helper and local_revision integration: test retained+new patches, explicit update, overlap, source/code tamper and restart; RED then minimal implementation then local/full-wire regression.
- [x] 2. Add independent contextual preflight validation, conditional reconciliation and native parallel reader graph: test no blind leakage, final merge parity, findings fallback, branch failure/restart and actual overlap; RED then implementation then native regressions.
- [x] 3. Paired copied-book comparison using frozen P0 baseline and same approved model; retain raw results/usage/latency and source hashes. Full tests, fresh review and fixes, install/coldload without resuming100k.

## Ledger

- COMPLETE: final local audit re-rendered all10 actual validated model requests and system prompts byte-for-byte from current source; checked all installed169resources+4runtime files against source; host Git clean. Installed99d70c17957ed296a0b6407c314668d5e6949f2e2aa904ded5531c89af93aaa5, cold-load loaded, user settings unchanged.867 paused-book files and98 original files unchanged, paused=true/autoNext=false/autoArmed=false. See C:/xs2/data/verification/20261109-performance-p1/validation-summary.json and tmp/performance-p1-final-check.log.
- Live comparison complete: normal baseline/new both fact pass/expression revise,371.582s→315.454s; model calls2→3 because blind finding required dependent reconciliation. Known t=10→t=6 defect caught by both, both refuse quality pass. New negative sample356.173s; old negative sample resumed after2first-chunk timeouts, elapsed excluded from speed claims. Only isolated benchmark first-chunk wait changed120→300s; no host model settings, model selection, prompts or quality gates changed. Cannot infer general chapter speed or universal quality equivalence.
-12total calls,10complete+2failed/usage-unknown;483732known tokens (436196prompt,47536completion); unknown reservations111286 are not actual tokens. Amount unpriced/null, not zero. Completed replies reused after network failure; prior failed calls as well as cached replies invalidate resumed-arm latency comparison (new RED/GREEN test). Eval5 supplementary tests passed0.14s; P0/P1 wiring idempotence2passed1.78s. No further model calls or novel generation needed.

- Final independent review identified2P1+3P2; all fixed in one pass with RED/GREEN repros: working retry packet-name shadowing (real CLI retained_progress added); lost parallel credential fail-closed (new native prepare schema2/parallel_required, legacy API remains sequential-compatible); length conflict recovery now measures cumulative edits; live system includes resolved dynamic preference and adopted file aliases; resumed/cached model results cannot contribute a fresh latency claim. Runtime whitespace default normalized and dynamic runtime files source-bound; missing actual context file fails closed. Targeted native/fix suite24 passed37.87s. Extra eval4 tests passed0.14s. First full run1363 passed/2 obsolete wiring assertions failed; new graph assertions corrected.
- Final full suite1373 passed486.40s (C:/xs2/tmp/performance-p1-full-final.log). No host Git edits. Production resources frozen during live comparison. Eval alias-only follow-up has no effect on these actual cases: all four copied books use inherit mode with0runtime aliases; final frozen request re-render will verify byte identity.
- Real bounded review comparison now running in comparison-v2, max20calls, same lingsuan:gpt-6.1-sol at the approved edge route. Initial comparison directory retains earlier offline preparations only, no paid requests there. No novel driver, writer or100k launcher. Baseline normal full reader returned revise/expression, facts pass; this does not establish that the prior local accepted chapter is universally issue-free. Report actual findings, retries and extra reconciliation calls honestly.

- Task1 pending retention regression RED→GREEN;47 local/pending/wire tests passed20.15s. Additional missing-head RED→GREEN and prompt-version invalidation covered; pending7 passed4.93s. Pending bytes/signature missing or changed fails closed, fact-incompatible drafts cannot be retained, explicit exact-span updates replace retained edits, partial overlaps reject. Original source and every original goal stay immutable; final reviewer sees all cumulative edits.
- Task2 native9 passed22.98s (C:/xs2/tmp/p1-reader-native4.log). Event barrier proves both model sessions started before either completed; no-finding case uses2 parallel model calls, finding case adds original dependent reviewer, malformed context retries only that branch while blind stays1call. New report path vars are text; source context uses existing text revision_context_path rather than file-content dereference. Added explicit bypass for native conditional merge discovery. Sources and no-reconciliation output SHA/equality rechecked before publication. Original full book-contract/style/evidence guidance preserved in independent first pass.
- Task3 offline actual-edit replay passed on real accepted5-edit chapter: carry2 edits and submitremaining3 produces exact actual accepted2449-prose candidate; old replace-only behavior loses2 edits. Existing actual full model audit replay passes; this is offline replay, not new model writing or judgments. Comparison copies prepared under C:/xs2/data/verification/20261109-performance-p1/comparison; original/stopped-book manifests match and paused flags unchanged. No live model requests yet. Whole-change reviewer dispatched; full suite running (C:/xs2/tmp/performance-p1-full.log).

- Pre-flight: Task1 changes only local revision; Task2 changes only reader scheduling and report preparation; both preserve existing full quality decisions. Task3 consumes both, freezing final resources before live calls. Whole-plugin baseline at C:/xs2/data/verification/20261109-performance-p1/baseline-plugin (P0 installed207f693d...,1344 full tests plus supplemental6). User-approved direction recovered from original chat: P1 pending draft and independent checks in parallel. Implementation details resolved above; no repeated approval needed.
