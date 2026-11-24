# Long-form distillation batching

The full-book workflow accepts a chapter limit and an original-character limit per model request. Its defaults are 10 chapters and 40,000 characters. Chapters keep their identity and original offsets. Long chapters occupy separate requests, and evidence repairs only send missing chapter segments.

The first pass records chapter events, character changes and leads. A local search nominates other portions of the source using verified chapter readings. Model rereads cover selected clues, while coverage records identify all chapters read on the first pass and the number selected for targeted verification.

Verification covers both batching limits, original-text evidence and replay, a workflow run with the original novel's opening chapters, and the planned batch count for the full novel. The old novel run is replaced after the sample run passes.
