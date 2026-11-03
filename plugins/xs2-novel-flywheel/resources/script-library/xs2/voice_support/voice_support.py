"""Plugin-owned voice documents. Templates do not infer character psychology."""
from pathlib import Path
from functools import lru_cache, wraps
import hashlib
import importlib.util
import re
import tempfile
import unicodedata


@lru_cache(maxsize=1)
def _character_edits():
    entry = Path(__file__).resolve().parent.parent / 'character_center' / 'character_center.py'
    if not entry.is_file():
        return None
    spec = importlib.util.spec_from_file_location('voice_character_center', entry)
    center = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(center)
    return center


def _serial_mutation(operation):
    @wraps(operation)
    def run(root, *args, **kwargs):
        center = _character_edits()
        if center is None:
            return operation(root, *args, **kwargs)
        with center.legacy_mutation(root):
            return operation(root, *args, **kwargs)
    return run


def _file(root: Path, name: str) -> Path:
    root = root.resolve()
    target = (root / 'meta' / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('角色文件路径必须位于当前工作区内')
    return target


def _text(path):
    return path.read_bytes().decode('utf-8-sig') if path.is_file() else ''


def _sections(text, *, require_closed_fences=False):
    """Keep offsets into the original document; fenced examples are not roles."""
    headings, offset, fence = [], 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)', line)
        if marker:
            token, rest = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            heading = re.match(r'^ {0,3}##[ \t]+(.+?)[ \t]*(?:\r?\n)?$', line)
            if heading:
                title = re.sub(r'[ \t]+#+[ \t]*$', '', heading[1]).strip()
                headings.append({'title': title, 'start': offset, 'body_start': offset + len(line)})
        offset += len(line)
    if require_closed_fences and fence is not None:
        raise ValueError('角色声音中存在未闭合的代码块，请先补齐代码块后再分人物保存。')
    for index, section in enumerate(headings):
        section['end'] = headings[index + 1]['start'] if index + 1 < len(headings) else len(text)
        section['body'] = text[section['body_start']:section['end']]
    return headings


