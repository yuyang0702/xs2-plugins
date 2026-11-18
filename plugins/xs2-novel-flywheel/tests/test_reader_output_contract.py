import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
PLUGIN = Path(__file__).resolve().parents[1]
REPORT = {'summary': '门锁状态与既定事实有冲突。',
          'revision_scope': {'mode': 'unrestricted', 'summary': '整章范围'},
          'issues': [{'id': 'context-1', 'location': '中段', 'impact': '人物已遗失钥匙',
                      'goal': '保持钥匙归属一致', 'priority': 'high', 'claim': '她用旧钥匙打开了门。',
                      'source_path': 'meta/world_foundation.md', 'source_quote': '旧钥匙已经销毁。'}]}
RESOLUTIONS = {'blind_resolutions': [{'issue_id': 'blind-1', 'reason': '当前原文有明确反证。',
                                     'excerpts': ['她进了室内。', '她用新钥匙打开了门。']}]}


def definition():
    return json.loads((PLUGIN / 'resources/workflows/reader-sim/definition.json').read_text(encoding='utf-8'))


def execute(root, record, node_id='agent_reader'):
    from src.workflow.definition import WorkflowDef
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    wf = WorkflowDef.from_dict(definition())
    node = next(n for n in wf.nodes if n.id == node_id)
    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            self.sessions['reader'] = SimpleNamespace(record=record)
            kwargs['on_auto_complete']('reader', 'done', 'success', '')
            return {'success': True, 'session_id': 'reader'}
    return asyncio.run(AgentNode().execute(NodeContext(definition=wf, node_def=node,
        node_state=NodeExecutionState(node_id=node.id), session_manager=Manager(), shared_ws=root,
        parameter_values={'chapter_number': '0001', 'language': '中文',
                          'reader_context_report_path': 'story/0001/reader_report.json',
                          'reader_preflight_raw_path': 'story/0001/context-preflight-raw.json'})))


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
    content = json.dumps(envelope) + json.dumps(RESOLUTIONS)
    result = execute(tmp_path, [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': content}])
    assert result.status == 'failed' and result.outputs == {}
    if old: assert target.read_text(encoding='utf-8') == 'previous report'
    else: assert not target.exists()


@pytest.mark.parametrize('tool', [False, True])
def test_direct_and_same_message_completion_tool_report_are_accepted(tmp_path, tool):
    record = [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(RESOLUTIONS)}]
    if tool:
        record[1]['tool_calls'] = [{'id': 'complete', 'function': {'name': 'complete_task', 'arguments': json.dumps({'status': 'success', 'artifact_path': ''})}}]
        record += [{'type': 'tool', 'tool_call_id': 'complete', 'content': '{"success":true,"status":"success"}'},
                   {'type': 'assistant', 'content': 'The review is ready.'}]
    result = execute(tmp_path, record)
    assert result.status == 'completed'
    assert json.loads((tmp_path / 'story/0001/reader_report.json').read_text(encoding='utf-8')) == RESOLUTIONS


@pytest.mark.parametrize('patch', [{'blind_resolutions': None}, {'verdict': 'success'}, {'issues': None},
                                   {'blind_resolutions': [{'issue_id':'blind-1', 'reason':'反证',
                                                          'excerpts':['同一处原文。']}]}])
def test_invalid_new_report_shape_is_rejected_before_write(tmp_path, patch):
    report = {**copy.deepcopy(RESOLUTIONS), **patch}
    result = execute(tmp_path, [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(report)}])
    assert result.status == 'failed'
    assert not (tmp_path / 'story/0001/reader_report.json').exists()


def test_independent_context_agent_accepts_a_report_without_blind_resolutions(tmp_path):
    record = [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(REPORT)}]
    result = execute(tmp_path, record, 'agent_context_reader')
    assert result.status == 'completed', result.error
    assert json.loads((tmp_path / 'story/0001/context-preflight-raw.json').read_text(encoding='utf-8')) == REPORT


def test_independent_context_rejects_a_finding_without_the_id_needed_for_scope(tmp_path):
    report = copy.deepcopy(REPORT)
    del report['issues'][0]['id']
    record = [{'type': 'user', 'content': 'review'}, {'type': 'assistant', 'content': json.dumps(report)}]
    result = execute(tmp_path, record, 'agent_context_reader')
    assert result.status == 'failed'
    assert "'id' is a required property" in result.error
    assert not list(tmp_path.rglob('*.json'))
