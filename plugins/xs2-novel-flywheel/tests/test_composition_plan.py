import copy
import importlib.util
import json
from pathlib import Path
import shutil
import pytest
from test_book_contract import PLUGIN,put


def module():
    p=PLUGIN/'resources/script-library/xs2/composition_plan/composition_plan.py'
    spec=importlib.util.spec_from_file_location('test_composition',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def prepared(root,ownership='planner'):
    m=module();put(root,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'3500-4000'}})
    put(root,'meta/length_policy.json',{'schema':1,'ownership':ownership})
    put(root,'meta/style_profile.md','可以铺陈、议论、静景，也可以紧凑叙事，按本书目的判断。')
    put(root,'story/0002/chapter.md','已有的选择。重复解释。')
    req=m.prepare(root,'0002','plan-test','3500-4000')
    plan={'request_digest':req['request_digest'],'status':'ready','reason':'先完成这次有限选择，后续章节承担后续工作。',
          'segments':[{'id':'quiet','purpose':'让犹疑转为愿意等待','development':'等待从被迫变成共同选择',
                       'minimum':2000,'maximum':3000}], 'minimum':2000,'maximum':3000}
    review={'request_digest':req['request_digest'],'plan_digest':m.identity(plan),'verdict':'approve',
        'scope_preserved':True,'length_feasible':True,'reason':'承载人物和声线作用，不要求新增事件。',
        'checks':[{'segment_id':'quiet','develops_function':True,'style_basis':'本书允许静景与议论','reason':'人物关系的作用不同于复述既有判断。'}]}
    return m,req,plan,review


def test_default_author_range_is_not_automatically_reduced(tmp_path):
    m,r,p,v=prepared(tmp_path,'author')
    with pytest.raises(ValueError,match='作者|篇幅'):m.accept(tmp_path,'plan-test',p,v)
    assert not (tmp_path/'planning/length/0002.json').exists()


@pytest.mark.parametrize('mode,fields,expected',[
    ('short',{'autoChapterLimit':1,'autoChapterStarted':None},1),
    ('short',{'autoChapterLimit':None,'autoChapterStarted':None},9999),
    ('short',{},9999),
    ('serial',{'autoChapterLimit':6,'autoChapterStarted':3},4),
    ('serial',{'autoChapterLimit':'6','autoChapterStarted':'3'},4),
    ('serial',{'autoChapterLimit':2,'autoChapterStarted':3},0),
])
def test_new_book_nullable_run_cursor_preserves_macro_budget_and_author_range(tmp_path,mode,fields,expected):
    m=module()
    put(tmp_path,'.novel-project.json',{'mode':mode,**fields,
        'values':{'chapter_number':'0001','target_word_count':'9600-12000'}})
    put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'author'})
    request=m.prepare(tmp_path,'0001','nullable-cursor','9600-12000')
    assert request['macro_guard']['slots']==expected
    assert request['macro_budget']['remaining_chapter_slots']==expected
    assert request['author_range']==[9600,12000]


