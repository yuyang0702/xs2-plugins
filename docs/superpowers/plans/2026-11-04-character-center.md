# Character Center and Narrative Preference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task by task, TDD and independent review before integration.

**Goal:** Ship the user's approved complete character-center and narrative-led writing improvements through the novel plugin, preserving old books/configurations.

**Architecture:** Add plugin-owned prose_policy and character_center libraries, reuse console assistant request jobs and shared story context, expose thin guarded host adapters and React views. No new database/model transport or default extra per-chapter LLM calls.

**Tech Stack:** Python 3.11 standard library/plugin services, existing FastAPI, React/TypeScript/Tailwind and node:test, existing pytest and real model transport.

**Spec:** ../specs/2026-11-04-character-center-design.md

## Global Constraints

Read the complete Spec's global constraints; they bind every task. Existing novels/configurations/models are immutable unless an explicit UI preview/confirmation selects a bounded change. Getters are read-only. Business belongs to the plugin. No remote push. Protect selected-workspace boundaries, stale revisions, confirmed-vs-planned knowledge, old card syntax and runtime task safety.

## Review Focus

1. Old/ambiguous Markdown must not be guessed into structured identity or lose bytes on editing.
2. Confirmed expression overrides must actually reach every consuming prompt without accidentally removing hard facts or changing original files.
3. A stale body, reset chapter, absent evidence or future plan must not masquerade as current character state.
4. Async AI results must stay bound to book/character/source revision; errors or navigation cannot apply or misattribute them.
5. UI and plugin disable/busy/manual-control boundaries must hold for previews, acceptance, history restore, style settings and AI jobs.

### Task 1: Narrative policy, rule audit and consuming-context integration

**Own:** new resources/script-library/xs2/prose_policy/ package + SCRIPT.md, local_archive/story_support context bridges, prompts.json and affected workflow definitions, focused plugin tests and the needed expected resource list.

**Produces:** a documented read/audit/save/effective-context API usable by character_center and host. Policy mode inherit/narrative_led with optimistic revision. Exact-source expression overrides are previewed/confirmed, never rewrite canonical source. Stale overrides are surfaced. Runtime copies/context aliases prevent old mechanical commands remaining in the consumed prompt. Existing workflow output formats/model parameters/calls remain.

- [ ] Write failing tests for read-only legacy auditing, legitimate hard constraints, exact expression overrides, stale binding, runtime context reaching real PromptBuilder for planning/writing/polish/review, no normal new calls and old mode no-op.
- [ ] Run RED with test temp/logs under the external task audit folder.
- [ ] Implement focused service modules and genuine runtime bridge; document exact signatures/return shapes in SCRIPT.md for later tasks. Coordinate ownership/import boundaries without host dependencies in plugin.
- [ ] Run focused + relevant plugin tests, self-review, commit ONLY owned source/test/doc files in the plugin worktree; provide report and review diff.

### Task 2: Character center data, local edit history and model-backed preview/trial APIs

**Own:** new resources/script-library/xs2/character_center/ package + SCRIPT.md; console_service assistant hooks/factory; host novel_plugin.py/humanware_routes.py/novel_assistant.py/novel_routes.py thin adapters; focused plugin and host tests; expected resources update.

**Consumes:** Task 1 prose_policy API and source binding. Existing voice_support, story_support confirmed chapter state and console assistant transport.

**Produces:** documented `/api/humanware/characters`, `/character-preview`, `/character-apply`, `/character-history`, `/prose-policy`, `/rule-audit`, and AI-purpose support in existing assistant API. Character-center response and request shapes MUST be frozen in a separate API-CONTRACT.md before handing to UI implementer. Include section/source identity, profile/voice grouping, directed relationships, current sourced states, planned arcs, revisions and legacy fallback.

- [ ] Write failing tests for old/structured cards, names/duplicates/fences, body-backed states and future/stale snapshots, selected fragment previews/apply/history/restore with BOM/CRLF and optimistic revisions, path and publication safety, audit/policy transport.
- [ ] Write failing tests for existing assistant character-edit/dialogue-trial purposes: frozen context, strict response format, selected expressive field only, same-book idempotency, stale responses, errors, saved trial results and author preference acceptance without body writes. Select models through existing workflow/book choices, never global config changes.
- [ ] Implement read-only projection from authoritative existing files; unknown syntax stays raw. Preview is inspectable before confirmed mutation; restore is another current-version preview.
- [ ] Extend existing durable AssistantJobs with plugin hooks; host only resolves enabled resources, workspace/owner/task policies and existing model selection. Record actual model/status/elapsed time. AI edit does not mutate until preview apply; trial acceptance persists source-bound author preference for relevant consumption, never forces repeated sentences.
- [ ] Implement thin routes using existing manual-control/idle/owner and strict workspace handling. Add documentation with every returned property and an offline fixture example.
- [ ] Run focused tests, self-review, commit only owned sources in both worktrees, report contract/test results and diff packages.

### Task 3: Complete character-center UI and truthful progress

**Own:** new frontend CharacterCenterPanel modules/types/api/views/tests; minimal workbench navigation integration preserving humanware deep links and old CharacterVoiceEditor fallback; plugin progress details + thin host delegation and frontend rendering; affected tests.

**Consumes:** completed Task 2 API-CONTRACT, existing APIs and Task 1 source policy. No frontend generation business rules.

- [ ] Add failing tests for response-to-view adapters, section comparison/history state, current-vs-planned evidence presentation, scoped async result acceptance and error/dirty-state handling; use behavioral DOM/browser verification for actual controls.
- [ ] Implement searchable per-person overview/motives/relationships/voice/state/arc/raw/history, directed relationship display, bounded section edit→diff→confirm and restore, chapter selection and source evidence.
- [ ] Implement per-book inherit/narrative-led policy and rule audit view with explicit previewed expression overrides and stale warnings. No fixed dialogue quotas, no silent source rewrite.
- [ ] Implement field AI suggestions + scene trials showing relation/scene/source, before/after, author preference/reason and actual task/model/progress/errors. Guard against cross-book/page late responses and duplicate submissions.
- [ ] Surface planned/draft/verified/export state and real node/model/elapsed/call facts when present. No fabricated price/ETA or quality score. Keep single/compact mode and no default extra calls.
- [ ] Run frontend tests + production build, relevant host/plugin tests, capture UI evidence with an isolated synthetic test book. Commit only owned source/test/doc files, report limitations.

### Task 4: Whole feature verification, real scene comparison and safe local activation

**Own:** integration/test artifacts outside repositories; fixes return to the owning implementer.

- [ ] Run 3 fixed scenes A/B through existing configured request transport, keep exact input/output/model metadata; preserve author facts/results/POV/word targets and do not hand-fix samples. Evaluate both readability and regressions, not dialogue ratio alone.
- [ ] Run full novel-plugin tests, affected host tests and frontend build/tests. Run new UI endpoints and controls on synthetic data; malformed/stale/disabled/busy cases must fail safely.
- [ ] Independent whole-branch review; resolve Important/Critical findings with RED/GREEN and focused verification.
- [ ] Apply tested source to local delivery branches without pushing. Review installed workflow resource upgrades and preserve user model preferences; rebuild UI; use existing idle-safe launcher for reload. Confirm actual served APIs/assets and original protected data/config hashes.
- [ ] Remove only this task's temporary QA workspace; keep reviewable report and the user's actual manuscript output. Finish with concrete implemented behavior, tests, activation and material limits.
