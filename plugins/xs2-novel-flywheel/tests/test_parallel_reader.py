import copy
import json
import importlib.util
import shutil
import pytest
from test_reader_review_p0 import review,book,blind,final,write
from test_book_contract import PLUGIN


def test_installed_parallel_profile_freezes_and_checks_required_resources(tmp_path):
    prepared=tmp_path/'prepared';scripts=prepared/'script-libraries/0/xs2-novel-flywheel-xs2'
    shutil.copytree(PLUGIN/'resources/script-library/xs2',scripts,
        ignore=shutil.ignore_patterns('__pycache__','*.pyc','vendor'))
    configs={
        'prompts.json':prepared/'json/prompts/0.json',
        'workflows/reader-sim/definition.json':prepared/'workflows/0/xs2-novel-flywheel-reader-sim/definition.json',
    }
    for source,target in configs.items():
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((PLUGIN/'resources'/source).read_bytes())
    spec=importlib.util.spec_from_file_location('installed_parallel_reader',scripts/'reader_review/reader_review.py')
    installed=importlib.util.module_from_spec(spec);spec.loader.exec_module(installed)
    assert installed.parallel_profile()==review().parallel_profile()
    root=tmp_path/'book';book(root)
    out=installed.prepare(root,'0001','installed-reader',parallel=True)
    write(root,'cache/story-support/context.md','本书已冻结资料。')
    installed.freeze_parallel(root,out['reader_review_binding'],out['reader_review_binding_sha'])
    binding=json.loads((root/out['reader_review_binding']).read_text(encoding='utf8'))
    installed.verify_parallel(root,binding)
    original=installed.parallel_profile()
    for path in (configs['prompts.json'],configs['workflows/reader-sim/definition.json'],scripts/'prose_policy/book_contract.py',scripts/'local_revision/pending_revision.py'):
        content=path.read_bytes();path.write_bytes(content+b'\n')
        assert installed.parallel_profile()!=original
        with pytest.raises(ValueError):installed.verify_parallel(root,binding)
        path.write_bytes(content)
        installed.verify_parallel(root,binding)
    configs['prompts.json'].unlink()
    with pytest.raises(FileNotFoundError):installed.parallel_profile()


def inputs(root,findings):
    m=review();book(root);out=m.prepare(root,'0001','parallel-test',parallel=True)
    write(root,'cache/story-support/context.md','本书冻结资料。')
    m.freeze_parallel(root,out['reader_review_binding'],out['reader_review_binding_sha'])
    initial=blind()
    if not findings:initial.update(verdict='pass',issues=[],decisions=[])
    write(root,out['reader_blind_raw_path'],initial)
    b=m.commit_blind(root,out['reader_review_binding'],out['reader_review_binding_sha'])
    context=final();context['revision_scope']['assessments']=[];context['blind_resolutions']=[]
    write(root,out['reader_preflight_raw_path'],context)
    c=m.commit_context(root,out['reader_review_binding'],out['reader_review_binding_sha'])
    return m,out,{**b,**c}


@pytest.mark.parametrize('findings',[False,True])
def test_parallel_join_requires_reconciliation_for_blind_findings(tmp_path,findings):
    m,out,h=inputs(tmp_path,findings)
    result=m.join(root=tmp_path,binding_path=out['reader_review_binding'],expected_sha=out['reader_review_binding_sha'],
        blind_sha=h['reader_blind_report_sha'],context_sha=h['reader_preflight_sha'])
    assert result['reader_reconcile_required']==('yes' if findings else 'no')
    if not findings:
        report=m.commit(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],h['reader_blind_report_sha'],h['reader_preflight_sha'])
        assert report['verdict']=='pass'
    else:assert not (tmp_path/'story/0001/reader_report.json').exists()


def test_parallel_join_rejects_mutated_sources_and_preflight(tmp_path):
    m,out,h=inputs(tmp_path,False)
    write(tmp_path,'meta/world_foundation.md','规则已变。')
    with pytest.raises(ValueError):m.join(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],h['reader_blind_report_sha'],h['reader_preflight_sha'])


