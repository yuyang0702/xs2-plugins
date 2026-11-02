# Contextual dialogue learning

This feature belongs to the novel plugin. It adds no provider, configuration migration, model dependency or per-utterance model loop.

## Data flow

1. `reference-distillation` analyzes complete visible exchanges in source windows. Each candidate may include `dialogue_samples`; uncertain speakers or incomplete exchanges yield an empty array.
2. `reference_distill normalize` verifies exact direct quotations, source offsets, order, intervening replies and nearby speaker names. It preserves bounded preceding/following source text and records a source-bound sample ID. The script verifies textual evidence, not semantic speaker attribution or relationship interpretation; the analyzer and compatibility reviewer must still judge those.
3. Merge retains one source identity with separate `analysis_variants` when overlapping windows interpret the same evidence differently. Existing mechanism IDs are unchanged by adding dialogue metadata. Full window results remain available; the source profile carries whole representative records within a documented budget.
4. The existing library persists candidates and the structured source profile. Reanalysis can retain an older candidate ID while exposing updated contextual samples through the refreshed profile. No library rewrite occurs during plugin startup.
5. Quick adoption supplies the verified source context and target book profiles/outline to the compatibility model. A specific mapping requires an accepted reference and sample ID, an existing book character and interlocutor, an exact relationship quotation and exact scene evidence belonging to its claimed chapter. Unknown relationships/scenes use `pending_context`; legacy libraries without samples remain usable as abstract references.
6. Reviewed mappings are published atomically with the existing adoption transaction to `learning/dialogue_adaptations.json`. Original character profiles, voice documents, manuscripts, settings and model preferences are not overwritten. Re-adoption can complete a pending mapping without changing an existing blueprint.
7. MVP and polish run `prepare-context --scope <stage> --chapter <chapter>`. Only selected mappings for the current chapter and unchanged positioning/profile/scene inputs enter generation as abstract guidance. Original source quotations stay in analysis storage. Unmatched, pending, stale and other-chapter mappings are omitted and counted in the stage receipt.
8. Both single-writer and specialist dialogue/integrator paths, plus review/polish, use the same dialogue-learning contract. The compact short-story branch already traverses the MVP context node and includes its output.

## Compatibility and limits

- Existing libraries, candidate IDs, blueprint formats, voice files and saved decisions continue to work. Missing dialogue metadata means no contextual sample is claimed or invented.
- Source verification currently supports complete direct speech in Chinese curly quotes, corner quotes and ASCII double quotes. Ambiguous or unsupported dialogue formats may still supply abstract mechanisms but must omit the contextual sample.
- Chapter-specific outline matching recognizes numeric chapter headings, including the plugin's generated `### 第N章` format. Unnumbered complete short-story plans apply only to chapter 0001; uncertain ownership must remain pending.
- Whole source scenes and stage review packets have size limits. Records are not cut through the middle of a quotation to fit a prompt. Oversized adoption requests require smaller batches.
- A passing evidence check or model review does not prove dialogue is natural. Literary quality still requires comparing complete exchanges, maintaining factual conditions and inspecting the final integrated prose.

## Design references

The implementation independently follows the design discussed with the user: contextual comparison examples from [webnovel-handbook](https://github.com/miserylee/webnovel-handbook/blob/main/docs/core-writing/59-dialogue-comparison-reference.md), relevant character-dialogue retrieval in [ChatHaruhi](https://github.com/LC1332/Chat-Haruhi-Suzumiya), character state/knowledge separation in [Talemate](https://github.com/vegu-ai/talemate), and conversational/character consistency checks in [CharacterEval](https://github.com/morecry/CharacterEval). No upstream runtime code, pretrained weights or character datasets are bundled by this feature.
