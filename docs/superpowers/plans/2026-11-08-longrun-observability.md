# Long-run acceptance and observation implementation plan

> Execute inline with superpowers:executing-plans and TDD. Use one fresh read-only
> reviewer after implementation. Preserve existing uncommitted P0/P1/P2 changes.

**Goal:** Observe and accept a real 100,000-character novel continuation on a copy.
**Architecture:** Plugin opt-in ledger/report + metered host engine driver; reuse
P0–P2 and existing host token/pricing code, with no host production changes.
**Tech stack:** Python, SQLite, native WorkflowEngine/AgentNode, configured LLM transport.
**Spec:** `docs/superpowers/specs/2026-11-08-longrun-observability-design.md`.

## Global constraints

- No original manuscript writes, remote calls before run authorization, guessed
  zero prices, fake model replies, acceptance bypasses or fixed literary style.
- Existing feature checkout is retained; source manifests and isolated copies
  protect manuscripts. No commit/push or destructive workspace operations.
- Report target count, quality coverage, recovery and spending separately.

## Review focus

- Repeated polling/resume must not double-count calls or erase unknown charges.
- Old/stale/unaccepted prose must not satisfy the new-character target.
- Missing or conflicting provider usage/prices must not look free or complete.
- Failed audits and source drift must remain visible and cannot silently pass.
- A real run must use the same generic writing/quality/archival gates as product.

### Task 1: Durable observation and source protection

Files: create `resources/script-library/xs2/longrun/{SCRIPT.md,longrun.py,ledger.py}`
and `tests/test_longrun.py`; modify plugin production hooks only when opted in.
Interfaces: `initialize_copy(source,destination,config)`, `observe_task(root,state,
stage,task,kind)`, `reserve_call(root,metadata,reserved_tokens)`, `finish_call(root,
call_id,result)`, `report(root)`.

- [ ] Write/run failing tests for copy protection, idempotent observation, unknown
  usage reservations, missing prices and accepted-new-character accounting.
- [ ] Implement the ledger, report and opt-in production observation/budget hooks.
- [ ] Verify unit tests and existing P0–P2 regression boundaries.

### Task 2: Real, resumable driver and anchored audits

Files: create `longrun/driver.py`, `longrun/audits.py`; extend CLI and tests.
Interfaces: `run(root,resources,host_root)`, `audit_input(root,chapter)`,
`accept_audit(root,chapter,request,result)`; callbacks use real host tasks/usage.

- [ ] Add/run failing tests for anchor validation, duplicate audited versions,
  restart state, exclusive execution and per-call budget guards.
- [ ] Implement the generic driver, actual configured transport usage capture,
  independent audits and retrieval probes, persisting all failures and usage.
- [ ] Verify actual workflow routing, structured output and CLI integration.

### Task 3: Install and real run on one copy

- [ ] Freeze the selected source and user-approved model routes/limits, adapt the
  copy's book scope and establish initial trusted archive/planning via real models.
- [ ] Run plugin checks and read-only review; install/cold-load the plugin.
- [ ] Generate at least 100,000 new accepted characters through actual generic
  workflows, audit memory/volume boundaries, exercise safe process resume and
  record real recovery/spending without bypassing content gates.
- [ ] Save exact results, source integrity proof, caveats and reproduction commands.

## Execution ledger

Task 0: baseline read. Existing host has per-call token ledgers and configurable
pricing, but no price rules for the selected models. External run authorization
and budget are pending async user input. No remote requests have been made.

Ruling: implement in the existing feature checkout because P0–P2 are uncommitted
and are required dependencies; a clean HEAD worktree would omit them. All book
writes and tests remain isolated, and no unrelated tracked changes are reverted.

User response: explicitly authorized both named services for this 100000-character
copy run and stated no spending upper limit. Technical retry/call bounds remain.

Ruling: use native SessionManager and ScriptNode as well as WorkflowEngine, without
a reply/CLI adapter. Runtime data stays in the copy; host config is read-only and
absolute. No remote MCP connections.

Ruling: controller state uses its own SQLite durable intent and P0 atomic/CAS pattern,
because publishing .novel-project.json intentionally changes chapter-local intent.
Original P0 fact semantics are unchanged. Completed nodes persist; in-progress nodes
are explicitly reissued and metered, without claiming completed session reuse.

Task 1 implementation: 17 tests pass, including source protection, unknown prices,
native run-id dedup, native runtime, controller crash replay including changed intent,
and interrupted-node history. Review found the three latter cases and they now pass.

Ruling: installation preflight correctly forbids Script Library imports of Core.
Keep ledger/audit input/standalone status in xs2/longrun; host integration lives in
the plugin's runtime/longrun/{main,driver,transport,audits}.py. Host pricing is reused
there and persisted as version-bound evidence for the independent report. This is
an architectural separation, not an import-check bypass. Installation must verify
both declared resources and the shipped runtime files.

## Active real-run handoff record

### 2026-11-09 00:05 CST update (supersedes older running snapshot below)

### 2026-11-09 02:13 CST handoff (supersedes all older snapshots)

### 2026-11-09 05:04 CST final bounded-run snapshot (newest)

- Main100kobjective NOTACHIEVED. Lasttaskc57a... writer3candidate3568lengthpassed,
  localreview1validlyrejected repeatedscience-boundary explanations inside newnextday
  workplan. Nativewriter3/automaticretry2exhausted; launcher46292exited1, processstopped.
  Stageattempts8/8 andreaderRepairCount2/2 preserved. No furtherrelaunch/capreset.