def test_installed_resource_layout_prepares_same_hard_range_and_detects_profile_changes(tmp_path):
    prepared=tmp_path/'prepared'
    scripts=prepared/'script-libraries/0/xs2-novel-flywheel-xs2'
    shutil.copytree(PLUGIN/'resources/script-library/xs2',scripts,
        ignore=shutil.ignore_patterns('__pycache__','*.pyc','vendor'))
    config_paths={
        'agents.json':prepared/'json/agents/0.json',
        'prompts.json':prepared/'json/prompts/0.json',
        'workflows/mvp/definition.json':prepared/'workflows/0/xs2-novel-flywheel-mvp/definition.json',
        'workflows/polish/definition.json':prepared/'workflows/0/xs2-novel-flywheel-polish/definition.json',
    }
    for source,target in config_paths.items():
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((PLUGIN/'resources'/source).read_bytes())
    spec=importlib.util.spec_from_file_location('installed_composition',scripts/'composition_plan/composition_plan.py')
    installed=importlib.util.module_from_spec(spec);spec.loader.exec_module(installed)
    assert installed.code_profile()==module().code_profile()
    root=tmp_path/'book'
    put(root,'.novel-project.json',{'mode':'short','autoChapterStarted':None,'autoChapterLimit':1,
        'values':{'chapter_number':'0001','target_word_count':'9600-12000'}})
    put(root,'meta/length_policy.json',{'schema':1,'ownership':'author'})
    request=installed.prepare(root,'0001','installed-check','9600-12000')
    assert request['author_range']==[9600,12000]
    assert request['macro_budget']['remaining_chapter_slots']==1
    before=installed.code_profile()
    target=config_paths['prompts.json'];target.write_text(target.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    assert installed.code_profile()!=before
    target.unlink()
    with pytest.raises(FileNotFoundError):installed.code_profile()


@pytest.mark.parametrize('function',['情绪转变','氛围发展','关系变化','语言与形式探索','事件推进'])
def test_planner_allocation_can_change_without_prescribing_literary_function(tmp_path,function):
    m,r,p,v=prepared(tmp_path);p['segments'][0]['purpose']=function;v['plan_digest']=m.identity(p)
    m.accept(tmp_path,'plan-test',p,v)
    assert m.current(tmp_path,'0002')['minimum']==2000
    # Planned prose is expected to change; a quota is not archived history.
    put(tmp_path,'story/0002/chapter.md','修订后有真实阅读作用的正文。')
    assert m.current(tmp_path,'0002')['maximum']==3000
    put(tmp_path,'meta/style_profile.md','作者改变了本书声线。')
    with pytest.raises(ValueError,match='来源|规则|契约|变化'):m.current(tmp_path,'0002')


@pytest.mark.parametrize('change',['source','review','sum','function','policy','unsigned'])
def test_pending_plans_fail_closed_on_source_or_review_defects(tmp_path,change):
    m,r,p,v=prepared(tmp_path)
    if change=='source':put(tmp_path,'story/0002/chapter.md','作者更新。')
    elif change=='review':v['plan_digest']='old'
    elif change=='sum':p['minimum']=1900;v['plan_digest']=m.identity(p)
    elif change=='function':v['checks'][0]['develops_function']=False
    elif change=='policy':put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'author'})
    elif change=='unsigned':
        put(tmp_path,'planning/length/0002.json',{'minimum':1,'maximum':9999})
        with pytest.raises(ValueError):m.current(tmp_path,'0002')
        return
    with pytest.raises(ValueError):m.accept(tmp_path,'plan-test',p,v)
    assert not (tmp_path/'planning/length/0002.json').exists()


def test_explicit_hard_envelope_limits_planner_and_preserves_author_feedback(tmp_path):
    m,r,p,v=prepared(tmp_path)
    put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'planner','minimum':3200,'maximum':5000})
    put(tmp_path,'author.md','保留长段心理，不要改成动作清单。')
    put(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'3500-4000','author_feedback_file':'author.md'}})
    r=m.prepare(tmp_path,'0002','hard','3500-4000');p['request_digest']=r['request_digest'];v.update(request_digest=r['request_digest'],plan_digest=m.identity(p))
    assert '保留长段心理' in r['author_feedback']
    with pytest.raises(ValueError):m.accept(tmp_path,'hard',p,v)


def test_all_length_gates_share_signed_effective_quota_but_explicit_override_stays_hard(tmp_path):
    from test_length_quality import quality
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    q=quality()
    assert q.resolve_target(tmp_path,'3500-4000')==(2000,3000)
    assert q.resolve_target(tmp_path,'6000-7000')==(6000,7000)
    put(tmp_path,'planning/length/0002.json',{'minimum':1,'maximum':9999})
    with pytest.raises(ValueError):q.resolve_target(tmp_path,'3500-4000')


