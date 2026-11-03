import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / 'resources/script-library/xs2'
spec = importlib.util.spec_from_file_location('progress_console', SCRIPTS / 'console_service/console_service.py',
                                              submodule_search_locations=[str(SCRIPTS / 'console_service')])
service = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = service
spec.loader.exec_module(service)


def write(root, name, contents):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding='utf-8')
    return path


def test_lifecycle_requires_scoped_plan_valid_confirmation_and_export_membership(tmp_path):
    write(tmp_path, 'planning/chapters/0002.json', '{}')
    body = write(tmp_path, 'story/0001/chapter.md', '正文')
    write(tmp_path, 'story/0001/confirmed_state.json', json.dumps({
        'chapter': '0001', 'source_hashes': {}, 'body_sha256': hashlib.sha256(body.read_bytes()).hexdigest(),
    }))
    write(tmp_path, 'export/manuscript.md', '之前导出的其他章')
    write(tmp_path, 'export/manifest.json', json.dumps({'output': 'export/manuscript.md', 'chapters': [
        {'chapter': '0003', 'path': 'story/0003/chapter.md'},
    ]}))
    first = service.progress.chapter_lifecycle(tmp_path, {'values': {}}, '0001')
    second = service.progress.chapter_lifecycle(tmp_path, {'values': {}}, '0002')
    assert first['confirmation'] == 'verified'
    assert first['export'] == 'missing'
    assert second['plan'] == 'missing'
    assert second['draft'] == 'missing'
    assert second['confirmation'] == 'missing'
    body.write_text('修改后的正文', encoding='utf-8')
    assert service.progress.chapter_lifecycle(tmp_path, {'values': {}}, '0001')['confirmation'] == 'stale'


def test_recorded_task_exposes_node_attempt_and_deduped_measured_usage(tmp_path):
    state = {'values': {'chapter_number': '0002'}, 'refs': {'mvp': {'task_id': 't-2', 'workflow_id': 'mvp'}}}
    tasks = {'mvp': {'task_id': 't-2', 'status': 'retry_waiting', 'parameter_values': {'chapter_number': '0002'},
                     'workspace_override': str(tmp_path),
                     'started_at': '2026-11-04T10:00:00Z',
                     'snapshot_definition': {'nodes': [{'id': 'writer', 'label': '执笔'}]},
                     'node_states': {'writer': {'status': 'retry_waiting', 'started_at': '2026-11-04T10:00:01Z',
                                                 'completed_at': '2026-11-04T10:00:04Z',
                                                 'attempt_count': 2, 'next_retry_at': '2026-11-04T10:00:10Z',
                                                 'error': '连接超时'}}}}
    measured = {'models': ['fixture:model'], 'total_tokens': 23, 'call_count': 1, 'basis': 'ledger'}
    result = service.progress.project_progress(tmp_path, state, tasks, {'mvp': measured})
    task = next(row['task'] for row in result['stages'] if row['id'] == 'mvp')
    assert task['task_id'] == 't-2'
    assert task['usage'] == measured
    assert task['nodes'][0] == {'id': 'writer', 'label': '执笔', 'status': 'retry_waiting', 'elapsed_seconds': 3,
                                'attempt_count': 2, 'next_retry_at': '2026-11-04T10:00:10Z', 'reason': '连接超时'}
    mismatched = service.progress.project_progress(tmp_path, state, {'mvp': {
        **tasks['mvp'], 'parameter_values': {'chapter_number': '0001'}}}, {'mvp': measured})
    assert 'task' not in next(row for row in mismatched['stages'] if row['id'] == 'mvp')
    unbound = service.progress.project_progress(tmp_path, state, {'mvp': {
        **tasks['mvp'], 'workspace_override': None}}, {'mvp': measured})
    assert 'task' not in next(row for row in unbound['stages'] if row['id'] == 'mvp')

def test_stage_completion_retains_legacy_tasks_and_checks_upstream_invalidation(tmp_path):
    for name in ['meta/world_foundation.md', 'meta/character_profiles.md', 'meta/story_plan.md',
                 'outline/near_term_outline.md', 'story/0001/chapter.md', 'quality/reader_report.json',
                 'story/0001/diff_story_confirmed.md', 'export/manuscript.md']:
        write(tmp_path, name, '{}' if name.endswith('.json') else '正文')
    state = {'mode': 'short', 'values': {'chapter_number': '0001'}, 'refs': {}}
    tasks = {}
    for index, (stage, _) in enumerate(service.progress.STAGES):
        state['refs'][stage] = {'workflow_id': stage, 'task_id': 'task'}
        tasks[stage] = {'status': 'completed', 'started_at': f'2026-10-07T10:{index:02d}:00',
                        'completed_at': f'2026-10-07T10:{index:02d}:30'}
    initial = service.progress.project_progress(tmp_path, state, tasks)
    assert initial['percent'] == 100
    assert initial['lifecycle']['export'] == 'unknown'
    tasks['polish'] = {'status': 'running', 'started_at': '2026-10-07T11:00:00'}
    actual = service.progress.project_progress(tmp_path, state, tasks)
    assert actual['percent'] == 56
    assert '润色正文处理中' in actual['label']
    assert not actual['export_current']
    assert actual['can_download']
