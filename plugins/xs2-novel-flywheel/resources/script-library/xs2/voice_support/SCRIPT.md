# Character voice documents

Host-loaded plugin capability: `status(root)`, `read(root)`, `save(root, content)` and `generate(root)`.
Only `meta/character_voice.md` is written. Workspace resolution, owner policy and busy-task checks belong to the host adapter.

`generate` creates a deterministic **manual template**, extracting `## Character name` headings from `meta/character_profiles.md`. It never calls a model, invents voice traits, changes character profiles, or overwrites an existing voice file. Documents without those headings must be edited manually.

AI-generated voice remains part of the existing `character` workflow. This helper does not introduce another generation or scoring engine. Humanware numeric scoring is unsupported; use the existing reader-sim workflow report.
