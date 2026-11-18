# Creative latitude implementation plan

**Goal:** Keep character cards descriptive and reference methods optional throughout the plugin's generation and review paths.

**Approved design:** The user approved the five changes discussed in this chat: separate personality from constraints, make reference use optional, remove compulsory style prohibitions, clarify context authority, and review plausible characterization rather than correct conduct.

**Architecture:** Change plugin-owned prompt resources and shared context renderers. Preserve schemas, author requirements, established facts, selected reference identities, model settings, workflow graphs and existing manuscripts. Do not rewrite old cards using keyword deletion.

**Tech stack:** Python script libraries, JSON prompt resources, pytest; existing host plugin deployment mechanism.

## Tasks

- [x] Add failing regression coverage for optional style boundaries, descriptive character prompts, context authority in both compact paths, and reference rendering without obligatory adoption.
- [x] Update existing prompt clauses and add concise common interpretation guidance to character, planning, writing and review roles. Remove contradictory compulsory commandments.
- [x] Carry the same authority guidance through book-contract and compact context rendering; update new reference questions and render old references as optional without mutating blueprints.
- [x] Run targeted plugin tests, review changes against the pre-task working tree, and deploy via the plugin resource lifecycle with custom settings preserved.
- [x] Verify installed resources and report the distinction between deterministic checks and literary quality, which requires a model comparison.

## Review focus

- Explicit author requests remain binding even if their wording resembles a preference.
- Character belief and speech may be wrong without silently changing world facts.
- Both short and full preparation, single and multiple writers, and review roles receive consistent interpretation.
- Existing reference blueprints and card data are not rewritten or stripped.
- Plugin upgrade must preserve user models, custom prompts, workflow graphs, running task snapshots and books.

## Execution notes

- Existing checkout has substantial uncommitted work. Work in place with pre-task snapshots of touched files; do not reset, commit unrelated changes or create an isolated checkout that omits these changes.
- Existing reference verdict handling already makes reference-only issues advisory; preserve and test it rather than creating a second gate.
- RED/GREEN: initial 23 failures/1 existing pass; shared guidance brought 24 green. Legacy reference model-view test failed before implementation. Reviewer found missing transition writer, verified RED and added it.
- Two test_book_contract assertions about removed workflow nodes/message fields fail identically against the untouched installed package; do not modify unrelated workflow definitions to satisfy stale expectations.
- Windows sandbox prevents asyncio socketpair creation. Run asyncio integration tests outside the sandbox and use a short workspace basetemp for subprocess portability.
- Installed files exactly match the pre-task snapshots. Deploy only this task's file delta into a new content-addressed copy of the installed plugin; do not install unrelated working-tree modifications.
- Final regression: 289 passed, 2 deselected (both reproduced on the unchanged installed baseline). Independent review found no blocking issues; added the omitted transition writer and removed remaining genre-taboo guidance.
- Installed revision bfdd4af6f6ca68fc9f5bd1df7e7be941e9d42f94 through PluginStore and ExtensionManager resource preparation. Verified all 55 namespaced prompt roles and changed script hashes; source and prepared resources match. Initial verification used an unprefixed script group path, corrected to the host's namespaced group and successfully rerun.
- No host source, workflow graph, model settings, reference blueprints or manuscript files were changed. Service was not listening on the configured port; prepared disk resources will be read on application start/new tasks. No model-generated literary comparison was run and no claim of proven literary improvement is made.
