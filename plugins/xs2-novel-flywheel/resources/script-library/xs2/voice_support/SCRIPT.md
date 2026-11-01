# Character voice documents

Host-loaded plugin capability: `status(root)`, `read(root)`, `save(root, content)` and `generate(root)`.
Only `meta/character_voice.md` is written. Workspace resolution, owner policy and busy-task checks belong to the host adapter.

`generate` creates a deterministic **manual template**, extracting `## Character name` headings from `meta/character_profiles.md`. It never calls a model, invents voice traits, changes character profiles, or overwrites an existing voice file. Documents without those headings must be edited manually.

AI-generated voice remains part of the existing `character` workflow. This helper does not introduce another generation or scoring engine. Humanware numeric scoring is unsupported; use the existing reader-sim workflow report.

`read(root)` also returns per-character views and matching profile references. It uses real level-two headings outside code fences, retains shared rules and unstructured legacy text, and reports uncertain name matches without guessing traits. Reading never rewrites the files.

`save_character(root, character_id, content, expected_revision)` updates only the selected voice section or explicitly adds a profile-only character's voice. Both original documents participate in revision checks. Other characters, global rules, BOM/newlines and profile bytes are retained; an outdated page cannot overwrite a newer document. The existing whole-document `save` remains compatible and accepts an optional revision.
