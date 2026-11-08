# Multi-writer scene and length allocation P1

Approved scope: change scene planning and draft allocation in the novel plugin, then verify on a fresh copy of the existing short novel. Preserve the original and all P0 work. No host-engine changes, new publication, or Git push.

Use the existing six execution slots as capacity, not a six-scene story template. The planner chooses 1–6 consecutive scenes, gives their relative integer weights and explains their narrative work. Slots 1 through N-1 write the earlier scenes through sequential conditional branches; existing slot 6 writes the actual final scene N after those active slots. Unused slots and their validators are skipped by workflow conditions.

Allocate reference word targets after planning, preserving exact chapter lower/upper totals without rounding loss. New plans do not enforce scene-specific minimum length beyond nonempty prose: a short transition must not be padded merely to meet a local quota. Per-scene upper bounds and chapter draft bounds still detect runaway or incomplete output; final polish/reader/export word-count gates remain unchanged. Short chapters retry the scene with the largest reference deficit rather than a fixed scene.

Plan/allocation identity is frozen per task. Accepted scene artifacts are bound to that allocation; changed plans, stale or missing active scenes cannot publish. Inactive stale files are ignored. Explicit scene recovery preserves accepted siblings and uses the actual allocation. Legacy six-scene tasks and script callers remain supported.

Copy-only verification uses existing configured analysis/writer services and the book's established facts. It exercises planning, active writer routing, measured draft assembly and the P0 reader on the new draft. The baseline is retained in the copy; the original is hashed before/after. A successful mechanical run is not by itself evidence of better prose.

## Host compatibility decision

Real scheduler tests showed that the current host flattens conditional gateways inside parallel branches, and bare convergence gateways are absent from the linear plan. Keep all product changes in the plugin: replace this writer fork with sequential conditional branches, guarded skip scripts and executable join checks. This preserves selective model calls, scene recovery and final-scene ownership at the cost of writer concurrency. The 1/3/6-scene scheduler tests exercise the supported graph.
