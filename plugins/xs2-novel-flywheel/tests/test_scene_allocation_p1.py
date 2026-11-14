import hashlib
import json
from pathlib import Path

import pytest

from test_multi_scene import module


def plan(count=3):
    return {'focus':'主角','plan_reason':'准备与交涉合并，重点留给选择和回应', 'scenes':[
        {'id':i,'entry':f'状态{i}','turn':f'选择{i}','exit':f'状态{i+1}', 'knowledge':'仅知此前见闻',
         'weight':6 if i==2 else 1,'budget_reason':'交涉改变结果' if i==2 else '过渡可简写'}
        for i in range(1,count+1)]}


def cli(m, root, monkeypatch, capsys, action, *extra):
    monkeypatch.chdir(root);monkeypatch.setenv('TASK_ID','task-p1')
    monkeypatch.setattr('sys.argv',['multi_scene',action,'--target','500-550','--pov','third_person',*extra])
    m.main();return capsys.readouterr().out


def prepared(m, root, monkeypatch, capsys, count=3):
    cli(m,root,monkeypatch,capsys,'prepare')
    directory=root/'cache/multi/task-p1'
    m.save_json(directory/'plan.json',plan(count))
    output=cli(m,root,monkeypatch,capsys,'plan')
    return directory,m.read_json(directory/'allocation.json'),output


def test_weighted_budgets_have_exact_totals_and_do_not_use_fixed_six_percentages():
    lo,hi=module().budgets('500-550',weights=[1,6,1])
    assert len(lo)==3 and sum(lo)==500 and sum(hi)==550
    assert lo[1]>lo[0]*5 and lo[0]==pytest.approx(lo[2],abs=1)


@pytest.mark.parametrize('count',[1,3,6])
def test_actual_scene_count_is_separate_from_six_execution_slots(tmp_path,monkeypatch,capsys,count):
    m=module();directory,a,output=prepared(m,tmp_path,monkeypatch,capsys,count)
    assert a['scene_count']==count
    assert [r['slot'] for r in a['scenes']]==list(range(1,count))+[6]
    assert [r['scene_id'] for r in a['scenes']]==list(range(1,count+1))
    assert sum(r['nominal_minimum'] for r in a['scenes'])==500
    assert sum(r['nominal_maximum'] for r in a['scenes'])==550
    final=m.read_json(directory/'brief-6.json')
    assert final['id']==count and final['is_final'] is True
    for slot in range(1,6):
        assert f'multi_active_{slot}:{"yes" if slot<count else "no"}' in output


def test_short_transition_does_not_force_local_padding_when_chapter_total_is_valid(tmp_path,monkeypatch,capsys):
    m=module();_,a,_=prepared(m,tmp_path,monkeypatch,capsys)
    assert m.validate(['春'*5,'夏'*425,'秋'*70],'500-550','third_person',allocation=a) is None
    problem=m.validate(['春'*5,'夏'*20,'秋'*5],'500-550','third_person',allocation=a)
    assert problem[0]==1 and '[chapter_length]' in problem[1]


def test_whole_chapter_retry_never_requests_more_than_a_scene_can_accept(tmp_path,monkeypatch,capsys):
    m=module();directory,a,_=prepared(m,tmp_path,monkeypatch,capsys,6)
    for row in a['scenes']:row['draft_target']=80;row['maximum']=140
    issue=m.validate([c for c in '春夏秋冬梅竹'],'500-550','third_person',allocation=a)
    assert '至少 190实字' in issue[1]


