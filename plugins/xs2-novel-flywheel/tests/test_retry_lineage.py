"""Logical retry budgets survive proven automatic native task recovery."""
import copy
import json

import pytest
from test_native_preflight import native,armed_state
from test_length_quality import policy


def put_task(host,task):
    path=host/'data/workflows'/task['workflow_id']/'tasks'/(task['task_id']+'.json')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(task,ensure_ascii=False),encoding='utf8')


def project(root,state):
    (root/'.novel-project.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf8')


def failed(host,task,count=1,reason='connection reset'):
    task['status']='failed';task['error']=reason
    task['node_states']={'writer':{'status':'failed','attempt_count':count,'error':reason,
        'attempt_history':[{'attempt_number':i,'status':'failed','error':reason+' '+str(i)} for i in range(1,count+1)]}}
    put_task(host,task)


def start(native):
    guard,root,task,_,host=native;state=armed_state();project(root,state)
    record=guard.run(root,'polish','0001','task-a','wf')
    return guard,root,task,host,state,record


def child(native,state,source,change=None):
    guard,root,_,_,host=native
    task=copy.deepcopy(source);task.update(task_id='task-b',status='running',created_at='2026-11-11T00:01:00+00:00',node_states={})
    task.pop('error',None)
    if change=='chapter':state['values']['chapter_number']='0002';task['parameter_values']['chapter_number']='0002'
    elif change=='author':state['values']['human_intent']='新的作者要求'
    elif change=='model':task['snapshot_definition']['nodes'][1]['model_override']='route:other-model'
    elif change=='manual_disarmed':state['autoArmed']=False
    state['refs']={'polish':{'workflow_id':'wf','task_id':'task-b'}}
    state['autoPending']={'id':'recovery-b','stage':'polish','workflow_id':'wf','task_id':'task-b',
                          'parameters':dict(task['parameter_values']),'before_task_ids':['task-a']}
    if change=='manual':state.pop('refs');state.pop('autoPending')
    project(root,state);put_task(host,task)
    return task,guard.run(root,'polish',state['values']['chapter_number'],'task-b','wf')


def test_two_failed_automatic_tasks_share_four_failure_budget_and_poll_is_idempotent(native):
    guard,root,task,host,state,first=start(native);failed(host,task,2)
    p=policy();action=p.recovery_action(state,'polish',task,root=root)
    assert action and action['updates']['productionRetryRecovery']
    assert len(guard.retry_history(root,'scene-writing/task-a'))==2
    assert p.recovery_action(state,'polish',task,root=root)['updates']['productionRetryRecovery']==action['updates']['productionRetryRecovery']
    assert len(guard.retry_history(root,'scene-writing/task-a'))==2
    state.update(action['updates']);second_task,second=child(native,state,task)
    assert second['retry_context']['intent_id']==first['retry_context']['intent_id']
    failed(host,second_task,2)
    assert p.recovery_action(state,'polish',second_task,root=root) is None
    assert len(guard.retry_history(root,'scene-writing/task-b'))==4
    assert p.recovery_action(state,'polish',second_task,root=root) is None
    assert len(guard.retry_history(root,'scene-writing/task-b'))==4


def test_same_deterministic_fingerprint_stops_across_recovered_tasks(native,monkeypatch):
    guard,root,task,host,state,first=start(native)
    task['node_states']={'writer':{'status':'completed','attempt_count':1,'attempt_history':[{'attempt_number':1,'status':'completed'}]}}
    put_task(host,task)
    guard.retry(root,'scene-writing/task-a','writer','引用原文不在当前候选')
    failed(host,task,2)
    action=policy().recovery_action(state,'polish',task,root=root);assert action
    state.update(action['updates']);second_task,second=child(native,state,task)
    monkeypatch.setenv('TASK_ID','task-b')
    with pytest.raises(ValueError,match='RETRY_STOP'):
        guard.retry(root,'scene-writing/task-b','writer','引用原文不在当前候选')
    assert len(guard.retry_history(root,'scene-writing/task-a'))==3


