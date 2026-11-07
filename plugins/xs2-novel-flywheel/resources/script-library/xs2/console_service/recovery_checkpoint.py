"""Plugin-owned continuation of verified MVP publication, never a body rewrite."""
import hashlib
import json
import os
from pathlib import Path

TAIL = ('sync_up_si', 'script_check_originality')
SCRIPT_NAMES = {'sync_up_si': 'local_archive', 'script_check_originality': 'reference_intelligence_helper'}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('恢复文件越过本书工作区')
    return path


def _profile(state):
    return {key: state.get(key) for key in ('analysisModel', 'writerModel', 'polishModel', 'writerModelParams')}


def prepare(root, state, task, chapter):
    nodes = task.get('node_states') or {}
    if nodes.get('script_render_si', {}).get('status') != 'completed':
        return None
    failed = {key for key, node in nodes.items() if node.get('status') == 'failed'}
    if not failed or not failed.issubset(TAIL):
        return None
    if Path(task.get('workspace_override') or '').resolve() != Path(root).resolve():
        raise ValueError('已落盘正文的失败任务不属于本书')
    relative = f'story/{chapter}/chapter.md'
    body = _path(root, relative)
    cached = _path(root, 'cache/si/body.json')
    value = json.loads(cached.read_text(encoding='utf-8-sig')).get('body')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('已落盘正文缺少对应的写手缓存')
    # Match the actual renderer's write_text conversion byte for byte,
    # including CRLF already present in model output on Windows.
    rendered = (value.rstrip() + '\n').replace('\n', os.linesep).encode('utf-8')
    if body.read_bytes() != rendered:
        raise ValueError('正文已在生成后被编辑，不能自动恢复旧产物')
    selected = [key for key in TAIL if nodes.get(key, {}).get('status') != 'completed']
    files = {relative: _digest(body), 'cache/si/body.json': _digest(cached)}
    if 'sync_up_si' in selected:
        relative_se = 'cache/se/se_output.json'
        files[relative_se] = _digest(_path(root, relative_se))
    return {'stage': 'mvp', 'chapter': chapter, 'source_task_id': task['task_id'],
            'selected_node_ids': selected, 'files': files,
            'values_sha256': _value_digest(state.get('values', {})), 'models': _profile(state)}


def validate(root, state, checkpoint):
    if not isinstance(checkpoint, dict) or checkpoint.get('stage') != 'mvp':
        raise ValueError('正文恢复凭据缺失')
    if checkpoint.get('chapter') != str(state.get('values', {}).get('chapter_number', '0001')).zfill(4):
        raise ValueError('正文恢复凭据不属于当前章节')
    if checkpoint.get('values_sha256') != _value_digest(state.get('values', {})) or checkpoint.get('models') != _profile(state):
        raise ValueError('本书要求或模型分工已变化，不能恢复旧生成任务')
    files = checkpoint.get('files') or {}
    if not files or not checkpoint.get('selected_node_ids') or not set(checkpoint['selected_node_ids']).issubset(TAIL):
        raise ValueError('正文恢复凭据不完整')
    for relative, digest in files.items():
        path = _path(root, relative)
        if not path.is_file() or _digest(path) != digest:
            raise ValueError('正文或生成缓存已变化，自动恢复没有覆盖后续编辑')


def options(root, state, definition, source):
    checkpoint = state.get('automaticCheckpoint')
    validate(root, state, checkpoint)
    if (not source or source.get('task_id') != checkpoint['source_task_id'] or source.get('status') != 'failed'
            or Path(source.get('workspace_override') or '').resolve() != Path(root).resolve()
            or source.get('node_states', {}).get('script_render_si', {}).get('status') != 'completed'):
        raise ValueError('正文恢复的来源任务不再有效')
    current = {node['id']: node for node in definition.get('nodes', [])}
    prior = {node['id']: node for node in source.get('snapshot_definition', {}).get('nodes', [])}
    for key in checkpoint['selected_node_ids']:
        node, old = current.get(key, {}), prior.get(key, {})
        params, old_params = node.get('node_params') or {}, old.get('node_params') or {}
        if (node.get('node_type') != 'script' or old.get('node_type') != 'script'
                or params.get('script_source') != 'library' or params.get('script_type') != 'python'
                or params.get('script_name') != SCRIPT_NAMES[key]
                or any(params.get(field) != old_params.get(field) for field in ('script_source', 'script_type', 'script_name', 'script_group', 'script_args', 'script_argv'))):
            raise ValueError('正文恢复尾部定义发生变化，需先核对插件升级')
    declared = {variable['key'] for variable in definition.get('variables', [])}
    parameters = {key: value for key, value in source.get('parameter_values', {}).items() if key in declared}
    return {'parameter_values': parameters, 'selected_node_ids': checkpoint['selected_node_ids']}


def validate_selection(task, checkpoint):
    selected = set(checkpoint['selected_node_ids'])
    disabled = set(task.get('disabled_node_ids') or [])
    definitions = task.get('snapshot_definition', {}).get('nodes', [])
    if not selected.issubset({node['id'] for node in definitions}):
        raise ValueError('正文恢复任务缺少需要执行的检查节点')
    for node in definitions:
        key = node['id']
        if key not in selected and not (key.startswith('__') and key.endswith('__')) and key not in disabled:
            raise ValueError('正文恢复任务包含不应重新执行的生成节点')


def verify(root, state, task):
    checkpoint = state.get('automaticCheckpoint')
    validate(root, state, checkpoint)
    validate_selection(task, checkpoint)
    nodes = task.get('node_states') or {}
    for key in checkpoint['selected_node_ids']:
        if nodes.get(key, {}).get('status') != 'completed':
            raise ValueError('正文恢复的归档或检查尚未完成')
