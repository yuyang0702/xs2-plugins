import json
from jsonschema import validate,ValidationError
import pytest
from test_learning_reading_objectives import source_candidates
from test_reference_distill import run,PLUGIN_ROOT


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
        assert result=='failed' and len(calls)==3
        assert not (tmp_path/'learning/cache/window-0001.validated.json').exists()
    else:
        assert result=='completed' and len(calls)==2
        assert (tmp_path/'learning/cache/window-0001.validated.json').exists()
