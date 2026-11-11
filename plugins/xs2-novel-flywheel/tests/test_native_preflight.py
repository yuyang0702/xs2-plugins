"""Native task boundary regressions; no model request or real book mutation."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_production_preflight import module


def test_effective_installed_namespace_resolves_canonical_script_identity():
    m=module()
    definition={'workflow_id':'xs2-novel-flywheel-polish','variables':[],
        'nodes':[{'id':'context','node_type':'script','node_params':{'script_source':'library',
         'script_type':'python','script_group':'xs2-novel-flywheel-xs2','script_name':'story_support'}}]}
    m.check_definition(definition,{})


@pytest.fixture
def native(tmp_path, monkeypatch):
    m = module()
    host = tmp_path / 'host'
    (host / 'src').mkdir(parents=True)
    root = tmp_path / 'book'
    root.mkdir()
    path = host / 'data/workflows/wf/tasks/task-a.json'
    path.parent.mkdir(parents=True)
    definition = {
        'workflow_id': 'polish',
        'variables': [
            {'key': 'chapter_number', 'source_type': 'input', 'default': '0001'},
            {'key': 'body', 'type': 'file', 'source_type': 'input', 'required': True},
            {'key': 'result', 'source_type': 'output'},
        ],
        'nodes': [
            {'id': 'script_production_start', 'node_type': 'script'},
            {'id': 'writer', 'node_type': 'agent', 'agent_type': 'novel-director',
             'model_override': 'route:model', 'first_message': '{{body}}',
             'system_prompt_template': 'Additional rule {{chapter_number}}',
             'node_params': {'json_output_schema': {'type': 'object'}}},
        ],
    }
    task = {'workflow_id': 'wf', 'task_id': 'task-a', 'status': 'running',
            'created_at': '2026-11-10T00:00:00+00:00', 'workspace_override': str(root),
            'snapshot_definition': definition, 'snapshot_variables': definition['variables'],
            'parameter_values': {'chapter_number': '0001', 'body': 'body.md'}}
    (root / 'body.md').write_text('完整原文。\n' * 100, encoding='utf8')
    def save():
        path.write_text(json.dumps(task, ensure_ascii=False), encoding='utf8')
    save()
    monkeypatch.setattr(m, 'host_root', lambda: host)
    monkeypatch.setenv('DETERMINFLOW_PROJECT_DIR', str(host))
    monkeypatch.setenv('TASK_ID', 'task-a')
    monkeypatch.setenv('WORKFLOW_ID', 'wf')
    return m, root, task, save, host


def test_native_start_budget_finish_replay_and_mutable_outputs(native):
    m, root, task, save, _ = native
    first = m.run(root, 'polish', '0001', 'task-a', 'wf')
    task['parameter_values'].update(result='new output', incidental_output='not an input')
    save()
    assert m.run(root, 'polish', '0001', 'task-a', 'wf') == first
    request = m.request_budget(root, 'writer')
    assert request['components']['message']['characters'] == len((root / 'body.md').read_bytes().decode('utf8'))
    assert request['components']['system_prompt']['characters'] > len('Additional rule 0001')
    assert request['exact_request_observed'] is False
    assert request['coverage'] != 'complete'
    assert m.run(root, 'polish', '0001', 'task-a', 'wf', finish=True) == first
    assert m.run(root, 'polish', '0001', 'task-a', 'wf', finish=True) == first
    with pytest.raises(ValueError, match='LEASE'):
        m.assert_current(root)
    with pytest.raises(ValueError, match='LEASE'):
        m.run(root, 'polish', '0001', 'task-a', 'wf')


def test_reuse_profile_resolves_host_relative_configuration_from_book_cwd(native, monkeypatch):
    m, root, _, _, host = native
    monkeypatch.chdir(root)
    monkeypatch.setenv('DETERMINFLOW_CONFIG_DIR', './config')
    monkeypatch.setenv('DETERMINFLOW_MODELS_CONFIG_FILE', './config/models_config.json')
    (host/'config').mkdir()
    model_config = host/'config/models_config.json'
    model_config.write_text('{"temperature":0.3}', encoding='utf8')
    before = m.reuse_profile(root, ('writer',))
    model_config.write_text('{"temperature":0.5}', encoding='utf8')
    assert m.reuse_profile(root, ('writer',)) != before


def test_native_snapshot_variables_used_when_definition_omits_them(native):
    m, root, task, save, _ = native
    task['snapshot_definition'].pop('variables')
    save()
    m.run(root, 'polish', '0001', 'task-a', 'wf')
    task['parameter_values']['result'] = 'mutable'
    save()
    m.run(root, 'polish', '0001', 'task-a', 'wf', finish=True)


def test_native_input_and_resource_drift_fence_publication(native, monkeypatch):
    m, root, task, save, _ = native
    first = m.run(root, 'polish', '0001', 'task-a', 'wf')
    task['parameter_values']['chapter_number'] = '0002'
    save()
    with pytest.raises(ValueError, match='PREFLIGHT'):
        m.assert_current(root)
    task['parameter_values']['chapter_number'] = '0001'
    save()
    monkeypatch.setattr(m, 'profile', lambda **kwargs: {'changed': 'hash'})
    with pytest.raises(ValueError, match='PREFLIGHT'):
        m.assert_current(root)
    m.verify_claim(root, first['lease'])


def test_same_native_owner_never_self_reconciles_on_terminal_status(native):
    m, root, task, save, _ = native
    first = m.run(root, 'polish', '0001', 'task-a', 'wf')
    task['status'] = 'completed'
    save()
    assert m.run(root, 'polish', '0001', 'task-a', 'wf', finish=True) == first


def test_terminal_owner_reconciles_but_old_publication_stays_fenced(native):
    m, root, task, save, host = native
    first = m.run(root, 'polish', '0001', 'task-a', 'wf')
    other = dict(task, task_id='task-b')
    other_path = host / 'data/workflows/wf/tasks/task-b.json'
    other_path.write_text(json.dumps(other), encoding='utf8')
    with pytest.raises(ValueError, match='LEASE'):
        m.run(root, 'polish', '0001', 'task-b', 'wf')
    task['status'] = 'failed'
    save()
    second = m.run(root, 'polish', '0001', 'task-b', 'wf')
    assert second['lease']['epoch'] > first['lease']['epoch']
    with pytest.raises(ValueError, match='LEASE'):
        m.assert_current(root)


def armed_state():
    return {'autoNext': True, 'autoController': 'server-v1', 'autoArmed': True,
            'values': {'chapter_number': '0001'}, 'stageId': 'polish'}


def test_reserve_launch_only_armed_and_concurrent_intents_one_winner(native):
    m, root, *_ = native
    assert m.reserve_launch(root, {}, 'polish') is None
    def take(_):
        state = armed_state()
        try:
            return state, m.reserve_launch(root, state, 'polish')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(take, range(2)))
    assert sum(r is not None for r in results) == 1
    state, lease = next(r for r in results if r)
    assert state['productionLaunchLease']['lease'] == lease
    assert m.reserve_launch(root, state, 'polish') == lease


def test_launch_handoff_requires_durable_task_ref_and_matching_token(native):
    m, root, task, _, _ = native
    state = armed_state()
    lease = m.reserve_launch(root, state, 'polish')
    state['autoPending'] = {'id': 'intent-a', 'stage': 'polish', 'workflow_id': 'wf',
                            'parameters': task['parameter_values'], 'before_task_ids': []}
    project = root / '.novel-project.json'
    project.write_text(json.dumps(state), encoding='utf8')
    with pytest.raises(ValueError, match='LEASE'):
        m.run(root, 'polish', '0001', 'task-a', 'wf')
    m.verify_claim(root, lease)
    state['refs'] = {'polish': {'workflow_id': 'wf', 'task_id': 'task-a'}}
    project.write_text(json.dumps(state), encoding='utf8')
    first = m.run(root, 'polish', '0001', 'task-a', 'wf')
    assert first['lease']['owner'] == 'wf/task-a'
    with pytest.raises(ValueError, match='LEASE'):
        m.verify_claim(root, lease)


def test_reservation_without_native_evidence_never_expires(native):
    m, root, *_ = native
    state = armed_state()
    lease = m.reserve_launch(root, state, 'polish')
    with pytest.raises(ValueError, match='LEASE'):
        m.reserve_launch(root, armed_state(), 'polish')
    assert m.release_launch(root, state, 'polish') is False
    m.verify_claim(root, lease)


def test_budget_ignores_unused_file_and_rejects_referenced_path_escape(native):
    m, root, task, save, _ = native
    task['snapshot_variables'].append({'key': 'unused', 'type': 'file', 'required': True})
    task['parameter_values']['unused'] = '../outside.txt'
    save()
    m.run(root, 'polish', '0001', 'task-a', 'wf')
    assert m.request_budget(root, 'writer')['unresolved_variables'] == []
    task['parameter_values']['body'] = '../outside.txt'
    save()
    # Input drift is fenced first; a fresh task also rejects escaped file references.
    with pytest.raises(ValueError, match='PREFLIGHT|CONTEXT_BUDGET'):
        m.request_budget(root, 'writer')


def test_budget_failure_persists_actionable_complete_input_diagnostics(native):
    m, root, _, _, _ = native
    (root / 'meta').mkdir()
    (root / 'meta/model_capabilities.json').write_text(json.dumps({
        'route:model': {'context_limit': 100, 'output_reserve': 90}}), encoding='utf8')
    m.run(root, 'polish', '0001', 'task-a', 'wf')
    with pytest.raises(ValueError, match='CONTEXT_BUDGET'):
        m.request_budget(root, 'writer')
    report = json.loads((root / 'cache/production-runs/task-a/budgets/writer.json').read_text(encoding='utf8'))
    assert report['capacity_status'] == 'over_budget'
    assert report['usable_context_limit'] == 10
    assert report['coverage_plan']['semantic_review_approved'] is False
    assert (root / 'body.md').read_text(encoding='utf8').startswith('完整原文。')


def test_different_chapter_cannot_take_active_book_owner(native):
    m, root, task, _, host = native
    first=m.run(root,'polish','0001','task-a','wf')
    assert first['lease']['scope']=='book/manuscript'
    other=dict(task,task_id='task-b',parameter_values={**task['parameter_values'],'chapter_number':'0002'})
    (host/'data/workflows/wf/tasks/task-b.json').write_text(json.dumps(other),encoding='utf8')
    with pytest.raises(ValueError,match='LEASE'):
        m.run(root,'polish','0002','task-b','wf')
    m.verify_claim(root,first['lease'])


def test_native_retry_refreshes_budget_for_direct_agent_target(native):
    m, root, *_ = native
    m.run(root,'polish','0001','task-a','wf')
    assert m.retry(root,'logical-review','writer','model returned unreadable json')=='format'
    report=root/'cache/production-runs/task-a/budgets/writer.json'
    assert json.loads(report.read_text(encoding='utf8'))['node_id']=='writer'
    with pytest.raises(ValueError,match='RETRY_STOP'):
        m.retry(root,'logical-review','writer','model returned unreadable json')


@pytest.mark.parametrize('layout,effective_namespaced,with_local_decoy',[
    ('source',True,False),('prepared',True,False),('prepared',False,False),('prepared',True,True)])
def test_budget_resolves_effective_agent_and_prompt_namespace(native,monkeypatch,layout,effective_namespaced,with_local_decoy):
    m,root,task,save,host=native
    owner='xs2-novel-flywheel-';local='fixture-role';effective=owner+local if effective_namespaced else local
    task['snapshot_definition']['nodes'][1]['agent_type']=effective
    save()
    library=host/'fixture-resources'
    key=local if layout=='source' else owner+local
    agent={'prompt_template':owner+'fixture-prompt','system_prompt_template':'Agent append. ',
           'tools':['read_file'],'model_params':{'max_output_tokens':12345}}
    agents={key:agent};prompts={('fixture-prompt' if layout=='source' else owner+'fixture-prompt'):{
        'sections':[{'content':'Known system rule {{custom_append}}','enabled':True},
                    {'content':'Disabled rule must not be counted','enabled':False}]}}
    if with_local_decoy:
        agents[local]={'prompt_template':'wrong-template','system_prompt_template':'Wrong local agent'}
        prompts['fixture-prompt']={'sections':[{'content':'Wrong local prompt'}]}
    for name,data in [('agents',agents),('prompts',prompts)]:
        file=(library/'resources'/f'{name}.json' if layout=='source' else library/'json'/name/'0.json')
        file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps({'agents':data}),encoding='utf8')
    actual_resource=m.resource
    def fixture_resource(here,name):
        if name in ('agents.json','prompts.json'):
            return actual_resource(library/'script-libraries/0/xs2-novel-flywheel-xs2',name)
        return actual_resource(here,name)
    monkeypatch.setattr(m,'resource',fixture_resource)
    m.run(root,'polish','0001','task-a','wf')
    report=m.request_budget(root,'writer')
    expected='Known system rule Agent append. Additional rule 0001'
    assert report['components']['system_prompt']['characters']==len(expected)
    assert not any(v.startswith(('host_agent_definition:','host_prompt_template:')) for v in report['unknown_components'])
    assert report['resource_resolution']=={'agent_key':key,'prompt_template_key':('fixture-prompt' if layout=='source' else owner+'fixture-prompt')}
    assert report['output_reserve']==12345
    assert report['exact_request_observed'] is False
    assert report['context_limit'] is None


@pytest.mark.parametrize('change',['resolved','path_alias','different_path','chapter'])
def test_manifest_normalizes_only_equivalent_declared_file_input_paths(native,change):
    m,root,task,save,_=native
    initial='cache/quality/{{chapter_number}}/length_context.md'
    canonical='cache/quality/0001/length_context.md'
    task['snapshot_definition']['variables'][1]['default']=initial
    task['parameter_values']['body']=initial
    file=root/canonical;file.parent.mkdir(parents=True);file.write_bytes('完整输入保持全文。\r\n'.encode('utf8'))
    save();first=m.run(root,'polish','0001','task-a','wf')
    assert first['manifest']['parameters_sha256']==m.digest({'chapter_number':'0001','body':canonical})
    task['parameter_values']['body']=canonical
    if change=='path_alias':task['parameter_values']['body']='./cache/quality/0001/../0001/length_context.md'
    elif change=='different_path':task['parameter_values']['body']='cache/quality/0002/length_context.md'
    elif change=='chapter':task['parameter_values']['chapter_number']='0002'
    save()
    if change in ('resolved','path_alias'):
        assert m.run(root,'polish','0001','task-a','wf')==first
        budget=m.request_budget(root,'writer')
        assert budget['input_files']['body']['path']==canonical
        assert m.run(root,'polish','0001','task-a','wf',finish=True)==first
    else:
        with pytest.raises(ValueError,match='PREFLIGHT'):m.assert_current(root)


@pytest.mark.parametrize('kind',['text_input','output_reference'])
def test_file_path_normalization_does_not_authorize_arbitrary_output_rewrites(native,kind):
    m,root,task,save,_=native
    variable=task['snapshot_definition']['variables'][1]
    if kind=='text_input':
        variable['type']='text';task['parameter_values']['body']='cache/{{chapter_number}}/input.md'
    else:task['parameter_values']['body']='cache/{{result}}/input.md'
    save();m.run(root,'polish','0001','task-a','wf')
    task['parameter_values']['result']='0001'
    task['parameter_values']['body']='cache/0001/input.md'
    save()
    with pytest.raises(ValueError,match='PREFLIGHT'):m.assert_current(root)


@pytest.mark.parametrize('emitted',['','new instruction'])
def test_manifest_absent_declared_empty_default_matches_only_same_emitted_value(native,emitted):
    m,root,task,save,_=native
    task['snapshot_definition']['variables'].append({'key':'length_execution_system','type':'text','source_type':'input','default':''})
    save();first=m.run(root,'polish','0001','task-a','wf')
    task['parameter_values']['length_execution_system']=emitted
    save()
    if emitted=='':
        assert m.run(root,'polish','0001','task-a','wf')==first
        m.request_budget(root,'writer')
        assert m.run(root,'polish','0001','task-a','wf',finish=True)==first
    else:
        with pytest.raises(ValueError,match='PREFLIGHT'):m.assert_current(root)
