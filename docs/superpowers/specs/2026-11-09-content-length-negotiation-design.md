# Content and length negotiation

User authorizes plugin-only generic flow repair and another real 100k continuation on the protected copy. Preserve styles, original manuscripts, previous failures and spending. No further design approval is needed for routine implementation choices within this request.

## Diagnosis and approach

The old loop treats a driver-assigned chapter allocation as an author requirement. Local patches cannot report an infeasible composition, so deleting redundant explanation returns to the same writer until it pads actions or exhausts retries. Prompt changes alone have already failed.

Use a book-owned length policy and independently reviewed composition plan before writing/revision. Existing books default to their explicit author range. Only books explicitly selecting planner-owned chapter budgets may negotiate those allocations. The protected 100k run opts in: 3500–4000 was a driver allocation, while 100000 newly accepted prose units remains the overall target.

Rejected alternatives: loosening every book's gate changes author requirements; adding more retries preserves the dead end; requiring new events, fixed emotion counts or shorter prose imposes a style.

## Contract

- `meta/length_policy.json`: schema1, ownership `author` or `planner`, optional author minimum/maximum. No genre defaults or universal chapter-size limits beyond existing technical representation.
- `xs2/composition_plan`: frozen inputs, structured plan, separate independent review, P0 publication to `planning/length/NNNN.json`. Enabled policy routes native MVP/polish through planning; legacy books bypass new model calls.
- Each plan describes reading functions and how segments develop them. Plot, emotion, relationship, atmosphere, voice and formal exploration are equally valid; these examples are not an enum. Segment budgets sum to the negotiated chapter range. Existing world/narration/author limits bind the plan. Plan is intent, never archived fact.
- Independent reviewer binds request/plan hashes, checks every segment for distinct or developing reading function, preserves book style/scope, and checks length feasibility. Invalid/unsupported plans cannot change quotas. Author-owned limits cannot be changed by either model.
- Source drift invalidates pending publication. Accepted budget remains usable across the expected prose revision; policy/book/author-source/declared chapter-plan drift invalidates it. Actual text still undergoes the existing fact, expression, blind-reader, archive and export gates.
- Local writer can return a typed `needs_replan` response with source-bound evidence. The script records a non-publication conflict receipt rather than asking for padding. Production treats the receipt as a bounded planning recovery, not an ordinary content rejection. Unknown/stale/unbound conflict data never authorizes recovery.
- Repeated deterministic short candidates in a content repair become a typed planning conflict. Hard author bounds produce explicit scope conflict instead of automatic reduction. Neither conflict path publishes prose or counts accepted words.

Ruling after integration: expose per-book workflow choice, inheriting current policy by default. A verified conflict in a legacy book bootstraps an author-owned policy and tries bounded composition planning within the unchanged author range; only infeasibility pauses for scope. Two evidenced substantive local rejections also return to planning. These counters detect operational repetition, not literary quality. Source inputs distinguish original author feedback from previous automatic advice, including author-edited wrappers.

## Integration and recovery

Insert optional planning nodes at the beginning of existing MVP and polish workflows, avoiding host changes/new host stages. They output effective chapter target variables before downstream guards freeze inputs. Central length resolution reads only verified accepted quotas for opted-in books. Freeze quota/policy in draft/revision evidence. Native workflow snapshots remain version-bound.

The user explicitly requested a new repaired validation phase. Finish the exhausted prior serial run, retain all records and initialize a new run epoch on the same copy with a linked phase event; don't alter old counters. Keep the overall call ledger and 100k total. No manual prose edits, no replay of already accepted chapters. Use previously approved providers/models and unlimited monetary budget; amounts remain unpriced until applicable prices exist.

## Acceptance

Tests cover author vs planner ownership, multiple literary functions/styles, range accounting, hash/quote/schema checks, stale plans/author changes, conflict no-publication, actual native routing and legacy bypass. Review the integration, run full plugin tests, install/cold-load, then continue real generation to 100000 accepted new prose units with transparent failures/costs and unchanged source manifest.
