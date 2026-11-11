from runtime_graph import literary_graph
import importlib.util
import json
from pathlib import Path

import pytest
from test_story_support import support, commit_chapter
from test_length_quality import policy


def serial():
    spec=importlib.util.spec_from_file_location('test_serial_helper',support.HERE/'serial.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def contract(root,authority='bounded'):
    value={'schema':1,'planning':{'horizon':2,'authority':authority},
        'volumes':[{'id':'v1','title':'初卷','start':1,'end':1},
                   {'id':'v2','title':'次卷','start':2,'end':4}],
        'threads':[{'id':'promise','intent':'一个可保留悬念的承诺'}],
        'run_limits':{'max_dispatches':20,'max_chapters':5,'max_stage_attempts':3}}
    support.write(root,'meta/serial_contract.json',value)
    return value


def proposal(module,root,task='roll-1',authority='bounded'):
    contract(root,authority)
    commit_chapter(root)
    module.prepare(root,'0002',task)
    request=support.load(root,f'cache/serial/{task}/request.json')
    candidate={'chapters':[{'chapter':'0002','title':'第二章','intent':'在既有处境里犹豫',
                           'setup':[{'source_id':'story/0001/chapter.md','quote':'决定留下救人'}]},
                          {'chapter':'0003','title':'第三章','intent':'保留未解问题',
                           'setup':[{'source_id':'story/0001/chapter.md','quote':'决定留下救人'}]}]}
    support.write(root,f'cache/serial/{task}/candidate.json',candidate)
    normalized=module.normalize(root,task)
    support.write(root,f'cache/serial/{task}/review.json',{'verdict':'pass',
        'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256'],
        'scope_change':False,'findings':[]})
    return normalized


def test_volume_entry_uses_actual_archive_and_keeps_open_threads(tmp_path):
    contract(tmp_path);commit_chapter(tmp_path)
    state=serial().status(tmp_path,'0002')
    assert state['volume']['id']=='v2'
    assert state['entry']['chapter']=='0001'
    assert state['threads']['promise']['status']=='unconfirmed'
    assert state['ready']


def test_explicit_exit_condition_blocks_unproven_cross_volume_progress(tmp_path):
    value=contract(tmp_path);value['volumes'][0]['exit_conditions']=[{'thread_id':'promise','status':'resolved'}]
    support.write(tmp_path,'meta/serial_contract.json',value);commit_chapter(tmp_path)
    state=serial().status(tmp_path,'0002')
    assert not state['ready'] and state['reason_code']=='volume_handoff_review'


def test_rolling_publication_preserves_written_text_and_is_idempotent(tmp_path):
    module=serial();proposal(module,tmp_path)
    before=(tmp_path/'story/0001/chapter.md').read_bytes()
    first=module.commit(tmp_path,'roll-1');second=module.commit(tmp_path,'roll-1')
    assert first==second and first['status']=='accepted'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==before
    assert support.load(tmp_path,'planning/chapters/0002.json')['origin']=='rolling'
    assert module.need_plan(tmp_path,'0002')['ready']
    assert not module.need_plan(tmp_path,'0004')['ready']


@pytest.mark.parametrize('path,equals',[('location','隔离站'),('snapshot.missing','隔离站'),
    ('snapshot.location','已经离开的另一处')])
def test_current_entry_conditions_cannot_publish_unreadable_or_false_state(tmp_path,path,equals):
    module=serial();proposal(module,tmp_path)
    candidate=support.load(tmp_path,'cache/serial/roll-1/candidate.json')
    person=support.confirmed(tmp_path,before=2)[0][-1]['characters'][0]
    candidate['chapters'][0]['expected_state']=[{'entity_id':person['entity_id'],'path':path,'equals':equals}]
    support.write(tmp_path,'cache/serial/roll-1/candidate.json',candidate)
    with pytest.raises(ValueError,match='状态|字段|路径'):module.normalize(tmp_path,'roll-1')