- Currentpublishedchapter2body3521; lastrejected3568NOTpublished. Newlyaccepted0,
  target100000notreached. Noacceptednewchapter -> far-memory/crossvolume/5chapterrestart
  REALvalidation NOTexercised. Mechanicalunit/fixture tests mustnotbe counted as that.
- Currentsource+installed46ac474b2b41e7d7e0443d15b5f492d3e990ca84e01f5fc52f280e831ed2d921,
  full1257tests/395.50s passed, plugincoldload+164resource/4runtimeverified; nohostchanges.
- Actual118calls, providerreported8283611known tokens(prompt7641835/output641776),
  unknown6calls/reserved859347tokens/failed4. Pricingunavailable->amountnull/unpriced,
  notfree/notactualproviderinvoice. Originalsource98filescheckedunchanged.
- Saved BASE/validation-status.json withstopped_at_quality_gate, exactcounts/limits,
  codeversion/tests/unknownfees/sourceproof andremainingwork. Refreshedbook/observability/
  report.json. Manualbaseline receipt/emotion issue remainsOPEN. Originalneveredited.
- Remainingcriticalflow: plan sceneinformationcapacity againstchapterlength without
  imposingliterarystyle; structuredscope/lengthconflict escalation instead of local
  paddingloop. Changingcaps/loweringwordtarget/manualnovelrewritewouldnotprove10w.
  Failedvalidationmustreportedhonestly. DO NOTresumeautomaticallyunderexhaustedbudget;
  needa new explicitlyscopedrepair/validation decision, not a fakecompletedstatus.

### 2026-11-09 04:59 CST prior snapshot

- Currentfreshlaststage c57a082c-9858-4d04-be44-9f27be4d09b6, POLISH chapter2.
  Critic1passed, writer1candidate3279short, writer2candidate3428short, writer3RUNNING.
  Allfromsamefrozen3521source withretainednewpatchfeedback; no manualtextchanges.
  Calls117/known8064901tokens/newaccepted0. Normal launcher46292/PID19240stillactive.
  Activeinstalled/source46ac/full1257greenunchanged. No pendingimplementationchanges.
- Existingstagecount8/8 alreadyconsumed fornewtask; afterthisnative task no further
  relaunchallowed. QualityreaderRepairCount2/limit2unchanged. Newplanexplicitly says
  reportscope/lengthconflict ratherthanpad; writerpatchschema currentlyno explicit
  blockedstatus, so exactlengthgate native retriescontinue. Ifthisrunfails, report
  unfinished10w andthat structuralcapacity-vs-length/repairrouting remainsunresolved;
  do notevadebyresettingledger/loweringtarget/rewritingmanually/fakeaccepted count.
- Rebuildhelper1699complete0andcannotrepeat; code/version proof/authororigin migration
  alreadyrecorded in SQLite operator_events andautomatic-plan-rebuild intent. Source
  filepreservation98andfeesunknown/currentunpricedmanualbaselineOPENallstillapply.

### 2026-11-09 04:53 CST prior snapshot

- Rebuildhelper1699SUCCESS0. Actualcall113total37548, knownsum7750632. Newautomatic
  feedback quality/repairs/0002/longrun-repair-641213a5-ca71-4bac-9a5a-d2ed453b548c/instructions.md
  explicitlyreports scope/lengthconflict if meaningfulcuts fallbelow3500, no padding
  operations. Originalauthorretention[] matchesverifiedpreautomaticselectionempty.
  readerRepairCount2unchanged, oldc3b0taskhistorypreserved, serialstage7/8beforefresh.
- Normal launcher46292/PID19240 RUNNINGlatest46ac, chapter2POLISH freshdispatch using
  last existingstageallowance8/8. DO NOT rerunrebuildhelper(alreadyusedpersistentintent).
  No pendingproductioncodechanges, full1257green, all164resources+4runtime installed.
- Newplanhasexplicitinstructions no narrower3500–3600, actualrange3500–4000, no
  requiredemotionrepeatcount. Uses nextdayworkplan onlyexistingfacts, no newdiscoveries.
  Iflast boundedtaskorfinalreader stillfails, don'tresetcounters/expandcaps/force100k;
  report realblockedquantity and identifiedplanning/length/quality conflict.
- Still0newaccepted/currentpublished3521, original98unchanged, manualbaselineOPEN,
  missingpricesamountnull/unknowncalls6 remain. Ifpass, continueposthoc/export then
  cleanstopresume and100000newaccepted, no prematurefinal atfirstgoodchapter.

### 2026-11-09 04:47 CST prior snapshot

- Latest FULLplugin1257passed/395.50s, sourceallgreen. Installed46ac474b2b41e7d7e0443d15b5f492d3e990ca84e01f5fc52f280e831ed2d921
  164resources+4runtime coldloaded/configunchanged. This includesallauto-plan origin/
  authorretention/idempotence/missingmetadata fixes andplan_repair extraction. Hostclean.
- BASE/rebuild_failed_automatic_plan.py --check-only passed actualproofs: legacyfeedback
  SHA d54272a4c3351ca33086804d675c32f284ac6ac6a7fc702c837393329ae345f3 exactlymatches
  storedrealresponse dbe718...+Hosttemplate; prefirstautomaticbindinge99a... selected
  authorfeedbackempty; existingP2attempts7/8. Checkonlydefault sandboxasynciohung then
  CtrlC(no model/no mutation), nativeescalatedcheckpassed0. Do nativeasyncioescalated.
