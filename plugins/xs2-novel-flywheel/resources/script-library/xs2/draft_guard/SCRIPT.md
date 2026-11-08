# Ordered chapter consistency and expression guard

This plugin CLI consumes an assembled multi-writer chapter, its frozen plan continuity contract and planning-sources.md. `prepare` writes task-scoped fact-repair input and enables the guarded workflow. No source manuscript is changed.

Facts are repaired and independently audited before expression repair. `candidate --phase facts|expression` binds the actual candidate to the contract and author constraints. `commit` requires complete observed money transfers, balances when present, event evidence and fact occurrences, plus grounded semantic findings. Money uses exact book-defined integer unit factors; amount/change arithmetic and before/after events are checked in Python. Model judgement remains necessary for completeness, POV and meaning.

A failed candidate returns to that phase's repair writer. A changed candidate with a completed auditor refreshes the audit input and explicitly retries the auditor, so old proof cannot approve new text. Expression candidates recheck all hard dimensions and cannot replace the approved factual source. Stage-one success does not publish; only a successful expression commit updates cache/si/chapter.json, downstream of which SI/render/archive steps run. Final manuscript word limits remain enforced.

Run from the book workspace with its TASK_ID, --multi-dir, --target and --pov. Do not alter contracts, sources or approved receipts within a task. Create a new task for changed planning. The audit schema uses exact text plus one-based occurrence numbers; it never treats absent observations or a model's bare pass claim as verification.
