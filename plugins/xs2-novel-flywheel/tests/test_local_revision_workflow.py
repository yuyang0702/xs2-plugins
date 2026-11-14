from runtime_graph import literary_graph
import json
from pathlib import Path
import pytest
from test_book_contract import PLUGIN
from test_local_revision import setup,patch,approved


def test_content_polish_uses_patches_and_independent_review_length_only_stays_separate():
    d=literary_graph(json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf-8')))
    nodes={n['id']:n for n in d['nodes']};edges={(e['source'],e['target']) for e in d['edges']}
    assert ('gw_polish_scope','script_local_prepare') in edges
    assert '--dialogue-check' in nodes['script_local_prepare']['node_params']['script_argv']
    assert nodes['script_local_prepare']['node_params']['script_argv'][-2:]==['--dialogue-check-version','4']
    assert nodes['script_local_writer_input']['enable_reject_upstream']
    assert nodes['agent_pl']['node_params']['json_output_schema']['required']==['source_sha256','edits']
    assert ('script_local_candidate','agent_local_review') in edges and ('agent_local_review','script_local_commit') in edges
    assert nodes['script_local_commit']['node_params']['script_stdin_variable']=='revision_review_result'
    assert ('script_focused_execution','agent_pp') in edges and ('agent_pp','script_fragment_review_context') in edges
    assert 'script_polish_post' not in nodes
    review_schema=nodes['agent_local_review']['node_params']['json_output_schema']
    schema=review_schema.get('anyOf',[review_schema])[0]['properties']['change_reviews']['items']['properties']
    assert review_schema['properties']['protocol']['const']=='local-review-v2'
    assert set(schema)=={'edit_index','effect','reason'}
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


@pytest.mark.parametrize('first_problem',['stale','quality','combined','catalog_refs','unknown_catalog_refs','planned_budget','native_conflict','cached_budget','compact_report','retained_progress'])
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
    if first_problem in ('planned_budget','native_conflict','cached_budget'):put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'planner'})
    (tmp_path/'story/0001').mkdir(parents=True);(tmp_path/'story/0001/chapter.md').write_bytes(BODY.encode())
    if first_problem=='cached_budget':
        from test_composition_plan import module as comp_module
        cm=comp_module();req=cm.prepare(tmp_path,'0001','cache-origin','1-5000')
        plan={'request_digest':req['request_digest'],'status':'ready','reason':'经批准的分配。','minimum':1,'maximum':4000,
            'segments':[{'id':'quiet','purpose':'保留回环','development':'情绪有发展','minimum':1,'maximum':4000}]}
        cm.accept(tmp_path,'cache-origin',plan,{'request_digest':req['request_digest'],'plan_digest':cm.identity(plan),
            'verdict':'approve','scope_preserved':True,'length_feasible':True,'reason':'依照本书。',
            'checks':[{'segment_id':'quiet','develops_function':True,'style_basis':'允许回环','reason':'有作用。'}]})
    raw=literary_graph(json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8')))
    wf=WorkflowDef.from_dict(raw);assert not wf.validate()
    calls=[];m=module();out=m.locations('cache/local-revision/scheduler-local')
    class Manager:
        sessions={};main_session_id=''
        async def create_sub_session(self,**kwargs):
            node=kwargs['node_id'];calls.append(node)
            assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
            if node=='agent_composition_plan':
                from test_composition_plan import module as comp_module
                cm=comp_module();req=json.loads((tmp_path/'cache/composition/scheduler-local/request.json').read_text())
                output={'request_digest':req['request_digest'],'status':'ready','reason':'保留回环并合并重复说明。',
                    'minimum':1,'maximum':4000,'segments':[{'id':'reflection','purpose':'心理与回环','development':'情绪有变化，承载本书声线','minimum':1,'maximum':4000}]}
            elif node=='agent_composition_review':
                req=json.loads((tmp_path/'cache/composition/scheduler-local/review-input.json').read_text())
                output={'request_digest':req['request_digest'],'plan_digest':req['plan_digest'],'verdict':'approve','scope_preserved':True,
                    'length_feasible':True,'reason':'不强制新增事件。','checks':[{'segment_id':'reflection','develops_function':True,'style_basis':'本书回环声线','reason':'情绪有发展。'}]}
            elif node=='agent_sc':
                output={'feels_human':True,'scene_assessment':'保留原声线，合并复述。','issues':[],
                        'dialogue_checks':[{'focus':focus,'status':'not_applicable','reason':'本章没有连续对白。','goal':'','turns':[]}
                                           for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery','voice_contrast')]}
            elif node=='agent_pl':
                if calls.count(node)>1:
                    assert '第二段简明。' in kwargs['task_description']
                    assert ('待验收工作稿' if first_problem=='retained_progress' else '未通过补丁') in kwargs['task_description']
                if first_problem=='native_conflict':
                    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
                    output={'source_sha256':source['source_sha256'],'edits':[],'status':'needs_replan','reason':'范围与篇幅无法同时满足。','evidence':['第二段重复说明。']}
                elif first_problem=='retained_progress' and calls.count(node)>1:
                    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
                    output={'source_sha256':source['source_sha256'],'edits':[{'paragraph_id':'p0001','old':'第一段保留。','occurrence':1,'replacement':'第一段仍旧保留。'}]}
                else:output=patch(m,out,tmp_path,'第二段简明。' if calls.count(node)==1 else '第二段只保留新信息。')
            else:
                output=json.loads(approved(m,out,tmp_path))
                if first_problem=='retained_progress':
                    for row in output['expression_checks']:row['excerpts']=['潮水会回来。']
                    if calls.count(node)==1:
                        output['expression_review']={'verdict':'revise','summary':'第一段尚需处理。','issues':[{'id':'remaining','category':'semantic_redundancy','location':'第一段','priority':'medium','excerpts':['第一段保留。'],'impact':'仍有无作用复述。','goal':'只处理剩余表达。'}]}
                        output['expression_checks'][0].update(status='issue',issue_ids=['remaining'],excerpts=['第一段保留。'])
                elif first_problem=='compact_report':
                    from test_review_wire import compact
                    output=compact(output)
                    if calls.count(node)==1:output['change_reviews']=[]
                elif first_problem in ('planned_budget','cached_budget'):pass
                elif first_problem in ('catalog_refs','unknown_catalog_refs'):
                    reference='c9999' if first_problem=='unknown_catalog_refs' and calls.count(node)==1 else 'c0001'
                    for row in output['expression_checks']:row['excerpts']=[{'ref_id':reference}]
                elif first_problem=='combined':
                    if calls.count(node)<=2:output['candidate_sha256']='stale'
                    elif calls.count(node)==3:output['change_reviews'][0]['effect']='regressed'
                elif calls.count(node)==1:
                    if first_problem=='stale':output['candidate_sha256']='stale'
                    else:output['change_reviews'][0]['effect']='regressed'
            if node=='agent_local_review' and 'protocol' not in output:
                from test_review_wire import compact
                stale=output.get('candidate_sha256')=='stale'
                output=compact(output)
                if stale:output['candidate_sha256']='stale'  # Invalid legacy binding remains rejected by the new schema.
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
    outcome=asyncio.run(run())
    assert task.node_states['script_composition_ready'].status=='completed'
    if first_problem in ('planned_budget','cached_budget'):
        for sid,session in engine._session_manager.sessions.items():
            if sid.startswith(('agent_sc','agent_pl')):
                assert '本章目标字数：1-4000' in session.record[0]['content']
        assert json.loads((tmp_path/'.novel-project.json').read_text(encoding='utf-8'))['values']['target_word_count']=='1-5000'
    if first_problem=='native_conflict':
        assert outcome=='failed';task.status='failed'
        action=policy().recovery_action(state,'polish',task.to_dict(),root=tmp_path)
        assert action['action']=='advance' and action['stage']=='polish'
        assert calls==['agent_composition_plan','agent_composition_review','agent_sc','agent_pl']
        assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
        return
    assert outcome=='completed',{k:s.error for k,s in task.node_states.items() if s.error}
    expected={'stale':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'quality':['agent_sc','agent_pl','agent_local_review','agent_pl','agent_local_review'],
              'combined':['agent_sc','agent_pl','agent_local_review','agent_local_review','agent_local_review','agent_pl','agent_local_review'],
              'catalog_refs':['agent_sc','agent_pl','agent_local_review'],
              'unknown_catalog_refs':['agent_sc','agent_pl','agent_local_review','agent_local_review'],
              'planned_budget':['agent_composition_plan','agent_composition_review','agent_sc','agent_pl','agent_local_review'],
              'cached_budget':['agent_sc','agent_pl','agent_local_review'],
              'compact_report':['agent_sc','agent_pl','agent_local_review','agent_local_review']}
    expected['retained_progress']=['agent_sc','agent_pl','agent_local_review','agent_pl','agent_local_review']
    assert calls==expected[first_problem]
    policy().verify_completion(tmp_path,state,'polish',task.to_dict())
    replacement='第二段简明。' if first_problem in ('stale','catalog_refs','unknown_catalog_refs','planned_budget','cached_budget','compact_report') else '第二段只保留新信息。'
    result=BODY.replace('第二段重复说明。',replacement)
    if first_problem=='retained_progress':result=BODY.replace('第二段重复说明。','第二段简明。').replace('第一段保留。','第一段仍旧保留。')
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==result.encode()
