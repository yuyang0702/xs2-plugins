import copy
import json
import os
import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_checkpoint_recovery import load
from test_continuity_contract import PLUGIN
from test_draft_guard import accepted_facts,save
from test_continuity_contract import evidence


def fixture(root,monkeypatch,capsys):
    guard,directory,body=accepted_facts(root,monkeypatch,capsys)
    definition=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    state={'values':{'chapter_number':'0001','target_word_count':'1-500','narrative_pov':'third_person'}}
    save(root/'cache/se/se_output.json',{})
    task={'task_id':'task-guard','status':'failed','workspace_override':str(root),
        'parameter_values':{**state['values'],'multi_dir':'cache/multi/task-guard'},
        'snapshot_definition':definition,'node_states':{key:{'status':'completed'} for key in
            ('script_multi_plan','script_guard_prepare','script_guard_facts_commit')}}
    task['node_states']['agent_guard_expression_repair']={'status':'failed','error':'invalid exact anchor'}
    return state,task,definition,body


def test_review_checkpoint_keeps_verified_prose_and_replays_all_gates_not_writers(tmp_path,monkeypatch,capsys):
    state,source,definition,body=fixture(tmp_path,monkeypatch,capsys);module=load('recovery_checkpoint')
    checkpoint=module.prepare_review(tmp_path,state,source,'0001');state['automaticCheckpoint']=checkpoint
    options=module.options(tmp_path,state,definition,source)
    selected=set(options['selected_node_ids'])
    assert {'script_guard_prepare','script_guard_facts_commit','script_guard_expression_commit',
        'script_guard_finish','script_si_post','script_render_si','sync_up_si','script_check_originality'}<=selected
    assert 'agent_sw' not in selected and 'agent_we' not in selected
    seed=options['parameter_values']['guard_source_file']
    assert json.loads((tmp_path/seed).read_text(encoding='utf-8'))['body']==body
    assert json.loads((tmp_path/'cache/si/chapter.json').read_text(encoding='utf-8'))['body']=='未经修订的原始试稿'
    assert not (tmp_path/'story/0001/chapter.md').exists()
    # Real native parameter merge must preserve the seed, not restore the default.
    from test_longrun import helper
    values=helper('driver').task_parameters(state,definition,load('production'),options)
    assert values['guard_source_file']==seed


def test_unpublished_expression_conflict_can_replan_without_publishing_fact_seed(tmp_path,monkeypatch,capsys):
    state,task,definition,body=fixture(tmp_path,monkeypatch,capsys)
    from test_draft_guard import module as guard_module,run
    guard=guard_module();directory=tmp_path/'cache/draft-guard/task-guard'
    payload={'source_sha256':guard.body_digest(body),'edits':[],'status':'needs_replan','reason':'分场配额不足以承载表达修订。','evidence':[body[:12]]}
    save(directory/'expression-draft.json',payload)
    with pytest.raises(ValueError,match='CONTENT_LENGTH_CONFLICT'):
        run(guard,tmp_path,monkeypatch,capsys,'candidate','expression')
    task['node_states']['agent_guard_expression_repair']={'status':'completed'}
    task['node_states']['script_guard_expression_candidate']={'status':'failed'}
    task['parameter_values']['guard_expression_patch_result']=json.dumps(payload,ensure_ascii=False)
    assert guard.verify_conflict(tmp_path,state,task)['origin']=='mvp'
    assert not (tmp_path/'story/0001/chapter.md').exists()
    task['parameter_values']['guard_expression_patch_result']='{}'
    with pytest.raises(ValueError):guard.verify_conflict(tmp_path,state,task)


@pytest.mark.parametrize('kind',['approved','plan','sources','book','new_body','inline'])
def test_review_checkpoint_rejects_changed_inputs_and_author_text(tmp_path,monkeypatch,capsys,kind):
    state,source,definition,body=fixture(tmp_path,monkeypatch,capsys);module=load('recovery_checkpoint')
    checkpoint=module.prepare_review(tmp_path,state,source,'0001');state['automaticCheckpoint']=checkpoint
    paths={'approved':'cache/draft-guard/task-guard/facts-approved.json','plan':'cache/multi/task-guard/plan.json',
           'sources':'cache/multi/task-guard/planning-sources.md','book':'meta/world_foundation.md',
           'new_body':'story/0001/chapter.md'}
    if kind=='inline':
        next(n for n in definition['nodes'] if n['id']=='script_si_post')['node_params']['script_source']='inline'
    else:
        file=tmp_path/paths[kind];file.parent.mkdir(parents=True,exist_ok=True);file.write_text('later change',encoding='utf-8')
    with pytest.raises((ValueError,KeyError)):module.options(tmp_path,state,definition,source)


