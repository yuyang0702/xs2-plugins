import copy
import pytest

from test_length_quality import policy


def test_recovery_relaunches_only_known_operational_failures_with_durable_bound():
    p = policy()
    state={'values':{'chapter_number':'0001'},'writerModel':'volcengine:writer','polishModel':'anthropic:polisher'}
    task={'task_id':'old','status':'failed','node_states':{'script':{'status':'failed','error':'Script Library 已漂移，请创建新任务'}}}
    first=p.recovery_action(state,'polish',task)
    assert first['action']=='advance' and first['stage']=='polish'
    assert set(first['reset'])=={'polish','reader-sim','post-hoc','export'}
    updated=copy.deepcopy(state);updated.update(first['updates'])
    second=p.recovery_action(updated,'polish',{**task,'task_id':'second'})
    assert second is not None
    updated.update(second['updates'])
    assert p.recovery_action(updated,'polish',{**task,'task_id':'third'}) is None
    assert updated['writerModel']=='volcengine:writer' and updated['polishModel']=='anthropic:polisher'


def test_recovery_never_restarts_user_stopped_tasks_or_content_rejections():
    p=policy();state={'values':{'chapter_number':'0001'}}
    assert p.recovery_action(state,'polish',{'task_id':'stop','status':'stopped','error':'connection reset'}) is None
    assert p.recovery_action(state,'mvp',{'task_id':'content','status':'failed','error':'人物提前知道账目；重复片段'}) is None


def test_recovery_does_not_spend_budget_twice_for_same_failed_task():
    p=policy();state={'values':{'chapter_number':'0001'}}
    task={'task_id':'summary','status':'failed','error':'开启了 save_output_to_file，但没有最终 AI 输出可保存'}
    first=p.recovery_action(state,'post-hoc',task);state.update(first['updates'])
    assert p.recovery_action(state,'post-hoc',task) is None


@pytest.mark.parametrize('error',[
    'No streaming chunk received for 120.0s (model=gpt-6.1-sol, chunks_received=6). The connection may be alive at the TCP layer but is not producing content.',
    'StreamChunkTimeoutError: incomplete streaming response',
])
def test_native_stream_inactivity_is_bounded_operational_recovery(error):
    p=policy();state={'values':{'chapter_number':'0002'}}
    task={'task_id':'stream-timeout','status':'failed','node_states':{'agent_pl':{'status':'failed','error':error}}}
    result=p.recovery_action(state,'polish',task)
    assert result and result['stage']=='polish'
    state.update(result['updates'])
    assert p.recovery_action(state,'polish',task) is None
    next_result=p.recovery_action(state,'polish',{**task,'task_id':'stream-timeout-2'})
    assert next_result;state.update(next_result['updates'])
    assert p.recovery_action(state,'polish',{**task,'task_id':'stream-timeout-3'}) is None


def test_first_character_model_provider_failure_uses_book_analysis_once(tmp_path):
    p = policy()
    author = {'id': 'agent_short_character', 'node_type': 'agent', 'model_override': 'primary:character'}
    reviewer = {'id': 'agent_card_semantic_review', 'node_type': 'agent'}
    definition = {'nodes': [author, reviewer]}
    draft = tmp_path / 'cache/character-review/task-character/draft'
    draft.mkdir(parents=True)
    state = {'values': {'chapter_number': '0001'}, 'analysisModel': 'fallback:analysis', 'writerModel': 'body:writer'}
    failure = {'status': 'failed', 'error': 'Error code: 500 - InternalServerError', 'session_id': 'failed-session'}
    task = {'task_id': 'task-character', 'status': 'failed', 'snapshot_definition': definition,
            'node_states': {author['id']: failure}}
    assert author['id'] not in p.model_overrides(state, definition, 'character')
    assert p.recovery_action(state, 'character', {**task, 'node_states': {
        author['id']: {**failure, 'error': '角色内容不符合作者设定'}}}, root=tmp_path) is None
    action = p.recovery_action(state, 'character', task, root=tmp_path)
    assert action['stage'] == 'character' and 'build' not in action['reset']
    updated = {**state, **action['updates']}
    assert p.model_overrides(updated, definition, 'character')[author['id']] == 'fallback:analysis'
    assert updated['writerModel'] == state['writerModel']
    assert p.recovery_action(updated, 'character', task, root=tmp_path) is None
    (draft / 'existing-card.json').write_text('{}', encoding='utf-8')
    assert p.recovery_action(state, 'character', task, root=tmp_path) is None