@pytest.mark.parametrize('change',['chapter','author','model','code','manual','manual_disarmed'])
def test_changed_context_or_new_manual_task_gets_independent_retry_intent(native,monkeypatch,change):
    guard,root,task,host,state,first=start(native);failed(host,task)
    action=policy().recovery_action(state,'polish',task,root=root);assert action
    state.update(action['updates'])
    if change=='code':monkeypatch.setattr(guard,'profile',lambda **kwargs:{'code':'new-version'})
    second_task,second=child(native,state,task,change)
    assert second['retry_context']['intent_id']!=first['retry_context']['intent_id']
    assert guard.retry_history(root,'scene-writing/task-b')==[]


def test_script_rejection_and_native_failed_attempt_are_charged_once(native):
    guard,root,task,host,state,_=start(native)
    task['node_states']={'writer':{'status':'completed','attempt_count':1,'attempt_history':[{'attempt_number':1,'status':'completed'}]}}
    put_task(host,task)
    guard.retry(root,'scene-writing/task-a','writer','json schema invalid')
    failed(host,task,1,reason='json schema invalid')
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context and not context['exhausted']
    assert len(guard.retry_history(root,'scene-writing/task-a'))==1
    guard.recovery_retry_context(root,state,'polish',task)
    assert len(guard.retry_history(root,'scene-writing/task-a'))==1


def test_successful_native_calls_are_not_charged_as_retries(native):
    guard,root,task,host,state,_=start(native)
    task.update(status='failed',error='connection reset in later script')
    task['node_states']={'writer':{'status':'completed','attempt_count':3,
        'attempt_history':[{'attempt_number':i,'status':'completed'} for i in range(1,4)]}}
    put_task(host,task)
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context and not context['exhausted']
    assert guard.retry_history(root,'scene-writing/task-a')==[]
    assert context['sdk_http_retry_observation']=='unknown'


def test_updated_composition_plan_gets_two_review_refreshes_inside_native_run(native):
    guard,root,task,host,_,_=start(native)
    planner='agent_composition_plan';reviewer='agent_composition_review'
    for attempt in (1,2):
        task['node_states']={role:{'status':'completed','attempt_count':attempt} for role in (planner,reviewer)}
        put_task(host,task)
        guard.retry(root,'composition/task-a',planner,'独立复核提出内容问题')
        guard.retry(root,'composition/task-a',reviewer,'COMPOSITION_REVIEW_REFRESH: 复查新方案。')
    assert len(guard.retry_history(root,'composition/task-a'))==2
    assert len(guard.retry_history(root,'composition-refresh/task-a'))==2
    task['node_states'][reviewer]['attempt_count']=3
    put_task(host,task)
    with pytest.raises(ValueError,match='RETRY_STOP: dependency_refresh'):
        guard.retry(root,'composition/task-a',reviewer,'COMPOSITION_REVIEW_REFRESH: 复查新方案。')


def test_actual_failed_transport_attempts_block_next_paid_boundary_once(native):
    guard,root,task,host,state,_=start(native);failed(host,task,4)
    with pytest.raises(ValueError,match='RETRY_STOP'):guard.request_budget(root,'writer')
    assert len(guard.retry_history(root,'scene-writing/task-a'))==4
    with pytest.raises(ValueError,match='RETRY_STOP'):guard.request_budget(root,'writer')
    assert len(guard.retry_history(root,'scene-writing/task-a'))==4


@pytest.mark.parametrize('change',['author','code','model_preference'])
def test_real_context_change_allows_new_intent_after_old_budget_exhaustion(native,monkeypatch,change):
    guard,root,task,host,state,_=start(native);failed(host,task,4)
    assert policy().recovery_action(state,'polish',task,root=root) is None
    if change=='author':state['values']['human_intent']='新的阅读作用'
    elif change=='model_preference':state['writerModel']='route:new-preference'
    else:
        actual_profile=guard.profile
        monkeypatch.setattr(guard,'profile',lambda **kwargs:{**actual_profile(**kwargs),'code-fix':'new'})
    # The source guard can distinguish the changed context without discarding
    # any charge from the original failed intent.
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context['meaningful_context_changed'] is True
    assert context['exhausted'] is False
    assert len(guard.retry_history(root,'scene-writing/task-a'))==4


