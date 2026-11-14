"""Novel production decisions owned by the plugin, independent of browser state."""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
import re

STAGES = ("novel-advisor", "build", "character", "story-plan", "outline", "mvp", "polish", "reader-sim", "post-hoc", "export")
PRODUCTION = ("mvp", "polish", "reader-sim", "post-hoc", "export")
ARTIFACTS = {
    "novel-advisor": "learning/advisor_report.json", "build": "meta/world_foundation.md",
    "character": "meta/character_profiles.md", "story-plan": "meta/story_plan.md",
    "outline": "outline/near_term_outline.md", "mvp": "story/{chapter}/chapter.md",
    "polish": "story/{chapter}/chapter.md", "reader-sim": "story/{chapter}/reader_report.json",
    "post-hoc": "story/{chapter}/diff_story_confirmed.md", "export": "export/manuscript.md",
}


@lru_cache(maxsize=1)
def length_quality():
    path = Path(__file__).with_name('length_quality.py')
    spec = importlib.util.spec_from_file_location(__name__ + '_length_quality', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter(state):
    value = str(state.get("values", {}).get("chapter_number", "0001")).zfill(4)
    if not re.fullmatch(r"[0-9]{4}", value) or value == "0000":
        raise ValueError("自动创作需要有效的章节号。")
    return value


def reader_report(root, state):
    number = chapter(state)
    body = Path(root) / f"story/{number}/chapter.md"
    report = Path(root) / f"story/{number}/reader_report.json"
    scoped = report.is_file()
    if not scoped:
        report = Path(root) / "quality/reader_report.json"
    if not report.is_file() or not body.is_file():
        raise ValueError("缺少本章正文或读者报告，请先完成模拟读者。")
    data = json.loads(report.read_text(encoding="utf-8"))
    bound = str(data.get("chapter_number", number if scoped else "")).zfill(4)
    if bound != number:
        raise ValueError("读者报告不属于当前章节，请重新评估。")
    expected = data.get("body_sha256")
    if (expected and expected != hashlib.sha256(body.read_bytes()).hexdigest()) or (
        not expected and body.stat().st_mtime > report.stat().st_mtime
    ):
        raise ValueError("正文在读者评估后有变化，请重新评估。")
    if data.get("verdict") not in {"pass", "revise", "reject"}:
        raise ValueError("读者报告没有有效结论，请重新评估。")
    return length_quality().gate_report(root, number, state.get('values', {}).get('target_word_count', ''), data)


@lru_cache(maxsize=1)
def run_ledger():
    path = Path(__file__).resolve().parents[1] / 'story_support/archive_store.py'
    spec = importlib.util.spec_from_file_location('production_archive_store', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def run_control():
    spec=importlib.util.spec_from_file_location('production_run_control',Path(__file__).with_name('run_control.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def serial():
    return run_control().serial()


@lru_cache(maxsize=1)
def longrun():
    spec=importlib.util.spec_from_file_location('production_longrun',Path(__file__).resolve().parents[1]/'longrun/ledger.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def continuous(state):
    return state.get('mode')=='serial' and (state.get('autoScope')=='serial_batch' or state.get('autoNext') is True or bool(state.get('serialRunId')))


@lru_cache(maxsize=1)
def execution_guard():
    spec=importlib.util.spec_from_file_location('production_execution_guard',Path(__file__).resolve().parents[1]/'production_guard/production_guard.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def record_stage(root, state, stage, kind, task=None):
    task = task or {}
    run_ledger().event(root, kind, {'chapter': chapter(state), 'stage': stage,
        'task_id': task.get('task_id', ''), 'status': task.get('status', ''),
        'input_version': run_ledger().identity({'values': state.get('values', {}),
            'contract': run_ledger().contract(root),
            'models': {k: v for k, v in state.items() if 'model' in k.lower()},
            'task_parameters': task.get('parameter_values', {})}),
        'artifact_sha256': run_ledger().digest(root, ARTIFACTS[stage].format(chapter=chapter(state)))})
    if longrun().enabled(root):longrun().observe_task(root,state,stage,task,kind)


def verify_completion(root, state, stage, task):
    run_ledger().recover(root)
    if stage=='outline' and task.get('parameter_values',{}).get('planning_mode')=='rolling':
        if ((task.get('node_states') or {}).get('script_serial_commit') or {}).get('status')!='completed':
            raise ValueError('本次滚动计划缺少完成节点')
        state['serialPlanningResult']=serial().verify_task(root,task['task_id'])
    else:_verify_completion(root, state, stage, task)
    if stage == 'post-hoc':
        path = Path(root) / f'story/{chapter(state)}/confirmed_state.json'
        if not path.is_file():
            raise ValueError('章节确认档案缺失，不能完成归档')
        snapshot = json.loads(path.read_text(encoding='utf-8-sig'))
        if (not snapshot.get('archive_commit_id') or not task.get('task_id')
                or snapshot.get('task_id') != task['task_id']
                or ((task.get('node_states') or {}).get('script_confirm_archive') or {}).get('status') != 'completed'):
            raise ValueError('本次任务缺少已完成的章节提交凭据')
        run_ledger().verify_snapshot(root, snapshot)
        if snapshot.get('body_sha256') != run_ledger().digest(root, f'story/{chapter(state)}/chapter.md'):
            raise ValueError('归档正文已有变化')
        if any(run_ledger().digest(root, p) != h for p, h in snapshot.get('source_hashes', {}).items()):
            raise ValueError('归档依据已有变化')
    record_stage(root, state, stage, 'stage_complete', task)
    run_control().observe(root,state,stage,task)
    if stage=='export' and longrun().enabled(root):longrun().accept_chapter(root,chapter(state),task)
    if state.get('productionLaunchLease'):
        execution_guard().release_launch(root,state,stage)
    refreshes=state.get('compositionReviewRefreshRecoveries') or {}
    key=f"{chapter(state)}/{stage}/{state.get('readerRepairCount') or 0}"
    if key in refreshes:
        state['compositionReviewRefreshRecoveries']={**refreshes,key:{**refreshes[key],'completed':task['task_id']}}


def _verify_completion(root, state, stage, task):
    if stage=='polish' and ((task.get('node_states') or {}).get('script_local_commit') or {}).get('status')=='completed':
        source=Path(__file__).resolve().parents[1]/'local_revision/local_revision.py'
        spec=importlib.util.spec_from_file_location('completed_local_revision',source)
        local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
        local.verify_attempt(root,task)
        return
    checkpoint = state.get('automaticCheckpoint') or {}
    if stage == 'mvp' and checkpoint.get('stage') == stage:
        recovery_checkpoint().verify(root, state, task)
        return
    focused = (task.get('node_states') or {}).get('script_focused_commit') or {}
    if stage == 'polish' and focused.get('status') == 'completed':
        length_quality().verify_focused_attempt(root, chapter(state), task, focused)
        return
    artifact = Path(root) / ARTIFACTS[stage].format(chapter=chapter(state))
    if not artifact.is_file() or not artifact.read_text(encoding="utf-8").strip():
        raise ValueError(f"任务结束但缺少有效产物 {artifact.relative_to(root)}，自动流程已暂停。")
    started = task.get("created_at")
    if started:
        try:
            timestamp = datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            raise ValueError("任务时间记录不完整，无法确认本次产物。")
        if artifact.stat().st_mtime + 2 < timestamp:
            raise ValueError("产物早于本次任务，请检查任务结果后再继续。")
    if stage == "reader-sim":
        reader_report(root, state)


def _launch_feedback(root,selected,pending_parameter,guard):
    """Bind selection and exact bytes, reusing the pending frozen parameter."""
    root=Path(root).resolve();source=(root/selected).resolve()
    if not source.is_relative_to(root):raise ValueError('作者意见文件不能离开当前作品。')
    frozen_pattern=r'cache/production-launch-feedback/([0-9a-f]{64})/feedback\.md'
    match=re.fullmatch(frozen_pattern,str(pending_parameter or ''))
    if match:
        frozen=(root/pending_parameter).resolve()
        if not frozen.is_relative_to(root) or not frozen.is_file():
            raise ValueError('待启动作者意见快照缺失，不能改写原意图。')
        raw=frozen.read_bytes();origin=frozen.parent/'automatic-origin.json'
        origin_raw=origin.read_bytes() if origin.is_file() else b''
        identity=hashlib.sha256(selected.encode()+b'\0'+raw+b'\0'+origin_raw).hexdigest()
        if identity!=match[1]:raise ValueError('作者意见选择或冻结快照已有变化。')
        receipt={'schema':1,'selected_parameter':selected,'frozen_parameter':pending_parameter,
                 'feedback_sha256':hashlib.sha256(raw).hexdigest(),
                 'origin_sha256':hashlib.sha256(origin_raw).hexdigest()}
        receipt_path=frozen.parent/'selection.json'
        if receipt_path.is_file() and json.loads(receipt_path.read_text(encoding='utf-8-sig'))!=receipt:
            raise ValueError('作者意见冻结来源凭据已有变化。')
        # A retained immutable snapshot remains usable if its mutable original
        # disappeared. An existing selected source must still match its bound
        # bytes and provenance; changed author input never silently reuses it.
        if source.exists():
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=receipt['feedback_sha256']:
                raise ValueError('已选择的作者意见内容已有变化，不能沿用待启动意图。')
            current_origin=source.parent/'automatic-origin.json'
            current_raw=current_origin.read_bytes() if current_origin.is_file() else b''
            if hashlib.sha256(current_raw).hexdigest()!=receipt['origin_sha256']:
                raise ValueError('已选择的作者意见来源已有变化。')
        elif (source.parent/'automatic-origin.json').is_file() and hashlib.sha256(
                (source.parent/'automatic-origin.json').read_bytes()).hexdigest()!=receipt['origin_sha256']:
            raise ValueError('已选择的作者意见来源已有变化。')
        # Earlier snapshots encoded the same source+byte proof in their path;
        # reconstruct only this receipt, never the pending request or its bytes.
        if not receipt_path.is_file():guard.store().atomic(root,receipt_path.relative_to(root).as_posix(),json.dumps(receipt,ensure_ascii=False,sort_keys=True))
        return pending_parameter
    if not source.is_file():raise ValueError('已确认的作者意见文件不可用，请重新选择。')
    if pending_parameter is not None:return selected  # Legacy, unfrozen intent.
    raw=source.read_bytes();origin=source.parent/'automatic-origin.json'
    origin_raw=origin.read_bytes() if origin.is_file() else b''
    folder='cache/production-launch-feedback/'+hashlib.sha256(selected.encode()+b'\0'+raw+b'\0'+origin_raw).hexdigest()
    parameter=folder+'/feedback.md'
    receipt={'schema':1,'selected_parameter':selected,'frozen_parameter':parameter,
             'feedback_sha256':hashlib.sha256(raw).hexdigest(),'origin_sha256':hashlib.sha256(origin_raw).hexdigest()}
    journal=guard.store()
    for relative,data in [(parameter,raw),(folder+'/selection.json',json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode()),
                          *([(folder+'/automatic-origin.json',origin_raw)] if origin_raw else [])]:
        target=(root/relative).resolve()
        if target.is_file():
            if target.read_bytes()!=data:raise ValueError('已有作者意见冻结快照或来源凭据变化。')
        else:journal.atomic(root,relative,data.decode('utf8'))
    return parameter


def parameters(state, definition):
    context=state.get('productionLaunchContext') or {}
    automatic_launch=(context and state.get('autoNext') is True and state.get('autoArmed') is True
                      and state.get('autoController')=='server-v1')
    workflow_id=str(definition.get('workflow_id',''))
    workflow=workflow_id.removeprefix('xs2-novel-flywheel-')
    if automatic_launch:
        stage=context['stage'];expected=context.get('workflow_id')
        if (workflow_id!=expected if expected else workflow!=stage) or context['chapter']!=chapter(state):
            raise ValueError('待启动步骤或章节已变化，请重新检查后启动。')
        workflow=stage
    spec=importlib.util.spec_from_file_location('production_launch_preflight',Path(__file__).resolve().parents[1]/'production_guard/production_guard.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    guard.check_definition(definition,state.get('values',{}),stage=workflow)
    values = dict(state.get("values", {}))
    short_fallback = state.get('shortContextFallback') or {}
    if workflow == 'mvp' and state.get('mode') == 'short' and short_fallback.get('chapter') == chapter(state):
        values['preparation_mode'] = 'full'
    active=state.get('activeCompositionBudget') or {}
    if (workflow in ('reader-sim','post-hoc','export') and active.get('chapter')==chapter(state)
            and active.get('nominal_target')==values.get('target_word_count','')):
        values.update(target_word_count=active['target'],words_per_chapter=active['target'])
    checkpoint=state.get('automaticCheckpoint') or {}
    if checkpoint.get('kind')=='draft_review' and checkpoint.get('effective_target'):
        values.update(target_word_count=checkpoint['effective_target'],words_per_chapter=checkpoint['effective_target'])
    premise = [values.get("premise", "")]
    for key, label in (("world_direction", "世界观方向（规划草稿）"),
                       ("source_idea", "用户原始设定（保留细节，矛盾处按已采用的顾问建议澄清）"),
                       ("advisor_guidance", "已采用的小说顾问建议")):
        if str(values.get(key) or "").strip():
            premise.append(f"{label}：\n{str(values[key]).strip()}")
    values["premise"] = "\n\n".join(part for part in premise if part)
    values["chapter_number"] = chapter(state)
    if state.get("mode") == "short":
        values.update(conflict_plan_mode="short_full", chapter_ending_mode="book_final")
    elif values.get("conflict_plan_mode") not in {"serial_opening", "serial_chapter", "serial_arc"}:
        values["conflict_plan_mode"] = "serial_chapter"
    if any(variable["key"] == "polish_pass" for variable in definition.get("variables", [])):
        receipt = state.get('lengthRepairFeedback') or {}
        values['polish_pass'] = ('length_only' if isinstance(receipt, dict)
            and receipt.get('path') == str(values.get('author_feedback_file') or '').strip()
            and receipt.get('chapter_number') == chapter(state) and receipt.get('path') else 'content')
    result = {}
    for variable in definition.get("variables", []):
        key = variable["key"]
        if variable.get("source_type") == "output" or (variable.get("type") == "file" and key != "author_feedback_file"):
            continue
        # The workflow's optional feedback path is a conventional location,
        # not an author-approved repair plan for this chapter.
        value = values.get(key, "" if key == "author_feedback_file" else variable.get("default", ""))
        if variable.get("required") and not variable.get("hidden") and variable.get("type") != "file" and not str(value or "").strip():
            raise ValueError(f"请先填写{variable.get('name') or key}。")
        if value is not None:
            result[key] = str(value)
    if automatic_launch:
        root=Path(context['root']).resolve();stage=context['stage']
        pending=state.get('autoPending') or {}
        feedback=result.get('author_feedback_file')
        if feedback:
            pending_parameter=(pending.get('parameters') or {}).get('author_feedback_file') if pending else None
            result['author_feedback_file']=_launch_feedback(root,feedback,pending_parameter,guard)
        options=context.get('checkpoint_options') or {}
        effective={**options.get('parameter_values',{}),**result}
        if pending:
            if effective!=pending.get('parameters'):
                raise ValueError('待启动任务的参数发生变化，请检查后重新启用。')
            if pending.get('selected_node_ids') and (
                    pending['selected_node_ids']!=options.get('selected_node_ids') or
                    pending.get('checkpoint_source_task_id')!=(state.get('automaticCheckpoint') or {}).get('source_task_id')):
                raise ValueError('待恢复任务的检查点发生变化')
        context.update(effective_parameters=effective,workflow_id=definition.get('workflow_id',stage))
        guard.reserve_launch(root,state,stage)
        state.pop('productionLaunchContext',None)
    return result


def launch_check(root, state, stage, support=None):
    state.pop('productionLaunchContext',None)
    run_ledger().recover(root)
    longrun().check_budget(root)
    if continuous(state):serial().bootstrap(root,state)
    if stage not in STAGES or stage == "novel-advisor":
        raise ValueError("请先在小说顾问中确认方向，再启用正文自动创作。")
    if stage in ('reader-sim','post-hoc','export'):
        source=Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py'
        spec=importlib.util.spec_from_file_location('launch_composition_budget',source)
        composer=importlib.util.module_from_spec(spec);spec.loader.exec_module(composer)
        quota=composer.current(root,chapter(state))
        state['activeCompositionBudget']=({'chapter':chapter(state),'nominal_target':state.get('values',{}).get('target_word_count',''),
            'target':f"{quota['minimum']}-{quota['maximum']}"} if quota else None)
    if stage == "mvp":
        body = Path(root) / f"story/{chapter(state)}/chapter.md"
        if body.is_file() and body.read_text(encoding="utf-8").strip():
            if (state.get('automaticCheckpoint') or {}).get('stage') == stage:
                recovery_checkpoint().validate(root, state, state['automaticCheckpoint'])
                if continuous(state):run_control().admit(root,state,stage)
                _stage_launch_context(root,state,stage)
                return
            raise ValueError("本章已有正文，自动创作不会覆盖；请从章节目录选择返修或重新生成。")
        if support is None:
            raise ValueError("故事连续性检查服务不可用，自动创作已暂停。")
        check = support.preflight(root, chapter(state))
        if not check.get("ready"):
            raise ValueError(check.get("message") or "请先完成本章规划与前文审核。")
    if stage in {"post-hoc", "export"} and reader_report(root, state)["verdict"] != "pass":
        raise ValueError("本章读者评估尚未通过，不能自动审核或导出。")
    if continuous(state):run_control().admit(root,state,stage)
    record_stage(root, state, stage, 'stage_launch')
    _stage_launch_context(root,state,stage)


def _stage_launch_context(root,state,stage):
    # No ownership exists until parameters() and selected feedback validate.
    state['productionLaunchContext']={'root':str(Path(root).resolve()),'stage':stage,'chapter':chapter(state),
        'checkpoint_options':state.pop('productionCheckpointOptions',{})}


def _length_cycle(state):
    cycle = max(0, int(state.get('readerRepairCount') or 0))
    prior_count = max(0, int(state.get('lengthRepairCount') or 0))
    total = max(prior_count, int(state.get('lengthRepairTotal') or 0))
    tracked = state.get('lengthRepairCycle')
    # Old states used one chapter-wide count. Preserve it in the total while
    # giving an already-started content revision its first tracked budget.
    same = (int(tracked) == cycle) if tracked is not None else cycle == 0
    focused_migration = ((cycle > 0 or state.get('lengthRepairStrategy') in {'fragment-v3', 'fragment-v4', 'fragment-v5'})
                         and state.get('lengthRepairStrategy') != length_quality().LENGTH_REPAIR_STRATEGY)
    # An explicit book-only writer selection is a new execution profile. Track
    # it durably so it receives one bounded budget without erasing history.
    writer_changed = (state.get('writerModel') or '') != (state.get('lengthRepairModel') or '')
    return cycle, prior_count if same and not focused_migration and not writer_changed else 0, total


NEW_BOOK_DEFAULTS_ENABLED = False  # Enable only after end-to-end verification.


def new_book_defaults(providers, default_model):
    """Resolve a new-book recipe against current configuration, never migrate it."""
    if not NEW_BOOK_DEFAULTS_ENABLED or not default_model:
        return {}
    def select(role):
        candidates = []
        for identity, provider in providers.items():
            name = str(provider.get('name', '')).lower()
            url = str(provider.get('base_url', '')).lower()
            models = provider.get('models') or []
            if not isinstance(models, list) or not models or not isinstance(models[0], str):
                continue
            matched = ('火山' in name or 'volcengine' in name or 'ark.cn-' in url) if role == 'writer' else (
                ('modelflare' in name or 'modelflare.' in url) and provider.get('provider_type') == 'anthropic')
            if matched:
                candidates.append(identity + ':' + models[0])
        return candidates[0] if len(candidates) == 1 else ''
    writer, polish = select('writer'), select('polish')
    if not writer or not polish:
        return {}
    return {'analysisModel': default_model, 'writerModel': writer, 'polishModel': polish,
            'values': {'writer_type': 'muti'}}


def recovery_checkpoint():
    path = Path(__file__).with_name('recovery_checkpoint.py')
    spec = importlib.util.spec_from_file_location(__name__ + '_checkpoint', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checkpoint_options(root, state, stage, definition, source):
    if stage != 'mvp' or not state.get('automaticCheckpoint'):
        return {}
    result=recovery_checkpoint().options(root, state, definition, source)
    nodes={n['id']:n for n in definition.get('nodes',[])}
    if 'script_production_start' in nodes:
        selected=result.get('selected_node_ids',[])
        result['selected_node_ids']=list(dict.fromkeys(['script_production_start','script_production_finish',
            *['script_budget_'+n for n in selected if nodes[n]['node_type']=='agent' and 'script_budget_'+n in nodes],*selected]))
    state['productionCheckpointOptions']=result
    return result


def validate_checkpoint(root, state, stage):
    if stage == 'mvp' and state.get('automaticCheckpoint'):
        recovery_checkpoint().validate(root, state, state['automaticCheckpoint'])


def validate_dispatch(root, state, stage, task):
    run_ledger().recover(root)
    record_stage(root, state, stage, 'stage_dispatch', task)
    run_control().observe(root,state,stage,task)
    if stage == 'mvp' and state.get('automaticCheckpoint'):
        validate_checkpoint(root, state, stage)
        recovery_checkpoint().validate_selection(task, state['automaticCheckpoint'])


def _character_provider_recovery(root, state, task):
    model = state.get('analysisModel')
    if root is None or not model or state.get('characterModelFallback'):
        return None
    states = task.get('node_states') or {}
    failed = [name for name, node in states.items() if node.get('status') == 'failed']
    if len(failed) != 1 or failed[0] not in {'agent_short_character', 'agent_skeleton'}:
        return None
    name = failed[0]
    error = str(states[name].get('error') or '').lower()
    if not any(marker in error for marker in ('internalservererror', 'error code: 500', 'error code: 502',
                                              'error code: 503', 'error code: 504')):
        return None
    definition = task.get('snapshot_definition') or {}
    node = next((item for item in definition.get('nodes', []) if item['id'] == name), {})
    previous = node.get('model_override')
    if not previous or previous == model:
        return None
    path = Path(__file__).resolve().parents[1] / 'character_review/character_review.py'
    gate = execution_guard().load('character_provider_retry', path)
    if gate.empty_unpublished_batch(Path(root), task['task_id']) is None:
        return None
    return {'action': 'advance', 'stage': 'character', 'reset': list(STAGES[STAGES.index('character'):]),
            'updates': {'characterModelFallback': {'node_id': name, 'model': model, 'source_model': previous,
                                                   'source_task_id': task['task_id']}}}


def _keep_audited_draft(root, state, task):
    number=chapter(state)
    if (state.get('mode')!='short' or state.get('readerRepairCount') or 'mvp' not in state.get('completed',[])
            or number not in (state.get('polishReviewRecoveries') or {}) or number in (state.get('polishDecisions') or {})
            or Path(task.get('workspace_override') or '').resolve()!=Path(root).resolve()):
        return None
    failed={key:node for key,node in (task.get('node_states') or {}).items() if node.get('status')=='failed'}
    if not failed or not set(failed)<={'agent_pl','agent_local_review','script_local_candidate','script_local_commit'}:
        return None
    errors='\n'.join(str(node.get('error') or '') for node in failed.values())
    if (any(marker in errors for marker in ('PREFLIGHT:','LEASE:','CONTEXT_BUDGET:'))
            or not any(marker in errors.lower() for marker in ('no streaming chunk received', 'streamchunktimeouterror',
                'invalid structured output', 'retry_stop: content', 'retry_stop: format', 'retry_stop: evidence'))):
        return None
    guard=execution_guard()
    local=guard.load('production_keep_audited_draft',Path(__file__).resolve().parents[1]/'local_revision/local_revision.py')
    if local.feedback_layers(root,state.get('values',{}).get('author_feedback_file'))[0].strip():
        return None
    ref=(state.get('refs') or {}).get('mvp') or {}
    if not ref.get('workflow_id') or not ref.get('task_id'):
        return None
    draft=guard.terminal_native_task(root,ref['workflow_id'],ref['task_id'])
    if (not draft or draft['status']!='completed' or any((draft.get('node_states') or {}).get(key,{}).get('status')!='completed'
            for key in ('script_guard_finish','script_render_si'))):
        return None
    directory=Path(root)/'cache/draft-guard'/ref['task_id']
    receipt_path=directory/'final-receipt.json';audit=directory/'expression-audit.json'
    body_path=Path(root)/f'story/{number}/chapter.md'
    if not all(path.is_file() for path in (receipt_path,audit,body_path)):
        return None
    receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig'));raw=body_path.read_bytes()
    text=body_path.read_text(encoding='utf-8-sig').rstrip()
    bounds=length_quality().target_range(state.get('values',{}).get('target_word_count'))
    if (receipt.get('phase')!='expression' or text!=receipt.get('body')
            or hashlib.sha256(text.encode()).hexdigest()!=receipt.get('body_sha256')
            or hashlib.sha256(audit.read_bytes()).hexdigest()!=receipt.get('audit_sha256')
            or receipt.get('book_contract_sha256')!=local.book.digest(local.book.resolve(root))
            or bounds and not bounds[0]<=length_quality().count_prose(text)<=bounds[1]):
        return None
    decision={'status':'retained_audited_draft','draft_task_id':ref['task_id'],'failed_task_id':task['task_id'],
              'body_sha256':hashlib.sha256(raw).hexdigest()}
    record_stage(root,state,'polish','stage_retained_audited_draft',task)
    return {'action':'advance','stage':'reader-sim','reset':list(PRODUCTION[2:]),
            'updates':{'polishDecisions':{**(state.get('polishDecisions') or {}),number:decision}}}


def recovery_action(state, stage, task, *, root=None):
    """Bounded, durable relaunch for known execution failures, never content."""
    if stage not in STAGES or task.get('status') != 'failed' or not task.get('task_id'):
        return None
    if root is not None:
        if state.get('productionLaunchLease'):execution_guard().release_launch(root,state,stage)
        record_stage(root, state, stage, 'stage_failed', task)
        run_control().observe(root,state,stage,task)
    if stage == 'character':
        fallback = _character_provider_recovery(root, state, task)
        if fallback:
            return fallback
    if stage in ('mvp','polish') and root is not None:
        nodes=task.get('node_states') or {}
        error=str(nodes.get('script_composition_commit',{}).get('error') or '')
        ref=(state.get('refs') or {}).get(stage) or {}
        key=f"{chapter(state)}/{stage}/{state.get('readerRepairCount') or 0}"
        previous=state.get('compositionReviewRefreshRecoveries') or {}
        if (key not in previous and ref.get('task_id')==task['task_id'] and ref.get('workflow_id')
                and 'RETRY_STOP: content：方案变化，已重建输入，请复查当前方案。' in error):
            path=Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py'
            planner=execution_guard().load('production_composition_refresh',path)
            if planner.review_refresh_candidate(root,chapter(state),ref['workflow_id'],ref['task_id']):
                return {'action':'advance','stage':stage,'reset':list(STAGES[STAGES.index(stage):]),
                        'updates':{'compositionReviewRefreshRecoveries':{**previous,key:dict(ref)}}}
    if stage == 'mvp' and root is not None and not state.get('automaticCheckpoint'):
        nodes = task.get('node_states') or {}
        failed_commits = [nodes.get(f'script_guard_{phase}_commit', {}) for phase in ('facts', 'expression')]
        if any(node.get('status') == 'failed' and 'RETRY_STOP:' in str(node.get('error') or '')
               and '核验凭据无效' in str(node.get('error') or '') for node in failed_commits):
            checkpoint = recovery_checkpoint().prepare_review(root, state, task, chapter(state))
            return {'action':'advance', 'stage':'mvp', 'reset':list(PRODUCTION),
                    'updates':{'automaticCheckpoint':checkpoint}}
    if stage == 'polish' and root is not None:
        candidate=(task.get('node_states') or {}).get('script_local_candidate') or {}
        if candidate.get('status')=='failed' and 'RETRY_STOP: evidence：重规划冲突缺少冻结原文和逐字证据' in str(candidate.get('error') or ''):
            path=Path(__file__).resolve().parents[1]/'local_revision/local_revision.py'
            local=execution_guard().load('production_conflict_evidence_recovery',path)
            local.verify_conflict(root,task,recover_evidence=True)
        commit=(task.get('node_states') or {}).get('script_local_commit') or {}
        chapter_number=chapter(state);previous=state.get('polishReviewRecoveries') or {}
        cycle=int(state.get('readerRepairCount') or 0)
        key=f'{chapter_number}/{cycle}' if cycle else chapter_number
        writer=(task.get('node_states') or {}).get('agent_pl') or {}
        writer_timeout=writer.get('status')=='failed' and any(token in str(writer.get('error') or '').lower() for token in (
            'streamchunktimeouterror','no streaming chunk received for ','执行超时','readtimeout'))
        rejected=commit.get('status')=='failed' and 'RETRY_STOP: content' in str(commit.get('error') or '')
        if key not in previous and (rejected or writer_timeout):
            path=Path(__file__).resolve().parents[1]/'local_revision/local_revision.py'
            local=execution_guard().load('production_polish_review_recovery',path)
            pending=(Path(root)/f"cache/local-revision/{task['task_id']}/working.json").is_file()
            if rejected or (pending and local.writer_retry_had_review(task)):
                feedback=local.recover_rejected_review(root,task,interrupted_writer=not rejected)
                return {'action':'advance','stage':'polish','reset':list(PRODUCTION[1:]),'updates':{
                    'polishReviewRecoveries':{**previous,key:task['task_id']},
                    'values':{**state['values'],'author_feedback_file':feedback}}}
    if (stage == 'mvp' and root is not None and state.get('mode') == 'short' and chapter(state) == '0001'
            and not state.get('shortContextFallback') and not state.get('automaticCheckpoint')
            and task.get('parameter_values', {}).get('preparation_mode') == 'compact'
            and not (Path(root) / 'story/0001/chapter.md').exists()):
        failed = {name: node for name, node in task.get('node_states', {}).items() if node.get('status') == 'failed'}
        error = str(failed.get('script_short_context', {}).get('error') or '')
        if set(failed) == {'script_short_context'} and any(marker in error for marker in (
                'SHORT_CONTEXT_OVERFLOW:', '超出轻量完整上下文范围', '资料总量超过轻量完整上下文范围')):
            return {'action': 'advance', 'stage': 'mvp', 'reset': list(PRODUCTION),
                    'updates': {'shortContextFallback': {'chapter': '0001', 'source_task_id': task['task_id']}}}
    if stage in ('mvp','polish') and root is not None:
        folder=(task.get('parameter_values') or {}).get('revision_dir','') if stage=='polish' else 'cache/draft-guard/'+task['task_id']
        if folder and (Path(root)/folder/'composition-conflict.json').is_file():
            histories={k:list(v) for k,v in (state.get('compositionReplans') or {}).items()};key=chapter(state)
            prior=histories.get(key,[])
            if task['task_id'] in prior:return None
            module_path=Path(__file__).resolve().parents[1]/('local_revision/local_revision.py' if stage=='polish' else 'draft_guard/draft_guard.py')
            spec=importlib.util.spec_from_file_location('composition_recovery_local',module_path)
            local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
            conflict=local.verify_conflict(root,task) if stage=='polish' else local.verify_conflict(root,state,task)
            planner=local.load('production_composition',Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py')
            # Preserve the latest verified diagnosis even when automatic replan
            # authority is exhausted. This records evidence; it grants no retry.
            planner.support.write(root,f'planning/composition-conflicts/{key}.json',conflict)
            if len(prior)>=2:return None
            config=planner.policy(root)
            if config is None:
                planner.support.write(root,'meta/length_policy.json',{'schema':1,'ownership':'author','origin':'verified_conflict_keep_author_bounds'})
            histories[key]=[*prior,task['task_id']]
            return {'action':'advance','stage':stage,'reset':list(PRODUCTION[1:] if stage=='polish' else PRODUCTION),
                'updates':{'compositionReplans':histories,'serialReservation':None,'automaticCheckpoint':None}}
    if stage == 'polish' and root is not None:
        retained=_keep_audited_draft(root,state,task)
        if retained:
            return retained
    if (stage == 'outline' and root is not None
            and task.get('parameter_values', {}).get('planning_mode') == 'rolling'):
        nodes = task.get('node_states') or {}
        failed = {key for key, node in nodes.items() if node.get('status') == 'failed'}
        required = {'script_serial_prepare', 'agent_rolling_plan', 'script_serial_normalize', 'agent_rolling_review'}
        if failed == {'script_serial_commit'} and all(nodes.get(key, {}).get('status') == 'completed' for key in required):
            run_ledger().recover(root)
            if (Path(root) / f"planning/serial/receipts/{task['task_id']}.json").is_file():
                state['serialPlanningResult'] = serial().verify_task(root, task['task_id'])
                record_stage(root, state, stage, 'stage_recovered', task)
                action = next_action(root, state, stage)
                action['updates'] = {**action.get('updates', {}),
                    'serialPlanningResult': state['serialPlanningResult'],
                    'completed': list(dict.fromkeys([*state.get('completed', []), stage]))}
                return action
    if stage == 'post-hoc' and root is not None:
        required = {'script_story_context', 'script_sync_down', 'script_review_source',
                    'agent_obs', 'script_validate_observation', 'agent_arb',
                    'script_sync_up', 'script_sync_down_final'}
        nodes = task.get('node_states') or {}
        failed = {key for key, node in nodes.items() if node.get('status') == 'failed'}
        ref=(state.get('refs') or {}).get(stage) or {}
        evidence_error=str(nodes.get('script_validate_observation',{}).get('error') or '')
        if (failed=={'script_validate_observation'} and 'RETRY_STOP: evidence：[archive_evidence]' in evidence_error
                and ref.get('task_id')==task['task_id'] and ref.get('workflow_id')
                and execution_guard().terminal_native_task(root,ref['workflow_id'],ref['task_id'])):
            number=chapter(state);report=reader_report(root,state);body=report['body_sha256']
            key=f'{number}/{body}';previous=state.get('archiveEvidenceRecoveries') or {}
            source=Path(root)/f"cache/story-support/reviews/{task['task_id']}/{number}/review-source.json"
            if key not in previous and report['verdict']=='pass' and source.is_file():
                frozen=json.loads(source.read_text(encoding='utf-8-sig'))
                if frozen.get('task_id')==task['task_id'] and frozen.get('body_sha256')==body:
                    return {'action':'advance','stage':stage,'reset':['post-hoc','export'],
                            'updates':{'archiveEvidenceRecoveries':{**previous,key:task['task_id']}}}
        if failed == {'script_confirm_archive'} and all(nodes.get(key, {}).get('status') == 'completed' for key in required):
            run_ledger().recover(root)
            file = Path(root) / f'story/{chapter(state)}/confirmed_state.json'
            snapshot = json.loads(file.read_text(encoding='utf-8-sig')) if file.is_file() else {}
            if snapshot.get('task_id') == task['task_id'] and snapshot.get('archive_commit_id'):
                run_ledger().verify_snapshot(root, snapshot)
                _verify_completion(root, state, stage, task)
                record_stage(root, state, stage, 'stage_recovered', task)
                action = next_action(root, state, stage)
                action['updates'] = {**action.get('updates', {}),
                    'completed':list(dict.fromkeys([*state.get('completed', []), stage]))}
                return action
    errors = [str(task.get('error') or '')]
    errors += [str(node.get('error') or '') for node in task.get('node_states', {}).values()
               if node.get('status') == 'failed']
    error = '\n'.join(errors)
    if any(marker in error for marker in ('RETRY_STOP:','PREFLIGHT:','CONTEXT_BUDGET:','LEASE:')):return None
    operational = ('Script Library' in error and '漂移' in error) or any(token in error.lower() for token in (
        '没有最终 ai 输出可保存', 'json 输出校验失败', 'connection reset', 'connection aborted',
        'remoteprotocolerror', 'connecttimeout', 'readtimeout', 'tls', 'ssl eof',
        'streamchunktimeouterror', 'no streaming chunk received for '))
    if (stage == 'outline' and task.get('parameter_values', {}).get('planning_mode') == 'rolling'
            and 'invalid structured output' in error.lower()):
        operational = True
    if not operational:
        return None
    retry_context=execution_guard().recovery_retry_context(root,state,stage,task) if root is not None else None
    if retry_context and retry_context['exhausted']:return None
    from copy import deepcopy
    attempts = deepcopy(state.get('automaticRecovery') or {})
    key = chapter(state) + '/' + stage
    history = attempts.get(key, [])
    if len(history) >= 2 or any(item.get('task_id') == task['task_id'] for item in history):
        return None
    attempts[key] = history + [{'task_id': task['task_id'], 'reason': error[:1000]}]
    updates = {'automaticRecovery': attempts}
    if retry_context:updates['productionRetryRecovery']=retry_context
    if state.get('serialReservation'):updates['serialReservation']=None
    if stage == 'mvp' and root is not None and (Path(root) / f'story/{chapter(state)}/chapter.md').is_file():
        checkpoint = state.get('automaticCheckpoint')
        if checkpoint and checkpoint.get('kind')=='draft_review':
            recovery_checkpoint().validate_review_publication(root,state,task)
            checkpoint=recovery_checkpoint().prepare(root,state,task,chapter(state))
            if checkpoint is None:return None
        if checkpoint:
            recovery_checkpoint().validate(root, state, checkpoint)
            failed_nodes = {key for key, node in task.get('node_states', {}).items() if node.get('status') == 'failed'}
            if not failed_nodes or not failed_nodes.issubset(checkpoint['selected_node_ids']):
                return None
        else:
            checkpoint = recovery_checkpoint().prepare(root, state, task, chapter(state))
        if checkpoint is None:
            return None
        updates['automaticCheckpoint'] = checkpoint
    return {'action': 'advance', 'stage': stage, 'reset': list(STAGES[STAGES.index(stage):]),
            'updates': updates}


def next_action(root, state, stage):
    if stage=='outline' and state.get('values',{}).get('planning_mode')=='rolling':
        result=state.get('serialPlanningResult',{})
        if result.get('status')!='accepted':
            return {'action':'pause','reason':'滚动计划已留存，须核对作者范围或采用候选后继续。'}
    action=_next_action(root,state,stage)
    if state.get('mode')=='serial' and serial().contract(root):
        updates=action.setdefault('updates',{})
        updates['serialReservation']=None
        if action['action']=='advance' and action.get('stage')=='mvp':
            values={**state.get('values',{}),**updates.get('values',{})}
            number=str(values.get('chapter_number','0001')).zfill(4)
            check=serial().need_plan(root,number)
            if not check['ready']:
                if check.get('requires_author') or check.get('reason_code') in ('volume_scope_missing','volume_handoff_review'):
                    return {'action':'pause','reason':'跨卷承接或作者计划需复核，未擅自改变范围。','updates':{**updates,'serialIssue':check}}
                if stage=='outline':
                    return {'action':'pause','reason':'刚发布的滚动计划仍不可用于本章，请核对字段、状态或来源变化；未重复付费规划。',
                            'updates':{**updates,'serialIssue':check}}
                action.update(stage='outline',reset=['outline',*PRODUCTION])
                values['planning_mode']='rolling'
            else:
                values['planning_mode']='legacy'
                current=serial().status(root,number)
                values['volume_number']=str(next(i+1 for i,v in enumerate(serial().contract(root)['volumes']) if v['id']==current['volume']['id']))
            updates['values']=values
        if action['action']=='finish':run_control().finish(root,state)
    return action


def _next_action(root, state, stage):
    if stage == 'polish':
        result = length_quality().assess(root, chapter(state), state.get('values', {}).get('target_word_count', ''))
        cycle, count, total = _length_cycle(state)
        progress = {'lengthRepairCycle': cycle, 'lengthRepairCount': count, 'lengthRepairTotal': total,
                    'lengthRepairStrategy': length_quality().LENGTH_REPAIR_STRATEGY}
        if state.get('lengthRepairStrategy') == 'fragment-v5' and length_quality().LENGTH_REPAIR_STRATEGY == 'fragment-v6':
            progress['lengthRepairMigration'] = {'from': 'fragment-v5', 'to': 'fragment-v6', 'cycle': cycle,
                                               'total_before': total, 'reason': '按真实缺口冻结连续多段源窗口，替代单句过量扩写契约'}
        if state.get('writerModel') or 'lengthRepairModel' in state:
            progress['lengthRepairModel'] = state.get('writerModel') or ''
        if result['status'] in {'short', 'long'}:
            limit = max(1, min(3, int(state.get('autoLengthRepairLimit') or 2)))
            if count >= limit:
                content_limit = max(1, min(5, int(state.get('autoRepairLimit') or 2)))
                if (int(state.get('readerRepairCount') or 0) < content_limit
                        and not state.get('assessmentOnly') and not state.get('repairReviewOnly')):
                    # A reader report is still strictly length-gated. Let the
                    # existing planner choose a better content repair instead
                    # of repeating the rejected local window or requiring UI surgery.
                    source = length_quality().original_feedback(root, state)
                    return {'action': 'advance', 'stage': 'reader-sim',
                            'reset': ['reader-sim', 'post-hoc', 'export'],
                            'updates': {**progress, 'lengthCheck': result, 'lengthRepairFeedback': {},
                                        'values': {**state.get('values', {}), 'author_feedback_file': source}}}
                return {'action': 'pause', 'reason': f"字数自动校正已达上限，实测{result['actual']}实字，目标{result['lower']}—{result['upper']}；未放行审核和导出。",
                        'updates': {**progress, 'lengthCheck': result}}
            feedback = length_quality().correction_feedback(root, {**state, 'lengthRepairCount': count}, result)
            return {'action': 'advance', 'stage': 'polish', 'reset': list(PRODUCTION[1:]),
                    'updates': {**progress, 'lengthRepairCount': count + 1, 'lengthRepairTotal': total + 1, 'lengthCheck': result,
                                'lengthRepairFeedback': feedback,
                                'values': {**state.get('values', {}), 'author_feedback_file': feedback['path']}}}
        length_quality().prepare_guidance(root, chapter(state), state.get('values', {}).get('target_word_count', ''))
        source = length_quality().original_feedback(root, state)
        return {'action': 'advance', 'stage': 'reader-sim', 'updates': {**progress, 'lengthCheck': result,
                'lengthRepairFeedback': {}, 'values': {**state.get('values', {}), 'author_feedback_file': source}}}
    if stage == "reader-sim":
        report = reader_report(root, state)
        if state.get("assessmentOnly"):
            return {"action": "finish", "reason": "本章读者评估已完成。", "updates": {"assessmentOnly": False}}
        if report.get('requires_scope_confirmation'):
            return {"action": "pause", "reason": "整篇审稿仍有超出或未明确属于本次修改范围的问题，请先确认修改范围。"}
        if state.get("repairReviewOnly") and report["verdict"] != "pass":
            return {"action": "pause", "reason": "本次返修复评尚未通过，请查看报告后决定后续操作。", "updates": {"repairReviewOnly": False}}
        if report["verdict"] != "pass":
            limit = max(1, min(5, int(state.get("autoRepairLimit") or 2)))
            if int(state.get("readerRepairCount") or 0) >= limit:
                return {"action": "pause", "reason": "已达到本章自动返修次数上限，请查看正文与读者报告。"}
            return {"action": "repair"}
    if stage == "post-hoc" and state.get("repairReviewOnly"):
        return {"action": "finish", "reason": "返修复评通过，故事档案已同步。", "updates": {"repairReviewOnly": False}}
    if stage == "export":
        started = int(state.get("autoChapterStarted") or 1)
        limit = max(1, int(state.get("autoChapterLimit") or 1))
        if (state.get("mode") == "serial" and state.get("autoScope") == "serial_batch" and started < limit
                and state.get("values", {}).get("chapter_ending_mode") != "book_final"):
            next_number = int(chapter(state)) + 1
            if next_number > 9999:
                return {"action": "pause", "reason": "已达到支持的章节号上限。"}
            number = f"{next_number:04d}"
            if (Path(root) / f"story/{number}/chapter.md").exists():
                return {"action": "pause", "reason": f"第 {number} 章已存在，自动创作不会覆盖。"}
            values = {**state.get("values", {}), "chapter_number": number, "prev_chapter": chapter(state),
                      "latest_chapter": chapter(state), "chapter_ending_mode": "continue", "author_feedback_file": "",
                      "human_intent": "", "world_intent": ""}
            return {"action": "advance", "stage": "mvp", "reset": list(PRODUCTION),
                    "updates": {"values": values, "autoChapterStarted": started + 1, "readerRepairCount": 0,
                                "lengthRepairCount": 0, "lengthRepairTotal": 0, "lengthRepairCycle": 0, "lengthRepairStrategy": length_quality().LENGTH_REPAIR_STRATEGY,
                                "lengthCheck": {}, "lengthRepairFeedback": {}}}
        return {"action": "finish", "reason": "本次指定范围已完成并导出。"}
    if stage not in STAGES:
        return {"action": "pause", "reason": "当前步骤不属于自动创作流程。"}
    return {"action": "advance", "stage": STAGES[STAGES.index(stage) + 1],
            'updates': {'automaticCheckpoint': None} if stage == 'mvp' else {}}


def repair_request(state):
    return {"question": "请依据本章正文与完整读者报告制定可执行的返修方案，逐项解决问题，保留既定事实和作者要求。",
            "purpose": "reader_repair", "chapter": chapter(state), "scope": "chapter", "stage": "reader-sim",
            "project": state, "_model_override": state.get("repairModel") or None}


def repair_feedback_sources(root,state):
    path=Path(__file__).resolve().parents[1]/'local_revision/local_revision.py'
    local=execution_guard().load('reader_repair_feedback_sources',path)
    return local.retained_feedback_sources(root,str(state.get('values',{}).get('author_feedback_file') or '').strip())


def repair_ready(state, feedback_path):
    cycle = int(state.get("readerRepairCount") or 0) + 1
    _, _, total = _length_cycle(state)
    return {"action": "advance", "stage": "polish", "reset": ["polish", "reader-sim", "post-hoc", "export"],
            "updates": {"values": {**state.get("values", {}), "author_feedback_file": feedback_path},
                        "readerRepairCount": cycle, "lengthRepairCount": 0,
                        "lengthRepairCycle": cycle, "lengthRepairTotal": total, "lengthRepairStrategy": length_quality().LENGTH_REPAIR_STRATEGY,
                        "autoRepairPlanId": "", "lengthRepairFeedback": {}}}


def dialogue_writer_node(definition, writer_type):
    if writer_type != 'muti':
        return 'agent_sw'
    if any(node['id'] == 'agent_dw' and node.get('agent_type', '').endswith('novel-multi-scene-writer')
           for node in definition.get('nodes', [])):
        return 'agent_dw'
    return 'agent_nw'


def _is_body_writer(node, stage):
    identity = node['id']
    if stage == 'mvp':
        if identity == 'agent_guard_expression_repair':
            return True
        agent_type = node.get('agent_type') or ''
        if agent_type.endswith('novel-multi-scene-writer'):
            return True
        if agent_type.endswith('novel-multi-scene-planner'):
            return False
        return identity in {'agent_sw', 'agent_nw', 'agent_dw', 'agent_aw', 'agent_tw', 'agent_iw', 'agent_dsw'}
    return stage == 'polish' and identity in {'agent_pl', 'agent_pp'}


def model_overrides(state, definition, stage):
    analysis = state.get('analysisModel')
    writer = state.get('writerModel')
    polisher = state.get('polishModel')
    repair = state.get('repairModel') if state.get('repairReviewOnly') or state.get('readerRepairCount') else None
    selected = {}
    for node in definition.get('nodes', []):
        identity = node['id']
        if (node.get('node_type', 'agent') != 'agent'
                or ((node.get('var_bindings') or {}).get('model_override') or {}).get('var_key')
                or '{{' in node.get('agent_type', '') or '{{' in (node.get('model_override') or '')):
            continue
        if identity == 'agent_fragment_review' and not analysis:
            continue
        if _is_body_writer(node, stage):
            model = (polisher or repair or writer) if stage == 'polish' else writer
        elif stage == 'character' and identity != 'agent_card_semantic_review':
            fallback = state.get('characterModelFallback') or {}
            model = analysis if fallback.get('node_id') == identity and fallback.get('model') == analysis else None
        else:
            model = analysis or (repair if stage in {'polish', 'reader-sim'} else None)
        if model:
            selected[identity] = model
    return selected or None


def model_params_overrides(state, definition, stage):
    """Book-only parameters follow the explicitly selected body writer model."""
    from copy import deepcopy
    params = state.get('writerModelParams')
    if params is None:
        return None
    if not isinstance(params, dict):
        raise ValueError('writerModelParams 必须是参数对象')
    writer = state.get('writerModel')
    if not params or not writer:
        return None
    selected = model_overrides(state, definition, stage) or {}
    return {node['id']: deepcopy(params) for node in definition.get('nodes', [])
            if _is_body_writer(node, stage) and selected.get(node['id']) == writer} or None
