---
name: reader_review
description: Freeze minimal first-reading input, validate quoted causal findings, and separate quality from repair permission.
type: python
---

`prepare --chapter 0001` freezes the current manuscript in a task-specific directory and emits workflow file variables. The initial reader receives only the frozen manuscript, genre, language, POV and story scope. It has no file tools, planning context, repair instructions or prior score.

`commit-blind --binding PATH --binding-sha SHA` validates the initial report and causal decision evidence. `commit` additionally takes `--blind-sha SHA`, merges independent findings with contextual review, and publishes only when manuscript, author scope, task input and initial report still match.

Quality always covers the complete chapter. `revision_scope` classifies whether each finding is editable, outside scope or unclear; material findings outside or ambiguously within permission pause automatic repair. Contextual resolutions must retain the original finding and cite current-text counterevidence. Legacy chapter reports remain readable.

Contextual findings use distinct IDs (the prompt recommends `context-`); colliding IDs are rejected before permission classification. Published reports retain the author-instruction snapshot. Editing those instructions invalidates the old permission decision and requires a fresh review before automatic production continues.
