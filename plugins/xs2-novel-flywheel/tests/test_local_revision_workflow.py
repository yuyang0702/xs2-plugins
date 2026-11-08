import json
from pathlib import Path
import pytest
from test_book_contract import PLUGIN
from test_local_revision import setup,patch,approved


def test_content_polish_uses_patches_and_independent_review_length_only_stays_separate():
    d=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf-8'))
    nodes={n['id']:n for n in d['nodes']};edges={(e['source'],e['target']) for e in d['edges']}
    assert ('gw_polish_scope','script_local_prepare') in edges
    assert nodes['agent_pl']['node_params']['json_output_schema']['required']==['source_sha256','edits']
    assert ('script_local_candidate','agent_local_review') in edges and ('agent_local_review','script_local_commit') in edges
    assert nodes['script_local_commit']['node_params']['script_stdin_variable']=='revision_review_result'
    assert ('script_focused_execution','agent_pp') in edges and ('agent_pp','script_fragment_review_context') in edges
    assert 'script_polish_post' not in nodes
    schema=nodes['agent_local_review']['node_params']['json_output_schema']['properties']['change_reviews']['items']['properties']
    assert 'replacement' in schema['after_excerpt'].get('description','')
    roles=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf8'))['agents']
    prompt='\n'.join(s['content'] for s in roles['xs2-local-revision-reviewer']['sections'])
    assert 'replacement为空字符串' in prompt


def test_completion_check_rejects_a_post_publication_edit(tmp_path):
    from test_length_quality import policy
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=approved(m,out,tmp_path)
    m.commit(tmp_path,out['revision_dir'],report)
    task={'task_id':'local-test','parameter_values':{**out,'revision_review_result':report},'node_states':{'script_local_commit':{'status':'completed'}}}
    state={'values':{'chapter_number':'0001'}}
    path=tmp_path/'story/0001/chapter.md';path.write_bytes(path.read_bytes()+'作者新改。'.encode())
    current=path.read_bytes()
    with pytest.raises(ValueError):policy().verify_completion(tmp_path,state,'polish',task)
    assert path.read_bytes()==current


@pytest.mark.parametrize('first_problem',['stale','quality','combined'])
def test_real_scheduler_retries_only_responsible_role_and_passes_actual_report_on_stdin(tmp_path,monkeypatch,first_problem):
    import asyncio,os,shlex,sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.failure_policy import activate_scheduled_retry
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.script import _parse_wf_vars,_parse_reject_upstream
    from src.workflow.variable_resolution import resolve_placeholders
    from test_length_quality import policy
    from test_local_revision import BODY,module
    from test_book_contract import put
    put(tmp_path,'.novel-project.json',{'mode':'short','values':{'chapter_number':'0001','target_word_count':'1-5000'}})
    (tmp_path/'story/0001').mkdir(parents=True);(tmp_path/'story/0001/chapter.md').write_bytes(BODY.encode())
    raw=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(raw);assert not wf.validate()
    calls=[];m=module();out=m.locations('cache/local-revision/scheduler-local')
    class Manager:
        sessions={};main_session_id=''
        async def create_sub_session(self,**kwargs):
            node=kwargs['node_id'];calls.append(node)
            assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
            if node=='agent_sc':output={'feels_human':True,'scene_assessment':'保留原声线，合并复述。','issues':[]}
            elif node=='agent_pl':
                if calls.count(node)>1:
                    assert '第二段简明。' in kwargs['task_description'] and '未通过补丁' in kwargs['task_description']
                output=patch(m,out,tmp_path,'第二段简明。' if calls.count(node)==1 else '第二段只保留新信息。')
            else:
                output=json.loads(approved(m,out,tmp_path))
                if first_problem=='combined':
                    if calls.count(node)<=2:output['candidate_sha256']='stale'
                    elif calls.count(node)==3:output['change_reviews'][0]['effect']='regressed'
                elif calls.count(node)==1:
                    if first_problem=='stale':output['candidate_sha256']='stale'
                    else:output['change_reviews'][0]['effect']='regressed'
            sid=node+str(calls.count(node))
            self.sessions[sid]=SimpleNamespace(record=[{'type':'user','content':kwargs['task_description']},
                {'type':'assistant','content':json.dumps(output,ensure_ascii=False)}])
            kwargs['on_auto_complete'](sid,'fixture at model boundary','success','')
            return {'success':True,'session_id':sid}
    class CLI(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            params=ctx.node_def.node_params
            if 'script_argv' in params:argv=[await resolve_placeholders(x,ctx.parameter_values,wf.variables,str(tmp_path)) for x in params['script_argv']]
            else:argv=shlex.split(await resolve_placeholders(params['script_args'],ctx.parameter_values,wf.variables,str(tmp_path)))
            script=PLUGIN/'resources/script-library'/params['script_group']/params['script_name']/(params['script_name']+'.py')
            stdin=ctx.parameter_values.get(params.get('script_stdin_variable',''))
            proc=await asyncio.create_subprocess_exec(sys.executable,str(script),*argv,cwd=tmp_path,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},creationflags=0x08000000 if sys.platform=='win32' else 0)
            stdout,stderr=await proc.communicate(stdin.encode() if stdin is not None else None)
            reject=_parse_reject_upstream(stdout.decode())
            if reject:
                reason,target=reject;result=ctx.on_reject_upstream('script:'+ctx.node_def.id,reason,target)
                assert result['success'],result
                return NodeResult(status='failed',error=reason)
            return NodeResult(status='completed' if proc.returncode==0 else 'failed',outputs=_parse_wf_vars(stdout.decode()),error=stderr.decode())
    monkeypatch.setitem(registry._plugins,'agent',AgentNode);monkeypatch.setitem(registry._plugins,'script',CLI)
    engine=WorkflowEngine(Manager())
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    state=json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf8'))
    values={v['key']:v.get('default','') for v in raw['variables']};values.update(policy().parameters(state,raw))
    task=WorkflowTask(task_id='scheduler-local',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run():
        for _ in range(8):
            for key,value in list(task.node_states.items()):
                if value.status=='retry_waiting':task.node_states[key]=activate_scheduled_retry(value)
            outcome=await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),
                disabled_ids=set(),shared_ws=tmp_path,parent_id='test',on_node_started=lambda *_:None,needs_approval=False,
                run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
            if outcome!='retry_waiting':return outcome
    assert asyncio.run(run())=='completed',{k:s.error for k,s in task.node_states.items() if s.error}
    expected={'stale':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'quality':['agent_sc','agent_pl','agent_local_review','agent_pl','agent_local_review'],
              'combined':['agent_sc','agent_pl','agent_local_review','agent_local_review','agent_local_review','agent_pl','agent_local_review']}
    assert calls==expected[first_problem]
    policy().verify_completion(tmp_path,state,'polish',task.to_dict())
    replacement='第二段简明。' if first_problem=='stale' else '第二段只保留新信息。'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.replace('第二段重复说明。',replacement).encode()
