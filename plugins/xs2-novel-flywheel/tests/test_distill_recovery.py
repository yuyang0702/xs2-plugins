import json
from jsonschema import validate,ValidationError
import pytest
from test_learning_reading_objectives import source_candidates
from test_reference_distill import run,PLUGIN_ROOT


def test_window_preserves_evidenced_entries_while_an_individual_sample_is_repaired(tmp_path):
    payload = source_candidates(tmp_path)
    basis = payload['candidates'][0]
    topic = basis | {'dimension': 'topic', 'mechanism': '用异常引出值得追问的选题'}
    layout = basis | {'dimension': 'layout', 'mechanism': '用短段让动作自己停顿'}
    voice = basis | {'dimension': 'voice', 'mechanism': '从人物发问看语气',
                     'dialogue_samples': [{'turns': []}]}
    # Model-provided source hashes may be omitted. Verified evidence still binds to the frozen window.
    payload = {'window_id': payload['window_id'], 'candidates': [topic, layout, voice],
               'conflict_patterns': [{'name': '缺前提的冲突链'}]}
    raw = tmp_path / 'learning/cache/raw.json'
    raw.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def validate_reply():
        return run(tmp_path, 'validate-window', '--input', 'learning/cache/raw.json', '--window-id', 'window-0001')

    first = validate_reply()
    assert first.returncode == 0, first.stderr
    assert 'candidate-03.dialogue-01' in first.stdout and 'conflict-01' in first.stdout
    assert '用异常引出值得追问的选题' not in first.stdout
    assert '用短段让动作自己停顿' not in first.stdout
    assert not (tmp_path / 'learning/cache/window-0001.validated.json').exists()

    # Re-running the check on the same response keeps the same round and validated records.
    assert validate_reply().stdout == first.stdout
    repaired = {'window_id': payload['window_id'], 'repair_round': 1, 'repairs': [
        {'repair_id': 'candidate-03.dialogue-01', 'value': None, 'reason': '现有定位没有连续对白'},
        {'repair_id': 'conflict-01', 'value': None, 'reason': '现有证据不支持冲突链'},
        {'repair_id': 'candidate-01', 'value': layout | {'mechanism': '旧条目不能被本轮替换'}},
    ]}
    raw.write_text(json.dumps(repaired, ensure_ascii=False), encoding='utf-8')
    finish = validate_reply()
    assert finish.returncode == 0, finish.stderr
    assert '<WF_REJECT_UPSTREAM' not in finish.stdout
    result = json.loads((tmp_path / 'learning/cache/window-0001.validated.json').read_text(encoding='utf-8'))
    assert [row['dimension'] for row in result['candidates']] == ['topic', 'layout', 'voice']
    assert result['candidates'][0]['mechanism'] == topic['mechanism']
    assert 'dialogue_samples' not in result['candidates'][2]
    assert result['conflict_patterns'] == []
    assert len(result['unresolved']) == 2
    assert run(tmp_path, 'merge').returncode == 0
    data = json.loads((tmp_path / 'learning/candidates.json').read_text(encoding='utf-8'))
    assert {row['dimension'] for row in data['candidates']} == {'topic', 'layout', 'voice'}


def test_new_split_of_identical_input_cannot_merge_stale_window_results(tmp_path):
    source_candidates(tmp_path)
    argv = ('validate-window', '--input', 'learning/cache/raw.json', '--window-id', 'window-0001')
    assert run(tmp_path, *argv).returncode == 0
    assert run(tmp_path, 'merge').returncode == 0
    split = run(tmp_path, 'split', '--input', 'references/source.txt', '--source-mode', 'short_full',
                '--learning-direction', 'zhihu_short')
    assert split.returncode == 0, split.stderr
    stale = run(tmp_path, 'merge')
    assert stale.returncode != 0 and '窗口结果过期' in stale.stderr
    assert run(tmp_path, *argv).returncode == 0
    assert run(tmp_path, 'merge').returncode == 0


def test_model_shape_error_returns_to_analyst_and_preserves_raw(tmp_path):
    raw=source_candidates(tmp_path);raw['candidates'][0]['source_pov']='first_person'
    p=tmp_path/'learning/cache/raw.json';p.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf8');before=p.read_bytes()
    result=run(tmp_path,'validate-window','--input','learning/cache/raw.json','--window-id','window-0001')
    assert result.returncode==0,result.stderr
    assert '<WF_REJECT_UPSTREAM target="agent_distill_window">' in result.stdout
    assert 'source_pov' in result.stdout
    assert p.read_bytes()==before
    assert not (tmp_path/'learning/cache/window-0001.validated.json').exists()
    archives=list((tmp_path/'learning/cache/rejected').glob('*.json'))
    assert len(archives)==1 and json.loads(archives[0].read_text(encoding='utf8'))['response']==raw


def test_wrong_evidence_id_is_not_silently_repaired(tmp_path):
    raw=source_candidates(tmp_path)
    raw['candidates'][0]['evidence']=[{'window_id':'window-0001','evidence_id':'window-0009','reason':'待核对'}]
    (tmp_path/'learning/cache/raw.json').write_text(json.dumps(raw,ensure_ascii=False),encoding='utf8')
    result=run(tmp_path,'validate-window','--input','learning/cache/raw.json','--window-id','window-0001')
    assert 'WF_REJECT_UPSTREAM' in result.stdout and '证据编号' in result.stdout
    assert not (tmp_path/'learning/cache/window-0001.validated.json').exists()


