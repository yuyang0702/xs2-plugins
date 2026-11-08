import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_expression_evidence import checks, module

PLUGIN = Path(__file__).resolve().parents[1]
REPORT = {'verdict': 'revise', 'continue_reading_score': 62, 'summary': '需要返修',
          'revision_scope': {'mode': 'unrestricted', 'summary': '完整审阅', 'assessments': []},
          'dimensions': {'middle_pacing': {'verdict': 'slow', 'note': '重复'}},
          'issues': [{'location': '中段', 'impact': '节奏重复', 'goal': '保留承重行动', 'priority': 'high'}],
          'repair_constraints': ['保留既定事实'],
          'fact_review': {'verdict': 'pass', 'summary': '情节成立'},
          'expression_review': {'verdict': 'revise', 'summary': '交谈重复解释', 'issues': [
              {'id': 'context-1', 'location': '中段', 'priority': 'medium', 'excerpts': ['我又解释一遍。'],
               'impact': '同一回答使交谈停住。', 'goal': '合并重复说明。'}]}}
REPORT['expression_checks'] = checks(module())
for row in REPORT['expression_checks']: row['excerpts'] = ['我又解释一遍。']


def definition():
    return json.loads((PLUGIN / 'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8'))


def execute(root, record):
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    wf = WorkflowDef.from_dict(definition())
    node = next(n for n in wf.nodes if n.id == 'agent_reader')
    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            self.sessions['reader'] = SimpleNamespace(record=record)
            kwargs['on_auto_complete']('reader', 'done', 'success', '')
            return {'success': True, 'session_id': 'reader'}
    return asyncio.run(AgentNode().execute(NodeContext(definition=wf, node_def=node,
        node_state=NodeExecutionState(node_id=node.id), session_manager=Manager(), shared_ws=root,
        parameter_values={'chapter_number': '0001', 'language': '中文',
                          'reader_context_report_path': 'story/0001/reader_report.json'})))


def test_reader_declares_current_turn_single_report_schema_and_automatic_finish():
    node = next(n for n in definition()['nodes'] if n['id'] == 'agent_reader')
    assert node['auto_flow'] is True and node['enable_complete_node_task'] is False
    assert node['auto_retry_count'] == 2 and node['auto_retry_interval_seconds'] == 5
    assert node['node_params']['output_selection'] == 'completion_tool_message'
    assert not node.get('model_override')


@pytest.mark.parametrize('old', [False, True])
def test_actual_single_assistant_envelope_plus_report_is_rejected_before_write(tmp_path, old):
    target = tmp_path / 'story/0001/reader_report.json'
    if old:
        target.parent.mkdir(parents=True);target.write_text('previous report', encoding='utf-8')
    envelope = {'status': 'success', 'summary': 'done', 'artifact_path': '', 'error': ''}
    content = json.dumps(envelope) + json.dumps(REPORT)
    result = execute(tmp_path, [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': content}])
    assert result.status == 'failed' and result.outputs == {}
    if old: assert target.read_text(encoding='utf-8') == 'previous report'
    else: assert not target.exists()


@pytest.mark.parametrize('tool', [False, True])
def test_direct_and_same_message_completion_tool_report_are_accepted(tmp_path, tool):
    record = [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(REPORT)}]
    if tool:
        record[1]['tool_calls'] = [{'id': 'complete', 'function': {'name': 'complete_task', 'arguments': json.dumps({'status': 'success', 'artifact_path': ''})}}]
        record += [{'type': 'tool', 'tool_call_id': 'complete', 'content': '{"success":true,"status":"success"}'},
                   {'type': 'assistant', 'content': 'The review is ready.'}]
    result = execute(tmp_path, record)
    assert result.status == 'completed'
    assert json.loads((tmp_path / 'story/0001/reader_report.json').read_text(encoding='utf-8')) == REPORT


@pytest.mark.parametrize('patch', [{'continue_reading_score': 101}, {'continue_reading_score': 62.5}, {'verdict': 'success'}, {'issues': None}, {'repair_constraints': [None]}])
def test_invalid_new_report_shape_is_rejected_before_write(tmp_path, patch):
    report = {**copy.deepcopy(REPORT), **patch}
    result = execute(tmp_path, [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(report)}])
    assert result.status == 'failed'
    assert not (tmp_path / 'story/0001/reader_report.json').exists()
