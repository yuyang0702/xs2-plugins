# Novel console service

Host-loaded plugin service for adviser discussion, configuration validation and durable production policy. Uses the host model and workflow runtime; no separate provider configuration.

## Review and adopt adviser recommendations

The host constructs `ReferenceAdoptionJobs(model_factory, catalog_loader, candidate_merger, reference_runner, lock, guard=None)`. All callbacks are injected; this resource imports neither host code nor sibling script resources.

| Callback | Contract |
| --- | --- |
| `model_factory(**kwargs)` | Current host model transport; accepts the adviser model override, streaming, timeout and retry settings. |
| `catalog_loader()` | Fresh list of `{library_id, name, candidates, profile, manifest}`. `candidates` is the complete normalized payload including style/conflict choices. |
| `candidate_merger(base, incoming)` | Merge exact source identities; preserve existing candidate IDs and prior adopted definitions. |
| `reference_runner(stage_root, selection)` | Run the enabled owner's real `reference_distill adopt --selection-json` using the selection dictionary. |
| `lock` / `guard(root)` | Shared reentrant workspace mutation lock and optional workflow/automation activity check. No lock is held while awaiting the model. |

Call `start(root, request_id, {"entry_id": saved_adviser_id, "_model_override": model_id})` from an active asyncio loop. The request ID is a UUID. `get(root, request_id)` and `latest(root)` restore durable results; repeating the same ID returns the same job. `has_active(root)` supports mutation guards; `await stop()` cancels checks during shutdown.

Recommendations come from the completed adviser entry in `learning/assistant-history.json`, never from client supplied recommendation arrays. Saved `.novel-project.json` is authoritative; a new book can use that entry's saved `configuration_base` without creating or changing project settings. New recommendations require exact `library_id` plus `candidate_id` (mechanisms) or `choice_id` (styles/conflicts). Legacy names resolve only when the normalized full name is unique across the catalog.

The compatibility model returns a decision for every requested source identity:

```json
{
  "decisions": [
    {
      "library_id": "source-library-id",
      "candidate_id": "mechanism-id",
      "decision": "adapt",
      "reason": "Fits the book's goal, viewpoint and planned scope.",
      "adaptation": "A concrete application grounded in this book's characters and causal chain."
    }
  ],
  "voice_adaptations": [
    {
      "character_name": "Exact existing book character name",
      "profile_evidence": "Exact excerpt from that character's own profile",
      "guidance": "Character-specific speaking guidance for different relationships or situations."
    }
  ]
}
```

Use `choice_id` instead of `candidate_id` for styles and conflicts. `recommend` and `adapt` are applicable; `caution` and `reject` appear in `skipped`. Unknown, duplicate or omitted identities fail review. Explicit incompatible viewpoint/scope cannot be overruled. Relevant character/dialogue rules require at least one suitable existing role with validated profile evidence. Without characters, abstract rules can be adopted with `voice_status: pending_characters`; adopting again after profiles exist can add voices without a new writing-blueprint version.

Jobs persist under `learning/adoption-jobs/<request UUID>/job.json`. Status is `checking`, `applied`, `no_match`, `review_required` or `failed`; responses include `summary`, `selected_references`, `skipped`, `voice_adaptations` and `voice_status` (`adapted`, `pending_characters`, `not_requested`). Only an actual new blueprint or new voice adaptation produces `applied`.

Application runs on a scratch copy of learning/meta files, verifies the real CLI's versioned blueprint, and publishes changed learning artifacts plus the separate `meta/character_voice_adaptations.md`. Existing novels, settings, profiles and `meta/character_voice.md` remain untouched. Book files, adviser data and selected source candidates/profiles/manifests are fingerprinted before and after review and again after the CLI. Source-ID collisions fail closed. Oversized review documents require a smaller review scope instead of silently dropping evidence.

`publication.json` records before/intended hashes and flat backup names before any publication. Recovery rolls back incomplete writes only when live bytes still match the job's intended output, preserving later author edits. A committed journal validates the immutable blueprint receipt and finalizes the job without replaying adoption.

## Supply adviser source IDs

`create_assistant(model_factory, support_loader, catalog_loader=None)` accepts the same catalog loader. The adviser sees a compact index containing actual source IDs, names, scope/viewpoint metadata and concise guidance. Full catalog data validates returned IDs; raw source evidence and full DNA documents are reserved for the selected compatibility check.