- Samehelper ACTUALLYRUNNING session1699, planrequest113reserved, onlyEDGEapproved.
  It holdsrunlock and haswritten one-timeintent + provenlegacyautomatic-origin metadata.
  Oldcursorstillpaused+c3b0failedwhileauxplanner runs; EXPECTED, donotreset/relaunch.
  Do NOT rerunhelper: persistentintent refusesanothercall. No prose/oldfeedback edit.
  Afterhelper completes(success0) it willpublish newfeedback selection, removefailed
  polishref andresume cursor, preservingcycle2/nativeoldhistory/P2budget8. Thenlaunch
  launch_run.py latest46ac. Ifhelperfails, keepunknownusage/noautomaticsecondattempt.
- Atlastsnapshot calls113/known7713084/newaccepted0; currentpublishedbody3521.
  NextnativePOLISHwillconsume last existingstageallowance8/8; no budgetreset/increase.
  Qualityreaderlimit2stillintact. Rebuildisprogram-defectfix withinunfinishedcycle2,
  notthirdreaderrepair. Ifboundedrunfailsagain, report10wNOTcompleted; don'tforcepass.
- Cleanstopafterchapter2exportstillpending; ifreached normalresumeWITHOUTrelaunchthen
  continued100000newaccepted. Source98/originalprotected, manualbaselineOPEN/costnull.

### 2026-11-09 04:41 CST prior snapshot

- ActualrunPAUSED: c3b0... writer3afterremovingadminpadding3433short, nativebudget
  exhausted. Launcher83749exited1. Calls112/known7713084tokens/newaccepted0. Current
  publishedbody3521, rejected3433unpublished. Keepalltaskcounters/failures/unknowncost.
- New runtimeonlyrepairguidance/originfix also retains original selectedauthorfeedback:
  repair_feedback_context passes selectedpath/hash/text into planning, verifies retained
  sources, new automatic-origin recordsfeedbackhash/retained_feedback_sources. Newauto
  plansinherit originalsources only, no recursiveautoplantext. Preapply path/metadata/
  originaltext hashes checked. Newfeedback preserves priorrawtext, authorsruleshigher.
- Readonlyreview found authorfeedbackmissing; fixed. Nextreview found appliedentry
  reentryneeds earlyhostbranch and missingretainedfieldmustreject; bothfixed. Newtest
  REDthen28longrunGREEN/11.59s. Hostprepare_repair stilldoes sourceverify/backups.
  Currentfrozenbookfiles/feedbackunchanged. plan_repair extracted from repair so caller
  may replace a diagnosed brokenplan within unfinishedcycle; ordinaryrepairstillcalls
  samepolicy.repair_ready, unchangedbudgetlogic. Fullsource1257suiteRUNNING47075(~28%).
- Prepared BASE/rebuild_failed_automatic_plan.py, NOT EXECUTED. Waitfulltests/install.
  It only permits failedc3b0 once, verifies112history/currenthashes, exactlegacyfeedback
  equals realstoredresponse+hosttemplate, and prefirstauto e99a...source-binding had
  author_feedback_file empty. Marks legacyfeedback automatic withsourceproof (no prose
  oroldfeedbackedit), then uses NEWplugin plan_repair+meteredmodels to rebuild SAME
  unfinishedreaderRepairCount2cycle. Doesnot increment/decrement/resetcycle2 or old
  taskcounts; clears onlyfailedstage ref/reservationfor newdispatch. ExistingP2stage
  attempts7/8, so onlyONEnewdispatchleft; scriptasserts <8 beforepaidrequest. Marks
  persistentintent beforecalls and refusessecondattempt. Operator event recordsall.
- Rationale: actual planexplicitly padded cuts withmoreoperations, contradicting
  acceptance; fixedplanner policy andtruthfulprovenance needreal retry. No author
  permission needed beyondexistingcopytest; no caps increased/wordtargetsrelaxed.
  Ifremainingboundeddispatchstillfails, donotforce100k orclaimcomplete.
- Afterhelperrebuild succeeds: launch_run.py latestnewresources/runtime, keep all
  providerapprovals/source98/nooriginaledits. Stopafterchapter2exportstillpending;
  atcleanstop normalresume WITHOUTrelaunchflagthenlaunchagain. Continue100000NEW.

### 2026-11-09 04:34 CST prior snapshot

- Secondreader report on3521stillREVISE:1mediumsame-principle repetition, endingissue
  nowlow. Driver automatic repair-plan106 then second(lastconfigured) readerrepair,
  readerRepairCount2/autoRepairLimit2. CurrentPOLISH taskc3b0cb6b-9d1e-4f6c-85fd-167260767bea,
  critic1, writer2candidate3516passlength, reviewer1missingrequiredissue_ids rejected;
  native reviewer2running. Calls111/known7552702tokens/newaccepted0. Launcher83749
  PID22044, installedf294e47... unchanged. No manualproseorbudgetchanges.
- Read actualautomatic repairplan quality/repairs/0002/longrun-repair-23877e3d.../
  instructions.md. It explicitly suggests filling cuts with more operationlayers,
  contrary to expression guard. Also hostprepare_repair title falselysaysuserconfirmed
  for automatic plans. This is PROGRAM adapter/prompt inconsistency, not newbookstyle.