def test_typed_entry_condition_survives_review_commit_and_ready_check(tmp_path):
    module=serial();proposal(module,tmp_path)
    candidate=support.load(tmp_path,'cache/serial/roll-1/candidate.json')
    person=support.confirmed(tmp_path,before=2)[0][-1]['characters'][0]
    candidate['chapters'][0]['expected_state']=[{'entity_id':person['entity_id'],
        'path':'snapshot.location','equals':person['snapshot']['location']}]
    support.write(tmp_path,'cache/serial/roll-1/candidate.json',candidate)
    normalized=module.normalize(tmp_path,'roll-1')
    support.write(tmp_path,'cache/serial/roll-1/review.json',{'verdict':'pass',
        'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256'],
        'scope_change':False,'findings':[]})
    module.commit(tmp_path,'roll-1')
    assert module.need_plan(tmp_path,'0002')['ready']


def test_future_entry_condition_may_differ_from_current_state(tmp_path):
    module=serial();proposal(module,tmp_path)
    candidate=support.load(tmp_path,'cache/serial/roll-1/candidate.json')
    person=support.confirmed(tmp_path,before=2)[0][-1]['characters'][0]
    candidate['chapters'][1]['expected_state']=[{'entity_id':person['entity_id'],
        'path':'snapshot.location','equals':'后续章节有条件抵达的地方'}]
    support.write(tmp_path,'cache/serial/roll-1/candidate.json',candidate)
    normalized=module.normalize(tmp_path,'roll-1')
    support.write(tmp_path,'cache/serial/roll-1/review.json',{'verdict':'pass',
        'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256'],
        'scope_change':False,'findings':[]})
    module.commit(tmp_path,'roll-1')
    assert module.need_plan(tmp_path,'0002')['ready']
    assert not module.need_plan(tmp_path,'0003')['ready']


def test_legacy_signed_plan_missing_field_is_not_satisfied_by_null(tmp_path):
    module=serial();proposal(module,tmp_path);module.commit(tmp_path,'roll-1')
    path='planning/chapters/0002.json';plan=support.load(tmp_path,path)
    person=support.confirmed(tmp_path,before=2)[0][-1]['characters'][0]
    plan['expected_state']=[{'entity_id':person['entity_id'],'path':'snapshot.missing','equals':None}]
    support.archive_store().publish_views(tmp_path,lambda write:write(tmp_path,path,plan),lambda:{})
    assert module.need_plan(tmp_path,'0002')=={'ready':False,'reason_code':'rolling_plan_stale'}


def test_fresh_accepted_but_unusable_plan_pauses_instead_of_paid_replanning(tmp_path,monkeypatch):
    module=serial();proposal(module,tmp_path);module.commit(tmp_path,'roll-1')
    production=policy()
    monkeypatch.setattr(production.serial(),'need_plan',lambda *_:{'ready':False,'reason_code':'rolling_plan_stale'})
    state={'mode':'serial','values':{'chapter_number':'0002','planning_mode':'rolling'},
        'serialPlanningResult':{'status':'accepted','chapter':'0002'}}
    action=production.next_action(tmp_path,state,'outline')
    assert action['action']=='pause'
    assert '计划' in action['reason']


def test_review_authority_stages_candidate_until_explicit_adoption(tmp_path):
    module=serial();proposal(module,tmp_path,authority='review')
    assert module.commit(tmp_path,'roll-1')['status']=='awaiting_author'
    assert not (tmp_path/'planning/chapters/0002.json').exists()
    assert module.commit(tmp_path,'roll-1',approve=True)['status']=='accepted'


def test_manual_future_plan_and_current_facts_are_protected(tmp_path):
    module=serial();proposal(module,tmp_path)
    support.write(tmp_path,'planning/chapters/0002.json',{'chapter':'0002','request_id':'author-choice'})
    with pytest.raises(ValueError,match='作者|变化|覆盖'):module.commit(tmp_path,'roll-1')
    assert support.load(tmp_path,'planning/chapters/0002.json')['request_id']=='author-choice'


