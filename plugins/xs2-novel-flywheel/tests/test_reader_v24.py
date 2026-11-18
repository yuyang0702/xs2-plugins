import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_reader_review_p0 import book, review, write


PLUGIN = Path(__file__).resolve().parents[1]
BODY = '“可以进吗？”\n\n她举手示停。\n\n“先关门。”\n\n他照做。\n\n窗外的灯灭了。\n\n她把钥匙交给他。'


def blind_v2(issues=()):
    return {'summary': '交谈和选择均有承接。', 'decisions': [], 'issues': list(issues),
            'coverage': {'first_exchange': ['p0001', 'p0002', 'p0003', 'p0004'], 'key_turn': ['p0006']}}


def style_issue():
    return {'id': 'blind-1', 'kind': 'expression', 'priority': 'high', 'location': '门边',
            'impact': '命令重复', 'goal': '检查是否仍需要这句', 'excerpts': ['“先关门。”', '他照做。']}


def fact_issue():
    return {'id': 'blind-1', 'kind': 'fact', 'priority': 'high', 'location': '结尾换钥匙',
            'impact': '所凭权限互相冲突。', 'goal': '让交接权限前后一致。',
            'excerpts': ['她举手示停。', '她把钥匙交给他。'],
            'contradiction': {'claim': {'ref_id': 'p0006'}, 'against': {'ref_id': 'p0002'}}}


def fact_v2(**updates):
    return {'summary': '对照已确认资料。', 'fact_review': {'summary': '已检查人物权限。'}, 'issues': [],
            'revision_scope': {'mode': 'restricted', 'summary': '只允许改开头', 'assessments': []}, **updates}


def prepared(tmp_path):
    m = review()
    book(tmp_path)
    write(tmp_path, 'story/0001/chapter.md', BODY)
    write(tmp_path, 'meta/world_foundation.md', '灯灭时可以把备用钥匙交给同行人。')
    write(tmp_path, 'cache/story-support/context.md', '已确认资料。')
    out = m.prepare(tmp_path, '0001', 'reader-v24', parallel=True, protocol=2)
    m.freeze_parallel(tmp_path, out['reader_review_binding'], out['reader_review_binding_sha'])
    return m, out


def branches(root, m, out, blind, context):
    write(root, out['reader_blind_raw_path'], blind)
    write(root, out['reader_preflight_raw_path'], context)
    args = (root, out['reader_review_binding'], out['reader_review_binding_sha'])
    blind_sha = m.commit_blind(*args)['reader_blind_report_sha']
    context_sha = m.commit_context(*args)['reader_preflight_sha']
    return (*args, blind_sha, context_sha)


def test_reader_v24_workflow_binds_small_phase_specific_schemas():
    raw = json.loads((PLUGIN / 'resources/workflows/reader-sim/definition.json').read_bytes())
    nodes = {node['id']: node for node in raw['nodes']}
    assert raw['version'] == 24
    assert nodes['script_reader_review_prepare']['node_params']['script_argv'][-2:] == ['--protocol', '2']
    assert 'coverage' in nodes['agent_blind_reader']['node_params']['json_output_schema']['required']
    for node_id in ('agent_blind_reader', 'agent_context_reader', 'agent_reader'):
        schema = nodes[node_id]['node_params']['json_output_schema']
        assert 'expression_checks' not in schema['properties']
    assert set(nodes['agent_reader']['node_params']['json_output_schema']['properties']) == {'blind_resolutions'}