- NewSOURCEONLYruntimefix: repair_packet reuses expression_review.GUIDANCE, says no
  auto narrowingauthorwordrange/no fixedemotionalrepeatcount/no paddingoperations;
  real conflictshouldbeexplicit. prepare_automatic_repair_feedback stillcallsHost
  prepare_repair forsourceverify/backups, onlynewfeedback gets truthfultitleautomatic
  suggestion plusbookauthority boundaries andautomatic-origin.json(user_reviewedfalse,
  sourcehashcontext/plan_digest). already_appliedreturnsunchanged. repairwiredtohelper.
  Current frozen authorfeedbackNOTedited. No hostcode changes. Not installed yet;
  deferuntilsafecompletedboundary/pausedtask. Readonlyreviewerfollowingthisnow.
-2tests RED then correctedfixture/placement errors;28longrun testsGREEN/11.54s.
  Full1255pass predatesonlythisruntime+2testfix; no currentfull1257claim. Sourcehelper
  isonlypendingproductiondiff sincef294. Preserveallremainingconstraints andmain100k.

### 2026-11-09 04:18 CST prior snapshot

- Actual100kstillNOTdone. Source/latestinstalled f294e47... unchanged, full1255green.
  Launcher83749/PID22044active, chapter0002POLISH tasklongrun-e2a179d0-0bf3-454a-9821-2003deaf0390.
- Repair-plan98completed, policyautomatically started contentpolish with reader2goals.
  Critic1passed, writer1candidate3538(8edits)lengthpassed; reviewer1validlyfound same
  two-person-edit permission repeated in3roundsofactions (plus residualconstraints).
  Native writer2candidate3521lengthpassed, review-inputrebuilt, reviewer2running.
  Calls103/known6872649tokens, newaccepted0. Originalcurrentbody still3552 untilcommit.
- No manual intervention/code mutation since03:55, allrecentrepair/retries autonomous.
  Keep priorfailures, costs, manualbaselineOPEN andoriginalsource98protection.
  Nextreader mustpass, posthoc/archive/export thenchapter2cleanstop (normalresume).
  Continue100000newaccepted; no stable-million/fully-unassisted claims.

### 2026-11-09 04:06 CST prior snapshot

- Reader-sim bothblind/permission-aware1responses valid, finalverdictREVISE with
  2mediumissues: repeated evidence/record/scientific-boundary conclusions, and
  constraint-analysis wording transcribed into narrative/dialogue. Local polish
  reviewer passed but blind downstream caught residuals. Keep that actual distinction.
- Driver automatically entered existing repair-plan auxiliary call98, nofailure,
  stillactive. Cursor staysreader-sim duringrepair, monitoractive_nodes empty is
  expected. Known6431129tokens/newaccepted0. Do NOT relaunch/kill as idle.
- Root read novel-writing skill+review/style references and fullchapter/currentbook
  contracts. Concrete repetition corroborates reader (initial record-only-organizes-
  evidence, nearend repeatsameprinciple, finalparagraph repeatsagain); book explicitly
  allowsomniscience/necessarytechnicalexposition. No globalban added; no manualproseedit.
  Revision-continuity skill read but StorySkillsCLI layoutinapplicable tothispluginbook.
- Latestcode unchanged/full1255passed; mainactual100kstillNOTcomplete. Followreal
  repair->polish->reader->posthoc->export, thencleanstop/resume and remainingchapters.

### 2026-11-09 04:02 CST prior snapshot

- Source+installedruntime/resources f294e47ad665cc6682172edf57fe94a2e339c630546337b9625446c9116b711b
  unchanged. Full latest plugin suite1255passed/395.00s, session85056complete.
  Host trackedclean, diff--checkpass. No newcode pending since classifier fix.
- Actualtasklongrun-e99a1d13-69a2-473d-9fc2-2bf88968ccb3 POLISH succeeded:
  critic1/writer1/reviewer1.6edits, final3552proseunits. Reviewer used20candidate
  referenceobjects; all resolved against currentcandidate, no inventedquotes accepted.
  Receipt before8f674192811778ba9c2cd0954cfe47d60aeecc52b0390a185903ec8942fc82e9
  after1474fcd1ed7ece5f55153feca2d4de8a506cdb86ffa0552657fcc6d65f7c0539.
  Body published normally by ScriptNode, no manualnovel edits.
- Normal launcher83749/PID22044 stillactive. Cursor READER-SIM chapter0002,
  blindreader1running. Calls96/known6088876tokens/newaccepted0. Need current reader,
  posthoc and export before accepted count. Follow through to100000newaccepted.
- Pending cleanstop afterchapter0002EXPORT, requestverify-first-chapter-commit-boundary.
  When launcher exitscode0+paused boundary: resume_after_fix.py --reason ... WITHOUT
  relaunchflag, thenlaunch_run.py latestsame.5newchapter safe restart stillconfigured.
- Originalsource98files protected/unchanged. Known manualbaseline receipt/emotion
  omission remainsOPEN; unknowncalls/feesnull persist. No stablemillion claim, no fake
  actualwordcount or testfixtures. Sourcebudget/current originalMVPwas3531 (NOT3519).

### 2026-11-09 03:56 CST prior snapshot