def test_reviewer_cannot_accept_another_candidate_version(tmp_path):
    module=serial();proposal(module,tmp_path)
    review=support.load(tmp_path,'cache/serial/roll-1/review.json');review['candidate_sha256']='other'
    support.write(tmp_path,'cache/serial/roll-1/review.json',review)
    with pytest.raises(ValueError,match='版本|验收'):module.commit(tmp_path,'roll-1')


def test_serial_export_routes_missing_window_to_rolling_outline(tmp_path):
    contract(tmp_path);commit_chapter(tmp_path)
    data={'mode':'serial','autoScope':'serial_batch','autoChapterStarted':1,'autoChapterLimit':3,
          'values':{'chapter_number':'0001'}}
    action=policy().next_action(tmp_path,data,'export')
    assert action['stage']=='outline' and action['updates']['values']['planning_mode']=='rolling'


def run_control():
    path=support.HERE.parent/'console_service/run_control.py'
    spec=importlib.util.spec_from_file_location('run_control_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_run_dispatch_reservation_survives_restart_without_double_count(tmp_path):
    contract(tmp_path);state={'values':{'chapter_number':'0001'}}
    first=run_control().admit(tmp_path,state,'outline')
    restarted=run_control();second=restarted.admit(tmp_path,state,'outline')
    assert first==second
    restarted.observe(tmp_path,state,'outline',{'task_id':'t1','status':'running'})
    restarted.observe(tmp_path,state,'outline',{'task_id':'t1','status':'running'})
    assert restarted.status(tmp_path,state)['dispatches']==1
    with pytest.raises(ValueError,match='重复|归属'):
        restarted.observe(tmp_path,state,'outline',{'task_id':'t2','status':'running'})


def test_failures_cannot_reset_attempt_budget_on_restart(tmp_path):
    value=contract(tmp_path);value['run_limits']['max_stage_attempts']=2
    support.write(tmp_path,'meta/serial_contract.json',value)
    state={'values':{'chapter_number':'0001'}}
    for i in range(2):
        module=run_control();module.admit(tmp_path,state,'outline')
        module.observe(tmp_path,state,'outline',{'task_id':f't{i}','status':'failed'})
    with pytest.raises(ValueError,match='预算|上限'):run_control().admit(tmp_path,state,'outline')


def test_window_remains_valid_when_expected_previous_chapter_is_written(tmp_path):
    module=serial();proposal(module,tmp_path);module.commit(tmp_path,'roll-1')
    commit_chapter(tmp_path,'0002')
    assert module.need_plan(tmp_path,'0003')['ready']


def test_pending_dispatch_reuses_same_reservation(tmp_path):
    contract(tmp_path);state={'values':{'chapter_number':'0001'}};module=run_control()
    first=module.admit(tmp_path,state,'outline')
    module.observe(tmp_path,state,'outline',{'task_id':'pending','status':'pending'})
    assert module.admit(tmp_path,state,'outline')==first
    assert module.status(tmp_path,state)['dispatches']==1


def test_author_approval_cannot_adopt_a_changed_unseen_candidate(tmp_path):
    module=serial();proposal(module,tmp_path,authority='review');module.commit(tmp_path,'roll-1')
    candidate=support.load(tmp_path,'cache/serial/roll-1/candidate.json')
    candidate['chapters'][0]['intent']='另一个选择'
    support.write(tmp_path,'cache/serial/roll-1/candidate.json',candidate)
    normalized=module.normalize(tmp_path,'roll-1')
    support.write(tmp_path,'cache/serial/roll-1/review.json',{'verdict':'pass','scope_change':False,
        'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256']})
    with pytest.raises(ValueError,match='预览|候选|版本'):module.commit(tmp_path,'roll-1',approve=True)


