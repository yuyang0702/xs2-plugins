import json
import pytest
from test_composition_plan import prepared
from test_book_contract import put


def test_identical_new_task_reuses_signed_plan_despite_operational_ref_changes(tmp_path):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    state=json.loads((tmp_path/'.novel-project.json').read_text());state['refs']={'polish':{'task_id':'new-native-task'}}
    put(tmp_path,'.novel-project.json',state)
    request=m.prepare(tmp_path,'0002','reuse-task','3500-4000')
    assert request['enabled'] is False and request['reused'] is True
    assert m.effective(tmp_path,'0002','reuse-task')['target_word_count']=='2000-3000'
    assert m.current(tmp_path,'0002')['task_id']=='plan-test'
    put(tmp_path,'story/0002/chapter.md','正文在命中后发生变化。')
    with pytest.raises(ValueError):m.effective(tmp_path,'0002','reuse-task')


@pytest.mark.parametrize('change',['body','reader','chapter_plan','conflict','author','style','scope','model','code'])
def test_dependency_changes_require_fresh_independent_planning(tmp_path,monkeypatch,change):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    assert m.prepare(tmp_path,'0002','before-change','3500-4000')['enabled'] is False
    state=json.loads((tmp_path/'.novel-project.json').read_text())
    if change=='body':put(tmp_path,'story/0002/chapter.md','新正文。')
    elif change=='reader':put(tmp_path,'story/0002/reader_report.json',{'issues':['new']})
    elif change=='chapter_plan':put(tmp_path,'planning/chapters/0002.json',{'intent':'新意图'})
    elif change=='conflict':put(tmp_path,'planning/composition-conflicts/0002.json',{'reason':'new'})
    elif change=='author':state['values']['human_intent']='作者要求新的结构。'
    elif change=='style':put(tmp_path,'meta/style_profile.md','改为有意复沓的声线。')
    elif change=='scope':state['mode']='short'
    elif change=='model':state['analysisModel']='different:model'
    else:monkeypatch.setattr(m,'code_profile',lambda:'new-review-protocol')
    put(tmp_path,'.novel-project.json',state)
    assert m.prepare(tmp_path,'0002','changed-task','3500-4000')['enabled'] is True


def test_tampered_plan_is_not_a_cache_miss_that_can_impersonate_approval(tmp_path):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    put(tmp_path,'planning/length/0002.json',{'minimum':1,'maximum':99999})
    with pytest.raises(ValueError):m.prepare(tmp_path,'0002','tamper-task','3500-4000')


def test_reuse_emitter_rechecks_code_and_prompt_profile_after_a_hit(tmp_path,monkeypatch):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    assert m.prepare(tmp_path,'0002','reuse-task','3500-4000')['reused']
    monkeypatch.setattr(m,'code_profile',lambda:'changed-after-prepare')
    with pytest.raises(ValueError):m.effective(tmp_path,'0002','reuse-task')


def test_reuse_emitter_rechecks_actual_macro_progress_after_a_hit(tmp_path):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    assert m.prepare(tmp_path,'0002','reuse-task','3500-4000')['reused']
    put(tmp_path,'observability/report.json',{'progress':{'accepted_new_characters':999}})
    with pytest.raises(ValueError):m.effective(tmp_path,'0002','reuse-task')


def test_plan_commit_rechecks_the_request_code_profile(tmp_path,monkeypatch):
    m,r,p,v=prepared(tmp_path);monkeypatch.setattr(m,'code_profile',lambda:'changed-during-review')
    with pytest.raises(ValueError):m.accept(tmp_path,'plan-test',p,v)


def test_effective_native_role_changes_invalidate_plan_reuse(tmp_path, monkeypatch):
    m, request, plan, review = prepared(tmp_path)
    m.accept(tmp_path, 'plan-test', plan, review)
    assert m.prepare(tmp_path, '0002', 'same-role', '3500-4000')['reused']
    monkeypatch.setattr(m, 'runtime_profile', lambda root: 'changed-native-role-parameters')
    assert m.prepare(tmp_path, '0002', 'changed-role', '3500-4000')['enabled']