- 03:59correction: current MVP body8f67419... is3531actual, NOT3519;3519was earlier
  pre-cognition-fix candidate. Checked current frozen/formal/newcounter all3531, raw
  starts正文(noBOM/noheading). Thus BOM mismatch is a reproducible GENERAL edge-case,
  not actual cause of current12word difference. Corrected user commentary and old
  misleading inference below. Generic fix valid/regression tested; no prose changed.
- Newtaske99a... writer1candidate3552passed length,6patches, reviewer1running.
  Calls95/known5900745tokens/newaccepted0. Fullsuite85056stillrunning (57percent).
- Taskdec83... writer3received6streamchunks then120s inactivity -> native
  StreamChunkTimeoutError, failedcall preserved UNKNOWN usage. Paused92calls/
  known5800857tokens/newaccepted0. Production operational classifier lacked this
  exact new exception/message, so existing bounded recovery wasn't invoked.
- Added only `streamchunktimeouterror` and `no streaming chunk received for ` to
  existing plugin known-execution classifier.2new tests RED then49recovery/checkpoint/
  longrun tests passed/20.80s. Same-task dedup and2recoveries max remain, no timeout
  disabling, no content retry widening. Native available action still retry/skip;
  used existing stage relaunch semantics, no new custom bypass.
- Installed latestf294e47ad665cc6682172edf57fe94a2e339c630546337b9625446c9116b711b:
  includes BOM and local refs fixes too.164resources+4runtime coldload/settings check.
  Normal resume_after_fix WITHOUT relaunch flag kept taskdec83 reference; driver saw
  failed task and new production recovery_action spent first0002/polish operational
  allowance, then relaunched fresh stage. Previous task and all serial counters kept.
- Normal launcher83749/PID22044 usinglatest runtime+resources. Newpolish critic1running;
  calls93/known5800857tokens/newaccepted0. Source remains protected, chapter2MVP body
  still current, no accepted chapters until reader/posthoc/export. STOP afterchapter2
  export still pending. At clean boundary normal resume(no relaunch)/launch same latest.
- Full latest-source plugin suite RUNNING session85056; prior1249passed preBOM/refs/
  streaming fixes plus98+38+49focused current tests. Do not assume1255fullgreen yet.
- Tiny changes aftersync onlytestformatting, plugin installed resources/runtime exact.
  Nohosttrackedchanges. Continue100000actualNEWaccepted, keep manualbaseline issueOPEN,
  unknowncalls and missingprices(null) visible, never claim stable-million/unassisted.

### 2026-11-09 03:37 CST prior snapshot

- 03:48update: taskdec83... reviewer1failed literal expression_checks quote; reviewer2
  gave valid evidence of low-increment admin/microactions after cuts. Writer3running
  autonomous, calls92/known5800857tokens/newaccepted0. Active2a resources unchanged.
- Another source-only compatibility fix: local-review prompts already allowed catalog
  IDs and backend resolve_report supported them, but JSONschema accepted onlystrings.
  Three candidate excerpts arrays now accept string/ref_id/start_ref+end_ref. Preferred
  current-candidate references in first_message, canonical visible schema re-synced.
  Native scheduler test RED on schema then38local-workflow/local/schema/expression
  tests passed/37.61s, including validrefs publish and invalidrefs reviewer-only retry.
  No backend semantic gate relaxed. NOT installed; wait safe boundary. Read-only
  reviewer followup found no newP1/no evidence weakening; original hash/raw output
  binding remain intact. Full suite1249prethese2tiny fixes.
- 03:42update: writer2candidate3506passed length, independent local reviewer1running,
  calls90/known5568589tokens. The fixed latest-patch feedback worked in real run.
- Found generic BOM discrepancy in explicit regression: local frozen raw.decode(utf8)
  can retain BOM, direct count_prose then counts title, while measurement excludes it.
  Current manuscript has no initialBOM/title and formallycounts3531 (seecorrection).
  Source count_prose now removes initial BOM;
  two explicit regressions RED then98length/local/draft/focused/fragment tests passed
  /43.92s. This tiny newest fix NOT installed yet; wait safe stage/export boundary.
  Do NOT alter frozen active task resources/inputs. Existing formal counting correct.
- The one pinnedE4C reissue reached3471 words, failed length (no body publication),
  and exhausted old native retry limit. Its old script again only returned stale
  review-input patches, so pinning old resources cannot exercise the new feedback.
  Preserved old task/history/fees; used normal resume_after_fix --relaunch-failed-stage
  for POLISH only. No counter resets within any old task or serial ledger.
- Newest source/installed2a2883e9ef65d3b4e8301db427fd562cdbf88c7d507110eeaf741680f9e9ab16
  includes malformedJSON fix.164resources+4runtime coldload/settings verified.
  Normal launcher64510/PID24236 now uses this revision for runtime AND resources.
- New tasklongrun-dec83d42-f1bb-428a-8908-6b801a72b178: critic passed first response;
  agent_pl attempt1running.88calls / known5335852tokens / acceptednew0 at03:36.
- Full plugin local suite1249 passed/425.73s, session18970completed. Latest actual
  new polish writer attempt1was3295short; native retry2running with fixed feedback.
  Calls89/known5392675tokens, acceptednew0. Source/unpriced/manual-open caveats hold.
  Clean stop after chapter2export remains. At boundary normal resume/launch same
  latest source, no relaunch needed. Continue actual100k, do not stop at tests.

