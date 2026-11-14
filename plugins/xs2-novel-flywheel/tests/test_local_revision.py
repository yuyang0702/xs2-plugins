import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from test_book_contract import put,PLUGIN
from test_expression_evidence import checks

BODY='\ufeff第一段保留。\r\n\r\n第二段重复说明。\r\n\r\n潮水会回来。\r\n'


def module():
    p=PLUGIN/'resources/script-library/xs2/local_revision/local_revision.py'
    s=importlib.util.spec_from_file_location('local_revision_tests',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def setup(root):
    m=module();put(root,'.novel-project.json',{'values':{'narrator_scope':'omniscient','author_feedback_file':'feedback.md'}})
    put(root,'feedback.md','保留全知和回环，仅合并无作用说明。')
    put(root,'meta/narrative_contract.json',{'schema':1,'protected_phrases':['潮水会回来。']})
    p=root/'story/0001/chapter.md';p.parent.mkdir(parents=True);p.write_bytes(BODY.encode())
    out=m.prepare(root,'0001','local-test','1-5000')
    put(root,'cache/sc/critique.json',{'feels_human':True,'issues':[]})
    m.writer_input(root,out['revision_dir'],'cache/sc/critique.json')
    return m,out


def patch(m,out,root,replacement='第二段简明。'):
    source=json.loads((root/out['revision_input']).read_text(encoding='utf-8'))
    edit={'paragraph_id':source['paragraphs'][1]['id'],'old':'第二段重复说明。','occurrence':1,'replacement':replacement}
    data={'source_sha256':source['source_sha256'],'edits':[edit]}
    put(root,out['revision_patch_path'],data);return data


def approved(m,out,root):
    context=json.loads((root/out['revision_review_input']).read_text(encoding='utf-8'))
    report={'candidate_sha256':context['candidate_sha256'],'book_contract_sha256':context['book_contract_sha256'],
        'review_input_sha256':context['review_input_sha256'],'compatible':True,'issues':[],
        'expression_review':{'verdict':'pass','summary':'含义未重复，风格保留。','issues':[]},
        'expression_checks':checks(m.expression),'issue_outcomes':[],
        'change_reviews':[{'edit_index':i,'effect':'improved','before_excerpt':e['old'],
            'after_excerpt':e['replacement'],'reason':'合并无增量的说明，保留全知声线。'} for i,e in enumerate(context['edits'])]}
    for c in report['expression_checks']:c['excerpts']=['第一段保留。']
    put(root,out['revision_review_path'],report);return json.dumps(report,ensure_ascii=False)


def test_exact_local_publication_keeps_untouched_bytes_and_recovers_after_publication(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    expected=approved(m,out,tmp_path);m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.replace('第二段重复说明。','第二段简明。').encode()
    m.commit(tmp_path,out['revision_dir'],expected)


@pytest.mark.parametrize('kind',['body','feedback','book','patch','review'])
def test_changed_inputs_or_old_audit_cannot_publish(tmp_path,kind):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    original=(tmp_path/'story/0001/chapter.md').read_bytes()
    if kind=='body':(tmp_path/'story/0001/chapter.md').write_bytes(original+'作者新改。'.encode())
    elif kind=='feedback':put(tmp_path,'feedback.md','作者已换意见。')
    elif kind=='book':put(tmp_path,'meta/world_foundation.md','本书规则已经变化。')
    elif kind=='patch':patch(m,out,tmp_path,'未经这份报告复查的新句。')
    else:
        report=json.loads(expected);report['candidate_sha256']='old';put(tmp_path,out['revision_review_path'],report);expected=json.dumps(report,ensure_ascii=False)
    current=(tmp_path/'story/0001/chapter.md').read_bytes()
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==current


def test_empty_edits_are_valid_and_protected_phrase_loss_is_rejected(tmp_path):
    m,out=setup(tmp_path)
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[]})
    m.candidate(tmp_path,out['revision_dir']);m.commit(tmp_path,out['revision_dir'],approved(m,out,tmp_path))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[
        {'paragraph_id':source['paragraphs'][2]['id'],'old':'潮水会回来。','occurrence':1,'replacement':''}]})
    with pytest.raises(ValueError,match='保留'):m.candidate(tmp_path,out['revision_dir'])


