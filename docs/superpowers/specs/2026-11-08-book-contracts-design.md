# Book-specific world and style contracts

The user approved generalizing the novel plugin and requested five genuinely generated short stories (古风、言情、末日、科幻、玄幻), each at most5000 real words. Preserve all previous work and original manuscripts. Product changes belong to xs2-novel-flywheel; local installation and read-only runtime checks are included. Do not push or publish.

## Contract boundary

Universal checks enforce the book's declared rules, not a particular realism, POV or literary taste. A locally resolved book contract combines project author settings, effective meta/style_profile.md and meta/world_foundation.md, and optional meta/narrative_contract.json. Genre never determines style automatically. narrator_scope defaults to preserve; explicit limited/omniscient/variable/unreliable scopes are supported. Intentional devices and protected phrases preserve repetition, exposition, symbolism and interiority when functional. Missing style instructions preserve the current voice. The optional JSON is validated data, never executable instructions.

Freeze this contract per task and bind its digest throughout planning, scene handoff, repair and review. Changing declared world/style during a task requires a new task. Writing, contextual review and revision receive the same contract; blind reading receives only the public style/narration lens, without author-only plot/world evidence. Existing prose-policy choices remain effective.

## Generalization and revision

Remove single-book names, transaction choreography, mandatory limited POV, unconditional bans on repeated meaning, and action-density assumptions from shared prompts. Scene continuity tracks actual events and participant knowledge under the selected narrator, not a forced focal protagonist for every style. Semantic repetition is judged by function and declared style, not lexical similarity alone.

Production expression revision returns exact-source local patches (paragraph IDs, original substrings, replacements) rather than regenerating the whole body. The plugin checks anchoring, overlap, protected phrases and actual length before an expensive independent audit; all hard facts are rechecked before adoption. Legacy body-based repair remains readable for old callers. New output includes a source hash. Do not silently relax word limits or rewrite test prose manually.

Current-candidate evidence receives deterministic paragraph/clause/amount IDs. Auditors can select IDs/ranges; Python resolves exact original spans and rejects invalid IDs with field paths. Existing literal quote reports remain compatible. Reports bind candidate, contract and source hashes. No fabricated proof or stale report may approve a new body.

## Validation

TDD covers scoped POV, style/world drift, legitimate repetition, unsupported book-specific prompt assumptions, patch grounding, early length feedback, exact evidence IDs and stale-proof recovery. Run the plugin suite and a fresh final review. Install through the existing immutable local-plugin store and verify installed content/definitions match source.

Generate five new isolated books through the actual plugin workflows/configured authorized providers, including genuinely different narration/style settings. Keep author fixtures, plans, actual requests/responses, drafts, audits and phase status. Assess money/resources, knowledge/causality, repetition function, style preservation and closure. Each delivered story must be <=5000 real words. Report failed trials honestly; do not call internal review a Zhuque rescan.
