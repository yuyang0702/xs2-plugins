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
