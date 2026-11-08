---
name: book_context
description: Prepare the common effective book contract for advisers before chapters or formal planning files exist.
type: python
---

`prepare` optionally accepts premise, genre, narrative-pov, narrator-scope and style-intent. Nonempty inputs overlay current project settings; explicit per-book narrative_contract fields retain their documented precedence. It writes only immutable task cache derivatives and emits book_contract_file. It creates no world, style, outline or manuscript archive.

The adviser writes a task-local draft. `commit` reads the actual model report on stdin, rechecks the frozen effective and disk-base rules, and atomically publishes learning/advisor_report.json only while those rules still match. Proposed changes remain unadopted.

`--target` and `--scope` freeze the author's requested length and work form in advisor_constraints_file, separately from literary style. Advice must fit an explicit ceiling and short/serial scope. Changed project length/scope or a changed frozen constraints file prevents publishing stale advice.
