"""Real gate CLI and host retry feedback/budget, without model calls or book data."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_character_semantic_review import MODULE, gate, setup, apply


RESOURCES = MODULE.parents[3]
AGENT = 'agent_card_semantic_review'
VALIDATOR = 'script_apply_card_review'


def workflow():
    return json.loads((RESOURCES / 'workflows/character/definition.json').read_text(encoding='utf-8'))


def missing_review(gate, tmp_path):
    variables, prepared, request, result = setup(gate, tmp_path)
    result['characters'][0]['changes'] = [c for c in result['characters'][0]['changes'] if c['field'] != 'personality']
    return variables, prepared, request, result


def quote_review(gate, tmp_path, *, combined=False):
    variables, prepared, request, result = missing_review(gate, tmp_path) if combined else setup(gate, tmp_path)
    entry = request['characters'][0]['editable_persona'][0]
    result['characters'][0]['persona_edits'] = [{'record_path': entry['record_path'], 'field_path': entry['field_path'],
        'before': entry['original'], 'after': '希望自主修好屋顶', 'reason': '保留动机，不指定手段',
        'source_id': 'world', 'evidence_quote': '尚未把蓝伞归还给顾石'}]
    return variables, prepared, request, result


def cli(variables, prepared, result, *, retry=True):
    text = json.dumps(result, ensure_ascii=False)
    Path(variables['card_review_result_file']).write_text(text, encoding='utf-8')
    args = [sys.executable, str(MODULE), 'apply', '--batch-dir', variables['card_batch_dir'],
            '--binding-sha', prepared['card_review_binding_sha']]
    if retry: args.append('--retry-review')
    return subprocess.run(args, input=text, cwd=Path(variables['card_batch_dir']).parents[2],
                          env={**os.environ, 'PYTHONUTF8': '1', 'TASK_ID': 'task-1'},
                          capture_output=True, text=True, encoding='utf-8')


def test_plain_python_apply_raises_typed_exact_missing_field_diagnostic(gate, tmp_path):
    variables, prepared, _, result = missing_review(gate, tmp_path)
    with pytest.raises(gate.ReviewCorrectionNeeded) as failure:
        apply(gate, variables, prepared, result)
    assert failure.value.missing_fields == {'林叶': ['personality']}
    assert '林叶' in str(failure.value) and 'personality' in str(failure.value)
    assert 'character_review_missing_evidence' in str(failure.value)
    assert not (Path(variables['card_batch_dir']) / 'candidate').exists()


@pytest.mark.parametrize('combined', [False, True])
def test_nonexact_quote_and_missing_rows_aggregate_safe_diagnostics(gate, tmp_path, combined):
    variables, prepared, _, result = quote_review(gate, tmp_path, combined=combined)
    with pytest.raises(gate.ReviewCorrectionNeeded) as failure:
        apply(gate, variables, prepared, result)
    error = failure.value
    assert error.missing_fields == ({'林叶': ['personality']} if combined else {})
    assert error.quote_mismatches == [{'name': '林叶', 'record_path': 'cache/short/characters.json',
        'field_path': ['want'], 'source_id': 'world'}]
    assert 'character_review_quote_mismatch' in str(error)
    assert '尚未把蓝伞归还给顾石' not in str(error)
    assert '希望自主修好屋顶' not in str(error)
    assert not (Path(variables['card_batch_dir']) / 'candidate').exists()


def test_semantic_quote_mismatch_reports_field_without_duplicating_missing_row(gate, tmp_path):
    variables, prepared, _, result = setup(gate, tmp_path)
    result['characters'][0]['changes'][0]['evidence_quote'] = '调换原文顺序的非精确引文'
    with pytest.raises(gate.ReviewCorrectionNeeded) as failure:
        apply(gate, variables, prepared, result)
    assert failure.value.missing_fields == {}
    assert failure.value.quote_mismatches == [{'name': '林叶', 'field': 'facts', 'source_id': 'world'}]
    assert '调换原文顺序的非精确引文' not in str(failure.value)


@pytest.mark.parametrize('fault', ['unknown_source', 'foreign_draft', 'facts_from_draft', 'path', 'before', 'collision'])
def test_quote_correction_never_masks_authority_path_or_collision_errors(gate, tmp_path, fault):
    variables, prepared, _, result = quote_review(gate, tmp_path, combined=True)
    reviewed = result['characters'][0]
    if fault == 'unknown_source': reviewed['persona_edits'][0]['source_id'] = 'unknown'
    elif fault == 'foreign_draft': reviewed['persona_edits'][0]['source_id'] = 'draft-persona.别人'
    elif fault == 'facts_from_draft': reviewed['changes'][0]['source_id'] = 'draft-persona.林叶'
    elif fault == 'path': reviewed['persona_edits'][0]['field_path'] = ['name']
    elif fault == 'before': reviewed['persona_edits'][0]['before'] = '不是真实原文'
    elif fault == 'collision': (tmp_path / 'meta/character_profiles.md').write_text('keep bytes', encoding='utf-8')
    response = cli(variables, prepared, result)
    assert response.returncode != 0
    assert 'WF_REJECT_UPSTREAM' not in response.stdout


@pytest.mark.parametrize('retry', [False, True])
def test_cli_retry_requires_explicit_flag_and_targets_only_semantic_agent(gate, tmp_path, retry):
    from src.workflow.nodes.script import _parse_reject_upstream
    variables, prepared, _, result = missing_review(gate, tmp_path)
    response = cli(variables, prepared, result, retry=retry)
    rejection = _parse_reject_upstream(response.stdout)
    if retry:
        assert rejection is not None, response.stderr
        reason, target = rejection
        assert target == AGENT
        assert 'personality' in reason and '林叶' in reason
    else:
        assert rejection is None
        assert response.returncode != 0 and 'personality' in response.stderr
    assert not (tmp_path / 'meta/character_profiles.md').exists()
    assert not (Path(variables['card_batch_dir']) / 'candidate').exists()


@pytest.mark.parametrize('fault', ['blocked', 'source', 'world', 'draft', 'raw', 'binding', 'collision', 'candidate', 'publication', 'persona_path'])
def test_missing_evidence_does_not_mask_nonretryable_failure(gate, tmp_path, fault):
    variables, prepared, _, result = missing_review(gate, tmp_path)
    batch = Path(variables['card_batch_dir'])
    if fault == 'blocked': result['status'] = 'blocked'
    elif fault == 'source': result['characters'][0]['changes'][0]['source_id'] = 'nonexistent'
    elif fault == 'world': (tmp_path / 'meta/world_foundation.md').write_text('changed world', encoding='utf-8')
    elif fault == 'draft': (Path(variables['card_draft_dir']) / 'meta/character_profiles.md').write_text('changed draft', encoding='utf-8')
    elif fault == 'raw': (batch / 'raw/cache/short/characters.json').write_text('{}', encoding='utf-8')
    elif fault == 'binding': prepared['card_review_binding_sha'] = '0' * 64
    elif fault == 'collision': (tmp_path / 'meta/character_profiles.md').write_text('keep user bytes', encoding='utf-8')
    elif fault == 'candidate': (batch / 'candidate').mkdir()
    elif fault == 'publication': (batch / 'publication.json').write_text('{}', encoding='utf-8')
    elif fault == 'persona_path':
        result['characters'][0]['persona_edits'] = [{'record_path': 'cache/short/characters.json',
            'field_path': ['name'], 'before': '林叶', 'after': '改名', 'reason': '非法身份修改',
            'source_id': 'world', 'evidence_quote': '林叶'}]
    response = cli(variables, prepared, result)
    assert response.returncode != 0
    assert 'WF_REJECT_UPSTREAM' not in response.stdout


@pytest.mark.parametrize('error', ['blocked authority', 'stale result', 'render failed', 'publication collision', 'source changed'])
def test_cli_never_tags_other_apply_errors(gate, monkeypatch, capsys, error):
    def fail(*_args): raise ValueError(error)
    monkeypatch.setattr(gate, 'apply', fail)
    monkeypatch.setattr(gate.sys, 'stdin', __import__('io').StringIO('{}'))
    with pytest.raises(SystemExit) as failure:
        gate.main(['apply', '--batch-dir', 'unused', '--binding-sha', 'unused', '--retry-review'])
    assert failure.value.code == 1
    output = capsys.readouterr()
    assert 'WF_REJECT_UPSTREAM' not in output.out
    assert error in output.err


def test_production_workflow_uses_existing_finite_retry_budget():
    nodes = {n['id']: n for n in workflow()['nodes']}
    assert nodes[VALIDATOR]['enable_reject_upstream'] is True
    assert '--retry-review' in nodes[VALIDATOR]['node_params']['script_argv']
    assert nodes[AGENT]['auto_retry_count'] == 2


def test_review_contract_requires_exact_changes_and_opening_time_state():
    prompts = json.loads((RESOURCES / 'prompts.json').read_text(encoding='utf-8'))['agents']
    text = '\n'.join(s['content'] for s in prompts['novel-character-semantic-review']['sections'])
    for term in ('逐字', '改述', 'changes', '开篇', '尚未发生', '关系'):
        assert term in text


def validator_node(tmp_path, monkeypatch):
    import src.config as config
    from src.workflow.definition import WorkflowNode
    node = copy.deepcopy(next(n for n in workflow()['nodes'] if n['id'] == VALIDATOR))
    node['node_params'].update(script_source='inline', script_name='validator')
    script = tmp_path / 'host-workflows/synthetic-review/script/validator.py'
    script.parent.mkdir(parents=True)
    script.write_text('import runpy\nrunpy.run_path(' + repr(str(MODULE)) + ', run_name="__main__")\n', encoding='utf-8')
    monkeypatch.setattr(config, 'WORKFLOWS_DIR', tmp_path / 'host-workflows')
    return WorkflowNode.from_dict(node)


@pytest.mark.parametrize('repair', [False, True])
@pytest.mark.parametrize('defect', ['missing', 'quote', 'combined'])
def test_native_scriptnode_engine_feedback_and_bounded_retry_exhaustion(gate, tmp_path, monkeypatch, repair, defect):
    from src.workflow.definition import WorkflowDef, WorkflowEdge, WorkflowNode, WorkflowRunRecord, WorkflowTask
    from src.workflow.engine import WorkflowEngine
    from src.workflow.failure_policy import activate_scheduled_retry
    from src.workflow.nodes.base import NodeContext
    from src.workflow.nodes.script import ScriptNode
    book = tmp_path / 'book'
    book.mkdir()
    variables, prepared, _, invalid = missing_review(gate, book) if defect == 'missing' else quote_review(gate, book, combined=defect == 'combined')
    valid = copy.deepcopy(invalid)
    if defect in ('missing', 'combined'):
        valid['characters'][0]['changes'].append({'field': 'personality', 'reason': '保留有据的人格表达',
            'source_id': 'author.human_intent', 'evidence_quote': '允许犹豫，也能求助'})
    if defect in ('quote', 'combined'):
        valid['characters'][0]['persona_edits'][0]['evidence_quote'] = '尚未归还'
    validator = validator_node(tmp_path, monkeypatch)
    original_agent = next(n for n in workflow()['nodes'] if n['id'] == AGENT)
    agent = WorkflowNode.from_dict(original_agent)
    definition = WorkflowDef(workflow_id='synthetic-review', nodes=[agent, validator],
        edges=[WorkflowEdge(source=AGENT, target=VALIDATOR)])
    definition._rebuild_caches()
    values = {**variables, **prepared}
    task = WorkflowTask(workflow_id=definition.workflow_id, task_id='task-1', status='running', parameter_values=values)

    class Engine(WorkflowEngine):
        def __init__(self):
            super().__init__(SimpleNamespace(sessions={}))
            self.messages = []
        async def _save_task_state(self, *_args): pass
        def _push_wf_task_update(self, *_args): pass
        async def _execute_node(self, definition, node, state, workspace, **kwargs):
            state.attempt_count += 1
            if node.id == AGENT:
                self.messages.append(node.first_message)
                result = valid if repair and len(self.messages) > 1 else invalid
                payload = json.dumps(result, ensure_ascii=False)
                Path(variables['card_review_result_file']).write_text(payload, encoding='utf-8')
                state.outputs = {'card_semantic_review_result': payload, '_output_file': variables['card_review_result_file']}
                kwargs['parameter_values'].update(state.outputs)
                state.status = 'completed'
                state.session_id = 'synthetic-session-' + str(len(self.messages))
            else:
                result = await ScriptNode().execute(NodeContext(definition=definition, node_def=node,
                    node_state=state, shared_ws=workspace, parameter_values=kwargs['parameter_values'],
                    workflow_id=definition.workflow_id, task_id='task-1', on_reject_upstream=kwargs['on_reject_upstream']))
                state.status = 'completed' if result.status == 'success' else 'failed'
                state.error, state.stdout, state.stderr = result.error, result.stdout, result.stderr
            return state

    engine = Engine()
    outcomes = []
    for _ in range(3):
        outcome = asyncio.run(engine._execute_node_sequence(definition=definition, task=task,
            node_ids=[AGENT, VALIDATOR], disabled_ids=set(), shared_ws=book, parent_id='synthetic-main',
            on_node_started=lambda _state: None, needs_approval=False,
            run_record=WorkflowRunRecord(workflow_id=definition.workflow_id)))
        outcomes.append(outcome)
        if outcome != 'retry_waiting': break
        assert not (book / 'meta/character_profiles.md').exists()
        task.node_states[AGENT] = activate_scheduled_retry(task.node_states[AGENT])
    state = task.node_states[AGENT]
    deterministic_stop=not repair and defect in ('quote','combined')
    assert len(engine.messages) == (2 if repair or deterministic_stop else 3)
    assert '下游校验反馈' not in engine.messages[0]
    assert '林叶' in engine.messages[1]
    assert ('personality' if defect == 'missing' else 'want') in engine.messages[1]
    assert '第 1/2 次重试' in engine.messages[1]
    assert state.automatic_retry_count == (1 if repair or deterministic_stop else 2)
    codes = (['character_review_missing_evidence'] if defect == 'missing' else
             ['character_review_quote_mismatch'] if defect == 'quote' else
             ['character_review_missing_evidence', 'character_review_quote_mismatch'])
    assert all(e['target_node_id'] == AGENT and e['error_codes'] == codes for e in state.rejection_history)
    if repair:
        assert outcomes == ['retry_waiting', 'completed']
        assert (book / 'meta/character_profiles.md').exists()
        assert state.rejection_history[-1]['resolution'] == 'passed'
    elif deterministic_stop:
        assert outcomes==['retry_waiting','failed']
        assert 'RETRY_STOP' in task.node_states[VALIDATOR].stderr
        assert not (book/'meta/character_profiles.md').exists()
    else:
        assert outcomes == ['retry_waiting', 'retry_waiting', 'failed']
        assert '第 2/2 次重试' in engine.messages[2]
        assert state.rejection_history[-1]['resolution'] == 'failed'
        assert not (book / 'meta/character_profiles.md').exists()