def test_progress_requires_real_prose_and_respects_declared_open_ending(tmp_path):
    value=contract(tmp_path);value['volumes'][0]['exit_conditions']=[{'thread_id':'promise','status':'intentionally_open'}]
    support.write(tmp_path,'meta/serial_contract.json',value)
    quote='他决定把那个问题留到以后。'
    support.write(tmp_path,'story/0001/chapter.md',quote)
    support.begin_review(tmp_path,'0001')
    support.write(tmp_path,support.review_file('0001','observer.json'),{'confirmed_state':{'characters':[]}})
    support.write(tmp_path,support.review_file('0001','arbiter.json'),{'story_confirmed':{},'serial_progress':[
        {'thread_id':'promise','status':'intentionally_open','evidence':quote}]})
    support.commit(tmp_path,'0001')
    assert serial().status(tmp_path,'0002')['ready']
    with pytest.raises(ValueError,match='依据'):
        serial().validate_progress(tmp_path,'0002',[{'thread_id':'promise','status':'resolved','evidence':'他解决了问题。'}],quote)


def test_outline_has_separate_rolling_and_legacy_routes():
    definition=literary_graph(json.loads((support.HERE.parents[2]/'workflows/outline/definition.json').read_text(encoding='utf-8')))
    nodes={n['id']:n for n in definition['nodes']}
    assert {'script_serial_prepare','agent_rolling_plan','script_serial_normalize','agent_rolling_review','script_serial_commit'}<=nodes.keys()
    assert any(g['id']=='gw-outline-mode' for g in definition['gateways'])
    fields={f['key']:f for f in definition['variables']}
    assert fields['rolling_candidate_path']['type']=='text' and fields['rolling_candidate_file']['type']=='file'
    assert nodes['agent_rolling_plan']['output_file_path']=='{{rolling_candidate_path}}'
    assert '{{rolling_candidate_sha256}}' in nodes['agent_rolling_review']['first_message']


def test_actual_commit_cli_is_idempotent_after_publication(tmp_path):
    import os,subprocess,sys
    module=serial();proposal(module,tmp_path)
    env=dict(os.environ,TASK_ID='roll-1',PYTHONIOENCODING='utf-8')
    script=support.HERE/'serial.py'
    for _ in range(2):
        result=subprocess.run([sys.executable,str(script),'commit'],cwd=tmp_path,env=env,
            capture_output=True,text=True,encoding='utf-8')
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['status']=='accepted'


def test_author_outline_changes_invalidate_accepted_window(tmp_path):
    module=serial();proposal(module,tmp_path);module.commit(tmp_path,'roll-1')
    support.write(tmp_path,'outline/near_term_outline.md','作者采用了新的近期安排。')
    assert not module.need_plan(tmp_path,'0002')['ready']


def test_every_allowed_evidence_file_is_frozen(tmp_path):
    module=serial();contract(tmp_path)
    support.write(tmp_path,'meta/current_world.md','最初世界存在一条旧河。')
    module.prepare(tmp_path,'0001','opening')
    request=support.load(tmp_path,'cache/serial/opening/request.json')
    assert request['source_hashes']['meta/current_world.md']==support.digest(tmp_path,'meta/current_world.md')


def test_same_host_task_can_resume_with_durable_retry_accounting(tmp_path):
    contract(tmp_path);state={'values':{'chapter_number':'0001'}};module=run_control()
    module.admit(tmp_path,state,'outline')
    module.observe(tmp_path,state,'outline',{'task_id':'resume','run_id':'first','status':'failed'})
    module.observe(tmp_path,state,'outline',{'task_id':'resume','run_id':None,'status':'resume_pending'})
    module.observe(tmp_path,state,'outline',{'task_id':'resume','run_id':'second','status':'completed'})
    assert module.status(tmp_path,state)['resumes']==1