def test_review_checkpoint_completion_rejects_old_render_cache(tmp_path,monkeypatch,capsys):
    state,source,definition,body=fixture(tmp_path,monkeypatch,capsys);module=load('recovery_checkpoint')
    checkpoint=module.prepare_review(tmp_path,state,source,'0001');state['automaticCheckpoint']=checkpoint
    task={'task_id':'review-new','snapshot_definition':definition,
        'disabled_node_ids':[n['id'] for n in definition['nodes'] if n['id'] not in checkpoint['selected_node_ids']],
        'node_states':{key:{'status':'completed'} for key in checkpoint['selected_node_ids']}}
    with pytest.raises((ValueError,FileNotFoundError)):module.verify(tmp_path,state,task)


@pytest.mark.parametrize('planned',[False,True])
def test_review_seed_runs_actual_guards_then_si_conversion_and_render(tmp_path,monkeypatch,capsys,planned):
    state,source,definition,body=fixture(tmp_path,monkeypatch,capsys);module=load('recovery_checkpoint')
    if planned:
        from test_composition_plan import module as composition
        state['values']['target_word_count']='1-600';save(tmp_path/'.novel-project.json',state)
        save(tmp_path/'meta/length_policy.json',{'schema':1,'ownership':'planner'})
        composer=composition();req=composer.prepare(tmp_path,'0001','seed-budget','1-600')
        plan={'request_digest':req['request_digest'],'status':'ready','reason':'本章作用足够。','minimum':1,'maximum':500,
            'segments':[{'id':'one','purpose':'关系与选择','development':'选择形成回应','minimum':1,'maximum':500}]}
        review={'request_digest':req['request_digest'],'plan_digest':composer.identity(plan),'verdict':'approve','scope_preserved':True,
            'length_feasible':True,'reason':'尊重本书声线','checks':[{'segment_id':'one','develops_function':True,'style_basis':'本书','reason':'有发展'}]}
        composer.accept(tmp_path,'seed-budget',plan,review)
    checkpoint=module.prepare_review(tmp_path,state,source,'0001');state['automaticCheckpoint']=checkpoint
    options=module.options(tmp_path,state,definition,source)
    from test_draft_guard import module as guard_module
    if planned:
        from test_longrun import helper
        assert helper('driver').task_parameters(state,definition,load('production'),options)['target_word_count']=='1-500'
    guard=guard_module();monkeypatch.setenv('TASK_ID','review-new')
    def run(action,phase='facts'):
        monkeypatch.setattr('sys.argv',['guard',action,'--phase',phase,'--multi-dir','cache/multi/task-guard',
            '--target','1-500','--pov','third_person','--expression-format','patches',
            '--source-file',options['parameter_values']['guard_source_file']])
        guard.main();assert 'WF_REJECT' not in capsys.readouterr().out
    run('prepare');directory=tmp_path/'cache/draft-guard/review-new'
    assert json.loads((directory/'facts-input.json').read_text(encoding='utf-8'))['source_body']==body
    _,report=evidence(body);report['book_contract_sha256']=json.loads((directory/'binding.json').read_text())['book_contract_sha256']
    save(directory/'facts-draft.json',{'body':body});run('candidate');save(directory/'facts-audit.json',report);run('commit')
    save(directory/'expression-draft.json',{'source_sha256':guard.body_digest(body),'edits':[]})
    run('candidate','expression');report['checks']['repetition']=True
    save(directory/'expression-audit.json',report);run('commit','expression');run('finish','expression')
    si=guard.load('checkpoint_si',PLUGIN/'resources/script-library/nvl/si_post/si_post.py')
    monkeypatch.setattr('sys.argv',['si','--input','cache/si/chapter.json']);si.main()
    renderer=guard.load('checkpoint_renderer',PLUGIN/'resources/script-library/nvl/local_archive/local_archive.py')
    monkeypatch.setattr('sys.argv',['archive','render','--inputs','cache/si/body.json','--outputs','story/0001/chapter.md']);renderer.main()
    task={'task_id':'review-new','snapshot_definition':definition,'parameter_values':options['parameter_values'],
        'disabled_node_ids':[n['id'] for n in definition['nodes'] if n['id'] not in checkpoint['selected_node_ids']],
        'node_states':{key:{'status':'completed'} for key in checkpoint['selected_node_ids']}}
    module.verify(tmp_path,state,task)
    # A later tail failure must switch to the existing body-publication recovery,
    # rather than trying to enter the unpublished-draft checkpoint again.
    task.update(status='failed',workspace_override=str(tmp_path),error='Script Library 已漂移')
    task['node_states']['script_check_originality']={'status':'failed','error':'Script Library 已漂移'}
    action=load('production').recovery_action(state,'mvp',task,root=tmp_path)
    assert action['action']=='advance'
    next_state={**state,**action['updates']}
    assert next_state['automaticCheckpoint'].get('kind')!='draft_review'
    assert next_state['automaticCheckpoint']['source_task_id']=='review-new'
    assert module.options(tmp_path,next_state,definition,task)['selected_node_ids']==['script_check_originality']
    save(tmp_path/'cache/si/body.json',{'body':'其他任务留下的旧缓存'})
    with pytest.raises(ValueError):module.verify(tmp_path,state,task)