def test_reader_v24_publishes_style_as_advice_with_no_second_model_review(tmp_path):
    m, out = prepared(tmp_path)
    args = branches(tmp_path, m, out, blind_v2([style_issue()]), fact_v2())
    assert m.join(*args)['reader_reconcile_required'] == 'no'
    report = m.commit(*args)
    assert report['reader_review_version'] == 2 and report['verdict'] == 'pass'
    assert report['book_contract_sha256'] == report['review_binding']['scope_source']['book_contract_sha256']
    assert report['expression_review']['issues'][0]['id'] == 'blind-1'
    assert report['expression_review']['issues'][0]['priority'] == 'low'
    assert report['expression_review']['issues'][0]['actionability'] == 'advisory'
    assert not report['requires_scope_confirmation']
    assert m.paragraph_coverage(report, BODY, 'p0002') == 'covered'
    assert m.paragraph_coverage(report, BODY, 'p0005') == 'not_separately_covered'


def test_reader_v24_keeps_exact_optional_polish_goal_without_blocking(tmp_path):
    m, out = prepared(tmp_path)
    issue = style_issue()
    issue.update(actionability='targeted', scene_focus={'quote':'“先关门。”', 'addressee':'来访的人'})
    args = branches(tmp_path, m, out, blind_v2([issue]), fact_v2())
    assert m.join(*args)['reader_reconcile_required'] == 'no'
    report = m.commit(*args)
    assert report['verdict'] == 'pass'
    assert report['issues'][0]['actionability'] == 'targeted'
    assert report['issues'][0]['scene_focus']['quote'] == '“先关门。”'
    assert report['issues'][0]['priority'] == 'low'


def test_reader_v24_does_not_route_untargeted_style_feedback_to_polish(tmp_path):
    m, out = prepared(tmp_path)
    issue = style_issue() | {'actionability':'targeted'}
    with pytest.raises(m.InvalidReviewReport, match='scene_focus'):
        branches(tmp_path, m, out, blind_v2([issue]), fact_v2())


def test_legacy_reader_evidence_does_not_infer_coverage_between_cited_paragraphs():
    report = {'expression_checks': [{'excerpts': ['“可以进吗？”', '“先关门。”']}]}
    m = review()
    assert m.paragraph_coverage(report, BODY, 'p0001') == 'covered'
    assert m.paragraph_coverage(report, BODY, 'p0002') == 'not_separately_covered'
    assert m.paragraph_coverage(report, BODY, 'p0003') == 'covered'


def test_reader_v24_keeps_material_fact_without_rerunning_the_general_review(tmp_path):
    m, out = prepared(tmp_path)
    args = branches(tmp_path, m, out, blind_v2([fact_issue()]), fact_v2())
    assert m.join(*args)['reader_reconcile_required'] == 'no'
    report = m.commit(*args)
    assert report['verdict'] == 'revise'
    assert [(row['id'], row['editability']) for row in report['issues']] == [('blind-1', 'unclear')]
    assert report['requires_scope_confirmation']


@pytest.mark.parametrize(('blind_claim', 'support_claim', 'required'), [
    ({'ref_id': 'p0006'}, '把钥匙交给他', 'yes'),
    ('把钥匙交给他', {'ref_id': 'p0006'}, 'yes'),
    ({'ref_id': 'p0006'}, {'ref_id': 'p0005'}, 'no'),
])
def test_reader_v24_matches_claims_at_the_same_location_with_different_citation_lengths(
        tmp_path, blind_claim, support_claim, required):
    m, out = prepared(tmp_path)
    issue = fact_issue()
    issue['contradiction']['claim'] = blind_claim
    support = {'claim': support_claim, 'source_path': 'meta/world_foundation.md',
               'source_quote': '灯灭时可以把备用钥匙交给同行人。', 'reason': '书内规则涉及熄灯与交接。'}
    args = branches(tmp_path, m, out, blind_v2([issue]), fact_v2(fact_support=[support]))
    assert m.join(*args)['reader_reconcile_required'] == required