def test_agent_output_policy_is_supported_by_host():
    from src.workflow.output_selection import select_agent_output
    definition=literary_graph(json.loads((support.HERE.parents[2]/'workflows/outline/definition.json').read_text(encoding='utf-8')))
    for node in definition['nodes']:
        if node['id'] in ('agent_rolling_plan','agent_rolling_review'):
            output=({'chapters':[{'chapter':'0002','intent':'延续选择','setup':[{}]}]}
                if node['id']=='agent_rolling_plan' else {'verdict':'pass','candidate_sha256':'c',
                    'request_sha256':'r','scope_change':False,'findings':[]})
            record=[{'type':'user','content':'current frozen input'},{'type':'assistant','content':json.dumps(output)}]
            _,error=select_agent_output(record,node['node_params'])
            assert not error
            record[-1]['content']='{}'
            _,error=select_agent_output(record,node['node_params'])
            assert error and 'schema' in error.lower()


def test_prepare_retry_reuses_frozen_input_not_index_counters(tmp_path):
    module=serial();contract(tmp_path);commit_chapter(tmp_path)
    first=module.prepare(tmp_path,'0002','same-input')
    assert module.prepare(tmp_path,'0002','same-input')==first


def test_future_volume_contract_edit_does_not_revoke_past_facts(tmp_path):
    value=contract(tmp_path);commit_chapter(tmp_path)
    value['volumes'][1]['title']='作者更新的后续卷名'
    support.write(tmp_path,'meta/serial_contract.json',value)
    assert [s['chapter'] for s in support.confirmed(tmp_path)[0]]==['0001']


def test_real_host_scheduler_selects_only_rolling_branch(monkeypatch):
    path=Path(__file__).resolve().parents[4]/'DeterminFlow/tests/test_novel_compact_graph.py'
    if not path.exists():pytest.skip('Sibling host checkout unavailable')
    spec=importlib.util.spec_from_file_location('p2_host_graph_probe',path)
    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
    task,calls,agents=host._run_graph(monkeypatch,'outline',{'planning_mode':'rolling','chapter_number':'0002'})
    guards={'script_production_start','script_production_finish','script_budget_agent_rolling_plan','script_budget_agent_rolling_review'}
    assert guards<=set(calls)
    assert [node for node in calls if node not in guards]==['script_serial_prepare','agent_rolling_plan','script_serial_normalize','agent_rolling_review','script_serial_commit']
    assert agents==['agent_rolling_plan','agent_rolling_review']
    assert task.node_states['script_story_context'].status=='skipped'


def test_outline_tail_recovery_reuses_signed_receipt(tmp_path):
    module=serial();proposal(module,tmp_path);module.commit(tmp_path,'roll-1')
    state={'mode':'serial','values':{'chapter_number':'0002','planning_mode':'rolling'}}
    nodes={key:{'status':'completed'} for key in ('script_serial_prepare','agent_rolling_plan',
        'script_serial_normalize','agent_rolling_review')}
    nodes['script_serial_commit']={'status':'failed','error':'fixture crash after publication'}
    task={'task_id':'roll-1','status':'failed','parameter_values':{'planning_mode':'rolling'},'node_states':nodes}
    action=policy().recovery_action(state,'outline',task,root=tmp_path)
    assert action['action']=='advance' and action['stage']=='mvp'
    assert 'outline' in action['updates']['completed']


@pytest.mark.parametrize('file',['request.json','prompt.json'])
def test_frozen_planning_inputs_reject_tampering(tmp_path,file):
    module=serial();proposal(module,tmp_path)
    value=support.load(tmp_path,f'cache/serial/roll-1/{file}')
    value['forged']='changed outside committed prepare'
    support.write(tmp_path,f'cache/serial/roll-1/{file}',value)
    with pytest.raises(ValueError):module.normalize(tmp_path,'roll-1')