def test_fact_pass_cannot_hide_expression_blocker_or_unhelpful_patch(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['change_reviews'][0]['effect']='regressed'
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_candidate_rejects_length_before_expensive_review(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'乙'*5001)
    with pytest.raises(m.Retry) as error:m.candidate(tmp_path,out['revision_dir'])
    assert error.value.target=='agent_pl'
    assert not (tmp_path/out['revision_review_input']).exists()


@pytest.mark.parametrize('kind',['critic','editor'])
def test_changed_editor_evidence_cannot_reuse_a_review(tmp_path,kind):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    if kind=='critic':put(tmp_path,'cache/sc/critique.json',{'issues':[],'new':'other review'})
    else:
        data=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'));data['author_feedback']='new'
        put(tmp_path,out['revision_input'],data)
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_fact_pass_cannot_hide_medium_expression_issue(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['expression_review']={'verdict':'revise','summary':'仍有解释性复述','issues':[
        {'id':'repeat-1','category':'semantic_redundancy','location':'中段','priority':'medium',
         'excerpts':['第二段简明。'],'impact':'再次说明相同结论。','goal':'合并重复结论。'}]}
    report['expression_checks'][0].update(status='issue',issue_ids=['repeat-1'],excerpts=['第二段简明。'])
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as error:m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert error.value.target=='agent_pl'
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_partial_deletion_quotes_the_nonempty_replacement_not_an_empty_after(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'第二段。');m.candidate(tmp_path,out['revision_dir']);report=json.loads(approved(m,out,tmp_path))
    report['change_reviews'][0].update(before_excerpt='重复说明。',after_excerpt='')
    put(tmp_path,out['revision_review_path'],report)
    with pytest.raises(m.Retry) as error:m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert error.value.target=='agent_local_review'
    report['change_reviews'][0]['after_excerpt']='第二段。';put(tmp_path,out['revision_review_path'],report)
    m.commit(tmp_path,out['revision_dir'],json.dumps(report,ensure_ascii=False))
    assert '第二段重复说明。'.encode() not in (tmp_path/'story/0001/chapter.md').read_bytes()


def test_writer_retry_receives_actual_rejected_edits_without_rebasing_source(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path,'上一轮未通过的新句。');m.candidate(tmp_path,out['revision_dir'])
    before=(tmp_path/out['revision_input']).read_bytes()
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],m.Retry('agent_pl','新句仍重复原结论。'))
    assert '上一轮未通过的新句。' in feedback and '第二段重复说明。' in feedback
    assert '未通过补丁' in feedback and '冻结原文' in feedback
    assert (tmp_path/out['revision_input']).read_bytes()==before
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    reviewer=m.retry_feedback(tmp_path,out['revision_dir'],m.Retry('agent_local_review','引文无效。'))
    assert '上一轮未通过的新句。' not in reviewer


def test_crash_after_atomic_publication_recovers_without_rewriting(tmp_path,monkeypatch):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir']);expected=approved(m,out,tmp_path)
    real_save=m.save
    def interrupted(path,data):
        if path.name=='receipt.json':raise OSError('simulated shutdown after replace')
        return real_save(path,data)
    monkeypatch.setattr(m,'save',interrupted)
    with pytest.raises(OSError):m.commit(tmp_path,out['revision_dir'],expected)
    published=(tmp_path/'story/0001/chapter.md').read_bytes()
    assert published!=BODY.encode()
    monkeypatch.setattr(m,'save',real_save);m.commit(tmp_path,out['revision_dir'],expected)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==published


def test_optional_unconfigured_length_does_not_block_content_revision(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','正文保留。')
    out=m.prepare(tmp_path,'0001','no-target')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    assert source['length']['status']=='unconfigured'
    put(tmp_path,'cache/sc/critique.json',{'issues':[]});m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[]})
    m.candidate(tmp_path,out['revision_dir'])