def test_compact_context_overflow_relaunches_only_mvp_with_full_preparation(tmp_path):
    p = policy()
    state = {'mode': 'short', 'values': {'chapter_number': '0001', 'preparation_mode': 'compact',
                                         'target_word_count': '11200-12800', 'human_intent': '保留作者原始设定'}}
    node = {'status': 'failed', 'error': 'ValueError: cache/story-support/context.md 超出轻量完整上下文范围，请选择完整准备；未截断'}
    task = {'task_id': 'task-compact', 'status': 'failed', 'parameter_values': {'preparation_mode': 'compact'},
            'node_states': {'script_short_context': node}}
    variables = [{'key': key, 'type': 'text'} for key in ('preparation_mode', 'target_word_count', 'human_intent')]
    definition = {'workflow_id': 'xs2-novel-flywheel-mvp', 'variables': variables}
    action = p.recovery_action(state, 'mvp', task, root=tmp_path)
    assert action['stage'] == 'mvp' and 'outline' not in action['reset']
    effective = {**state, **action['updates']}
    assert p.parameters(effective, definition) == {'preparation_mode': 'full', 'target_word_count': '11200-12800',
                                                   'human_intent': '保留作者原始设定'}
    assert p.parameters(effective, {**definition, 'workflow_id': 'build'})['preparation_mode'] == 'compact'
    assert p.recovery_action(effective, 'mvp', task, root=tmp_path) is None
    assert p.recovery_action(state, 'mvp', {**task, 'node_states': {'script_short_context': {
        **node, 'error': '缺少 meta/character_profiles.md，请先完成准备'}}}, root=tmp_path) is None
    body = tmp_path / 'story/0001/chapter.md'
    body.parent.mkdir(parents=True)
    body.write_text('已有正文', encoding='utf-8')
    assert p.recovery_action(state, 'mvp', task, root=tmp_path) is None


def test_exhausted_polish_can_send_unchanged_audited_draft_to_readers(tmp_path, monkeypatch):
    import hashlib
    import json
    from test_book_contract import helper
    p=policy();root=tmp_path/'book';root.mkdir()
    host=tmp_path/'host';(host/'src').mkdir(parents=True)
    workflow='xs2-novel-flywheel-mvp'; identity='task-draft'
    task_file=host/'data/workflows'/workflow/'tasks'/f'{identity}.json';task_file.parent.mkdir(parents=True)
    task_file.write_text(json.dumps({'task_id':identity,'workflow_id':workflow,'status':'completed','workspace_override':str(root),
        'node_states':{node:{'status':'completed'} for node in ('script_guard_finish','script_render_si')}}),encoding='utf-8')
    monkeypatch.setenv('DETERMINFLOW_PROJECT_DIR',str(host))
    text='已经审核的完整稿。';body=root/'story/0001/chapter.md';body.parent.mkdir(parents=True);body.write_text(text+'\n',encoding='utf-8')
    cache=root/'cache/draft-guard'/identity;cache.mkdir(parents=True)
    audit=cache/'expression-audit.json';audit.write_text('{}',encoding='utf-8')
    book=helper()
    (cache/'final-receipt.json').write_text(json.dumps({'phase':'expression','body':text,'book_contract_sha256':book.digest(book.resolve(root)),
        'body_sha256':hashlib.sha256(text.encode()).hexdigest(),'audit_sha256':hashlib.sha256(audit.read_bytes()).hexdigest()}),encoding='utf-8')
    state={'mode':'short','values':{'chapter_number':'0001','target_word_count':'1-20'},'completed':['mvp'],
           'refs':{'mvp':{'workflow_id':workflow,'task_id':identity}},'polishReviewRecoveries':{'0001':'first-polish'}}
    failed={'task_id':'second-polish','status':'failed','workspace_override':str(root),
            'node_states':{'agent_pl':{'status':'failed','error':'No streaming chunk received for 120.0s'}}}
    action=p.recovery_action(state,'polish',failed,root=root)
    assert action['stage']=='reader-sim' and action['reset']==['reader-sim','post-hoc','export']
    decision=action['updates']['polishDecisions']['0001']
    assert decision['draft_task_id']==identity and decision['body_sha256']==hashlib.sha256(body.read_bytes()).hexdigest()
    assert decision['failed_task_id']=='second-polish' and state['completed']==['mvp']
    assert (p.recovery_action({**state,'readerRepairCount':1},'polish',failed,root=root) or {}).get('stage')!='reader-sim'
    body.write_text(text+'正文另有改动。',encoding='utf-8')
    assert (p.recovery_action(state,'polish',failed,root=root) or {}).get('stage')!='reader-sim'
