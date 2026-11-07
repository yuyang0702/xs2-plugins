import asyncio
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_length_quality import PLUGIN, policy, quality, write


def definition():
    return json.loads((PLUGIN / 'resources/workflows/polish/definition.json').read_text(encoding='utf-8'))


def prose(count):
    return '\n\n'.join('衣'*min(100, count-index) for index in range(0, count, 100))


def managed(root):
    write(root, 'story/0001/chapter.md', prose(4708))
    write(root, 'quality/author.md', '保留已经落实的当场交易，不重写事实。')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '4800-5200', 'author_feedback_file': 'quality/author.md'}}
    state.update(policy().next_action(root, state, 'polish')['updates'])
    write(root, '.novel-project.json', json.dumps(state, ensure_ascii=False))
    return state


def cli(root, scope):
    script = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    result = subprocess.run([sys.executable, str(script), 'guidance', '--chapter', '0001', '--target', '4800-5200', '--scope', scope], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert result.returncode == 0, result.stderr
    from src.workflow.nodes.script import _parse_wf_vars
    return _parse_wf_vars(result.stdout)


def test_scope_is_derived_from_receipt_not_persistent_input(tmp_path):
    state = managed(tmp_path)
    assert policy().parameters(state, definition())['polish_pass'] == 'length_only'
    state['values']['author_feedback_file'] = 'quality/author.md'
    state['values']['polish_pass'] = 'length_only'
    assert policy().parameters(state, definition())['polish_pass'] == 'content'


def test_focused_cli_uses_current_body_and_real_file_injection(tmp_path):
    state = managed(tmp_path)
    write(tmp_path, 'cache/pl/body.json', '{"body":"OLD PL MUST NOT RETURN"}')
    write(tmp_path, 'story/0001/chapter.md', prose(4597))
    outputs = cli(tmp_path, 'length_only')
    assert outputs['polish_pass'] == 'length_only'
    assert outputs['critique_file'] == '' and outputs['reader_report_file'] == ''
    data = json.loads((tmp_path / outputs['pl_body_file']).read_text(encoding='utf-8'))
    assert data['body'].replace('\r\n', '\n') == prose(4597)
    from src.workflow.definition import WorkflowDef
    from src.workflow.variable_resolution import resolve_placeholders
    d = definition(); wf = WorkflowDef.from_dict(d)
    values = {v['key']: v.get('default', '') for v in d['variables']}
    values.update(state['values']); values.update(outputs)
    pp = next(n for n in d['nodes'] if n['id'] == 'agent_pp')
    prompt = asyncio.run(resolve_placeholders(pp['first_message'], values, wf.variables, str(tmp_path)))
    assert 'OLD PL MUST NOT RETURN' not in prompt
    assert '仅做字数' in prompt and '203' in prompt
    assert '{{length_execution_context}}' not in prompt


def test_edited_managed_feedback_falls_back_without_overriding_content_inputs(tmp_path):
    state = managed(tmp_path)
    file = tmp_path / state['values']['author_feedback_file']
    file.write_text(file.read_text(encoding='utf-8') + '\n作者新增事实修改', encoding='utf-8')
    outputs = cli(tmp_path, 'length_only')
    assert outputs['polish_pass'] == 'content'
    assert outputs['length_execution_context'] == ''
    assert 'pl_body_file' not in outputs and 'critique_file' not in outputs
    assert '作者新增事实修改' in file.read_text(encoding='utf-8')


def test_focused_strategy_migrates_old_revision_budget_once_and_keeps_total(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4708)
    state = {'readerRepairCount': 2, 'lengthRepairCycle': 2, 'lengthRepairCount': 3, 'lengthRepairTotal': 6,
             'autoLengthRepairLimit': 3, 'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    first = policy().next_action(tmp_path, state, 'polish')
    assert first['action'] == 'advance'
    state.update(first['updates'])
    assert state['lengthRepairStrategy'] == quality().LENGTH_REPAIR_STRATEGY
    assert state['lengthRepairCount'] == 1 and state['lengthRepairTotal'] == 7
    for _ in range(2): state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    assert policy().next_action(tmp_path, state, 'polish')['action'] == 'pause'
    assert state['lengthRepairTotal'] == 9
    state['readerRepairCount'] = 0; state['lengthRepairCycle'] = 0; state.pop('lengthRepairStrategy')
    assert policy().next_action(tmp_path, state, 'polish')['stage'] == 'reader-sim'


@pytest.mark.parametrize('scope,agents', [('length_only', ['agent_pp', 'agent_fragment_review']), ('content', ['agent_sc', 'agent_pl', 'agent_pp'])])
def test_real_engine_branch_executes_only_existing_selected_agents(tmp_path, monkeypatch, scope, agents):
    from src.workflow.definition import WorkflowDef, WorkflowTask, WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin, NodeResult, registry
    calls = []
    class Agent(BaseNodePlugin):
        node_type = 'agent'
        async def execute(self, ctx):
            calls.append(ctx.node_def.id)
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type = 'script'
        async def execute(self, ctx):
            return NodeResult(status='completed', outputs={'polish_pass': scope} if ctx.node_def.id == 'script_length_context' else {})
    monkeypatch.setitem(registry._plugins, 'agent', Agent)
    monkeypatch.setitem(registry._plugins, 'script', Script)
    wf = WorkflowDef.from_dict(definition())
    assert wf.validate() == []
    engine = WorkflowEngine(SimpleNamespace(sessions={}, main_session_id=''))
    async def no_save(*args, **kwargs): pass
    monkeypatch.setattr(engine, '_save_task_state', no_save)
    monkeypatch.setattr(engine, '_push_wf_task_update', lambda *args: None)
    task = WorkflowTask(workflow_id=wf.workflow_id, status='running', snapshot_definition=wf.to_dict(), parameter_values={'polish_pass': scope})
    async def run():
        return await engine._execute_plan_segment(definition=wf, task=task, execution_plan=wf.get_execution_plan(), disabled_ids=set(), shared_ws=tmp_path, parent_id='main', on_node_started=lambda state: None, needs_approval=False, run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    assert asyncio.run(run()) == 'completed'
    assert calls == agents


def test_normal_scope_never_overrides_regular_editor_inputs(tmp_path):
    managed(tmp_path)
    outputs = cli(tmp_path, 'content')
    assert outputs['polish_pass'] == 'content'
    assert outputs['length_execution_context'] == ''
    assert not {'pl_body_file', 'critique_file', 'reader_report_file'} & outputs.keys()


def test_focused_ready_aborts_on_author_edit_and_never_modifies_body(tmp_path):
    state = managed(tmp_path)
    before = (tmp_path / 'story/0001/chapter.md').read_bytes()
    feedback = tmp_path / state['values']['author_feedback_file']
    feedback.write_text(feedback.read_text(encoding='utf-8') + '作者批准的新事实', encoding='utf-8')
    script = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    result = subprocess.run([sys.executable, str(script), 'focused-ready', '--chapter', '0001', '--target', '4800-5200'], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert (tmp_path / 'story/0001/chapter.md').read_bytes() == before
    assert '作者批准的新事实' in feedback.read_text(encoding='utf-8')


def test_focused_history_does_not_overwrite_old_strategy_attempt(tmp_path):
    old = write(tmp_path, 'quality/length-repairs/0001/cycle-02/attempt-01-old/instructions.md', 'old strategy history')
    before = old.read_bytes()
    write(tmp_path, 'story/0001/chapter.md', '衣' * 4597)
    state = {'readerRepairCount': 2, 'lengthRepairCycle': 2, 'lengthRepairCount': 3, 'lengthRepairTotal': 6,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    action = policy().next_action(tmp_path, state, 'polish')
    receipt = action['updates']['lengthRepairFeedback']
    assert receipt['strategy'] == quality().LENGTH_REPAIR_STRATEGY and ('/'+quality().LENGTH_REPAIR_STRATEGY+'/') in receipt['path']
    assert old.read_bytes() == before


def test_changed_original_feedback_reaches_content_agents_via_actual_variables(tmp_path):
    state = managed(tmp_path)
    write(tmp_path, 'quality/author.md', 'NEW AUTHOR REQUIREMENT 保留新批准的交割条件')
    outputs = cli(tmp_path, 'length_only')
    assert outputs['polish_pass'] == 'content'
    assert outputs['author_feedback_file'] == 'quality/author.md'
    from src.workflow.definition import WorkflowDef
    from src.workflow.variable_resolution import resolve_placeholders
    d = definition(); wf = WorkflowDef.from_dict(d)
    values = {v['key']: v.get('default', '') for v in d['variables']}
    values.update(state['values']); values.update(outputs)
    for node_id in ['agent_sc', 'agent_pp']:
        prompt = asyncio.run(resolve_placeholders(next(n['first_message'] for n in d['nodes'] if n['id'] == node_id), values, wf.variables, str(tmp_path)))
        assert 'NEW AUTHOR REQUIREMENT' in prompt


def test_simultaneous_author_edits_to_managed_and_original_pause(tmp_path):
    state = managed(tmp_path)
    write(tmp_path, 'quality/author.md', 'NEW SOURCE REQUIREMENT')
    file = tmp_path / state['values']['author_feedback_file']
    file.write_text(file.read_text(encoding='utf-8') + 'NEW MANAGED REQUIREMENT', encoding='utf-8')
    with pytest.raises(ValueError): quality().prepare_execution(tmp_path, '0001', '4800-5200', 'length_only')


def publish(root, outputs):
    script = PLUGIN / 'resources/script-library/nvl/polish_post/polish_post.py'
    return subprocess.run([sys.executable, str(script), '--body-json', 'cache/pp/body.json', '--output', 'story/0001/chapter.md',
        '--expected-body-sha', outputs['length_expected_body_sha'], '--focused-guard', outputs['length_commit_guard'],
        '--focused-guard-sha', outputs['length_commit_guard_sha']], cwd=root, capture_output=True)


def test_actual_focused_commit_accepts_unchanged_inputs_then_rejects_model_runtime_edits(tmp_path):
    managed(tmp_path)
    outputs = cli(tmp_path, 'length_only')
    write(tmp_path, 'cache/pp/body.json', '{"body":"NEW MODEL BODY"}')
    success = publish(tmp_path, outputs)
    assert success.returncode == 0, success.stderr
    managed(tmp_path)
    outputs = cli(tmp_path, 'length_only')
    write(tmp_path, 'story/0001/chapter.md', 'AUTHOR NEW BODY')
    refused = publish(tmp_path, outputs)
    assert refused.returncode != 0
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == 'AUTHOR NEW BODY'


def test_focused_commit_rejects_feedback_edit_while_model_runs(tmp_path):
    managed(tmp_path)
    outputs = cli(tmp_path, 'length_only')
    before = (tmp_path / 'story/0001/chapter.md').read_bytes()
    write(tmp_path, 'quality/author.md', 'AUTHOR CHANGED DURING MODEL RUN')
    write(tmp_path, 'cache/pp/body.json', '{"body":"STALE MODEL BODY"}')
    refused = publish(tmp_path, outputs)
    assert refused.returncode != 0
    assert (tmp_path / 'story/0001/chapter.md').read_bytes() == before


def test_focused_ready_checks_existing_base_without_rebasing_author_changes(tmp_path):
    managed(tmp_path)
    outputs = cli(tmp_path, 'length_only')
    base = tmp_path / outputs['pl_body_file']; before = base.read_bytes()
    script = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    command = [sys.executable, str(script), 'focused-ready', '--chapter', '0001', '--target', '4800-5200',
        '--expected-body-sha', outputs['length_expected_body_sha'], '--focused-guard', outputs['length_commit_guard'],
        '--focused-guard-sha', outputs['length_commit_guard_sha']]
    assert subprocess.run(command, cwd=tmp_path, capture_output=True).returncode == 0
    write(tmp_path, 'story/0001/chapter.md', 'AUTHOR NEW BODY')
    assert subprocess.run(command, cwd=tmp_path, capture_output=True).returncode != 0
    assert base.read_bytes() == before
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == 'AUTHOR NEW BODY'


def test_legacy_receipt_without_source_hash_uses_latest_source_in_content_mode(tmp_path):
    state = managed(tmp_path)
    state['lengthRepairFeedback'].pop('source_sha256')
    write(tmp_path, '.novel-project.json', json.dumps(state, ensure_ascii=False))
    write(tmp_path, 'quality/author.md', 'NEW LEGACY SOURCE')
    outputs = cli(tmp_path, 'length_only')
    assert outputs['polish_pass'] == 'content' and outputs['author_feedback_file'] == 'quality/author.md'
    assert outputs['length_expected_body_sha'] == '' and outputs['length_commit_guard'] == ''


def test_normal_content_publish_still_has_no_focused_guard(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', 'OLD BODY')
    write(tmp_path, 'cache/pp/body.json', '{"body":"NORMAL CONTENT BODY"}')
    script = PLUGIN / 'resources/script-library/nvl/polish_post/polish_post.py'
    done = subprocess.run([sys.executable, str(script), '--body-json', 'cache/pp/body.json', '--output', 'story/0001/chapter.md',
        '--expected-body-sha', '', '--focused-guard', '', '--focused-guard-sha', ''], cwd=tmp_path, capture_output=True)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == 'NORMAL CONTENT BODY'
