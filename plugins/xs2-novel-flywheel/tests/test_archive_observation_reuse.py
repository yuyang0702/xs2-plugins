import copy
import importlib.util
import json
from types import SimpleNamespace

import pytest

from test_story_support import MODULE, support
from test_native_preflight import native
from test_retry_lineage import put_task


def module():
    spec = importlib.util.spec_from_file_location('test_archive_observation', MODULE.with_name('archive_observation.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_archive_context_ignores_current_review_output_but_keeps_previous_chapter(tmp_path):
    support.write(tmp_path, 'story/0001/chapter.md', '舟子从渡口出发。')
    support.write(tmp_path, 'story/0001/diff_story_confirmed.md', '前章已确认交接。')
    support.write(tmp_path, 'story/0002/chapter.md', '舟子关了门。')
    current_review = 'story/0002/diff_story_confirmed.md'
    support.write(tmp_path, current_review, '本章旧观察。')
    before = support.context(tmp_path, '0002', archive_observation=True)
    support.write(tmp_path, current_review, '本章新观察。')
    after = support.context(tmp_path, '0002', archive_observation=True)
    assert before['sources'] == after['sources']
    ids = {source['source_id'] for source in after['sources']}
    assert 'story/0002/chapter.md' in ids and 'story/0001/diff_story_confirmed.md' in ids
    assert current_review not in ids and current_review not in after['source_hashes']


def test_only_exact_native_tool_free_observation_can_be_reused(tmp_path, monkeypatch):
    monkeypatch.setenv('DETERMINFLOW_DATA_DIR', './data')
    observer = {'confirmed_state': {'characters': []}}
    task = {'task_id': 'task-a', 'workflow_id': 'archive', 'node_states': {'agent_obs': {
        'status': 'completed', 'session_id': 'session-a',
        'summary': json.dumps(observer),
    }}}
    session = {'session_id': 'session-a', 'task_id': 'task-a', 'workflow_id': 'archive',
               'node_id': 'agent_obs', 'workspace_path': str(tmp_path), 'model_id': 'model:test',
               'record': [{'type': 'user', 'content': '当前正文与规则'}, {'type': 'assistant', 'content': json.dumps(observer)}]}
    guard = SimpleNamespace(host_root=lambda: tmp_path)
    def saved(value):
        support.write(tmp_path, 'data/sessions/session-a.json', value)
        return module().native_proof(tmp_path, guard, task, observer, 'model:test')
    assert saved(session)['session_id'] == 'session-a'
    for change in ('tool', 'wrong_model', 'wrong_output', 'wrong_task'):
        changed = copy.deepcopy(session)
        if change == 'tool':
            changed['record'][-1]['tool_calls'] = [{'function': {'name': 'read_file'}}]
        elif change == 'wrong_model':
            changed['model_id'] = 'model:other'
        elif change == 'wrong_output':
            changed['record'][-1]['content'] = '{}'
        else:
            changed['task_id'] = 'another-task'
        assert saved(changed) is None


@pytest.mark.parametrize('change', [None, 'body', 'model', 'book_rules'])
def test_archive_reuse_uses_completed_receipt_and_still_requires_arbiter(native, monkeypatch, change):
    guard, root, task, save, host = native
    monkeypatch.setenv('DETERMINFLOW_DATA_DIR', str(host/'data'))
    chapter = '0001'
    relative = f'story/{chapter}/chapter.md'
    support.write(root, relative, '舟子关了门。')
    task['parameter_values']['body'] = relative
    task['snapshot_definition']['nodes'][1].update(id='agent_obs', agent_type='novel-chapter-observer')
    save()
    guard.run(root, 'post-hoc', chapter, 'task-a', 'wf')
    support.begin_review(root, chapter)
    guard.request_budget(root, 'agent_obs')

    observation = {'confirmed_state': {'characters': [{'name': '舟子', 'evidence': '舟子关了门。'}]}}
    arbitration = {'story_confirmed': {'summary': '舟子关门'}}
    task['node_states'] = {'agent_obs': {'status': 'completed', 'session_id': 'session-a'}}
    save()
    support.write(host, 'data/sessions/session-a.json', {
        'session_id': 'session-a', 'workflow_id': 'wf', 'task_id': 'task-a', 'node_id': 'agent_obs',
        'workspace_path': str(root), 'model_id': 'route:model',
        'record': [{'type': 'user', 'content': '舟子关了门。'},
                   {'type': 'assistant', 'content': json.dumps(observation, ensure_ascii=False)}],
    })
    support.write(root, support.review_file(chapter, 'observer.json'), observation)
    support.write(root, support.review_file(chapter, 'arbiter.json'), arbitration)
    first = support.commit(root, chapter)
    guard.run(root, 'post-hoc', chapter, 'task-a', 'wf', finish=True)

    child = copy.deepcopy(task)
    child.update(task_id='task-b', created_at='2026-11-10T00:01:00+00:00', node_states={})
    if change == 'body':
        support.write(root, relative, '舟子推开窗。')
    elif change == 'model':
        child['snapshot_definition']['nodes'][1]['model_override'] = 'route:changed'
    elif change == 'book_rules':
        support.write(root, 'meta/narrative_contract.json', {'narrator_scope': 'omniscient'})
    put_task(host, child)
    monkeypatch.setenv('TASK_ID', 'task-b')
    guard.run(root, 'post-hoc', chapter, 'task-b', 'wf')
    support.begin_review(root, chapter)
    guard.request_budget(root, 'agent_obs')
    assert support.reuse_observation(root, chapter) is (change is None)
    if change is None:
        support.validate_cached_observation(root, chapter)
        with pytest.raises(ValueError, match='后验产物不完整'):
            support.commit(root, chapter)
        support.write(root, support.review_file(chapter, 'arbiter.json'), arbitration)
        support.write(root, support.review_file(chapter, 'observer.json'),
                      {**observation, 'character_diff': {'summary': '未在原观察中出现的解释'}})
        with pytest.raises(ValueError, match='复用观察的依据已有变化'):
            support.commit(root, chapter)
        assert support.load(root, f'story/{chapter}/confirmed_state.json') == first
