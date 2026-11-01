"""Plugin-owned voice documents. Templates do not infer character psychology."""
from pathlib import Path
import re
import tempfile


def _file(root: Path, name: str) -> Path:
    root = root.resolve()
    target = (root / 'meta' / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('角色文件路径必须位于当前工作区内')
    return target


def read(root: Path) -> dict:
    target = _file(root, 'character_voice.md')
    return {'status': 'success' if target.is_file() else 'not_found',
            'content': target.read_text(encoding='utf-8-sig') if target.is_file() else '',
            'file_path': str(target)}


def status(root: Path) -> dict:
    document = read(root)
    exists = document['status'] == 'success'
    return {'voice_file_exists': exists,
            'profiles_file_exists': _file(root, 'character_profiles.md').is_file(),
            'humanware_enabled': exists, 'scoring_supported': False,
            'generation_mode': 'template',
            'character_count': len(re.findall(r'^##\s+\S.*$', document['content'], re.MULTILINE))}


def save(root: Path, content: str) -> dict:
    if not isinstance(content, str) or '\x00' in content or len(content) > 500_000:
        raise ValueError('角色声音内容无效或超过 500000 字符')
    target = _file(root, 'character_voice.md')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status': 'success', 'file_path': str(target)}


def generate(root: Path) -> dict:
    target = _file(root, 'character_voice.md')
    if target.exists():
        raise FileExistsError(target)
    profiles = _file(root, 'character_profiles.md')
    if not profiles.is_file():
        raise ValueError('请先创建角色档案')
    names = list(dict.fromkeys(re.findall(r'^##\s+(.+?)\s*$', profiles.read_text(encoding='utf-8-sig'), re.MULTILINE)))
    if not names:
        raise ValueError('档案中未找到二级标题（## 角色名），请直接编辑声音文件或使用角色工作流。')
    content = '# 角色声音锚点\n\n> 手工填写模板：仅提取档案中的二级标题，不调用模型，不推断人物声音。\n'
    for name in names:
        content += f'\n## {name}\n\n- 表达习惯：待填写\n- 关注点与情绪表达：待填写\n- 不会使用的表达：待填写\n- 对话示例：待填写\n'
    with target.open('x', encoding='utf-8') as handle:
        handle.write(content)
    return {'status': 'success', 'generation_mode': 'template', 'character_count': len(names),
            'message': '已创建待填写模板；未调用模型，未修改角色档案。', 'file_path': str(target)}
