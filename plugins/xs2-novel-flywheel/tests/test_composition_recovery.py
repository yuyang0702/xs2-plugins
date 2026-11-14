import json
import copy
import io
import sys
import pytest
from test_local_revision import setup
from test_book_contract import put
from test_length_quality import policy
from test_composition_plan import prepared


def test_native_composition_keeps_full_binding_after_short_model_refs(tmp_path,monkeypatch,capsys):
    m,request,plan,review=prepared(tmp_path)
    base='cache/composition/plan-test'
    view=m.model_packet.composition(request)
    put(tmp_path,base+'/request-model.json',view)
    raw_plan={**plan,'request_digest':view['request_digest']}
    put(tmp_path,base+'/plan.json',raw_plan)
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('TASK_ID','plan-test')
    monkeypatch.setattr(sys,'argv',['composition_plan.py','candidate','--dir',base])
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(raw_plan,ensure_ascii=False)))
    m.main();assert 'WF_REJECT' not in capsys.readouterr().out
    model=m.support.load(tmp_path,base+'/review-model.json')
    raw_review={**review,'request_digest':model['request_digest'],'plan_digest':model['plan_digest']}
    put(tmp_path,base+'/review.json',raw_review)
    monkeypatch.setattr(sys,'argv',['composition_plan.py','commit','--dir',base])
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(raw_review,ensure_ascii=False)))
    m.main();assert 'WF_REJECT' not in capsys.readouterr().out
    approved=m.current(tmp_path,'0002')
    assert approved['plan']==plan and approved['review']==review
    assert m.support.load(tmp_path,base+'/plan.json')==raw_plan
    assert m.support.load(tmp_path,base+'/review.json')==raw_review


@pytest.mark.parametrize('source_changed',[False,True])
def test_legacy_refresh_stop_can_seed_one_fresh_independent_review(tmp_path,monkeypatch,source_changed):
    root=tmp_path/'book';m,request,plan,review=prepared(root)
    host=tmp_path/'host';(host/'src').mkdir(parents=True)
    monkeypatch.setenv('DETERMINFLOW_PROJECT_DIR',str(host))
    old_review={**review,'verdict':'revise'}
    plan['reason']='把预算压回现稿，只修改原对话。'
    base='cache/composition/plan-test'
    packet={'request':request,'plan':plan,'request_digest':request['request_digest'],'plan_digest':m.identity(plan)}
    put(root,base+'/plan.json',plan);put(root,base+'/review.json',old_review)
    put(root,base+'/review-input.json',packet);put(root,base+'/review-model.json',m.model_packet.composition(packet))
    ref={'task_id':'plan-test','workflow_id':'native-polish'}
    task={**ref,'status':'failed','workspace_override':str(root),'parameter_values':{'chapter_number':'0002'},'node_states':{
        'agent_composition_plan':{'status':'completed','outputs':{'composition_plan_result':json.dumps(plan)}},
        'agent_composition_review':{'status':'completed','outputs':{'composition_review_result':json.dumps(old_review)}},
        'script_composition_commit':{'status':'failed','error':'RETRY_STOP: content：方案变化，已重建输入，请复查当前方案。'}}}
    put(host,'data/workflows/native-polish/tasks/plan-test.json',task)
    state=m.support.load(root,'.novel-project.json');state.update(stageId='polish',autoArmed=True,readerRepairCount=1,refs={'polish':ref})
    put(root,'.novel-project.json',state)
    p=policy()
    if source_changed:
        put(root,'story/0002/chapter.md','作者已更新。')
        with pytest.raises(ValueError,match='已有变化'):p.recovery_action(state,'polish',task,root=root)
        return
    action=p.recovery_action(state,'polish',task,root=root)
    assert action['stage']=='polish' and action['action']=='advance'
    state.update(action['updates']);put(root,'.novel-project.json',state)
    new=m.prepare(root,'0002','fresh-task','3500-4000')
    assert new['current_prose_count']==9
    assert new['prior_unreviewed_plan']['plan']['reason']==plan['reason']
    assert 'request_digest' not in new['prior_unreviewed_plan']['plan']
    assert new['request_digest']!=request['request_digest']
    assert p.recovery_action(state,'polish',task,root=root) is None
    assert not (root/'planning/length/0002.json').exists()


