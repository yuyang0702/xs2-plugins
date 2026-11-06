# Multi-writer chapter scene budgets, validated scene briefs and guarded assembly before publication.

`reset-scene --scene N --target RANGE --pov POV --reason REASON` is an explicit
recovery operation for a failed or stopped task. Run from that book workspace
with its original `TASK_ID`. It archives the rejected scene and expansion seed,
refreshes only that scene's retry instructions, and preserves accepted siblings.
Retry the failed workflow node afterward; this does not publish manuscript text.

Scene limits are draft allocation bounds, not the final manuscript target. Current
scene workflow retries return a complete scene, avoiding conflicts between workflow
retry feedback and partial insertion instructions. Final length checks remain in
polish, reader assessment and export. A task pinned to a changed library must be
recreated with the new snapshot; never bypass the library drift check.