def test_native_selected_graph_replays_review_without_any_authoring_node(tmp_path,monkeypatch,capsys):
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.manager import WorkflowManager
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    from test_longrun import helper
    state,source,raw,body=fixture(tmp_path,monkeypatch,capsys);module=load('recovery_checkpoint')
    state['automaticCheckpoint']=module.prepare_review(tmp_path,state,source,'0001')
    options=module.options(tmp_path,state,raw,source);wf=WorkflowDef.from_dict(raw)
    values=helper('driver').task_parameters(state,raw,load('production'),options)
    disabled=WorkflowManager._resolve_disabled_nodes(None,wf,selected_node_ids=options['selected_node_ids'])
    calls=[]
    class Agent(BaseNodePlugin):
        node_type='agent'
        async def execute(self,ctx):
            key=ctx.node_def.id;calls.append(key)
            assert key in {'agent_guard_facts_repair','agent_guard_facts_audit','agent_guard_expression_repair','agent_guard_expression_audit'}
            directory=tmp_path/ctx.parameter_values['guard_dir'];phase='expression' if 'expression' in key else 'facts'
            if key.endswith('_repair'):
                data={'source_sha256':__import__('hashlib').sha256(body.encode()).hexdigest(),'edits':[]} if phase=='expression' else {'body':body}
                save(directory/f'{phase}-draft.json',data)
            else:
                _,report=evidence(body);packet=json.loads((directory/f'{phase}-audit-input.json').read_text(encoding='utf-8'))
                report['book_contract_sha256']=packet['book_contract_sha256']
                if phase=='expression':report['checks']['repetition']=True
                save(directory/f'{phase}-audit.json',report)
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            node=ctx.node_def;params=node.node_params
            if node.id in ('sync_up_si','script_check_originality'):return NodeResult(status='completed')
            args=params.get('script_argv')
            if args is None:
                import shlex
                args=shlex.split(params.get('script_args',''))
            args=[await resolve_placeholders(a,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for a in args]
            file=PLUGIN/'resources/script-library'/params['script_group']/params['script_name']/(params['script_name']+'.py')
            result=subprocess.run([sys.executable,str(file),*args],cwd=tmp_path,env={**os.environ,'TASK_ID':'review-graph'},capture_output=True,text=True,encoding='utf-8')
            assert result.returncode==0,result.stderr
            assert 'WF_REJECT' not in result.stdout,result.stdout
            return NodeResult(status='completed',outputs=_parse_wf_vars(result.stdout))
    monkeypatch.setitem(registry._plugins,'agent',Agent);monkeypatch.setitem(registry._plugins,'script',Script)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def save_task(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',save_task);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    task=WorkflowTask(workflow_id=wf.workflow_id,task_id='review-graph',status='running',parameter_values=values,disabled_node_ids=sorted(disabled),snapshot_definition=raw)
    async def run():
        return await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),
            disabled_ids=disabled,shared_ws=tmp_path,parent_id='test',on_node_started=lambda _:None,
            needs_approval=False,run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    outcome=asyncio.run(run())
    if outcome!='completed':raise AssertionError(json.dumps({key:(node.status,node.error) for key,node in task.node_states.items() if key in options['selected_node_ids']}))
    assert len(calls)==4
    module.verify(tmp_path,state,task.to_dict())
