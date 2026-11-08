# Multi-writer scene allocation P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** choose story scenes and draft targets from narrative work rather than fixed six-scene percentages.

**Architecture:** a plugin-local allocation helper validates weighted scene plans and produces frozen logical-scene/execution-slot mappings; conditional workflow branches skip unused writers. Existing script gates consume the allocation and preserve legacy callers.

**Tech Stack:** Python, plugin JSON workflow/prompt resources, pytest, existing workflow engine and configured model transport.

**Spec:** ../specs/2026-11-07-multi-scene-p1-design.md

## Global Constraints

- Product changes stay in plugins/xs2-novel-flywheel; preserve existing P0 edits.
- Keep six worker slots, with 1–6 actual scenes and the last actual scene on slot 6.
- Preserve final 5000–5300-word acceptance when configured; reference scene budgets cannot force filler.
- Preserve the original book; model verification runs a new copy only.

## Review Focus

- One-scene and six-scene plans route the correct writers and closing scene.
- An inactive slot's old draft cannot enter assembly or trigger retries.
- Plan or allocation drift cannot reuse accepted siblings from different assignments.
- A short transition is accepted when the whole chapter is sufficiently complete.
- Fractional/invalid weights, partial new schemas and legacy six-scene plans receive explicit treatment.

## Task 1: Allocation policy and guarded script consumption

Files: add resources/script-library/xs2/multi_scene/scene_allocation.py; modify multi_scene.py and SCRIPT.md; add tests/test_scene_allocation_p1.py.
Interfaces: budgets(target, weights=None); allocate_plan(data, bounds, plan_sha) -> immutable allocation; validate(bodies, target, pov, allocation=None); active-slot-aware CLI prepare/plan/scene/assemble/reset-scene.

- [x] Write allocation, short-transition, stale-artifact and recovery tests; observe RED.
- [x] Implement weighted reference targets and frozen slot mapping; observe GREEN.

## Task 2: Planner and conditional writer workflow

Files: resources/workflows/mvp/definition.json, resources/prompts.json; relevant workflow tests.

- [x] Exercise the real scheduler with actual allocation CLIs for 1, 3 and 6 scenes; observe RED.
- [x] Deliver planning constraints before draft allocation; branch only into active slots, with the real final scene on slot 6; observe GREEN.
- [x] Run the plugin suite and affected host graph tests. Obtain one fresh code review and fix material findings with regression tests.

## Task 3: Fresh-copy model verification

- [x] Freeze original hashes and a baseline copy; use the configured analysis and body-writer models.
- [x] Run actual planning and writer nodes, inspect planned/actual word allocation, and run the P0 reader on the draft.
- [x] Recheck original hashes and record prose limitations separately from mechanical success.

## Execution ledger

- User explicitly requested P1 implementation and copy-only validation; continue without another design approval round.
- Work in the existing feature checkout and preserve the uncommitted P0 changes.
- Only the current six-slot capacity remains fixed; actual scene count and allocation are chosen per chapter.

## Host compatibility decision

Real scheduler tests showed that the current host flattens conditional gateways inside parallel branches, and bare convergence gateways are absent from the linear plan. Keep all product changes in the plugin: replace this writer fork with sequential conditional branches, guarded skip scripts and executable join checks. This preserves selective model calls, scene recovery and final-scene ownership at the cost of writer concurrency. The 1/3/6-scene scheduler tests exercise the supported graph.

- Fresh review reproduced stale scene acceptance after a whole-chapter rejection. Added source SHA binding and assembly revalidation; real scheduler regression verifies only the rejected writer reruns.
- Fresh review reproduced partial allocation publication on historical brief drift. All existing briefs are now checked before any allocation is published; legacy continued scene checks remain usable. Regression observed RED then GREEN.
- Bounded whole-chapter retry targets cannot exceed the selected scene gate; short drafts may repair several scenes without contradictory length instructions.

- Verification: plugin suite 963 passed (280.65 s), final affected suite 55 passed (51.78 s), host graph suite 21 passed (0.94 s). Fresh reviewer confirmed all material findings resolved.
- Fresh copy and resources frozen at C:/xs2/data/verification/20261107-scene-p1. Original all 366 files unchanged. Automatic review rejected body-writer transmission to ark.cn-beijing.volces.com because prior destination authorization named only edge.lingsuan.org. User input pending; authorized analysis-only planning continues on edge.

- Actual configured planner finished in 108.93 s: five logical scenes, weights36/34/90/16/30, reference targets899/850/2249/400/751, slots1/2/3/4/6. Exact nominal sums5000/5300. Model input/output hashes and frozen resources recorded. No body model called pending the explicit destination answer; a fresh-draft P0 reader remains outstanding. Source resource snapshot matches current plugin resources; original366 files still unchanged.

- User explicitly approved this copy validation to ark.cn-beijing.volces.com with volcengine:doubao-seed-character-260628. Resumed the existing planned task without replanning or altering the original.

- Final live verification completed: actual scene words710/769/2249/444/580, total4752. Main writer needed4 whole-chapter retries (5 calls total); inactive writer and validator skipped. All12 sibling artifacts stayed unchanged; assembly used the final source-bound scene despite a completed scene validator. P0 blind plus contextual review both completed, final verdictrevise, score72; export preflight rejected the draft. Content findings include underpaid paper debt, POV overreach, unclear payment/hand-off order and repeated explanation. No manual prose changes, polish or publication; final target5000–5300 remains enforced. Original366 files unchanged, live resource snapshot matches current source, all12 model-call input/output hashes verified. Evidence: C:/xs2/data/verification/20261107-scene-p1/verification-status.json and verification-result.txt.