### 2026-11-09 03:31 CST prior snapshot

- User asked whether100k is one output: answered sequential chapters3500–4000
  prose units, all gates before count, rolling4chapter plan. Main100k task continues.
- Local polish attempt3failed3399 words. New shared revision_patch.length_edit_budget
  and local writer_input/retry_feedback give frozen-source net budget and retain
  actual latest patch before native output cleanup, even before review-input exists.
  Related55tests passed/31.30s. Read-only review found malformed JSON read outside
  try; new test RED then37local+patch tests passed/7.99s after including read in try.
- Installed316a7ca40ed176ad18c6d0976a65f788bbdfccf980957c9701f8cfbb3ca9f274,
  164resources+4runtime, coldload/settings verified. Tiny malformed-JSON fix is source
  only, not yet installed. Runtime now uses316a but frozen task pinsE4C resources.
- Helper resume_local_patch_budget.py matched genuine native session25f68001 against
  failed candidate hash60aa13464fad2dcf19f494ae3dbf107bd8059427906a333fb4eb0dd87f787b76,
  generated fixed diagnostic feedback, snapshots before/after+last-rejected-patch,
  and native reissued agent_pl/candidate/reviewer/commit preserving every counter.
  No prose edits. Operator event records intervention. Do NOT repeat that helper.
- Launcher49696/PID26616, task6946ef62... same POLISH; agent_pl attempt4 running.
  Calls86 / known tokens5229144, new accepted0. E4C task resource pin retained until
  chapter2 clean export stop; then sync latest source, normal resume/launch newest.
  All source protections/open manual observation/unpriced costs from older snapshot
  still apply. Main run not complete. Continue100000 NEW accepted, no fake passes.

### 2026-11-09 03:05 CST prior snapshot

- Current active+installed revision `e4c1832e22ada5531b4a772a82aed38c633a83f1d73284d4f8fbe34006d3ec66`,
  164 resources+4 runtime files, cold loaded, user settings unchanged. Launcher
  session75779/PID21400, chapter0002 POLISH, task `longrun-6946ef62-2d1a-4f23-a8b4-00c219b3f846`.
- Chapter0002 MVP finally completed from verified draft checkpoint. All14 actual
  guard/si_post/render/tail nodes passed; body is physically in story/0002/chapter.md.
  No manually edited prose. ZERO accepted new prose until reader/archive/export.
- In checkpoint task0a1b9255..., facts repair1/audit3: new handoff logic correctly
  returned late-recap witnesses to auditor instead of rewriting valid prose.
  Expression frozen source3350 words, successive patches hovered3449/3450: feedback
  used last-candidate deficit while patches always reapply frozen source. Source
  fixes now give frozen net-change budget, suggested midrange, and retain matching
  previous_patch before host deletes rejected output. Actual final candidate3519
  had genuine cognition error introduced by replacement (“he knows selected branch”).
- `resume_with_retained_patch_feedback.py` found real native response session0e7b922b
  by exact candidate-body hash, reconstructed patch for diagnostic snapshot, generated
  corrected feedback, then native reissued repair+candidate+audit+commit without
  resetting counters or touching prose. Pinned oldFb0 resources for that frozen task;
  updated observation runtime8d3e...; launcher60023 ended only later at polish failure.
  The single reissued edit then passed and MVP published. Previous native history intact.
- Initial polish taskd0804c5b... failed3 critic responses: validator required fields
  and evidence arrays but first_message never exposed schema. This was a PROGRAM
  contract visibility defect, not merely model instability. Added plugin maintenance
  tool `tools/sync_output_schemas.py` and equality/idempotence tests.11 agent prompts
  across character/outline/polish/reader-sim now expose exact canonical node schema;
  MVP schemas already matched.49 focused tests passed/26.10s; actual restarted polish
  critic passed FIRST response, writer passed FIRST anchor/length composition.
- Current local reviewer first report hallucinated2 quote strings; evidence gate
  rejected, second valid review found genuine repeated time-chain explanation and
  returned to writer. Latest observed writer agent_pl attempt2; all autonomous so far.
  Backend audit_evidence supports excerpts references, but local-review schema still
  strings only; noted possible future improvement, NOT implemented during this run.
- Full source suite1247 passed/401.61s after schema visibility changes; earlier1245
  passed after frozen-budget/previous-patch fix. No current tests or code changes pending.
- Calls83 / known provider tokens5031699 at last snapshot; plus unknown interrupted/
  failed calls preserved. No applicable prices -> amounts null/unpriced, not zero.
- Current autoCheckpoint consumed after MVP. Stop request remains: clean stop after
  chapter0002 EXPORT (`verify-first-chapter-commit-boundary`). On code0+paused boundary,
  use normal resume_after_fix.py reason (NO relaunch flag) then launch_run.py. Configured
  automatic restart after5 newly accepted chapters still remains for chapter0006.
- Source98files unchanged; original manuscript never edited. Baseline manual emotion/
  receipt timing observation remains OPEN despite model audit pass. Keep all failures,
  costs and operator interventions in final report. DO NOT claim unassisted run or
  stability merely because eventually reaching target. Continue100000 NEW accepted.

- Active installed revision `fb0a528452a6da916ef3a5cb74db456df4bb53a9b5faf0087fa8021d8ca23976`,
  164 resource files and4 runtime files verified/cold loaded. Launcher session45910,
  venv PID23960, task `longrun-0a1b9255-bb25-4e0b-9011-2858b8c6556b`,chapter0002 MVP.