def test_missing_failed_attempt_history_does_not_authorize_fresh_stage_budget(native):
    guard,root,task,host,state,_=start(native);failed(host,task,3)
    task['node_states']['writer']['attempt_history']=[];put_task(host,task)
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context['exhausted'] is True and context['native_attempt_coverage']=='incomplete'
    assert len(guard.retry_history(root,'scene-writing/task-a'))==1
    assert policy().recovery_action(state,'polish',task,root=root) is None
    assert len(guard.retry_history(root,'scene-writing/task-a'))==1


def test_reused_caller_prefix_cannot_merge_distinct_logical_role_groups(native):
    guard,root,task,save,host=native
    review=copy.deepcopy(task['snapshot_definition']['nodes'][1]);review['id']='agent_local_review'
    task['snapshot_definition']['nodes'].append(review);save()
    state=armed_state();project(root,state);guard.run(root,'polish','0001','task-a','wf')
    guard.retry(root,'shared-prefix/task-a','writer','connection reset from writing')
    guard.retry(root,'shared-prefix/task-a','agent_local_review','connection reset from review')
    assert len(guard.retry_history(root,'scene-writing/task-a'))==1
    assert len(guard.retry_history(root,'local-revision/task-a'))==1


@pytest.mark.parametrize('source',['body','declared_rules','book_contract'])
def test_changed_existing_file_bytes_at_same_path_start_new_retry_intent(native,source):
    guard,root,task,save,host=native
    if source=='body':path=root/'body.md'
    elif source=='declared_rules':
        path=root/'meta/custom-rules.md';path.parent.mkdir(parents=True)
        task['snapshot_definition']['variables'].append({'key':'rules','type':'file','source_type':'input'})
        task['parameter_values']['rules']='meta/custom-rules.md'
        task['snapshot_definition']['nodes'][1]['system_prompt_template']+=' {{rules}}'
    else:
        path=root/'meta/narrative_contract.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'style_intent':'原有文风'}) if source=='book_contract' else '原有完整资料',encoding='utf8')
    save();guard,root,task,host,state,first=start(native);failed(host,task,4)
    assert policy().recovery_action(state,'polish',task,root=root) is None
    path.write_text(json.dumps({'style_intent':'作者新文风'}) if source=='book_contract' else '作者修改后的完整资料',encoding='utf8')
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context['meaningful_context_changed'] is True and context['exhausted'] is False
    action=policy().recovery_action(state,'polish',task,root=root);assert action
    state.update(action['updates']);_,second=child(native,state,task)
    assert second['retry_context']['intent_id']!=first['retry_context']['intent_id']
    assert len(guard.retry_history(root,'scene-writing/task-a'))==4
    assert guard.retry_history(root,'scene-writing/task-b')==[]


@pytest.mark.parametrize('kind',['derived_cache','declared_output'])
def test_regenerated_runtime_artifact_does_not_reset_observed_retry_budget(native,kind):
    guard,root,task,save,host=native
    relative='cache/quality/0001/length_context.md' if kind=='derived_cache' else 'story/0001/machine.json'
    key='length_context_file' if kind=='derived_cache' else 'machine_output'
    task['snapshot_definition']['variables'].append({'key':key,'type':'file',
        'source_type':'input' if kind=='derived_cache' else 'output','default':relative})
    task['parameter_values'][key]=relative
    if kind=='derived_cache':task['snapshot_definition']['nodes'][1]['first_message']+=' {{length_context_file}}'
    path=root/relative;path.parent.mkdir(parents=True);path.write_text('old runtime artifact',encoding='utf8')
    save();guard,root,task,host,state,first=start(native);failed(host,task,2)
    path.write_text('regenerated derived runtime artifact',encoding='utf8')
    context=guard.recovery_retry_context(root,state,'polish',task)
    assert context['meaningful_context_changed'] is False
    action=policy().recovery_action(state,'polish',task,root=root);assert action
    state.update(action['updates']);second_task,second=child(native,state,task)
    assert second['retry_context']['intent_id']==first['retry_context']['intent_id']
    failed(host,second_task,2)
    assert policy().recovery_action(state,'polish',second_task,root=root) is None
    assert len(guard.retry_history(root,'scene-writing/task-b'))==4
