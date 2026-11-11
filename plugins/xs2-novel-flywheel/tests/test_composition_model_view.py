import copy
import hashlib
import json
import pytest
from test_context_packet import module


def sample():
    body='当前原文。\n\n故意复沓，也可以有作用。\n'
    return {'chapter':'0001','body':body,'source_hashes':{'story/0001/chapter.md':hashlib.sha256(body.encode()).hexdigest()},
        'request_digest':'canonical-request','book_contract':{'style_intent':'允许全知、复沓与技术计数'},
        'author_feedback':'保留作者指定的数字与节奏。','reader_report':{'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'verdict':'pass','issues':[],'reading_checks':[{'reason':'回环推进情绪'}],
        'blind_review':{'decisions':[{'text':'真实选择与推理'}]},'review_binding':{'paths':'machine-only'}},
        'conflict':{'source_sha256':'different-old-version','rejected_candidate':'过期候选。'*5000,'reason':'旧章旧稿冲突'}}


def test_planning_model_view_keeps_complete_current_body_rules_and_semantic_evidence():
    p=module();data=sample();original=copy.deepcopy(data);view=p.composition(data)
    assert data==original
    assert view['body']==data['body']
    for key in ('book_contract','author_feedback','request_digest'):assert view[key]==data[key]
    assert view['reader_report']['blind_review']==data['reader_report']['blind_review']
    assert view['reader_report']['reading_checks']==data['reader_report']['reading_checks']
    assert 'review_binding' not in view['reader_report'] and 'source_hashes' not in view
    assert view['conflict']['status']=='stale_not_authoritative'
    assert 'rejected_candidate' not in view['conflict']
    assert len(json.dumps(view,ensure_ascii=False))<len(json.dumps(data,ensure_ascii=False))/2
    p.verify_composition(view,data)
    view['body']='篡改原文。'
    with pytest.raises(ValueError):p.verify_composition(view,data)


def test_current_conflict_remains_complete_and_stale_reader_report_is_not_presented_as_current():
    p=module();data=sample();data['conflict']['source_sha256']=data['source_hashes']['story/0001/chapter.md']
    data['reader_report']['body_sha256']='older-report'
    view=p.composition(data)
    assert view['conflict']==data['conflict']
    assert view['reader_report']['status']=='stale_not_authoritative'
    assert 'verdict' not in view['reader_report']


def test_review_view_reuses_same_verified_model_request_and_keeps_full_plan():
    p=module();data={'request':sample(),'plan':{'segments':[{'purpose':'跨卷余波','development':'人物改变判断'}]},'request_digest':'r','plan_digest':'p'}
    view=p.composition(data)
    assert view['plan']==data['plan'] and view['request']['body']==data['request']['body']
    p.verify_composition(view,data)