def test_changed_source_is_a_fatal_integrity_error_not_model_retry(tmp_path):
    source_candidates(tmp_path)
    m=json.loads((tmp_path/'learning/cache/windows.json').read_text(encoding='utf8'))
    (tmp_path/m['source']['snapshot_path']).write_text('来源已被更改。',encoding='utf8')
    result=run(tmp_path,'validate-window','--input','learning/cache/raw.json','--window-id','window-0001')
    assert result.returncode!=0 and 'WF_REJECT_UPSTREAM' not in result.stdout
    assert '快照哈希不一致' in result.stderr


def test_native_analyst_schema_rejects_scalar_pov_and_feedback_is_bounded(tmp_path):
    raw=source_candidates(tmp_path)
    wf=json.loads((PLUGIN_ROOT/'resources/workflows/reference-distillation/definition.json').read_text(encoding='utf8'))
    node=next(n for n in wf['nodes'] if n['id']=='agent_distill_window')
    schema=node['node_params']['json_output_schema'];validate(raw,schema)
    assert node['auto_retry_count']==2 and not node.get('fail_auto_skip',False)
    raw['candidates'][0]['source_pov']='first_person'
    with pytest.raises(ValidationError):validate(raw,schema)
    gate=next(n for n in wf['nodes'] if n['id']=='script_validate_window')
    assert gate['enable_reject_upstream'] is True and gate['max_reject_count']==2
    assert gate['node_params']['script_argv'][0]=='validate-window'
    assert '{{distill_feedback_file}}' in node['first_message']


@pytest.mark.parametrize('persistent',[False,True])
def test_scheduler_retries_only_analyst_and_stops_at_limit(tmp_path,monkeypatch,persistent):
    import asyncio,os,sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.script import _parse_wf_vars,_parse_reject_upstream
    from src.workflow.variable_resolution import resolve_placeholders
    from src.workflow.failure_policy import activate_scheduled_retry
    raw=source_candidates(tmp_path)
    full=json.loads((PLUGIN_ROOT/'resources/workflows/reference-distillation/definition.json').read_text(encoding='utf8'))
    selected=[n for n in full['nodes'] if n['id'] in ('agent_distill_window','script_validate_window')]
    definition={'workflow_id':'bounded-distill-copy','nodes':selected,'variables':full['variables'],
        'edges':[{'id':'next','source':'agent_distill_window','target':'script_validate_window'}]}
    wf=WorkflowDef.from_dict(definition);calls=[]
    class Analyst(BaseNodePlugin):
        async def execute(self,ctx):
            calls.append(ctx.node_def.id)
            if len(calls)>1:
                assert '证据编号' in (tmp_path/'learning/cache/window-0001.feedback.md').read_text(encoding='utf8')
            value=json.loads(json.dumps(raw))
            if len(calls)==1 or persistent:value['candidates'][0]['evidence']=[{'window_id':'window-0001','evidence_id':'window-0001-e9999','reason':'须原文复核'}]
            if len(calls) > 1:
                value = {'window_id': value['window_id'], 'repair_round': len(calls) - 1,
                         'repairs': [{'repair_id': 'candidate-01', 'value': value['candidates'][0]}]}
            (tmp_path/'learning/cache/window-0001.raw.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
            return NodeResult(status='completed')
    class CLI(BaseNodePlugin):
        async def execute(self,ctx):
            params=ctx.node_def.node_params
            argv=[await resolve_placeholders(v,ctx.parameter_values,wf.variables,str(tmp_path)) for v in params['script_argv']]
            script=PLUGIN_ROOT/'resources/script-library/xs2/reference_distill/reference_distill.py'
            proc=await asyncio.create_subprocess_exec(sys.executable,str(script),*argv,cwd=tmp_path,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env={**os.environ,'PYTHONUTF8':'1'},
                creationflags=0x08000000 if sys.platform=='win32' else 0)
            stdout,stderr=await proc.communicate();reject=_parse_reject_upstream(stdout.decode())
            if reject:
                assert ctx.node_def.enable_reject_upstream
                reason,target=reject;result=ctx.on_reject_upstream('script:'+ctx.node_def.id,reason,target)
                return NodeResult(status='failed',error=reason if result['success'] else result.get('message','limit'))
            return NodeResult(status='completed' if proc.returncode==0 else 'failed',outputs=_parse_wf_vars(stdout.decode()),error=stderr.decode())
    monkeypatch.setitem(registry._plugins,'agent',Analyst);monkeypatch.setitem(registry._plugins,'script',CLI)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    values={v['key']:v.get('default','') for v in full['variables']};values.update(window_id='window-0001')
    task=WorkflowTask(task_id='distill-recovery-copy',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run_loop():
        for _ in range(6):
            for key,state in list(task.node_states.items()):
                if state.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(state)
            result=await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),
                disabled_ids=set(),shared_ws=tmp_path,parent_id='test',on_node_started=lambda *_:None,needs_approval=False,
                run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
            if result!='retry_waiting':return result
    result=asyncio.run(run_loop())
    if persistent:
        assert result=='completed' and len(calls)==3
        approved = json.loads((tmp_path/'learning/cache/window-0001.validated.json').read_text(encoding='utf-8'))
        assert not approved['candidates'] and len(approved['unresolved']) == 1
    else:
        assert result=='completed' and len(calls)==2
        assert (tmp_path/'learning/cache/window-0001.validated.json').exists()
