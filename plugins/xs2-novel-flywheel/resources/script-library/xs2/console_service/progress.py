"""Read-only projection of chapter artifacts and persisted workbench task facts."""
from datetime import datetime, timezone
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import re

from . import production

STAGES = [('build', '建立世界观'), ('character', '创建角色'), ('story-plan', '规划故事'),
          ('outline', '生成大纲'), ('mvp', '生成正文'), ('polish', '润色正文'),
          ('reader-sim', '读者评估'), ('post-hoc', '质量审核'), ('export', '导出成品')]
ACTIVE = {'pending', 'preparing', 'pre_running', 'running', 'retry_waiting', 'resume_pending', 'waiting_approval'}
TERMINAL = {'completed', 'failed', 'interrupted', 'stopped', 'cancelled'}
CHAPTER_STAGES = {'mvp', 'polish', 'reader-sim', 'post-hoc'}
BODY = 'story/{chapter}/chapter.md'
EXPORT = 'export/manuscript.md'


@lru_cache(maxsize=1)
def support():
    path = Path(__file__).resolve().parents[1] / 'story_support/story_support.py'
    spec = importlib.util.spec_from_file_location('novel_progress_story_support', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter_id(value):
    value = str(value)
    return value.zfill(4) if re.fullmatch(r'[0-9]{1,4}', value) and int(value) else ''


def _file(root, name):
    path = root / name
    try:
        if path.resolve().is_relative_to(root.resolve()) and path.is_file() and path.stat().st_size:
            return path
    except (OSError, RuntimeError):
        pass
    return None


def _json(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig')) if path else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _text(path):
    try:
        return path.read_text(encoding='utf-8-sig').strip() if path else ''
    except (OSError, ValueError):
        return ''


def _reader_path(root, chapter):
    scoped = f'story/{chapter}/reader_report.json'
    if _file(root, scoped):
        return scoped
    legacy = 'quality/reader_report.json'
    report = _json(_file(root, legacy))
    return legacy if chapter_id(report.get('chapter_number') or '1') == chapter else scoped


def _export_status(root, chapter, body):
    artifact = _file(root, EXPORT)
    manifest_path = _file(root, 'export/manifest.json')
    if not artifact:
        return 'missing'
    manifest = _json(manifest_path)
    rows = manifest.get('chapters')
    if manifest.get('output') != EXPORT or not isinstance(rows, list):
        return 'unknown'
    if not any(isinstance(row, dict) and chapter_id(row.get('chapter')) == chapter
               and row.get('path') == BODY.format(chapter=chapter) for row in rows):
        return 'missing'
    if not body or not manifest_path:
        return 'stale'
    return 'recorded' if body.stat().st_mtime_ns <= min(artifact.stat().st_mtime_ns, manifest_path.stat().st_mtime_ns) else 'stale'


def chapter_lifecycle(root, state, chapter):
    story = support()
    valid, stale = story.confirmed(root)
    body = _file(root, BODY.format(chapter=chapter))
    outline_path = _file(root, 'outline/near_term_outline.md')
    guide = _file(root, f'story/{chapter}/single_chapter_guide.md')
    adopted = _json(_file(root, f'planning/chapters/{chapter}.json'))
    if adopted:
        hashes = adopted.get('source_hashes')
        plan = 'planned' if isinstance(hashes, dict) and not story.changed_sources(root, hashes) else 'stale'
    else:
        plan = 'planned' if _text(guide) or story.chapter_outline(root, chapter, _text(outline_path)) else 'missing'
    report = _file(root, _reader_path(root, chapter))
    review = 'missing'
    if report:
        try:
            review = production.reader_report(root, {**state, 'values': {**state.get('values', {}), 'chapter_number': chapter}})['verdict']
        except (KeyError, OSError, ValueError):
            review = 'unverified'
    return {
        'chapter': chapter, 'plan': plan, 'draft': 'present' if _text(body) else 'missing', 'assessment': review,
        'confirmation': 'stale' if chapter in stale else 'verified' if any(row['chapter'] == chapter for row in valid) else 'missing',
        'export': _export_status(root, chapter, body),
    }


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        # Legacy Python serializers wrote local, timezone-naive timestamps.
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _elapsed(start, end):
    left, right = _timestamp(start), _timestamp(end)
    return round((right - left).total_seconds(), 1) if left and right and right >= left else None


def _task_details(task, reference, usage, now):
    snapshot = task.get('snapshot_definition') or {}
    if snapshot.get('workflow_id') not in (None, reference.get('workflow_id')):
        snapshot = {}
    nodes = task.get('node_states') or {}
    rows = []

    def project_node(identity, node, name):
        status = node.get('status') or 'unknown'
        end = node.get('completed_at') or (now if status == 'running' else None)
        row = {'id': identity, 'label': name, 'status': status, 'elapsed_seconds': _elapsed(node.get('started_at'), end)}
        for key in ('attempt_count', 'automatic_retry_count', 'next_retry_at'):
            if node.get(key):
                row[key] = node[key]
        if node.get('error'):
            row['reason'] = node['error']
        rows.append(row)
        for child_id, child in (node.get('child_states') or {}).items():
            if isinstance(child, dict):
                project_node(f'{identity}/{child_id}', child, f'{name} › {child.get("name") or child_id}')

    labels = {row['id']: row.get('label') or row['id'] for row in snapshot.get('nodes', []) if isinstance(row, dict) and row.get('id')}
    for key, node in nodes.items():
        if isinstance(node, dict):
            project_node(key, node, labels.get(key, node.get('name') or key))
    end = task.get('completed_at') if task.get('status') in TERMINAL else now
    return {'task_id': task.get('task_id') or reference.get('task_id'), 'status': task.get('status') or 'unknown',
            'current_node_id': task.get('current_node_id'), 'elapsed_seconds': _elapsed(task.get('started_at'), end),
            'reason': task.get('error') or '', 'nodes': rows, 'usage': usage or None}


def project_progress(root, state, tasks, usages=None, *, selected='', include_details=True, archived=None):
    root = Path(root)
    project_chapter = chapter_id(state.get('values', {}).get('chapter_number', '1')) or '0001'
    chapter = chapter_id(selected) or project_chapter
    refs = state.get('refs') or {}
    now = datetime.now(timezone.utc).isoformat()
    bodies = list((root / 'story').glob('[0-9][0-9][0-9][0-9]/chapter.md'))
    export = _file(root, EXPORT)
    stages = []
    current = ''
    newest_upstream = None
    for stage, label in STAGES:
        reference = refs.get(stage) or {}
        task = tasks.get(stage) or {}
        historical = (archived or {}).get(stage)
        if historical and chapter != project_chapter and stage in CHAPTER_STAGES:
            task = historical
            reference = {'workflow_id': task.get('workflow_id'), 'task_id': task.get('task_id')}
        parameters = task.get('parameter_values')
        task_chapter = chapter_id(parameters.get('chapter_number')) if isinstance(parameters, dict) else ''
        chapter_bound = stage not in CHAPTER_STAGES or task_chapter == chapter
        if not chapter_bound and (task_chapter or chapter != project_chapter):
            task, reference = {}, {'mismatched_chapter': True}
        status = task.get('status', '')
        rel = _reader_path(root, chapter) if stage == 'reader-sim' else production.ARTIFACTS[stage].format(chapter=chapter)
        exists = _file(root, rel)
        complete = bool(exists and (status == 'completed' or not reference and stage in state.get('completed', [])))
        ended = _timestamp(task.get('completed_at'))
        started = _timestamp(task.get('started_at'))
        if ended and newest_upstream and ended < newest_upstream:
            complete = False
        if started and (not newest_upstream or started > newest_upstream):
            newest_upstream = started
        if status in ACTIVE:
            current = label + '处理中'
            complete = False
        elif status in TERMINAL - {'completed'}:
            current = label + '未完成，请处理任务提示'
        if stage == 'export' and exists and any(body.stat().st_mtime_ns > exists.stat().st_mtime_ns for body in bodies):
            complete = False
        row = {'id': stage, 'label': label, 'completed': complete, 'status': status or ('completed' if complete else 'not_started')}
        if include_details and chapter_bound and task.get('workspace_override'):
            row['task'] = _task_details(task, reference, (usages or {}).get(stage), now)
        stages.append(row)
    completed = sum(item['completed'] for item in stages)
    exported = stages[-1]['completed']
    report = _json(_file(root, _reader_path(root, chapter)))
    if chapter_id(report.get('chapter_number', chapter)) != chapter:
        report = {}
    label = current or ('导出步骤已完成' if exported else next(
        (item['label'] + '未完成' for item in stages if not item['completed']), '尚未开始'))
    result = {'percent': round(completed / len(stages) * 100), 'completed_count': completed,
              'total_count': len(stages), 'label': label, 'stages': stages, 'chapter_count': len(bodies),
              'can_download': bool(export), 'export_current': exported, 'reader_verdict': report.get('verdict', '')}
    if include_details:
        result['lifecycle'] = chapter_lifecycle(root, state, chapter)
        assessment = result['lifecycle']['assessment']
        result['reader_verdict'] = assessment if assessment in {'pass', 'revise', 'reject'} else ''
        if chapter == project_chapter and isinstance(state.get('autoPauseReason'), str) and state['autoPauseReason']:
            result['pause_reason'] = state['autoPauseReason']
    return result
