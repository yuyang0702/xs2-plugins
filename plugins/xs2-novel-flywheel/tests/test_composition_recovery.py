import json
import copy
import io
import sys
import pytest
from test_local_revision import setup
from test_book_contract import put
from test_length_quality import policy
from test_composition_plan import prepared


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
