"""Fact-compatible padding must not bypass grounded expression review."""
import copy
import json
from types import SimpleNamespace
import asyncio

import pytest
from test_length_quality import PLUGIN, quality
from test_fragment_review import reviewed


def report(body, verdict='revise', priority='medium'):
    return {'compatible': True, 'issues': [], 'expression_review': {
        'verdict': verdict, 'issues': [{'category': 'action_dilation', 'priority': priority,
            'excerpts': [body], 'impact': '反复收手与停手没有改变现场判断，拖住原有交涉。',
            'goal': '合并同一结果中的动作，把注意留给对方的回应。'}]}}


def commit(root, outputs, binding):
    return quality().focused_commit(root, '0001', outputs['length_expected_body_sha'],
        outputs['length_commit_guard'], outputs['length_commit_guard_sha'], 'task-review',
        binding['fragment_review_binding'], binding['fragment_review_binding_sha'], binding['fragment_review_result'])


def test_fact_pass_expression_revise_keeps_existing_body_and_saves_reason(tmp_path):
    body='乙'*35+'她把手收回来，又放回去。她停了停，再慢慢收手，仍未回答。'
    _, outputs, raw, binding=reviewed(tmp_path, body, report(body))
    result=commit(tmp_path, outputs, binding)
    receipt=json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf8'))
    assert not receipt['accepted'] and '表达审查' in receipt['rejection_reason']
    assert 'action_dilation' in receipt['rejection_reason']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


@pytest.mark.parametrize('patch', [
    {'excerpts':['不存在的引文']}, {'excerpts':[]}, {'priority':'optional'},
    {'impact':''}, {'goal':''}, {'category':'sentence_too_long'},
])
def test_expression_rejection_requires_literal_candidate_evidence_and_reading_impact(tmp_path, patch):
    body='乙'*35+'丁'*30;r=report(body);r['expression_review']['issues'][0].update(patch)
    _, outputs, raw, binding=reviewed(tmp_path, body, r)
    with pytest.raises(ValueError):commit(tmp_path, outputs, binding)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


@pytest.mark.parametrize('expression', [None, {}, {'verdict':'revise','issues':[]},
    {'verdict':'pass','issues':[report('乙')['expression_review']['issues'][0]]}])
def test_present_malformed_or_inconsistent_expression_report_never_silently_passes(tmp_path, expression):
    _, outputs, raw, binding=reviewed(tmp_path, '乙'*35+'丁'*30,
        {'compatible':True,'issues':[], 'expression_review':expression})
    with pytest.raises(ValueError):commit(tmp_path, outputs, binding)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


@pytest.mark.parametrize('legacy', [True, False])
def test_old_fact_report_and_new_pass_with_optional_low_issue_remain_usable(tmp_path, legacy):
    body='乙'*35+'丁'*30
    r={'compatible':True,'issues':[]} if legacy else report(body,'pass','low')
    _, outputs, _, binding=reviewed(tmp_path, body, r)
    result=commit(tmp_path, outputs, binding)
    assert json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf8'))['accepted']


def execute(root, report_value):
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    definition=json.loads((PLUGIN/'resources/workflows/polish/definition.json').read_text(encoding='utf8'))
    wf=WorkflowDef.from_dict(definition);node=next(n for n in wf.nodes if n.id=='agent_fragment_review')
    class Manager:
        sessions={}
        async def create_sub_session(self, **kwargs):
            self.sessions['r']=SimpleNamespace(record=[{'type':'user','content':'review'},
                {'type':'assistant','content':json.dumps(report_value,ensure_ascii=False)}])
            kwargs['on_auto_complete']('r','done','success','')
            return {'success':True,'session_id':'r'}
    return asyncio.run(AgentNode().execute(NodeContext(definition=wf,node_def=node,
        node_state=NodeExecutionState(node_id=node.id),session_manager=Manager(),shared_ws=root,
        parameter_values={'fragment_review_input':'input.json','fragment_review_report_path':'review.json'})))


def test_current_generation_requires_expression_review_before_output_is_written(tmp_path):
    result=execute(tmp_path,{'compatible':True,'issues':[]})
    assert result.status=='failed' and not (tmp_path/'review.json').exists()