@pytest.mark.parametrize('source_changed',[False,True])
def test_changed_plan_with_invalid_goal_links_returns_to_planner_without_approval(tmp_path,monkeypatch,capsys,source_changed):
    m,request,plan,review=prepared(tmp_path)
    request['book_contract']['reading_contract']={'objectives':[{'id':'goal-1'}]}
    plan['goal_plans']=[{'goal_id':'goal-1','status':'planned','basis':'本书明确选择的阅读作用',
        'segment_ids':['quiet'],'reader_start':'尚未愿意等','reader_end':'愿意等'}]
    base='cache/composition/plan-test'
    put(tmp_path,base+'/request.json',request)
    put(tmp_path,base+'/review-input.json',{'request':request,'plan':copy.deepcopy(plan),
        'request_digest':request['request_digest'],'plan_digest':m.identity(plan)})
    put(tmp_path,base+'/review-model.json',m.model_packet.composition({'request':request,'plan':copy.deepcopy(plan),
        'request_digest':request['request_digest'],'plan_digest':m.identity(plan)}))
    plan['segments'][0]['id']='id_tmp'
    put(tmp_path,base+'/plan.json',plan)
    put(tmp_path,base+'/review.json',review)
    original=(tmp_path/base/'plan.json').read_bytes()
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('TASK_ID','plan-test')
    monkeypatch.setattr(sys,'argv',['composition_plan.py','commit','--dir',base])
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(review,ensure_ascii=False)))
    if source_changed:
        put(tmp_path,'meta/style_profile.md','作者已更新本书声线。')
        with pytest.raises(ValueError):m.main()
        assert '<WF_REJECT_UPSTREAM' not in capsys.readouterr().out
    else:
        m.main()
        assert '<WF_REJECT_UPSTREAM target="agent_composition_plan">' in capsys.readouterr().out
        assert '阅读目标' in (tmp_path/base/'feedback.md').read_text(encoding='utf-8')
    assert not (tmp_path/'planning/length/0002.json').exists()
    assert (tmp_path/base/'plan.json').read_bytes()==original


@pytest.mark.parametrize('ownership',['author','planner'])
@pytest.mark.parametrize('exhausted',[False,True])
def test_native_conflict_returns_to_planning_only_with_book_authority(tmp_path,ownership,exhausted):
    m,_=setup(tmp_path);put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':ownership})
    out=m.prepare(tmp_path,'0001','conflict-task','1-5000');m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    payload={'source_sha256':source['source_sha256'],'edits':[],'status':'needs_replan','reason':'需要重排阅读作用与预算。','evidence':['第一段保留。']}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.CompositionConflict):m.candidate(tmp_path,out['revision_dir'])
    task={'task_id':'conflict-task','status':'failed','parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False)},
        'node_states':{'agent_pl':{'status':'completed'},'script_local_candidate':{'status':'failed'}}}
    state={'values':{'chapter_number':'0001','author_feedback_file':'feedback.md'},'readerRepairCount':1}
    if exhausted:state['compositionReplans']={'0001':['previous-1','previous-2']}
    p=policy();action=p.recovery_action(state,'polish',task,root=tmp_path)
    if exhausted:
        assert action is None
        assert state['compositionReplans']=={'0001':['previous-1','previous-2']}
        diagnostic=json.loads((tmp_path/'planning/composition-conflicts/0001.json').read_text())
        assert diagnostic['task_id']=='conflict-task'
        return
    assert action
    assert action['action']=='advance' and action['stage']=='polish'
    state.update(action['updates']);assert state['readerRepairCount']==1
    assert p.recovery_action(state,'polish',task,root=tmp_path) is None
    assert (tmp_path/'planning/composition-conflicts/0001.json').exists()
    assert json.loads((tmp_path/'meta/length_policy.json').read_text())['ownership']==ownership
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8-sig').startswith('第一段保留。')
