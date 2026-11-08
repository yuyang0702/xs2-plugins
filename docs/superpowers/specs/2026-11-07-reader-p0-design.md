# Plugin reader review P0

Approved scope: implement the three P0 items from this chat in the novel plugin, then run the actual reader workflow against a copy of the manuscript. Preserve the original book byte for byte. P1 work, manuscript rewriting, publishing, and pushing are outside this change.

The reader workflow begins with a frozen, task-bound manuscript and minimal genre/POV/story-scope input. A new tool-free reader runs before historical feedback, character planning, or previous scores are loaded. It identifies grounded expression/fact issues and audits consequential decisions: prior knowledge, leverage, alternatives, choice, and consequence. It may find no issues; quiet scenes need no invented conflict.

A plugin script validates source quotations and binds the blind report to the chapter hash. The existing contextual reader subsequently checks the complete chapter and prior repair requests. Its report separately classifies whether each independent finding can be edited within the current author scope. It may resolve a finding only with an explicit explanation and current-text counterevidence; the original finding stays visible.

The plugin merges unresolved findings, independently gates literary quality and revision permission, and pauses automatic repair when a material issue is outside or ambiguously within a restricted scope. Assessment-only runs still finish with a truthful report. Legacy reports remain readable. Existing host APIs, UI, and model selection continue to be used.

Verification: tests exercise frozen-input isolation, quotation and task/hash binding, missing/malformed review data, grounded causal issues, scope classification, contextual resolution, and production decisions. Run the complete novel-plugin suite, then the actual workflow with configured models in an isolated copy; retain raw reports and hashes of the protected original.