@pytest.mark.parametrize('expression', [
    {'verdict':'pass','issues':[]},report('她托住灯底。')['expression_review'],
])
def test_actual_agent_accepts_separate_fact_and_expression_conclusions(tmp_path, expression):
    r={'compatible':True,'issues':[],'expression_review':copy.deepcopy(expression)}
    result=execute(tmp_path,r)
    assert result.status=='completed'
    assert json.loads((tmp_path/'review.json').read_text(encoding='utf8'))==r


def test_cross_selection_semantic_repetition_has_candidate_and_grounded_context_evidence(tmp_path):
    body='乙'*35+'丁'*30;r=report(body)
    r['expression_review']['issues'][0].update(category='semantic_redundancy',context_excerpts=['甲'*20])
    _,outputs,raw,binding=reviewed(tmp_path,body,r)
    result=commit(tmp_path,outputs,binding)
    receipt=json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf8'))
    assert not receipt['accepted'] and 'semantic_redundancy' in receipt['rejection_reason']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw
    context=json.loads((tmp_path/binding['fragment_review_input']).read_text(encoding='utf8'))
    start,end=context['selection_range']
    assert context['current_body'][start:end]==context['selected_text']


@pytest.mark.parametrize('quote',['未在冻结正文出现','乙'*20,'丁'*20])
def test_fake_or_selected_original_text_is_not_outside_context_evidence(tmp_path,quote):
    body='乙'*35+'丁'*30;r=report(body)
    r['expression_review']['issues'][0]['context_excerpts']=[quote]
    _,outputs,raw,binding=reviewed(tmp_path,body,r)
    with pytest.raises(ValueError,match='上下文'):
        commit(tmp_path,outputs,binding)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_context_quote_cannot_jump_across_the_removed_selection(tmp_path):
    body='乙'*35+'丁'*30;r=report(body)
    _,outputs,raw,binding=reviewed(tmp_path,body,r)
    context=json.loads((tmp_path/binding['fragment_review_input']).read_text(encoding='utf8'))
    start,end=context['selection_range'];quote=context['current_body'][:start][-4:]+context['current_body'][end:][:4]
    from test_fragment_review import write
    r['expression_review']['issues'][0]['context_excerpts']=[quote]
    binding['fragment_review_result']=json.dumps(r,ensure_ascii=False)
    write(tmp_path,binding['fragment_review_report_path'],binding['fragment_review_result'])
    with pytest.raises(ValueError,match='上下文'):
        commit(tmp_path,outputs,binding)
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_legacy_context_can_be_resolved_without_new_selection_offsets():
    q=quality()
    assert q.expression_context_regions({'current_body':'前段。\n选段。\n后段。','selected_text':'选段。'})==['前段。\n','\n后段。']


def test_retry_preserves_legacy_review_input_bytes_and_binding(tmp_path):
    import hashlib
    from test_fragment_review import write
    body='乙'*35+'丁'*30;r=report(body)
    r['expression_review']['issues'][0]['context_excerpts']=['甲'*20]
    _,outputs,raw,binding=reviewed(tmp_path,body,r)
    input_file=tmp_path/binding['fragment_review_input']
    old=json.loads(input_file.read_text(encoding='utf8'));old.pop('selection_range')
    write(tmp_path,binding['fragment_review_input'],json.dumps(old,ensure_ascii=False,indent=2)+'\n')
    record=json.loads((tmp_path/binding['fragment_review_binding']).read_text(encoding='utf8'))
    record['input_sha256']=hashlib.sha256(input_file.read_bytes()).hexdigest()
    write(tmp_path,binding['fragment_review_binding'],json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    before=input_file.read_bytes();stamp=input_file.stat().st_mtime_ns
    retried=quality().prepare_fragment_review(tmp_path,'0001',outputs['length_expected_body_sha'],
        outputs['length_commit_guard'],outputs['length_commit_guard_sha'],'task-review')
    assert input_file.read_bytes()==before and input_file.stat().st_mtime_ns==stamp
    binding.update(retried)
    result=commit(tmp_path,outputs,binding)
    assert not json.loads((tmp_path/result['length_attempt_receipt']).read_text(encoding='utf8'))['accepted']
    assert (tmp_path/'story/0001/chapter.md').read_bytes()==raw


def test_old_ambiguous_selection_does_not_guess_which_copy_is_outside():
    with pytest.raises(ValueError,match='不唯一'):
        quality().expression_context_regions({'current_body':'相同句。相同句。','selected_text':'相同句。'})
