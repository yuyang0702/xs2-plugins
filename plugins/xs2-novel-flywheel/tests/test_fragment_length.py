import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from test_length_quality import PLUGIN, policy, quality, write
from test_focused_length import definition


def setup(root, raw=None):
    raw = raw or ('甲'*35 + '\n\n“' + '乙'*35 + '”\n\n' + '丙'*35).encode('utf-8')
    path = write(root, 'story/0001/chapter.md', '')
    path.write_bytes(raw)
    write(root, 'quality/author.md', '保持已确定事实与结局')
    state = {'values': {'chapter_number': '0001', 'target_word_count': '130-160', 'author_feedback_file': 'quality/author.md'}}
    state.update(policy().next_action(root, state, 'polish')['updates'])
    write(root, '.novel-project.json', json.dumps(state, ensure_ascii=False))
    outputs = quality().prepare_execution(root, '0001', '130-160', 'length_only')
    return state, outputs, raw


def commit(root, outputs, fragment, task_id='task-fragment-test'):
    write(root, 'cache/pp/body.json', json.dumps({'body': fragment}, ensure_ascii=False))
    script = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
    binding_path = f'quality/length-attempts/0001/{task_id}/review-binding.json'
    if (root/binding_path).is_file():
        stored=json.loads((root/binding_path).read_text(encoding='utf-8'))
        binding={'fragment_review_binding':binding_path,'fragment_review_binding_sha':hashlib.sha256((root/binding_path).read_bytes()).hexdigest(),'fragment_review_report_path':stored['report_path']}
    else:
        binding=quality().prepare_fragment_review(root,'0001',outputs['length_expected_body_sha'],outputs['length_commit_guard'],outputs['length_commit_guard_sha'],task_id)
    write(root,binding['fragment_review_report_path'],json.dumps({'compatible':True,'issues':[]}))
    env = {**os.environ, 'TASK_ID': task_id, 'PYTHONIOENCODING': 'utf-8'}
    result = subprocess.run([sys.executable, str(script), 'focused-commit', '--chapter', '0001', '--target', '130-160',
        '--expected-body-sha', outputs['length_expected_body_sha'], '--focused-guard', outputs['length_commit_guard'],
        '--focused-guard-sha', outputs['length_commit_guard_sha'], '--review-binding', binding['fragment_review_binding'], '--review-binding-sha', binding['fragment_review_binding_sha'], '--review-result', (root/binding['fragment_review_report_path']).read_text(encoding='utf-8')], cwd=root, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    from src.workflow.nodes.script import _parse_wf_vars
    variables = _parse_wf_vars(result.stdout.decode('utf-8'))
    receipt = json.loads((root / variables['length_attempt_receipt']).read_text(encoding='utf-8'))
    return variables, receipt


def test_fragment_expansion_is_plugin_composed_and_preserves_all_outside_bytes(tmp_path):
    raw = b'\xef\xbb\xbf' + ('甲'*35 + '\r\n\r\n“' + '乙'*35 + '”\r\n\r\n' + '丙'*35).encode('utf-8')
    state, outputs, original = setup(tmp_path, raw)
    guard = json.loads((tmp_path / outputs['length_commit_guard']).read_text(encoding='utf-8'))
    variables, receipt = commit(tmp_path, outputs, original[guard['fragment']['start']:guard['fragment']['end']].decode('utf-8')+'丁'*30)
    result = (tmp_path / 'story/0001/chapter.md').read_bytes()
    offset = guard['fragment']['start']
    assert result[:offset] == original[:offset]
    assert result.endswith(original[guard['fragment']['end']:])
    assert result.startswith(b'\xef\xbb\xbf') and b'\r\n\r\n' in result
    assert receipt['accepted'] is True and receipt['actual'] == 135
    assert receipt['task_id'] == 'task-fragment-test'
    task = {'task_id': receipt['task_id'], 'created_at': datetime.now(timezone.utc).isoformat(),
            'node_states': {'script_focused_commit': {'status': 'completed', 'outputs': variables}}}
    policy().verify_completion(tmp_path, state, 'polish', task)


@pytest.mark.parametrize('fragment', ['丁'*200, '', '乙'*35])
def test_rejected_fragment_is_real_completed_attempt_without_touching_body(tmp_path, fragment):
    state, outputs, original = setup(tmp_path)
    body = tmp_path / 'story/0001/chapter.md'
    os.utime(body, (1000000000, 1000000000)); before = body.stat().st_mtime_ns
    variables, receipt = commit(tmp_path, outputs, fragment)
    assert receipt['accepted'] is False and receipt['rejection_reason']
    assert body.read_bytes() == original and body.stat().st_mtime_ns == before
    assert (tmp_path / receipt['candidate_path']).is_file()
    task = {'task_id': receipt['task_id'], 'created_at': datetime.now(timezone.utc).isoformat(),
            'node_states': {'script_focused_commit': {'status': 'completed', 'outputs': variables}}}
    policy().verify_completion(tmp_path, state, 'polish', task)
    followup = policy().next_action(tmp_path, state, 'polish')
    assert followup['action'] == 'advance' and followup['updates']['lengthRepairCount'] == 2
    with pytest.raises(ValueError): policy().verify_completion(tmp_path, state, 'polish', {**task, 'task_id': 'wrong-task'})


def test_partial_fragment_progress_and_author_edit_protection(tmp_path):
    state, outputs, original = setup(tmp_path)
    guard = json.loads((tmp_path/outputs['length_commit_guard']).read_text(encoding='utf-8'))
    old = original[guard['fragment']['start']:guard['fragment']['end']].decode('utf-8')
    _, receipt = commit(tmp_path, outputs, old+'丁'*10)
    assert receipt['accepted'] and receipt['actual'] == 115 and receipt['status'] == 'accepted_partial'
    assert quality().count_prose((tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8-sig')) == 115
    state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    write(tmp_path, '.novel-project.json', json.dumps(state, ensure_ascii=False))
    outputs = quality().prepare_execution(tmp_path, '0001', '130-160', 'length_only')
    write(tmp_path, 'story/0001/chapter.md', 'AUTHOR NEW BODY')
    with pytest.raises((AssertionError, ValueError)): commit(tmp_path, outputs, '戊'*20, 'task-fragment-next')
    assert (tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8') == 'AUTHOR NEW BODY'


def test_fragment_system_contract_is_empty_for_content_and_local_for_focused(tmp_path):
    state, outputs, _ = setup(tmp_path)
    from src.workflow.definition import WorkflowDef
    from src.workflow.variable_resolution import resolve_placeholders
    d = definition(); wf = WorkflowDef.from_dict(d)
    pp = next(n for n in d['nodes'] if n['id'] == 'agent_pp')
    values = {v['key']: v.get('default', '') for v in d['variables']}; values.update(state['values']); values.update(outputs)
    assert '片段' in asyncio.run(resolve_placeholders(pp['system_prompt_template'], values, wf.variables, str(tmp_path)))
    normal = quality().prepare_execution(tmp_path, '0001', '130-160', 'content'); values.update(normal)
    assert asyncio.run(resolve_placeholders(pp['system_prompt_template'], values, wf.variables, str(tmp_path))) == ''


def test_fragment_strategy_reinitializes_v1_budget_once_without_losing_total(tmp_path):
    write(tmp_path, 'story/0001/chapter.md', '衣'*4360)
    state = {'readerRepairCount': 2, 'lengthRepairCycle': 2, 'lengthRepairCount': 3, 'lengthRepairTotal': 9,
             'lengthRepairStrategy': 'focused-v1', 'autoLengthRepairLimit': 3,
             'values': {'chapter_number': '0001', 'target_word_count': '4800-5200'}}
    state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    assert state['lengthRepairStrategy'] == quality().LENGTH_REPAIR_STRATEGY and state['lengthRepairTotal'] == 10
    for _ in range(2): state.update(policy().next_action(tmp_path, state, 'polish')['updates'])
    assert policy().next_action(tmp_path, state, 'polish')['action'] == 'pause'
    assert state['lengthRepairTotal'] == 12


def test_whole_chapter_echo_is_rejected_and_candidate_retained(tmp_path):
    state, outputs, original = setup(tmp_path)
    _, receipt = commit(tmp_path, outputs, original.decode('utf-8'))
    assert receipt['accepted'] is False
    assert (tmp_path / 'story/0001/chapter.md').read_bytes() == original


def test_focused_commit_replay_is_idempotent(tmp_path):
    state, outputs, raw = setup(tmp_path)
    guard = json.loads((tmp_path/outputs['length_commit_guard']).read_text(encoding='utf-8'))
    expanded = raw[guard['fragment']['start']:guard['fragment']['end']].decode('utf-8')+'丁'*30
    first_outputs, first = commit(tmp_path, outputs, expanded)
    before = (tmp_path / 'story/0001/chapter.md').read_bytes()
    next_outputs, again = commit(tmp_path, outputs, expanded)
    assert first_outputs == next_outputs and first == again
    assert (tmp_path / 'story/0001/chapter.md').read_bytes() == before


def test_long_fragment_replaces_only_frozen_paragraph_and_keeps_bom(tmp_path):
    raw = b'\xef\xbb\xbf' + ('甲'*35 + '\r\n\r\n“' + '乙'*35 + '”\r\n\r\n' + '丙'*35).encode('utf-8')
    state, _, _ = setup(tmp_path, raw)
    state['values']['target_word_count'] = '70-90'
    write(tmp_path, '.novel-project.json', json.dumps(state, ensure_ascii=False))
    outputs = quality().prepare_execution(tmp_path, '0001', '70-90', 'length_only')
    guard = json.loads((tmp_path / outputs['length_commit_guard']).read_text(encoding='utf-8'))
    assert guard['fragment']['kind'] == 'replace'
    _, receipt = commit(tmp_path, outputs, '丁'*10)
    result = (tmp_path / 'story/0001/chapter.md').read_bytes()
    start, end = guard['fragment']['start'], guard['fragment']['end']
    assert result[:start] == raw[:start] and result.endswith(raw[end:])
    assert result.startswith(b'\xef\xbb\xbf') and receipt['accepted'] and receipt['actual'] == 80


@pytest.mark.parametrize('compatible', [True, False])
def test_real_engine_with_actual_fragment_cli_invokes_one_pp_and_commits(tmp_path, monkeypatch, compatible):
    import shlex
    from types import SimpleNamespace
    from src.workflow.definition import WorkflowDef, WorkflowTask, WorkflowRunRecord
    from src.workflow.engine import WorkflowEngine
    from src.workflow.nodes import BaseNodePlugin, NodeResult, registry
    from src.workflow.nodes.script import _parse_wf_vars
    from src.workflow.variable_resolution import resolve_placeholders
    state, initial, original = setup(tmp_path)
    initial_guard = json.loads((tmp_path/initial['length_commit_guard']).read_text(encoding='utf-8'))
    span = initial_guard['fragment']
    expansion = original[span['start']:span['end']].decode('utf-8')+'丁'*30
    calls, scripts = [], []
    class Agent(BaseNodePlugin):
        node_type = 'agent'
        async def execute(self, ctx):
            calls.append(ctx.node_def.id)
            system = await resolve_placeholders(ctx.node_def.system_prompt_template, ctx.parameter_values, ctx.definition.variables, str(tmp_path))
            if ctx.node_def.id == 'agent_pp':
                assert '片段' in system
                write(tmp_path, 'cache/pp/body.json', json.dumps({'body': expansion}, ensure_ascii=False))
            else:
                context=json.loads((tmp_path/ctx.parameter_values['fragment_review_input']).read_text(encoding='utf-8'))
                assert context['candidate']==expansion and context['operation']=='expand' and '保持已确定事实' in context['author_feedback']
                from src.workflow.nodes.agent import AgentNode
                return await AgentNode().execute(ctx)
            return NodeResult(status='completed')
    class Script(BaseNodePlugin):
        node_type = 'script'
        async def execute(self, ctx):
            scripts.append(ctx.node_def.id)
            if ctx.node_def.id not in {'script_length_context', 'script_focused_execution', 'script_fragment_review_context', 'script_focused_commit'}:
                return NodeResult(status='completed')
            if 'script_argv' in ctx.node_def.node_params:
                arguments=[await resolve_placeholders(item,ctx.parameter_values,ctx.definition.variables,str(tmp_path)) for item in ctx.node_def.node_params['script_argv']]
            else:
                arguments=shlex.split(await resolve_placeholders(ctx.node_def.node_params['script_args'],ctx.parameter_values,ctx.definition.variables,str(tmp_path)))
            cli = PLUGIN / 'resources/script-library/xs2/manuscript_quality/manuscript_quality.py'
            run = subprocess.run([sys.executable, str(cli), *arguments], cwd=tmp_path, capture_output=True,
                env={**os.environ, 'TASK_ID': ctx.task_id, 'PYTHONIOENCODING': 'utf-8'})
            return NodeResult(status='completed' if run.returncode == 0 else 'failed',
                outputs=_parse_wf_vars(run.stdout.decode('utf-8')), error=run.stderr.decode('utf-8', errors='replace'))
    monkeypatch.setitem(registry._plugins, 'agent', Agent); monkeypatch.setitem(registry._plugins, 'script', Script)
    raw = definition(); wf = WorkflowDef.from_dict(raw); assert not wf.validate()
    class Manager:
        sessions = {}
        main_session_id = ''
        async def create_sub_session(self, **kwargs):
            report={'expression_review':{'verdict':'pass','issues':[]},'compatible':compatible,'issues':[] if compatible else [{'category':'new_fact','candidate_quote':'丁'*30,'source_quote':'乙'*25,'reason':'不能假设“隐藏账册”已存在'}]}
            text=json.dumps(report,ensure_ascii=False,indent=2)
            self.sessions['review-session']=SimpleNamespace(record=[{'type':'user','content':'review'},{'type':'assistant','content':text}])
            kwargs['on_auto_complete']('review-session','done','success','')
            return {'success':True,'session_id':'review-session'}
    engine = WorkflowEngine(Manager())
    async def no_save(*args, **kwargs): pass
    monkeypatch.setattr(engine, '_save_task_state', no_save)
    monkeypatch.setattr(engine, '_push_wf_task_update', lambda *args: None)
    values = {v['key']: v.get('default', '') for v in raw['variables']}; values.update(policy().parameters(state, raw))
    task = WorkflowTask(task_id='task-engine-fragment', workflow_id=wf.workflow_id, status='running', snapshot_definition=wf.to_dict(), parameter_values=values)
    async def run():
        return await engine._execute_plan_segment(definition=wf, task=task, execution_plan=wf.get_execution_plan(), disabled_ids=set(), shared_ws=tmp_path,
            parent_id='main', on_node_started=lambda state: None, needs_approval=False, run_record=WorkflowRunRecord(workflow_id=wf.workflow_id))
    assert asyncio.run(run()) == 'completed'
    assert calls == ['agent_pp', 'agent_fragment_review'] and 'script_polish_post' not in scripts
    assert 'script_focused_commit' in scripts
    proof = task.node_states['script_focused_commit']
    policy().verify_completion(tmp_path, state, 'polish', {'task_id': task.task_id, 'node_states': {'script_focused_commit': {'status': proof.status, 'outputs': proof.outputs}}})
    assert quality().count_prose((tmp_path / 'story/0001/chapter.md').read_text(encoding='utf-8-sig')) == (135 if compatible else 105)
    review=task.node_states['agent_fragment_review'].outputs['fragment_review_result']
    path=tmp_path/task.parameter_values['fragment_review_report_path']
    assert path.read_text(encoding='utf-8')==review
    if sys.platform=='win32': assert b'\r\n' in path.read_bytes()