def test_short_candidate_retry_retains_latest_patch_before_review_input_exists(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','甲'*100)
    out=m.prepare(tmp_path,'0001','short-patch','150-200')
    put(tmp_path,'cache/sc/critique.json',{'issues':[]});m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    assert source['length_edit_budget']['source_word_count']==100
    assert source['length_edit_budget']['net_change_minimum']==50
    payload={'source_sha256':source['source_sha256'],'edits':[{
        'paragraph_id':'p0001','old':'甲','occurrence':1,'replacement':'甲'*50}]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry) as failure:m.candidate(tmp_path,out['revision_dir'])
    assert not (tmp_path/out['revision_review_input']).exists()
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],failure.value)
    assert '"net_change_minimum": 50' in feedback and 'rejected_edits' in feedback and '不累计' in feedback
    (tmp_path/out['revision_patch_path']).unlink()
    snapshot=json.loads((tmp_path/out['revision_dir']/'last-rejected-patch.json').read_text(encoding='utf-8'))
    assert snapshot['rejected_edits']==payload['edits'] and snapshot['candidate_length']['actual']==149
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')=='甲'*100


def test_malformed_patch_still_returns_writer_retry_feedback(tmp_path):
    m,out=setup(tmp_path)
    (tmp_path/out['revision_patch_path']).write_text('{"edits":',encoding='utf-8')
    with pytest.raises(m.Retry) as failure:m.candidate(tmp_path,out['revision_dir'])
    feedback=m.retry_feedback(tmp_path,out['revision_dir'],failure.value)
    assert '冻结原文' in feedback and 'source_word_count' in feedback
    assert not (tmp_path/out['revision_dir']/'last-rejected-patch.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_structured_scope_conflict_never_publishes_or_retries_same_writer(tmp_path):
    m,out=setup(tmp_path);source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf-8'))
    payload={'source_sha256':source['source_sha256'],'edits':[],'status':'needs_replan',
        'reason':'在当前范围内压缩复述后不足，不能用同义动作补足。','evidence':['第二段重复说明。']}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.CompositionConflict):m.candidate(tmp_path,out['revision_dir'])
    task={'task_id':'local-test','status':'failed','parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False)},
        'node_states':{'agent_pl':{'status':'completed'},'script_local_candidate':{'status':'failed'}}}
    assert m.verify_conflict(tmp_path,task)['kind']=='content_length_conflict'
    assert not (tmp_path/out['revision_review_input']).exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    task['parameter_values']['revision_patch_result']='{}'
    with pytest.raises(ValueError):m.verify_conflict(tmp_path,task)