@pytest.mark.parametrize('changed',[False,True])
def test_interrupted_rolling_publication_replays_only_unchanged_input(tmp_path,monkeypatch,changed):
    module=serial();proposal(module,tmp_path);journal=module.support().archive_store()
    with monkeypatch.context() as patch:
        patch.setattr(journal,'atomic',lambda *_:(_ for _ in ()).throw(OSError('fixture power loss')))
        with pytest.raises(OSError):module.commit(tmp_path,'roll-1')
    if changed:
        support.write(tmp_path,'story/0001/chapter.md','作者修改了原文。')
        with pytest.raises(ValueError):journal.recover(tmp_path)
        assert not (tmp_path/'planning/chapters/0002.json').exists()
    else:
        journal.recover(tmp_path)
        assert module.commit(tmp_path,'roll-1')['status']=='accepted'


def test_fast_failed_same_task_resume_cannot_hide_between_polls(tmp_path):
    config=contract(tmp_path);config['run_limits']['max_stage_attempts']=2
    support.write(tmp_path,'meta/serial_contract.json',config)
    state={'values':{'chapter_number':'0001'}};module=run_control()
    module.admit(tmp_path,state,'outline')
    def failed(n):return {'task_id':'fast','run_id':str(n),'status':'failed',
        'node_states':{'planner':{'attempt_count':n}}}
    module.observe(tmp_path,state,'outline',failed(1))
    module.observe(tmp_path,state,'outline',failed(2))
    module.observe(tmp_path,state,'outline',failed(2))
    assert module.status(tmp_path,state)['resumes']==1
    with pytest.raises(ValueError,match='预算'):module.observe(tmp_path,state,'outline',failed(3))


def test_rolling_files_resolve_as_content_but_output_targets_remain_paths(tmp_path):
    import asyncio
    from src.workflow.variable_resolution import resolve_placeholders
    definition=literary_graph(json.loads((support.HERE.parents[2]/'workflows/outline/definition.json').read_text(encoding='utf-8')))
    nodes={n['id']:n for n in definition['nodes']}
    file='cache/serial/targets/candidate.json'
    values={'rolling_candidate_file':file,'rolling_candidate_path':file}
    def resolve(text):return asyncio.run(resolve_placeholders(text,values,definition['variables'],str(tmp_path)))
    assert resolve(nodes['agent_rolling_plan']['output_file_path'])==file
    support.write(tmp_path,file,{'chapters':[]})
    assert resolve(nodes['agent_rolling_plan']['output_file_path'])==file
    assert 'chapters' in resolve('{{rolling_candidate_file}}')


@pytest.mark.parametrize('planning',[[],{'max_input_chars':True},{'max_input_chars':0}])
def test_invalid_planning_budget_is_rejected_before_dispatch(tmp_path,planning):
    value=contract(tmp_path);value['planning']=planning
    support.write(tmp_path,'meta/serial_contract.json',value)
    with pytest.raises(ValueError):serial().contract(tmp_path)


def test_resume_does_not_charge_downstream_nodes_first_execution(tmp_path):
    config=contract(tmp_path);config['run_limits']['max_stage_attempts']=2
    support.write(tmp_path,'meta/serial_contract.json',config)
    state={'values':{'chapter_number':'0001'}};module=run_control()
    module.admit(tmp_path,state,'outline')
    module.observe(tmp_path,state,'outline',{'task_id':'tail','run_id':'a','status':'failed',
        'node_states':{'first':{'attempt_count':1}}})
    module.observe(tmp_path,state,'outline',{'task_id':'tail','run_id':'b','status':'completed',
        'node_states':{'first':{'attempt_count':2},**{f'tail-{n}':{'attempt_count':1} for n in range(8)}}})
    assert module.status(tmp_path,state)['resumes']==1


def test_rolling_schema_transport_error_has_bounded_operational_recovery():
    state={'values':{'chapter_number':'0002','planning_mode':'rolling'}}
    task={'task_id':'format-1','status':'failed','parameter_values':{'planning_mode':'rolling'},
        'error':'LLM 输出选择失败: invalid structured output: JSON schema validation failed'}
    action=policy().recovery_action(state,'outline',task)
    assert action and action['action']=='advance' and action['stage']=='outline'
    state.update(action['updates'])
    assert policy().recovery_action(state,'outline',task) is None