- Actual baseline/first new draft exposed further gates. First Doubao draft1704
  prose units; fact repair reached3571, approved. Scene planner had invented one
  source_quote; bounded retry correctly rejected it. Fact audit needed source-name
  evidence/schema corrections and an incomplete stream caused unknown usage.
- Old MVP task `longrun-19bef798-5f16-4166-a2fd-8cb40d229389` failed at expression
  patches after6 attempts. Cause: auditor split correct “对+姜未+来说” as a new name;
  repair hallucinated an extra 来 in old anchor. Strict patch matcher refused it.
  One explicit native operator reissue kept counters/history and all prefix nodes;
  fresh audit corrected naming but selected a later recap as event e003, which
  positional validation incorrectly sent to body repair; attempt7 stopped.
- No prose was manually changed to appease those reports. Calls62 and3460247 known
  provider tokens retained before checkpoint; unknown failed/interrupted costs also retained.
- Generic fixes (no book names in universal templates): exact-anchor error now returns
  actual frozen paragraph; auditor/repairer prompts cover name+grammatical continuation,
  checks-as-coverage, and event occurrence vs narrative placement. Positional reversal
  without a grounded same-pair semantic handoff issue is invalid evidence and goes
  back to auditor; actual semantic handoff issues still block body publication.
- New plugin `draft_review_checkpoint.py` extends existing checkpoint kind. It binds
  failed source task/chapter/workspace, facts-approved/input/audit, plan/sources,
  book contract and immutable body seed. New native task disables all authors and
  prep, reruns14 fact/expression/si_post/render/tail gates. `guard_source_file` is
  text+output (file type inlined content in real script argv; fixed after native test).
  validate_selection checks actual seed path; render/final receipt/cache equality
  verified. If render succeeds but tail fails, proof is checked and converted to
  existing tail checkpoint. Changed source/author body rejected.
-117 focused tests passed/36.56s, including actual native selected-DAG execution
  with test-only model replies and real guard/si_post/render scripts. Read-only
  review found/repaired tail transition and missing si_post risks. Full suite
  currently running session7808; previous full suite1231 passed before these last changes.
- `resume_verified_draft_checkpoint.py` successfully prepared actual copy checkpoint
  seed `cache/recovery/draft-review/461a43299bdbbb8cecc50f23/body.json` with3571 prose
  units. New task currently starts facts_repair from this seed, no writer replay.
  Calls63, known tokens3460247 at last snapshot, ZERO new accepted prose yet.
- `observability/stop-request.json` requests a clean stop after chapter0002 export
  to test committed-boundary resume. Runner supports this generically and reports
  boundary_stops separately. On clean stop, resume with normal resume_after_fix.py
  then launch_run.py; don't reissue the old failed source task. Existing configured
  safe_restart_after_chapters5 still remains for later in-run automatic restart.
- Manual baseline archive timing mixup remains open in manual_observations/report,
  despite automatic audit pass. Source98files unchanged; original manuscript never
  edited. Continue actual100000 NEW accepted target; do not stop at tests/checkpoints.

Latest 00:11 CST: installed revision `c9540d7d8b4ed57666e7caa1ef253cf8f57e905b17fa7740894e4e349ae047c2`,
launcher session31363, venv launcher PID25800. Read-only review found the repair
packet always fell back to style text; replaced with real book_contract.resolve,
tested omniscient/world/author intent without a model (23 longrun tests pass).
Native full plugin suite collected before this last added test: 1221 pass/370.16s.
An intentional running-node interruption was performed on actual child PID23388,
not its venv launcher. Blind reader had completed immediately before interruption;
it remained completed on resume. Reader arbiter was in flight and was explicitly
reissued as attempt2; its old reserved/unknown usage was retained. Last snapshot
735657 provider-reported tokens,17calls,0 new accepted prose; two calls reserved,
one abandoned by controlled interruption and one currently in flight. This is an
observed process recovery, not yet an accepted chapter or long-run quality result.

Latest 00:34 CST: real runner is revision `5bd92f1251842da58510cf0217ea2e181c0faab9b428d67ceaecf20b39f92d55`,
launcher session5889/PID8268, phase continuation, chapter0002 rolling planner.
Baseline reader passed on unchanged body, with a recorded disagreement over whether
branch thresholds needed more explanation. Native posthoc completed with nonempty
characters/world facts, then direct auxiliary audit disconnected twice (server
RemoteProtocolError before response). Both failed usage records remain unknown.
Auxiliary requests now use native streaming=True, ainvoke aggregates final content
and metered usage. Test watched false→true;24 tests passed/10.94s. This real streaming
audit succeeded and returned170256 provider tokens, bringing completed known total
to1323143. Baseline original body not edited; zero new accepted prose so far.

Manual source review found a real archive-summary timing mixup: t=8 command-receipt
relief was summarized as reaction after survival confirmation at t=10. Recorded in
copy observability/manual-observations.json and manual_observation event, with
quotes/hashes. Automatic baseline independent audit missed it and returned pass.
Source ledger report now retains open manual observations even after model passes;
stale evidence is flagged, never silently treated as resolved.25 tests pass/11.86s.
This report-only change is not yet in active runner revision; install with next
necessary restart or final status refresh. Generation can continue without editing
the archived fact to conceal the observed error. Final acceptance must mention it.