def _name(title):
    name = unicodedata.normalize('NFKC', title).strip().strip('*_`').strip()
    name = re.sub(r'^\d+[.、)]\s*', '', name)
    name = re.sub(r'\s*\([^()]*\)\s*$', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def _id(kind, index, title):
    return f'{kind}-{index}-{hashlib.sha256(title.encode()).hexdigest()[:12]}'


def _raw_documents(root):
    result = {}
    for name in ('character_voice.md', 'character_profiles.md'):
        path = _file(root, name)
        result[name] = path.read_bytes() if path.is_file() else None
    return result


def _revision(root, documents=None):
    documents = _raw_documents(root) if documents is None else documents
    digest = hashlib.sha256()
    for name in ('character_voice.md', 'character_profiles.md'):
        data = documents[name]
        digest.update(name.encode() + b'\0' + (b'missing' if data is None else b'present' + str(len(data)).encode() + b'\0' + data))
    return digest.hexdigest()


def read(root: Path) -> dict:
    target = _file(root, 'character_voice.md')
    documents = _raw_documents(root)
    content = (documents['character_voice.md'] or b'').decode('utf-8-sig')
    voices = _sections(content)
    profiles = _sections((documents['character_profiles.md'] or b'').decode('utf-8-sig'))
    used, characters = set(), []
    for index, section in enumerate(voices):
        name = _name(section['title'])
        matches = [(i, item) for i, item in enumerate(profiles) if _name(item['title']) == name]
        matched = matches[0] if len(matches) == 1 else None
        if matched:
            used.add(matched[0])
        characters.append({'id': _id('voice', index, section['title']), 'name': name or section['title'],
                           'title': section['title'], 'voice': section['body'].strip('\r\n'),
                           'voice_status': 'present', 'profile': matched[1]['body'].strip() if matched else '',
                           'profile_status': 'matched' if matched else 'ambiguous' if matches else 'missing'})
    for index, profile in enumerate(profiles):
        if index not in used:
            characters.append({'id': _id('profile', index, profile['title']), 'name': _name(profile['title']) or profile['title'],
                               'title': profile['title'], 'voice': '', 'voice_status': 'missing',
                               'profile': profile['body'].strip(), 'profile_status': 'matched'})
    return {'status': 'success' if documents['character_voice.md'] is not None else 'not_found',
            'content': content, 'revision': _revision(root, documents), 'characters': characters,
            'preamble': content[:voices[0]['start']] if voices else '',
            'unsectioned_voice': content if not voices else '',
            'file_path': str(target)}


def status(root: Path) -> dict:
    document = read(root)
    exists = document['status'] == 'success'
    return {'voice_file_exists': exists,
            'profiles_file_exists': _file(root, 'character_profiles.md').is_file(),
            'humanware_enabled': exists, 'scoring_supported': False,
            'generation_mode': 'template',
            'character_count': len(_sections(document['content']))}


def _validate_content(content):
    if not isinstance(content, str) or '\x00' in content or len(content) > 500_000:
        raise ValueError('角色声音内容无效或超过 500000 字符')


def _write(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _check_revision(root, expected):
    if expected is not None and expected != _revision(root):
        raise ValueError('角色声音或人物档案已更新，请保留当前编辑，刷新后重新核对再保存。')


@_serial_mutation
def save(root: Path, content: str, expected_revision=None) -> dict:
    _validate_content(content)
    _check_revision(root, expected_revision)
    target = _file(root, 'character_voice.md')
    _write(target, content.encode('utf-8'))
    return {'status': 'success', 'file_path': str(target)}


@_serial_mutation
def save_character(root: Path, character_id: str, content: str, expected_revision: str) -> dict:
    _validate_content(content)
    if not expected_revision:
        raise ValueError('缺少当前档案版本，请刷新后再保存。')
    if _sections(content, require_closed_fences=True):
        raise ValueError('单个人物声音不能加入其他人物的二级标题；小节请使用三级标题。')
    document = read(root)
    if document['revision'] != expected_revision:
        raise ValueError('角色声音或人物档案已更新，请保留当前编辑，刷新后重新核对再保存。')
    character = next((item for item in document['characters'] if item['id'] == character_id), None)
    if character is None:
        raise ValueError('未找到当前人物，请刷新档案后再编辑。')
    original = document['content']
    newline = '\r\n' if '\r\n' in original else '\n'
    body = content.strip('\r\n').replace('\r\n', '\n').replace('\n', newline)
    sections = _sections(original, require_closed_fences=True)
    if character['voice_status'] == 'present':
        section = next(item for i, item in enumerate(sections) if _id('voice', i, item['title']) == character_id)
        old = section['body']
        leading = old[:len(old) - len(old.lstrip('\r\n'))]
        trailing = old[len(old.rstrip('\r\n')):] if old.strip('\r\n') else newline * 2
        heading_gap = '' if original[:section['body_start']].endswith(('\r', '\n')) else newline
        updated = original[:section['body_start']] + heading_gap + leading + body + trailing + original[section['end']:]
        saved_id = character_id
    else:
        prefix = original or '# 角色声音锚点' + newline
        separator = '' if prefix.endswith(newline * 2) else newline if prefix.endswith(newline) else newline * 2
        updated = prefix + separator + '## ' + character['title'] + newline * 2 + body + newline
        saved_id = _id('voice', len(sections), character['title'])
    expected_titles = [item['title'] for item in sections]
    if character['voice_status'] != 'present':
        expected_titles.append(character['title'])
    if [item['title'] for item in _sections(updated, require_closed_fences=True)] != expected_titles:
        raise ValueError('保存会改变其他人物的分段，请检查标题和代码块后再保存。')
    _validate_content(updated)
    target = _file(root, 'character_voice.md')
    bom = b'\xef\xbb\xbf' if target.is_file() and target.read_bytes().startswith(b'\xef\xbb\xbf') else b''
    _check_revision(root, expected_revision)
    _write(target, bom + updated.encode('utf-8'))
    return {'status': 'success', 'character_id': saved_id, 'file_path': str(target)}


@_serial_mutation
def generate(root: Path) -> dict:
    target = _file(root, 'character_voice.md')
    if target.exists():
        raise FileExistsError(target)
    profiles = _file(root, 'character_profiles.md')
    if not profiles.is_file():
        raise ValueError('请先创建角色档案')
    names = list(dict.fromkeys(item['title'] for item in _sections(_text(profiles))))
    if not names:
        raise ValueError('档案中未找到二级标题（## 角色名），请直接编辑声音文件或使用角色工作流。')
    content = '# 角色声音锚点\n\n> 手工填写模板：仅提取档案中的二级标题，不调用模型，不推断人物声音。\n'
    for name in names:
        content += f'\n## {name}\n\n- 表达习惯：待填写\n- 关注点与情绪表达：待填写\n- 不会使用的表达：待填写\n- 对话示例：待填写\n'
    with target.open('x', encoding='utf-8') as handle:
        handle.write(content)
    return {'status': 'success', 'generation_mode': 'template', 'character_count': len(names),
            'message': '已创建待填写模板；未调用模型，未修改角色档案。', 'file_path': str(target)}