def test_validated_context_issue_survives_reconciliation_and_keeps_its_polish_id(tmp_path):
    from test_local_revision import module

    m, out, hashes = inputs(tmp_path, True)
    preflight = final()
    finding = {'id': 'context-1', 'category': 'post_action_restatement', 'location': '开头',
               'priority': 'medium', 'excerpts': ['她没见过验单。', '买方说不同意就付给陆。'],
               'impact': '复述刚出现的信息。', 'goal': '合并开头的重复解释。'}
    preflight['expression_review'].update(verdict='revise', issues=[finding])
    preflight['revision_scope']['assessments'] = [
        {'issue_id': 'context-1', 'status': 'editable', 'reason': '在作者允许改动的开头。'}]
    write(tmp_path, out['reader_preflight_raw_path'], preflight)
    hashes.update(m.commit_context(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha']))
    write(tmp_path, out['reader_context_report_path'], final())
    report = m.commit(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'],
                      hashes['reader_blind_report_sha'], hashes['reader_preflight_sha'])
    rows = {row['id']: row for row in report['issues']}
    assert rows['context-1']['editability'] == 'editable'
    assert rows['blind-1']['editability'] == 'outside_scope'
    assert [(row['id'], row['goal']) for row in module().goals({'reader_report': report}, {})] == [
        ('context-1', '合并开头的重复解释。')]


def test_context_issue_cannot_disappear_with_an_unrelated_resolution_quote():
    from test_reader_review_p0 import BODY

    m = review()
    issue = {'id': 'context-1', 'source': 'expression_review', 'priority': 'medium', 'editability': 'editable',
             'location': '开头', 'impact': '意图被直译', 'goal': '让读者看到动作',
             'excerpts': ['她没见过验单。']}
    preflight = {'issues': [issue], 'revision_scope': {'summary': '允许修改', 'assessments': []}}
    report = final()
    report['context_resolutions'] = [{'issue_id': 'context-1', 'reason': '正文已经给出动作依据。',
                                      'excerpts': ['陆同意分付。']}]
    with pytest.raises(ValueError, match='所在的原文'):
        m.retain_context_findings(copy.deepcopy(report), preflight, blind(), BODY)
    report['context_resolutions'][0]['excerpts'] = ['她没见过验单。']
    resolved = m.retain_context_findings(report, preflight, blind(), BODY)
    assert resolved['expression_review']['issues'] == []
    assert resolved['context_resolutions'][0]['issue_id'] == 'context-1'


def test_fast_publication_cannot_swap_the_validated_context_report(tmp_path):
    m,out,h=inputs(tmp_path,False)
    m.join(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],h['reader_blind_report_sha'],h['reader_preflight_sha'])
    value=json.loads((tmp_path/out['reader_context_report_path']).read_text(encoding='utf8'));value['summary']='未经模型审查的替换报告'
    write(tmp_path,out['reader_context_report_path'],value)
    with pytest.raises(ValueError):m.commit(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],h['reader_blind_report_sha'],h['reader_preflight_sha'])


def test_independent_context_cannot_invent_blind_resolutions(tmp_path):
    m=review();book(tmp_path);out=m.prepare(tmp_path,'0001','parallel-test')
    context=final();context['blind_resolutions']=[{'issue_id':'guessed','reason':'猜测初审','excerpts':['她没见过验单。']}]
    write(tmp_path,out['reader_preflight_raw_path'],context)
    with pytest.raises(m.InvalidReviewReport):m.commit_context(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])


def contextual_findings(root, general, expression):
    m, out, _ = inputs(root, False)
    context = final()
    context.update(verdict='revise', issues=[general])
    context['expression_review'].update(verdict='revise', issues=[expression])
    context['revision_scope']['assessments'] = [
        {'issue_id': 'context-1', 'status': 'outside_scope', 'reason': '只允许改开头'}]
    write(root, out['reader_preflight_raw_path'], context)
    return m, out