def test_reset_scene_replacement_is_checked_at_assembly_without_repeating_completed_gate(tmp_path,monkeypatch,capsys):
    m=module();directory,a,_=prepared(m,tmp_path,monkeypatch,capsys)
    for slot,body in {1:'春'*5,2:'夏'*425,6:'秋'*70}.items():
        (directory/f'scene-{slot}.txt').write_text(body,encoding='utf-8')
        cli(m,tmp_path,monkeypatch,capsys,'scene','--scene',str(slot))
    sibling=(directory/'validated-1.json').read_bytes()
    cli(m,tmp_path,monkeypatch,capsys,'reset-scene','--scene','2')
    (directory/'scene-2.txt').write_text('冬'*425,encoding='utf-8')
    cli(m,tmp_path,monkeypatch,capsys,'assemble')
    assert m.read_json(tmp_path/'cache/si/chapter.json')['body']=='春'*5+'\n\n'+'冬'*425+'\n\n'+'秋'*70
    assert (directory/'validated-1.json').read_bytes()==sibling


@pytest.mark.parametrize('patch',[
    {'weight':0},{'weight':True},{'weight':-1},{'weight':1.2},{'weight':101},{'budget_reason':''}])
def test_invalid_new_plan_does_not_fall_back_to_legacy_weights(patch):
    p=plan(6);p['scenes'][0].update(patch)
    with pytest.raises(ValueError):module().validate_plan(p)


def test_changed_plan_cannot_reuse_accepted_scene_files(tmp_path,monkeypatch,capsys):
    m=module();directory,_,_=prepared(m,tmp_path,monkeypatch,capsys)
    m.save_json(directory/'validated-1.json',{'body':'已接受场景'})
    old=(directory/'validated-1.json').read_bytes()
    changed=plan();changed['scenes'][0]['turn']='不同的事件'
    m.save_json(directory/'plan.json',changed)
    with pytest.raises(ValueError,match='变化|新任务|不同'):
        cli(m,tmp_path,monkeypatch,capsys,'plan')
    assert (directory/'validated-1.json').read_bytes()==old


def test_replanning_legacy_briefs_does_not_partially_publish_a_new_allocation(tmp_path,monkeypatch,capsys):
    m=module();directory=tmp_path/'cache/multi/task-p1'
    legacy=plan(6);legacy.pop('plan_reason')
    for row in legacy['scenes']:row.pop('weight');row.pop('budget_reason')
    m.save_json(directory/'plan.json',legacy)
    m.save_json(directory/'brief-1.json',{'entry':'历史场景卡'})
    before=(directory/'brief-1.json').read_bytes()
    with pytest.raises(ValueError,match='新任务'):
        cli(m,tmp_path,monkeypatch,capsys,'plan')
    assert not (directory/'allocation.json').exists()
    assert (directory/'brief-1.json').read_bytes()==before
    (directory/'scene-1.txt').write_text('春'*75,encoding='utf-8')
    assert 'WF_REJECT' not in cli(m,tmp_path,monkeypatch,capsys,'scene','--scene','1')


def test_assembly_uses_only_active_bound_scenes_and_never_stale_inactive_files(tmp_path,monkeypatch,capsys):
    m=module();directory,a,_=prepared(m,tmp_path,monkeypatch,capsys)
    bodies={1:'春'*5,2:'夏'*425,6:'秋'*70}
    for slot,body in bodies.items():
        (directory/f'scene-{slot}.txt').write_text(body,encoding='utf-8')
        assert 'WF_REJECT' not in cli(m,tmp_path,monkeypatch,capsys,'scene','--scene',str(slot))
    m.save_json(directory/'validated-3.json',{'body':'绝不能混入的旧场景'})
    cli(m,tmp_path,monkeypatch,capsys,'assemble')
    assert m.read_json(tmp_path/'cache/si/chapter.json')['body'].split('\n\n')==list(bodies.values())
    m.save_json(directory/'validated-2.json',{'body':'旧分场下的正文','allocation_sha256':'different'})
    before=(tmp_path/'cache/si/chapter.json').read_bytes()
    with pytest.raises(ValueError,match='分场|分配|不同|绑定'):
        cli(m,tmp_path,monkeypatch,capsys,'assemble')
    assert (tmp_path/'cache/si/chapter.json').read_bytes()==before