def test_scene_writers_receive_approved_reading_functions_as_intent(tmp_path):
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    path=PLUGIN/'resources/script-library/xs2/multi_scene/multi_scene.py'
    spec=importlib.util.spec_from_file_location('composition_scene_sources',path);scenes=importlib.util.module_from_spec(spec);spec.loader.exec_module(scenes)
    text=scenes.planning_sources(tmp_path,'0002')
    assert '让犹疑转为愿意等待' in text and '不是已发生事实' in text


def test_changed_selected_target_during_planning_cannot_publish_old_allocation(tmp_path):
    m,r,p,v=prepared(tmp_path)
    put(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'6000-7000'}})
    with pytest.raises(ValueError):m.accept(tmp_path,'plan-test',p,v)
    assert not (tmp_path/'planning/length/0002.json').exists()


def test_changed_author_target_invalidates_an_already_published_budget(tmp_path):
    from test_length_quality import quality
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    put(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'6000-7000'}})
    with pytest.raises(ValueError):quality().resolve_target(tmp_path,'6000-7000')


def test_planning_also_separates_automatic_advice_from_author_requirements(tmp_path):
    m,r,p,v=prepared(tmp_path)
    put(tmp_path,'author.md','保留长段心理。');text=(tmp_path/'author.md').read_text()
    put(tmp_path,'auto/instructions.md','自动旧配额：一定补到四千字。')
    put(tmp_path,'auto/automatic-origin.json',{'origin':'automatic','feedback_sha256':m.support.digest(tmp_path,'auto/instructions.md'),
        'retained_feedback_sources':[{'source_id':'author.md','sha256':m.support.digest(tmp_path,'author.md'),'text':text}]})
    put(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'3500-4000','author_feedback_file':'auto/instructions.md'}})
    req=m.prepare(tmp_path,'0002','layered','3500-4000')
    assert req['author_feedback']==text
    assert '自动旧配额' in req['automatic_revision_advice']


def test_author_edited_automatic_wrapper_is_frozen_as_an_author_source(tmp_path):
    m,r,p,v=prepared(tmp_path)
    put(tmp_path,'edited/instructions.md','旧的自动稿。')
    old=m.support.digest(tmp_path,'edited/instructions.md')
    put(tmp_path,'edited/automatic-origin.json',{'origin':'automatic','feedback_sha256':old,'retained_feedback_sources':[]})
    put(tmp_path,'edited/instructions.md','作者手动修改：保留议论。')
    put(tmp_path,'.novel-project.json',{'values':{'chapter_number':'0002','target_word_count':'3500-4000','author_feedback_file':'edited/instructions.md'}})
    req=m.prepare(tmp_path,'0002','edited','3500-4000');p['request_digest']=req['request_digest']
    v.update(request_digest=req['request_digest'],plan_digest=m.identity(p));m.accept(tmp_path,'edited',p,v)
    put(tmp_path,'edited/instructions.md','作者再次修改：保留回环。')
    with pytest.raises(ValueError):m.current(tmp_path,'0002')


def test_book_workflow_choice_can_enable_planning_without_changing_hard_envelope(tmp_path):
    m,r,p,v=prepared(tmp_path,'author')
    put(tmp_path,'meta/length_policy.json',{'schema':1,'ownership':'author','minimum':2500,'maximum':5000})
    req=m.prepare(tmp_path,'0002','chosen','3500-4000',ownership='按内容规划')
    assert req['policy']['ownership']=='planner' and req['policy']['minimum']==2500


def test_writer_system_roles_allow_the_structured_replan_exit():
    prompts=json.loads((PLUGIN/'resources/prompts.json').read_text(encoding='utf-8-sig'))
    for key in ('xs2-local-revision-writer','xs2-draft-repairer'):
        text='\n'.join(s['content'] for s in prompts['agents'][key]['sections'])
        assert 'needs_replan' in text
    definition=json.loads((PLUGIN/'resources/workflows/mvp/definition.json').read_text(encoding='utf-8-sig'))
    node=next(n for n in definition['nodes'] if n['id']=='agent_guard_expression_repair')
    assert '金额parts/change' not in node['first_message']