Latest 00:45 CST: installed/active revision `d9c767bbfe215d002b5d13aaa8bacb1c0b74f5960de9c336e978dad40a13d8ac`,
launcher session45020/PID21468. Chapter0002 successfully entered MVP after fresh
outline task. Real runs exposed expected_state path bug: 'location' was accepted
although state actually uses 'snapshot.location'; accepted plan immediately stale,
old controller repeated paid planning. Stopped actual child12584 (venv parent8268),
retained all candidates/tasks/costs; `relaunch_outline_after_schema_fix.py` records
native interrupted history, settles failed P2 dispatch, clears only current ref,
creates new task under changed frozen plugin resource guards. No manuscript edits.
Strict normalize now verifies entity/full path and current-entry equality;
need_plan separates missing vs null. Fresh unusable outline now pauses rather than
returning to another paid outline. Planner prompt explicitly names full paths.
75 tests passed/46.88s (serial39+longrun25+import6+outline5). Read-only review no P1;
nonblocking boolean-vs-number equality nuance remains in Python comparison.
Current real output validates new paths; second chapter MVP underway, zero accepted
new characters yet. Known provider tokens1695859 after30 calls, plus unknown calls.

00:55 CST: full current plugin suite1231 passed/379.85s. Added boundary tests confirm
future chapter assumptions may differ from current state and legacy signed plans
cannot satisfy missing fields via null. Actual MVP preparation reached scene planner
agent_nw (also used by single writer); single authoring model stays approved Doubao.
Latest known tokens2311748/42calls, zero new accepted prose. No more source edits
pending; active installed revision remains d9c767bbfe21..., session45020.

- Current installed revision `fe30a4cd4854796f643d46bcefa4ddfab19d6798d884d8e64e301ff02a25fb7d`;
  launcher session 58957, PID 1236. Use parent `monitor_run.py` for compact current status.
- Fresh native inputs now materialize hidden file defaults exactly as the host task manager.
  Earlier incomplete-input setup was invalidated; all nine calls/188663 tokens retained.
- Imported Markdown world/character data survives preparation, trimming and rendering;
  canonical P0 index refresh avoids format-only rolling-plan invalidation. Six tests cover this.
- Controller has separate durable journal for intentional scope changes. Native session
  persistence flushes periodically. Completed nodes remain; interrupted nodes are reissued.
- Fresh baseline review found a medium causal omission (98% branch trigger not explained)
  and a low repeated explanation. No new accepted prose yet; 593003 reported tokens at last snapshot.
- Baseline nonpass now follows existing production repair/scope policy, never skips the gate.
  Copy chapter intent explicitly permits minimum fixes; original source still unchanged.
  Old reader report/task retained; current new reader task will reassess repair scope.
- Latest longrun tests: 22 passed/8.20s, including repair, outside-scope pause and baseline
  polish→reader transition. Installed 163 resources+4 runtime files verified; cold load passes.
- Technical target remains 100000 NEW accepted prose units; no completion claim is permitted
  until real export-bound target reached. Keep all setup/retry usage in total costs.

- Source: `C:/xs2/data/verification/20261108-local-revision-v1/cases/scifi/book`.
- Copy/artifacts: `C:/xs2/data/verification/20261108-longrun-100k/book` and parent.
- Real runner launcher: parent `launch_run.py`; PID and installed root in `process.json`.
- Current installed revision: `4672b2067ee0615f58221c37773d1697444a0664ef85d38864ecdcc7ffc9f3d9`.
- Launcher tool session: 60234 (may complete/pause; read `run-native.log` and cursor).
- No original writes. Source manifest checks 98 files; protected host config hashes
  are in copy `observability/protected-user-config.json` and were unchanged.
- Native runtime-data/session persistence and workflows are inside the copy.
- Two real story-plan/style requests completed: total 29496 provider tokens.
  They produced new long-form meta/story_plan and style_profile in copy only.
- Initial no-call startup failed because native ScriptLibrary registration lacked
  revision; fixed with resource SHA identity and real ScriptNode test.
- Next baseline post-hoc launch correctly rejected old reader scope after story
  plan/style change. Added baseline_plan→baseline_reader→baseline_archive sequence
  and stale baseline migration. Existing first chapter remains unchanged/un-counted.
- Both resumes retained all ledgers; `resume_after_fix.py --reason ...` records an
  operator_resume and clears paused, without resetting budgets or task evidence.
- Last observed real request: baseline `reader-sim/agent_blind_reader`, third call,
  reserved/in flight; wait for native result (600-second request timeout).
- `launch_run.py` allows one configured clean process restart after 5 new accepted
  chapters, then automatically resumes. Natural errors stop and retain cursor.
- Source full plugin regression 1210 passed / 362.45s; host novel 171 passed /
  27.67s (existing Starlette deprecation warning); final focused long-run tests19
  passed / 9.41s after adding baseline-reader and recovery-summary tests.
- Machine report now includes process_recovered, controlled_restarts and operator
  resumes. Read-only reviewer found no remaining P1 before the real requests.
- Real target remains 100000 NEW accepted prose units (Han characters, Latin/digit
  words, excluding headings/punctuation/whitespace and original chapter0001).
- Do not stop at prototype/unit tests or claim target reached early. Continue real
  generic workflows, diagnose actual gates, retain all failed/unknown calls and
  record any implementation fixes. Do not bypass reader/archive/length gates.