def test_inactive_slot_cannot_be_recovered_as_an_extra_story_scene(tmp_path,monkeypatch,capsys):
    m=module();prepared(m,tmp_path,monkeypatch,capsys)
    with pytest.raises(ValueError,match='未启用|不存在|场景'):
        cli(m,tmp_path,monkeypatch,capsys,'reset-scene','--scene','4')


def test_changed_scene_brief_cannot_claim_the_original_allocation_identity(tmp_path,monkeypatch,capsys):
    m=module();directory,_,_=prepared(m,tmp_path,monkeypatch,capsys)
    brief=m.read_json(directory/'brief-1.json');brief['turn']='不同事件';m.save_json(directory/'brief-1.json',brief)
    (directory/'scene-1.txt').write_text('春'*50,encoding='utf-8')
    with pytest.raises(ValueError,match='场景卡|变化|绑定'):
        cli(m,tmp_path,monkeypatch,capsys,'scene','--scene','1')


def test_deleted_allocation_cannot_turn_a_current_plan_into_legacy_mode(tmp_path,monkeypatch,capsys):
    m=module();directory,_,_=prepared(m,tmp_path,monkeypatch,capsys,6)
    (directory/'allocation.json').unlink()
    (directory/'scene-1.txt').write_text('春'*80,encoding='utf-8')
    with pytest.raises(ValueError,match='分配|分场|缺少'):
        cli(m,tmp_path,monkeypatch,capsys,'scene','--scene','1')


def test_skip_guard_refuses_an_active_slot(tmp_path,monkeypatch,capsys):
    m=module();prepared(m,tmp_path,monkeypatch,capsys)
    with pytest.raises(ValueError,match='未启用'):
        cli(m,tmp_path,monkeypatch,capsys,'skip-scene','--scene','1')
    cli(m,tmp_path,monkeypatch,capsys,'skip-scene','--scene','4')


def test_recovering_active_scene_preserves_sibling_and_reference_target(tmp_path,monkeypatch,capsys):
    m=module();directory,a,_=prepared(m,tmp_path,monkeypatch,capsys)
    sibling=directory/'validated-2.json';m.save_json(sibling,{'body':'已接受的邻场'})
    before=sibling.read_bytes();brief=(directory/'brief-1.json').read_bytes()
    (directory/'scene-1.txt').write_text('旧稿',encoding='utf-8')
    cli(m,tmp_path,monkeypatch,capsys,'reset-scene','--scene','1')
    assert sibling.read_bytes()==before and (directory/'brief-1.json').read_bytes()==brief
    assert m.allocation_policy.read_allocation(directory,(500,550))==a


def test_one_scene_small_target_is_not_rejected_by_unused_six_slot_budget(tmp_path,monkeypatch,capsys):
    m=module();monkeypatch.chdir(tmp_path);monkeypatch.setenv('TASK_ID','small')
    monkeypatch.setattr('sys.argv',['multi_scene','prepare','--target','3-5','--pov','third_person'])
    m.main();directory=tmp_path/'cache/multi/small';m.save_json(directory/'plan.json',plan(1))
    monkeypatch.setattr('sys.argv',['multi_scene','plan','--target','3-5','--pov','third_person'])
    m.main();assert m.read_json(directory/'allocation.json')['scenes'][0]['draft_target']==4


@pytest.mark.parametrize('count,assembly_retry,writer_type',[(1,False,'muti'),(3,False,'muti'),
    (6,False,'muti'),(3,True,'muti'),(1,False,'single')])
