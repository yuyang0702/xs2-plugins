# Plugin long-run acceptance and observation

The user authorized implementing plugin-owned long-run observation and a real
100,000-character continuous generation run on one copy. Originals must remain
unchanged and literary rules must remain book-owned. This extends the accepted
P0–P2 architecture; it does not replace the production pipeline.

## Approach

Reuse the existing WorkflowEngine, AgentNode, generic plugin CLIs, production
policy, P0 journal and P1/P2 continuity interfaces. Add an opt-in `xs2/longrun`
script library for source protection, durable observation, acceptance reports
and a resumable headless driver. The driver uses the host's configured request
transport. Agent replies and novel prose must always come from real configured
models. Transport adaptation and script execution remain explicit in reports.

A separate toy prose generator would not exercise the product. Running without
durable evidence would lose failed requests and restarts. Neither is used.
Implementation proceeds inline in the existing feature checkout to preserve
the user's uncommitted P0/P1/P2 work; tests and manuscripts use isolated copies.

## Observation and acceptance

An optional `meta/longrun_contract.json` freezes target, baseline chapters,
model routes, request limits and pricing. `observability/longrun.sqlite3`
records calls (including uncertain failures), task snapshots, events, audits
and accepted chapter versions. Stable identifiers make repeat observation
idempotent; edits cannot erase historical spending or previous findings.

Only new prose with current P0 confirmed archives, passing reader reports and
completed export counts toward target. Counts exclude baseline prose, headings
and whitespace using the plugin's existing length convention where possible.
Archive validity and source hashes are rechecked when reporting. A changed or
unaccepted chapter does not count. A target count alone is not a quality pass:
coverage, unresolved findings, unknown request outcomes and missing audits are
reported independently.

Memory checks combine source-anchored probes and independent model audits of
facts, cognition and volume handoffs. Retrieval misses, suspected archival
omissions and actual prose contradictions are distinct. Audit findings require
real source/excerpt anchors and source versions. Audits do not silently modify
prose, facts or book direction. Every audit is itself recorded and metered.

Reuse host pricing for configured prices; missing or incomplete prices remain
unpriced. Configured cost is an estimate, not an account invoice. Real provider
token usage is retained separately from conservative pre-call reservations.
Unknown usage after a failed request retains a reservation; restarting cannot
erase it. Each real request must pass the driver budget guard. No silent model
fallback. CLI/production observation outside this driver does not claim to
intercept arbitrary manually issued provider calls.

## Copy run

Select an existing science-fiction validation copy of 回声在四分钟之后, preserve
its narrator/style/world rules and existing first chapter. Adapt only the new
copy's writing scope from a finished short story to a continuation experiment.
The test target is at least 100,000 newly generated accepted body characters,
excluding the original chapter. Use bounded windows and several declared volume
ranges; the final volume stays open so a test stop is not a forced book ending.
Novel adviser/planning and later semantic audits use actual model responses.

Source manifest and copy identity are persisted before any writing; nested
destinations, reused destinations and symlink escapes are rejected. The driver
has an exclusive process lock. Resume uses saved task states, P0 recovery and
P2 reservations, retaining rejected outputs and failure history. Operational
recovery follows existing bounded policy; content gates are never bypassed to
reach the word count. Natural and deliberate safe restarts are distinguished.

External transmission for this particular run and a usable spending/token limit
are pending the user's answers. No model request starts until these are clear.

## Evidence

Produce machine-readable status, calls, chapter and issue records plus a human
report: new accepted characters, chapters/volumes, audit coverage and findings,
retrieval probes, interruptions/recoveries, time, actual tokens, priced/unpriced
usage, reservations, settings integrity and source integrity. Do not claim
100,000 characters completed if a gate, budget or provider failure stops early.

## Verification

Test idempotency, failure reservations and restart budgets, missing prices,
source/copy protection, stale/unaccepted chapter exclusion, issue anchors and
audit coverage. Test real host routing/output selection and script entry points.
Use native UTF-8 Windows test execution for host async scheduler tests. Review
the final plugin change with one read-only reviewer, then sync and cold-load the
plugin. The real run must retain all evidence; its results are not fixtures.
