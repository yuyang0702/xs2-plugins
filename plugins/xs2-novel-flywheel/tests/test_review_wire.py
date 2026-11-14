import copy
import importlib.util
import json
import pytest
from test_book_contract import PLUGIN
from test_local_revision import setup,patch,approved,BODY


def module():
    path=PLUGIN/'resources/script-library/xs2/prose_policy/review_wire.py'
    assert path.exists(),'Missing compact review protocol'
    spec=importlib.util.spec_from_file_location('review_wire_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def compact(report):
    result={k:copy.deepcopy(v) for k,v in report.items() if k not in ('candidate_sha256','book_contract_sha256','review_input_sha256')}
    result['protocol']='local-review-v2'
    for row in result['change_reviews']:
        row.pop('before_excerpt');row.pop('after_excerpt')
    return result


def test_compact_decodes_to_full_same_judgment_and_preserves_raw_response(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    legacy=json.loads(approved(m,out,tmp_path));wire=compact(legacy)
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    assert module().expand(wire,context)==legacy
    assert 'candidate_sha256' not in wire and 'before_excerpt' not in wire['change_reviews'][0]
    (tmp_path/out['revision_review_path']).write_text(json.dumps(wire,ensure_ascii=False),encoding='utf-8')
    m.commit(tmp_path,out['revision_dir'],json.dumps(wire,ensure_ascii=False))
    assert json.loads((tmp_path/out['revision_review_path']).read_text(encoding='utf-8'))==wire
    assert json.loads((tmp_path/out['revision_review_expanded']).read_text(encoding='utf-8'))==legacy


@pytest.mark.parametrize('defect',[None,'revise','issue_status','issue_id'])
def test_omitted_expression_issues_requires_explicit_pass_and_no_flagged_check(tmp_path,defect):
    from src.workflow.output_selection import select_agent_output

    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    legacy=json.loads(approved(m,out,tmp_path));report=compact(legacy)
    del report['expression_review']['issues']
    if defect=='revise':report['expression_review']['verdict']='revise'
    if defect=='issue_status':report['expression_checks'][0]['status']='issue'
    if defect=='issue_id':report['expression_checks'][0]['issue_ids']=['unresolved']
    definition=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf-8'))
    params=next(n['node_params'] for n in definition['nodes'] if n['id']=='agent_local_review')
    selected,error=select_agent_output([{'type':'user','content':'审查候选'},
        {'type':'assistant','content':json.dumps(report,ensure_ascii=False)}],params)
    if defect:
        assert error
        context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
        with pytest.raises(ValueError):module().expand(report,context)
    else:
        assert not error and json.loads(selected)==report
        (tmp_path/out['revision_review_path']).write_text(selected,encoding='utf-8')
        receipt=m.commit(tmp_path,out['revision_dir'],selected)
        assert receipt['accepted']
        assert json.loads((tmp_path/out['revision_review_path']).read_text(encoding='utf-8'))==report
        assert json.loads((tmp_path/out['revision_review_expanded']).read_text(encoding='utf-8'))==legacy


@pytest.mark.parametrize('defect',['fact','expression','regressed','missing_edit','missing_check','invented_evidence','wrong_edit','missing_verdict'])
def test_compact_cannot_remove_or_fill_a_semantic_quality_failure(tmp_path,defect):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    legacy=json.loads(approved(m,out,tmp_path));wire=compact(legacy)
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    assert module().expand(wire,context)==legacy
    assert m.review_decision(wire,context)==[]
    if defect=='fact':
        wire['compatible']=False;wire['issues']=[{'id':'f','candidate_quote':'第二段简明。','source_quote':'第二段重复说明。','reason':'改变事实。'}]
    elif defect=='expression':wire['change_reviews'][0]['effect']='equivalent'
    elif defect=='regressed':wire['change_reviews'][0]['effect']='regressed'
    elif defect=='missing_edit':wire['change_reviews']=[]
    elif defect=='missing_check':wire['expression_checks']=[]
    elif defect=='invented_evidence':wire['expression_checks'][0]['excerpts']=['正文从来没有这句话。']
    elif defect=='wrong_edit':wire['change_reviews'][0]['edit_index']=99
    else:wire.pop('compatible')
    (tmp_path/out['revision_review_path']).write_text(json.dumps(wire,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(ValueError):m.commit(tmp_path,out['revision_dir'],json.dumps(wire,ensure_ascii=False))
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==BODY.encode()


def test_v2_rejects_overridden_binding_metadata_and_legacy_wrong_binding_stays_invalid(tmp_path):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    legacy=json.loads(approved(m,out,tmp_path));context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    wire=compact(legacy);wire['candidate_sha256']='injected'
    with pytest.raises(ValueError):module().expand(wire,context)
    legacy['candidate_sha256']='old'
    with pytest.raises(ValueError):m.review_decision(legacy,context)


@pytest.mark.parametrize('status',['missing','remaining','resolved'])
def test_v2_preserves_each_original_goal_verdict(tmp_path,status):
    m,out=setup(tmp_path);patch(m,out,tmp_path);m.candidate(tmp_path,out['revision_dir'])
    legacy=json.loads(approved(m,out,tmp_path))
    context=json.loads((tmp_path/out['revision_review_input']).read_text(encoding='utf-8'))
    context['goals']=[{'id':'goal-1','goal':'保留回环，删除无作用复述。'}]
    if status!='missing':
        legacy['issue_outcomes']=[{'id':'goal-1','status':status,'reason':'按本书目的逐项判断。','excerpts':['第二段简明。']}]
    wire=compact(legacy)
    if status=='missing':
        for report in (legacy,wire):
            with pytest.raises(ValueError,match='逐项复核'):m.review_decision(report,context)
    else:
        assert m.review_decision(legacy,context)==m.review_decision(wire,context)
        assert bool(m.review_decision(wire,context))==(status=='remaining')