def test_repeated_short_content_repair_keeps_length_gate_without_invented_scope_conflict(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','甲'*200)
    put(tmp_path,'story/0001/reader_report.json',{'body_sha256':m.sha(('甲'*200).encode()),
        'issues':[{'id':'repeat','priority':'medium','goal':'合并复述','excerpts':['甲甲']} ]})
    out=m.prepare(tmp_path,'0001','short-content','180-220');put(tmp_path,'cache/sc/critique.json',{'issues':[]})
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    for count in (101,102):
        payload={'source_sha256':m.sha(('甲'*200).encode()),'edits':[{'paragraph_id':'p0001','old':'甲'*200,'occurrence':1,'replacement':'乙'*count}]}
        put(tmp_path,out['revision_patch_path'],payload)
        with pytest.raises(m.Retry):m.candidate(tmp_path,out['revision_dir'])
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_text(encoding='utf-8')=='甲'*200


def test_complete_reader_report_stays_bound_to_independent_review(tmp_path):
    m,_=setup(tmp_path)
    report={'body_sha256':m.sha(BODY.encode()),'verdict':'pass','issues':[],
            'blind_review':{'summary':'整篇报告原文'},'expression_checks':[{'detail':'复核检查明细'}]}
    put(tmp_path,'story/0001/reader_report.json',report)
    out=m.prepare(tmp_path,'0001','focused-review','1-5000')
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf-8'))
    review=json.loads((tmp_path/out['revision_review_model']).read_text(encoding='utf-8'))
    assert 'reader_report' not in writer and review['reader_report']==report
    assert 'critique' not in writer and review['critique']=={'feels_human':True,'issues':[]}
    assert m.packet.restore(review['source_body'],review['candidate'])==BODY
    assert 'same_as_candidate' in review['source_body']['paragraphs'][0]
    review['reader_report']['blind_review']['summary']='篡改的报告'
    put(tmp_path,out['revision_review_model'],review)
    with pytest.raises(ValueError,match='模型所见输入'):
        m.commit(tmp_path,out['revision_dir'],approved(m,out,tmp_path))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_automatic_advice_is_not_promoted_above_original_author_requirements(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原正文。')
    put(tmp_path,'author.md','保留心理和抒情，不增加无关动作。')
    put(tmp_path,'auto/instructions.md','旧自动建议：用更多操作补到四千字。')
    original=(tmp_path/'author.md').read_text(encoding='utf-8')
    put(tmp_path,'auto/automatic-origin.json',{'origin':'automatic','feedback_sha256':m.sha((tmp_path/'auto/instructions.md').read_bytes()),
        'retained_feedback_sources':[{'source_id':'author.md','sha256':m.sha((tmp_path/'author.md').read_bytes()),'text':original}]})
    out=m.prepare(tmp_path,'0001','layers','1-5000',feedback_path='auto/instructions.md')
    data=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    assert data['author_feedback']==original
    assert '旧自动建议' in data['automatic_revision_advice']
    put(tmp_path,'author.md','作者后来修改了要求。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_exhausted_polish_reuses_verified_review_as_automatic_feedback(tmp_path):
    from test_length_quality import policy
    m,out=setup(tmp_path)
    payload=patch(m,out,tmp_path,'第二段新的说明。');m.candidate(tmp_path,out['revision_dir'])
    report=json.loads(approved(m,out,tmp_path));report['change_reviews'][0]['effect']='regressed'
    put(tmp_path,out['revision_review_path'],report);raw=json.dumps(report,ensure_ascii=False)
    with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],raw)
    task={'task_id':'local-test','status':'failed','workspace_override':str(tmp_path),
          'parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False),'revision_review_result':raw},
          'node_states':{'agent_pl':{'status':'completed'},'agent_local_review':{'status':'completed'},
                         'script_local_commit':{'status':'failed','error':'RETRY_STOP: content：局部改动仍需处理'}}}
    state={'values':{'chapter_number':'0001','target_word_count':'1-5000'}}
    p=policy();action=p.recovery_action(state,'polish',task,root=tmp_path)
    assert action['stage']=='polish' and 'mvp' not in action['reset']
    updates=action['updates'];feedback=updates['values']['author_feedback_file']
    authored, automatic, _=m.feedback_layers(tmp_path,feedback)
    assert authored=='保留全知和回环，仅合并无作用说明。'
    assert report['change_reviews'][0]['reason'] in automatic
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert p.recovery_action({**state,**updates},'polish',task,root=tmp_path) is None


def test_repeated_content_rejection_alone_does_not_prove_scope_conflict(tmp_path):
    m,out=setup(tmp_path)
    for i,text in enumerate(('第二段简明。','第二段新的说明。')):
        payload=patch(m,out,tmp_path,text);m.candidate(tmp_path,out['revision_dir'])
        report=json.loads(approved(m,out,tmp_path));report['change_reviews'][0]['effect']='regressed'
        put(tmp_path,out['revision_review_path'],report);raw=json.dumps(report,ensure_ascii=False)
        with pytest.raises(m.Retry):m.commit(tmp_path,out['revision_dir'],raw)
    task={'task_id':'local-test','status':'failed','parameter_values':{**out,'revision_patch_result':json.dumps(payload,ensure_ascii=False),
        'revision_review_result':raw},'node_states':{'agent_pl':{'status':'completed'},'agent_local_review':{'status':'completed'},'script_local_commit':{'status':'failed'}}}
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


@pytest.mark.parametrize('changed',['story/0001/chapter.md','story/0001/diff_story_confirmed.md',
    'planning/chapters/0003.json','learning/active_context.md','learning/character_center/preferences.json'])
def test_old_history_and_adopted_planning_are_bound_even_when_context_cache_is_unchanged(tmp_path,changed):
    m=module();put(tmp_path,'story/0001/chapter.md','第一章。');put(tmp_path,'story/0003/chapter.md','第三章。')
    out=m.prepare(tmp_path,'0003','history','1-5000')
    put(tmp_path,changed,'作者更新了此前依据。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_local_editor_uses_current_runtime_context_alias_instead_of_old_legacy_file(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原文。')
    put(tmp_path,'cache/story-support/context.md','旧的继承模式上下文。')
    put(tmp_path,'learning/prose_policy/runtime/task/current/common.md','本次已采用的表达与事实。')
    out=m.prepare(tmp_path,'0001','alias','1-5000','learning/prose_policy/runtime/task/current/common.md')
    source=json.loads((tmp_path/out['revision_input']).read_text(encoding='utf8'))
    assert source['confirmed_context']=='本次已采用的表达与事实。'
    put(tmp_path,'learning/prose_policy/runtime/task/current/common.md','来源被改。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_direct_workflow_feedback_override_is_frozen_and_cannot_drift(tmp_path):
    m=module();put(tmp_path,'story/0001/chapter.md','原文。')
    put(tmp_path,'.novel-project.json',{'values':{'author_feedback_file':'old.md'}})
    put(tmp_path,'old.md','旧选择。');put(tmp_path,'new.md','本次作者要求。')
    out=m.prepare(tmp_path,'0001','direct-feedback','1-5000',feedback_path='new.md')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf8'))
    assert source['author_feedback']=='本次作者要求。'
    put(tmp_path,'new.md','本次意见又改变。')
    with pytest.raises(ValueError):m.bound(tmp_path,out['revision_dir'])


def test_two_bad_length_candidates_do_not_invent_reading_scope_conflict(tmp_path):
    m=module();body=tmp_path/'story/0001/chapter.md';body.parent.mkdir(parents=True);body.write_bytes(BODY.encode())
    out=m.prepare(tmp_path,'0001','length-rejections','1-5000')
    put(tmp_path,'cache/sc/critique.json',{'issues':[{'severity':'medium','description':'说明重复',
        'suggestion':'合并无作用说明','evidence':['第二段重复说明。']}]})
    m.writer_input(tmp_path,out['revision_dir'],'cache/sc/critique.json')
    for count in (5001,5002):
        patch(m,out,tmp_path,'乙'*count)
        with pytest.raises(m.Retry) as exc:m.candidate(tmp_path,out['revision_dir'])
        assert exc.value.target=='agent_pl'
    assert not (tmp_path/out['revision_dir']/'composition-conflict.json').exists()
    assert len(json.loads((tmp_path/out['revision_dir']/'length-candidates.json').read_text(encoding='utf8')))==2
    assert body.read_bytes()==BODY.encode()
@pytest.mark.parametrize('body,details,replacement',[
    ('“我接了六十份，七点前送到。”',['六十份','七点'],'“这单得在上工前送过去。”'),
    ('“城门要收三十枚，八点前到。”',['三十枚','八点'],'“天黑前赶到，守门的还肯放人。”'),
])
def test_precision_target_rejects_unmodified_candidate_and_allows_exact_details_with_purpose(tmp_path,body,details,replacement):
    m=module();put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','precision-target','1-100')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    checks=[{'paragraph_id':'p0001','action':'revise','remove':details,'reason':'数量和时间都可用现场条件交代。'}]
    critique={'issues':[],'precision_checks':checks}
    put(tmp_path,'critique.json',critique)
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    editor=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf-8'))
    assert editor['goals'][0]['paragraph_ids']==['p0001']
    payload={'source_sha256':source['source_sha256'],'edits':[]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry,match='确数仍在') as err:m.candidate(tmp_path,out['revision_dir'])
    assert err.value.target=='agent_pl'
    if details[0]=='六十份':
        payload['edits']=[{'paragraph_id':'p0001','old':body,'occurrence':1,'replacement':'“接了60份，07:00要送到。”'}]
        put(tmp_path,out['revision_patch_path'],payload)
        with pytest.raises(m.Retry,match='确数仍在'):m.candidate(tmp_path,out['revision_dir'])
    payload['edits']=[{'paragraph_id':'p0001','old':body,'occurrence':1,'replacement':replacement}]
    put(tmp_path,out['revision_patch_path'],payload)
    m.candidate(tmp_path,out['revision_dir'])
    checks[0].update(action='keep',remove=[],reason='确数用于定量和交付凭证。')
    assert m.precision_goals(source,checks)==[]
    with pytest.raises(ValueError,match='逐项'):m.precision_goals(source,[])


def test_precision_scope_preserves_useful_dose_and_same_number_in_another_paragraph(tmp_path):
    m=module()
    first='“城门要收三十枚，八点前到。”'
    useful='“这药只能吃五毫克，八点前服完才能取血。”'
    put(tmp_path,'story/0001/chapter.md',first+'\n\n'+useful)
    out=m.prepare(tmp_path,'0001','mixed-precision','1-100')
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf-8'))
    put(tmp_path,'critique.json',{'issues':[],'precision_checks':[
        {'paragraph_id':'p0001','action':'revise','remove':['三十枚','八点'],'reason':'收费数和具体钟点不改变此处的去留。'},
        {'paragraph_id':'p0002','action':'keep','remove':[],'reason':'剂量和时限决定能否完成后续检查。'},
    ]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    put(tmp_path,out['revision_patch_path'],{'source_sha256':source['source_sha256'],'edits':[
        {'paragraph_id':'p0001','old':first,'occurrence':1,'replacement':'“关门前还来得及，过门得交钱。”'},
    ]})
    m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    assert context['candidate'].endswith(useful)
    assert [row['id'] for row in context['goals']]==['precision-p0001']


def test_precision_repeated_turns_are_checked_and_rejected_when_moved(tmp_path):
    m = module()
    body = '“六点？”\n\n“六点还得对账。”\n\n她手里的账本还没合上。'
    put(tmp_path, 'story/0001/chapter.md', body)
    out = m.prepare(tmp_path, '0001', 'repeated-precision', '1-100')
    source = json.loads((tmp_path / out['revision_source_input']).read_text(encoding='utf-8'))
    assert [row['paragraph_id'] for row in source['precision_candidates']] == ['p0001', 'p0002']
    checks = [dict(paragraph_id=key, action='revise', remove=['六点'], reason='只需知道对账以后才能走。')
              for key in ('p0001', 'p0002')]
    m.precision_goals(source, checks)
    with pytest.raises(ValueError, match='范围'):
        m.precision_goals(source, [dict(row, action='outside_scope', remove=[]) for row in checks])
    put(tmp_path, 'critique.json', {'issues': [], 'precision_checks': checks})
    m.writer_input(tmp_path, out['revision_dir'], 'critique.json')
    payload = {'source_sha256': source['source_sha256'], 'edits': [
        dict(paragraph_id='p0001', old='六点？', replacement='收摊就走？', occurrence=1),
        dict(paragraph_id='p0002', old='六点还得对账。', replacement='我还得对账。', occurrence=1),
        dict(paragraph_id='p0003', old='她手里的账本', replacement='06:00她手里的账本', occurrence=1),
    ]}
    put(tmp_path, out['revision_patch_path'], payload)
    with pytest.raises(m.Retry, match='确数仍在'):
        m.candidate(tmp_path, out['revision_dir'])
    payload['edits'].pop()
    put(tmp_path, out['revision_patch_path'], payload)
    m.candidate(tmp_path, out['revision_dir'])


def test_dialogue_exchange_is_anchored_and_returns_unfixed_turns_to_writer(tmp_path):
    m=module()
    body='“你替我答应了？”\n\n他手里还提着她的饭盒。\n\n“我已经替你答应了这件事。”\n\n门响了。'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','dialogue-example','1-100',dialogue_check=True)
    source=json.loads((tmp_path/out['revision_source_input']).read_text(encoding='utf8'))
    assert source['dialogue_check'] is True
    put(tmp_path,'critique.json',{'issues':[]})
    with pytest.raises(m.Retry) as exc:
        m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    assert exc.value.target=='agent_sc'

    turns=[{'paragraph_id':'p0001','quote':'你替我答应了？'},
           {'paragraph_id':'p0003','quote':'我已经替你答应了这件事。'}]
    row={'status':'revise','turns':turns,'reason':'后一轮只重复双方已知的承诺。',
         'goal':'让回应交代他怎么处理承诺。'}
    put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':[row]})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf8'))
    assert writer['goals'][0]['paragraph_ids']==['p0001','p0002','p0003']

    payload={'source_sha256':source['source_sha256'],'edits':[]}
    put(tmp_path,out['revision_patch_path'],payload)
    with pytest.raises(m.Retry,match='对白返修目标') as exc:
        m.candidate(tmp_path,out['revision_dir'])
    assert exc.value.target=='agent_pl'
    payload['edits']=[{'paragraph_id':'p0003','old':turns[1]['quote'],'occurrence':1,'replacement':'我去跟人家说。'}]
    put(tmp_path,out['revision_patch_path'],payload)
    m.candidate(tmp_path,out['revision_dir'])
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf8'))
    assert [row['id'] for row in context['goals']]==['dialogue-1']
    report=json.loads(approved(m,out,tmp_path))
    for check in report['expression_checks']:check['excerpts']=['门响了。']
    report['issue_outcomes']=[{'id':'dialogue-1','status':'remaining','reason':'答话仍回避了对方的追问。',
                               'excerpts':['你替我答应了？','我去跟人家说。']}]
    assert any('仍未解决' in reason for reason in m.review_decision(report,context))


def test_dialogue_exchange_rejects_unrelated_or_unordered_quotes():
    m=module();body='“你走吧。”\n\n桌上有碗。\n\n“票在这儿。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body)}
    row={'status':'revise','reason':'接话生硬','goal':'修改接话','turns':[
        {'paragraph_id':'p0003','quote':'票在这儿。'},{'paragraph_id':'p0001','quote':'你走吧。'}]}
    with pytest.raises(ValueError,match='顺序'):
        m.dialogue_goals(source,[row])
    row['turns']=[{'paragraph_id':'p0001','quote':'你走吧。'},{'paragraph_id':'p0002','quote':'桌上有碗。'}]
    with pytest.raises(ValueError,match='对白'):
        m.dialogue_goals(source,[row])


def test_dialogue_review_v2_requires_both_checks_and_changes_the_targeted_line(tmp_path):
    m=module()
    body='“别揪着这事不——”\n\n“我没揪。”\n\n她把收据递了过去。\n\n“东西能自己走回去？”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':2}
    echo={'focus':'literal_echo','status':'revise','reason':'顺着动词抢白，没接住对方想停下争执的意思。',
          'goal':'让她接住对方想叫停的意思。','target_turn':1,'turns':[
              {'paragraph_id':'p0001','quote':'别揪着这事不——'},
              {'paragraph_id':'p0002','quote':'我没揪。'}]}
    with pytest.raises(ValueError,match='逐项'):
        m.dialogue_goals(source,[echo])
    no_pressure={'focus':'situational_speech','status':'not_applicable','reason':'没有可对照的忙碌说明。','goal':'','turns':[]}
    goals=m.dialogue_goals(source,[echo,no_pressure])
    assert goals[0]['target']==echo['turns'][1]
    unrelated_edit={'paragraph_id':'p0001','old':'别揪着这事不——','occurrence':1,'replacement':'你先等等——'}
    with pytest.raises(ValueError,match='目标原话'):
        m.check_dialogue_goals([unrelated_edit],goals,source)
    target=echo['turns'][1]['quote']
    edit={'paragraph_id':'p0002','old':target,'occurrence':1,'replacement':'你先把箱子抬下来。'}
    m.check_dialogue_goals([edit],goals,source)
    edit['replacement']='我没揪。你先把箱子抬下来。'
    with pytest.raises(ValueError,match='目标原话'):
        m.check_dialogue_goals([edit],goals,source)


def test_dialogue_review_v3_anchors_checklist_and_one_sided_speech(tmp_path):
    m=module()
    body='“来过没有？”\n\n“没有。”\n\n“门呢？”\n\n她给房东留了一段语音：“您好。锁坏了。我还在门口。”'
    put(tmp_path,'story/0001/chapter.md',body)
    out=m.prepare(tmp_path,'0001','dialogue-v3','1-100',dialogue_check=True,dialogue_check_version=3)
    absent={'status':'not_applicable','reason':'没有适用情境。','goal':'','turns':[]}
    legacy=[dict(absent,focus=focus) for focus in ('literal_echo','situational_speech')]
    with pytest.raises(m.Retry,match='逐项'):
        put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':legacy})
        m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    checks=legacy+[
        {'focus':'checklist_exchange','status':'revise','reason':'第二问与未等到的人脱节。','target_turn':2,
         'goal':'由没等到人时必须处理的事引出锁。','preserve':['人还没来，门的情况影响下一步'],
         'turns':[{'paragraph_id':key,'quote':quote} for key,quote in
                  [('p0001','来过没有？'),('p0002','没有。'),('p0003','门呢？')]]},
        {'focus':'scripted_delivery','status':'revise','reason':'她急着进屋却逐项宣读现状。','target_turn':0,
         'goal':'先说要房东帮忙的事。','preserve':['锁坏了','还在门口'],
         'turns':[{'paragraph_id':'p0004','quote':'您好。锁坏了。我还在门口。'}]},
    ]
    put(tmp_path,'critique.json',{'issues':[],'dialogue_checks':checks})
    m.writer_input(tmp_path,out['revision_dir'],'critique.json')
    writer=json.loads((tmp_path/out['revision_editor_model']).read_text(encoding='utf8'))
    assert [(row['focus'],row['preserve']) for row in writer['goals']]==[
        ('checklist_exchange',['人还没来，门的情况影响下一步']),('scripted_delivery',['锁坏了','还在门口'])]
    assert writer['goals'][1]['target']['paragraph_id']=='p0004'


def test_dialogue_v4_turns_voice_flattening_into_a_grounded_repair():
    m=module()
    body='“你先说门怎么坏的。”\n\n“门的确坏了，没约修理时间。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':4}
    checks=[{'focus':focus,'status':'not_applicable','reason':'本处无该类情境。','goal':'','turns':[]}
            for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery')]
    with pytest.raises(ValueError,match='voice_contrast'):
        m.dialogue_goals(source,checks)
    checks.append({'focus':'voice_contrast','status':'revise','reason':'答话在汇报，与对方问的事脱节。',
                   'goal':'让他避开追责，先争取进屋。','target_turn':1,'preserve':['锁坏了，且无人约时间'],
                   'turns':[{'paragraph_id':'p0001','quote':'你先说门怎么坏的。'},
                            {'paragraph_id':'p0002','quote':'门的确坏了，没约修理时间。'}]})
    assert m.dialogue_goals(source,checks)[0]['preserve']==['锁坏了，且无人约时间']


def test_dialogue_v4_accepts_identical_words_at_distinct_source_turns():
    m=module()
    body='“我已经说过了。”\n\n“我已经说过了。你再想想。”'
    source={'source_body':body,'paragraphs':m.patches.paragraphs(body),'dialogue_check_version':4}
    checks=[{'focus':focus,'status':'not_applicable','reason':'无该类情境。','goal':'','turns':[]}
            for focus in ('literal_echo','situational_speech','checklist_exchange','scripted_delivery')]
    review={'focus':'voice_contrast','status':'revise','reason':'各自用同一句发言开头。','goal':'按各自所求接话。',
            'preserve':['两人先前已说过此事'],'target_turn':1,'turns':[
                {'paragraph_id':'p0001','quote':'我已经说过了。'},
                {'paragraph_id':'p0002','quote':'我已经说过了。你再想想。'}]}
    assert m.dialogue_goals(source,[*checks,review])[0]['target']==review['turns'][1]
    review['turns'][1]=review['turns'][0].copy()
    with pytest.raises(ValueError,match='不可重叠'):
        m.dialogue_goals(source,[*checks,review])