def test_reader_v24_reconciles_only_a_verified_conflicting_claim(tmp_path):
    m, out = prepared(tmp_path)
    support = {'claim': {'ref_id': 'p0006'}, 'source_path': 'meta/world_foundation.md',
               'source_quote': '灯灭时可以把备用钥匙交给同行人。', 'reason': '灯灭以后发生交接。'}
    args = branches(tmp_path, m, out, blind_v2([fact_issue()]), fact_v2(fact_support=[support]))
    assert m.join(*args)['reader_reconcile_required'] == 'yes'
    proof = {'blind_resolutions': [{'issue_id': 'blind-1', 'reason': '止步手势次于灯灭前的边界。',
                                   'excerpts': [{'ref_id': 'p0006'}, {'ref_id': 'p0005'}]}]}
    fabricated = copy.deepcopy(proof)
    fabricated['blind_resolutions'][0]['excerpts'][-1] = '从未发生的放行'
    write(tmp_path, out['reader_context_report_path'], fabricated)
    with pytest.raises(m.InvalidReviewReport, match='excerpts'):
        m.commit(*args)
    write(tmp_path, out['reader_context_report_path'], proof)
    report = m.commit(*args)
    assert report['verdict'] == 'pass' and report['issues'] == []
    assert report['blind_review']['issues'][0]['id'] == 'blind-1'


def test_reader_v24_rejects_a_context_claim_without_literal_frozen_source(tmp_path):
    m, out = prepared(tmp_path)
    support = {'claim': {'ref_id': 'p0006'}, 'source_path': 'meta/world_foundation.md',
               'source_quote': '从未写进资料的说法。', 'reason': '捏造凭证。'}
    with pytest.raises(m.InvalidReviewReport, match='source_quote'):
        branches(tmp_path, m, out, blind_v2([fact_issue()]), fact_v2(fact_support=[support]))


def test_reader_v24_reconciliation_cannot_close_the_wrong_occurrence():
    m = review()
    body = BODY + '\n\n她把钥匙交给他。'
    issue = fact_issue()
    issue['contradiction'] = {'claim': {'text':'她把钥匙交给他。','occurrence':2}, 'against':'她举手示停。'}
    conflicts = [{'issue': issue, 'book_support': []}]
    raw = {'blind_resolutions': [{'issue_id': issue['id'], 'reason': '另有依据。',
                                  'excerpts': [{'ref_id':'p0006'}, {'ref_id':'p0005'}]}]}
    with pytest.raises(ValueError, match='主张'):
        m._apply_factual_resolutions(raw, {}, conflicts, body)


def test_blind_revision_hint_names_only_new_paragraphs_of_exact_accepted_current_body(tmp_path):
    m = review()
    book(tmp_path)
    current_path = write(tmp_path, 'story/0001/chapter.md', BODY)
    old = BODY.replace('窗外的灯灭了。\n\n', '')
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    folder = 'cache/local-revision/previous'
    contract_sha = m.book_contract.digest(m.book_contract.resolve(tmp_path))
    old_path = write(tmp_path, folder + '/source.md', old)
    write(tmp_path, folder + '/source-binding.json',
          {'task_id': 'previous', 'body_path': 'story/0001/chapter.md', 'body_sha256': sha(old_path)})
    receipt = {'accepted': True, 'task_id': 'previous', 'before_sha256': sha(old_path),
               'after_sha256': sha(current_path), 'book_contract_sha256': contract_sha}
    write(tmp_path, folder + '/receipt.json', receipt)
    out = m.prepare(tmp_path, '0001', 'with-addition', parallel=True, protocol=2)
    model = json.loads((tmp_path / out['reader_blind_model']).read_bytes())
    assert model['new_passage_refs'] == ['p0005']
    assert 'SECRET_SCOPE' not in str(model) and 'SECRET_INTENT' not in str(model)
    write(tmp_path, folder + '/receipt.json', {**receipt, 'after_sha256': sha(old_path)})
    out = m.prepare(tmp_path, '0001', 'without-proven-addition', parallel=True, protocol=2)
    assert json.loads((tmp_path / out['reader_blind_model']).read_bytes())['new_passage_refs'] == []