def test_context_publication_derives_empty_blind_resolutions(tmp_path):
    m, out, _ = inputs(tmp_path, False)
    context = final()
    context['revision_scope']['assessments'] = []
    for row in context['expression_checks']:
        del row['issue_ids']
    write(tmp_path, out['reader_preflight_raw_path'], context)
    m.commit_context(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'])
    report = json.loads((tmp_path / out['reader_preflight_path']).read_text(encoding='utf-8'))
    assert report['blind_resolutions'] == []
    assert all(row['issue_ids'] == [] for row in report['expression_checks'])


def test_colliding_context_ids_cannot_borrow_scope_for_another_finding(tmp_path):
    expression = {'id': 'context-1', 'location': '结尾', 'priority': 'medium',
                  'excerpts': ['陆同意分付。'], 'impact': '重复结论', 'goal': '合并说明'}
    general = {**expression, 'impact': '凭据断裂', 'goal': '补进前置铺垫'}
    m, out = contextual_findings(tmp_path, general, expression)
    with pytest.raises(m.InvalidReviewReport, match=r'expression_review\.issues\[0\]'):
        m.commit_context(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'])


def test_structurally_identical_context_issue_has_one_scoped_canonical_finding(tmp_path):
    issue = {'id': 'context-1', 'location': '结尾', 'priority': 'medium',
             'excerpts': ['陆同意分付。'], 'impact': '重复结论', 'goal': '合并说明'}
    m, out = contextual_findings(tmp_path, issue, issue)
    m.commit_context(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'])
    report = json.loads((tmp_path / out['reader_preflight_path']).read_text(encoding='utf-8'))
    assert report['verdict'] == 'revise' and report['requires_scope_confirmation']
    assert [(row['id'], row['source'], row['editability']) for row in report['issues']] == [
        ('context-1', 'expression_review', 'outside_scope')]


def test_duplicate_context_dimension_identifies_missing_and_repeated_dimensions(tmp_path):
    m, out, _ = inputs(tmp_path, False)
    context = final()
    context['revision_scope']['assessments'] = []
    context['blind_resolutions'] = []
    context['expression_checks'][-1] = copy.deepcopy(context['expression_checks'][-2])
    write(tmp_path, out['reader_preflight_raw_path'], context)
    with pytest.raises(m.InvalidReviewReport, match=r'expression_checks.*scene_conflict_progression.*aftermath_transition'):
        m.commit_context(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'])


def test_missing_parallel_credentials_cannot_downgrade_to_legacy_review(tmp_path):
    m,out,h=inputs(tmp_path,False)
    (tmp_path/out['reader_parallel_sources']).unlink()
    with pytest.raises(ValueError):m.commit_blind(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])


def test_disabled_whitespace_runtime_is_not_the_book_root(tmp_path):
    m=review();book(tmp_path);out=m.prepare(tmp_path,'0001','runtime-test',parallel=True)
    write(tmp_path,'cache/story-support/context.md','已确认资料。')
    m.freeze_parallel(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],runtime_path=' ')
    frozen=json.loads((tmp_path/out['reader_parallel_sources']).read_text(encoding='utf8'))
    assert frozen['runtime_path']=='' and 'quality/old.json' not in frozen['sources']


def test_dynamic_style_runtime_is_bound_with_the_same_frozen_inputs(tmp_path):
    m=review();book(tmp_path);out=m.prepare(tmp_path,'0001','runtime-test',parallel=True)
    write(tmp_path,'cache/story-support/context.md','已确认资料。')
    write(tmp_path,'cache/policy-runtime/preference.md','作者选择全知和复沓。')
    m.freeze_parallel(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'],runtime_path='cache/policy-runtime')
    write(tmp_path,'cache/policy-runtime/preference.md','未经作者确认的替换。')
    with pytest.raises(ValueError):m._bound(tmp_path,out['reader_review_binding'],out['reader_review_binding_sha'])


def test_reader_workflow_has_native_parallel_branches_and_conditional_reconciliation():
    from src.workflow.definition import WorkflowDef
    raw=json.loads((PLUGIN/'resources/workflows/reader-sim/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(raw);assert not wf.validate()
    assert any(g.gateway_type=='parallel' for g in wf.gateways)
    nodes={n['id']:n for n in raw['nodes']}
    assert '{{reader_blind_report}}' not in nodes['agent_context_reader']['first_message']
    assert '{{book_contract_file}}' in nodes['agent_context_reader']['first_message']
    assert '{{reader_fact_sources}}' in nodes['agent_context_reader']['first_message']
    assert 'expression_checks' not in nodes['agent_context_reader']['node_params']['json_output_schema']['properties']
    assert '{{reader_fact_conflicts}}' in nodes['agent_reader']['first_message']
    assert '{{reader_review_binding}}' in nodes['script_reader_join']['node_params']['script_argv']