def test_real_scheduler_runs_only_planned_scenes_with_actual_allocation_clis(tmp_path,monkeypatch,caplog,count,assembly_retry,writer_type):
    import asyncio
    import os
    import shlex
    import subprocess
    import sys
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef,WorkflowTask,WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin,NodeResult,registry
    from src.workflow.nodes.script import _parse_wf_vars,_parse_reject_upstream
    from src.workflow.variable_resolution import resolve_placeholders
    from src.agent import definition as agents
    from src.core import llm_client
    from src.web import novel_plugin
    from langchain_core.messages import AIMessage
    caplog.set_level('ERROR',logger='src.workflow.variable_resolution')
    m=module();plugin=Path(__file__).resolve().parents[1]
    raw=json.loads((plugin/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    wf=WorkflowDef.from_dict(raw);assert not wf.validate()
    calls=[]
    rehearsal_calls=[]
    (tmp_path/'meta').mkdir()
    (tmp_path/'meta/character_profiles.md').write_text(
        '## 阿杏\n- 当前欲望：救下柜台\n## 掌柜\n- 当前欲望：让人能出门\n',encoding='utf-8')
    (tmp_path/'adopted.md').write_text('先给动作，再让人接话',encoding='utf-8')
    service_path=plugin/'resources/script-library/xs2/character_center/character_center.py'
    import importlib.util
    spec=importlib.util.spec_from_file_location('native_rehearsal_test',service_path,
                                                  submodule_search_locations=[str(service_path.parent)])
    service=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,service)
    spec.loader.exec_module(service)
    monkeypatch.setattr(novel_plugin,'script_service',lambda _name:service)
    monkeypatch.setattr(agents,'get_agent_definition',lambda _name:SimpleNamespace(model='test:writer',model_params={}))

    class Model:
        metadata={'determinflow_model_id':'test:writer'}

        async def ainvoke(self,messages):
            packet=json.loads(messages[1].content)
            if 'turns' in packet:
                assert packet['turns'][1]['action']=='把门撑住'
                reply={'question_pileup': [], 'unsupported_commitment': [], 'voice_or_knowledge': []}
            elif 'role' in packet:
                if packet['role']['name']=='阿杏':
                    assert '救下柜台' in str(packet) and '让人能出门' not in str(packet)
                    reply={'speech':'这头我来。','action':'扶住柜台','private_beat':'','wants_reply':False}
                else:
                    assert packet['observable_turns'][0]['speech']=='这头我来。'
                    reply={'speech':'','action':'把门撑住','private_beat':'','wants_reply':False}
            else:
                assert '先给动作，再让人接话' in str(packet)
                reply={'public_start':'门口下着雨','roles':[
                    {'name':'阿杏','knowledge':'柜台淋雨','goal':'把柜台搬开','voice':'开口短'},
                    {'name':'掌柜','knowledge':'门打开了','goal':'守着门口','voice':'话少'}]}
            rehearsal_calls.append(packet)
            return AIMessage(content=json.dumps(reply,ensure_ascii=False),
                usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15})

    monkeypatch.setattr(llm_client,'create_llm',lambda **_kwargs:Model())

    class Agent(BaseNodePlugin):
        node_type='agent'
        async def execute(self,ctx):
            calls.append(ctx.node_def.id)
            directory=tmp_path/ctx.parameter_values['multi_dir']
            if ctx.node_def.id=='agent_nw':
                sequence=plan(count)
                sequence['scenes'][-1]['rehearsal_cast']=['阿杏','掌柜']
                m.save_json(directory/'plan.json',sequence)
            elif ctx.node_def.id in m.WRITERS:
                slot=m.WRITERS.index(ctx.node_def.id)+1
                brief=m.read_json(directory/f'brief-{slot}.json')
                size=20 if assembly_retry and slot==2 and calls.count('agent_dw')==1 else brief['draft_target']
                (directory/f'scene-{slot}.txt').write_text('春夏秋冬梅竹'[slot-1]*size,encoding='utf-8')
            if ctx.node_def.id in {'agent_si','agent_sw'}:
                prompt=await resolve_placeholders(ctx.node_def.first_message,ctx.parameter_values,ctx.definition.variables,str(tmp_path))
                assert '把门撑住' in prompt and '先给动作，再让人接话' in prompt
                assert 'assigned_roles' not in prompt
                if ctx.node_def.id=='agent_sw':
                    m.save_json(tmp_path/'cache/si/chapter.json',{'body':'试演后单写手交稿'})
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type='script'
        async def execute(self,ctx):
            if not ctx.node_def.id.startswith('script_multi_'):return NodeResult(status='completed')
            params=ctx.node_def.node_params
            args=[await resolve_placeholders(x,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for x in params['script_argv']]
            run=subprocess.run([sys.executable,str(plugin/'resources/script-library/xs2/multi_scene/multi_scene.py'),*args],
                cwd=tmp_path,capture_output=True,env={**os.environ,'TASK_ID':ctx.task_id,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},
                creationflags=0x08000000 if sys.platform=='win32' else 0)
            rejection=_parse_reject_upstream(run.stdout.decode('utf-8'))
            if rejection:
                reason,target=rejection
                assert ctx.on_reject_upstream('test',reason,target)['success']
                return NodeResult(status='failed',error=reason)
            return NodeResult(status='completed' if run.returncode==0 else 'failed',outputs=_parse_wf_vars(run.stdout.decode('utf-8')),
                error=run.stderr.decode('utf-8'))
    monkeypatch.setitem(registry._plugins,'agent',Agent);monkeypatch.setitem(registry._plugins,'script',Script)
    engine=WorkflowEngine(SimpleNamespace(sessions={},main_session_id=''))
    async def no_save(*_):pass
    monkeypatch.setattr(engine,'_save_task_state',no_save);monkeypatch.setattr(engine,'_push_wf_task_update',lambda *_:None)
    values={v['key']:v.get('default','') for v in raw['variables']}
    values.update(writer_type=writer_type,preparation_mode='compact',conflict_plan_mode='short_full',chapter_number='0001',
                  target_word_count='500-550',learning_context='adopted.md')
    task=WorkflowTask(task_id='task-scheduler-p1',workflow_id=wf.workflow_id,status='running',parameter_values=values)
    async def run():
        return await engine._execute_plan_segment(definition=wf,task=task,execution_plan=wf.get_execution_plan(),disabled_ids=set(),
            shared_ws=tmp_path,parent_id='test',on_node_started=lambda _:None,needs_approval=False,
            run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    outcome=asyncio.run(run())
    if assembly_retry:
        from src.workflow.failure_policy import activate_scheduled_retry
        assert outcome=='retry_waiting'
        assert task.node_states['script_multi_scene_2'].status=='completed'
        task.node_states['agent_dw']=activate_scheduled_retry(task.node_states['agent_dw'])
        outcome=asyncio.run(run())
        assert calls.count('agent_dw')==2 and calls.count('agent_aw')==calls.count('agent_si')==1
    assert outcome=='completed',json.dumps({'calls':calls,'states':{k:vars(s) for k,s in task.node_states.items() if s.status not in {'completed','skipped'}},'control':task.control_flow_state},ensure_ascii=False,default=str)
    assert len(rehearsal_calls)==4
    owner='agent_sw' if writer_type=='single' else 'agent_si'
    assert task.node_states[f'rehearse_{owner}'].token_usage['test:writer']['total_tokens']==60
    if writer_type=='single':
        assert calls[-1]=='agent_sw' and not set(calls)&set(m.WRITERS)
        assert m.read_json(tmp_path/'cache/si/chapter.json')['body']=='试演后单写手交稿'
        return
    expected=[m.WRITERS[i-1] for i in list(range(1,count))+[6]]
    assert set(calls)&set(m.WRITERS)==set(expected)
    if not assembly_retry:assert calls[-1]=='agent_si'
    for i in range(count,6):assert task.node_states[m.WRITERS[i-1]].status=='skipped'
    result=m.read_json(tmp_path/'cache/si/chapter.json')['body']
    assert len(result.split('\n\n'))==count