def test_reader_model_receives_effective_budget_without_changing_nominal_author_state(tmp_path):
    from test_length_quality import policy
    m,r,p,v=prepared(tmp_path);m.accept(tmp_path,'plan-test',p,v)
    state=json.loads((tmp_path/'.novel-project.json').read_text())
    production=policy();production.launch_check(tmp_path,state,'reader-sim')
    variables=[{'key':'target_word_count','type':'text','source_type':'input','default':'3500-4000'}]
    assert production.parameters(state,{'workflow_id':'reader-sim','variables':variables})['target_word_count']=='2000-3000'
    assert state['values']['target_word_count']=='3500-4000'
    assert production.parameters(state,{'workflow_id':'mvp','variables':variables})['target_word_count']=='3500-4000'


@pytest.mark.parametrize('workflow',['mvp','polish'])
def test_composition_emitter_is_a_shared_convergence_outside_both_branches(workflow):
    from src.workflow.definition import WorkflowDef
    raw=json.loads((PLUGIN/f'resources/workflows/{workflow}/definition.json').read_text(encoding='utf-8-sig'))
    definition=WorkflowDef.from_dict(raw)
    gateway=next(s for s in definition.get_execution_plan() if s.get('gateway_id')=='gw_composition_enabled')
    assert gateway['convergence_node_id']=='script_composition_ready'
    assert all(b['target']!='script_composition_ready' for b in gateway['branches'])


@pytest.mark.parametrize('newline',['','\r\n'])
@pytest.mark.parametrize('references',[False,True])
def test_replanning_keeps_source_bound_unaccepted_diagnostics_for_the_next_revision(tmp_path,newline,references):
    import hashlib
    from test_local_revision import module as revision_module
    m,_,p,v=prepared(tmp_path)
    candidate='已有的选择。'+newline+'重复解释。'
    (tmp_path/'story/0002/chapter.md').write_bytes(candidate.encode())
    report={'compatible':True,'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
        'book_contract_sha256':m.book.digest(m.book.resolve(tmp_path)),
        'expression_review':{'issues':[{'id':'repeat','priority':'medium','goal':'让后句承担新的关系变化。',
            'excerpts':[{'ref_id':'p0001'}] if references else ['重复解释。']}]}}
    put(tmp_path,'planning/composition-conflicts/0002.json',{'task_id':'previous-task',
        'source_sha256':m.support.digest(tmp_path,'story/0002/chapter.md'),'rejected_candidate':candidate,'review_report':report})
    request=m.prepare(tmp_path,'0002','next-plan','3500-4000');p['request_digest']=request['request_digest']
    v.update(request_digest=request['request_digest'],plan_digest=m.identity(p));m.accept(tmp_path,'next-plan',p,v)
    revision=revision_module();out=revision.prepare(tmp_path,'0002','next-writer','3500-4000')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    assert source['prior_revision']['candidate']==candidate
    goals=revision.goals(source,{'issues':[]})
    assert any(g['goal']=='让后句承担新的关系变化。' and g['excerpts'] for g in goals)
    # Author prose edits can retain a quota, but never silently reuse an old draft.
    put(tmp_path,'story/0002/chapter.md','作者重新选择了表达。')
    out=revision.prepare(tmp_path,'0002','after-author-edit','3500-4000')
    changed=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    assert changed['prior_revision'] is None
    assert 'prior_revision' not in changed['composition_plan']


def test_medium_critic_findings_remain_explicit_revision_goals():
    from test_local_revision import module as revision_module
    rows=revision_module().goals({}, {'issues':[{'severity':'medium','suggestion':'压缩同义确认。','evidence':['原句。']}],
        'blocking_issues':[]})
    assert rows==[{'id':'critic-0','goal':'压缩同义确认。','excerpts':['原句。']}]
