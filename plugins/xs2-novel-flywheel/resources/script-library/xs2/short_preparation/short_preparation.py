"""Plugin-owned compact short-story preparation, with original archive contracts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

DIMENSIONS = {'core_laws': '核心规则', 'space_time': '时间与地点', 'society': '关系与现实压力',
              'history_culture': '相关背景', 'existence': '必要的存在约束', 'information': '信息与认知边界'}
REQUIRED = ('meta/world_foundation.md', 'meta/character_profiles.md', 'meta/character_voice.md',
            'meta/style_profile.md', 'meta/story_plan.md', 'outline/volume_outline.md', 'outline/near_term_outline.md')
OPTIONAL = ('meta/character_voice_adaptations.md', 'learning/context/mvp.md',
            'meta/current_world.md', 'meta/current_characters.md', 'meta/conflict_ledger.md',
            'meta/hooks.md', 'meta/debts.md', 'cache/story-support/context.md')


def _path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('轻量产物路径不能越出本书工作区')
    return path


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'轻量准备缺少{label}')
    return value.strip()


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def _v2_text(value):
    if isinstance(value, str):
        if any(re.match(r'^[ \t]{0,3}#{1,6}(?:[ \t]|$)', line) for line in value.splitlines()):
            raise ValueError('v2角色文本不能包含Markdown标题；请改为普通段落，角色分段由渲染器生成')
        if any(re.match(r'^[ \t]{0,3}(?:`{3,}|~{3,})', line) for line in value.splitlines()):
            raise ValueError('v2角色文本不能包含Markdown代码围栏；请改为普通段落，避免隐藏后续角色')
    elif isinstance(value, dict):
        for item in value.values():
            _v2_text(item)
    elif isinstance(value, list):
        for item in value:
            _v2_text(item)


def _v2_identity(item):
    name = item.get('name')
    if (not isinstance(name, str) or not name.strip() or len(name) > 60
            or re.search(r'[\x00-\x1f\x85\u2028\u2029/\\<>:"|?*#]', name) or name.strip() in {'.', '..'}):
        raise ValueError('v2人物姓名name必须是非空安全字符串，不能包含路径或标题字符')
    aliases = item.get('aliases', [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip()
            or re.search(r'[\x00-\x1f\x85\u2028\u2029]', alias) for alias in aliases):
        raise ValueError('v2的aliases必须是非空单行字符串数组')
    if 'true_name' in item and (not isinstance(item['true_name'], str)
            or re.search(r'[\x00-\x1f\x85\u2028\u2029]', item['true_name'])):
        raise ValueError('v2的true_name必须是单行字符串；真名未知可留空')


def _card_v2(item):
    if 'card_schema' not in item:
        return False
    if item['card_schema'] != 'xs2.character.v2':
        raise ValueError('不支持的card_schema；请使用xs2.character.v2或保留无版本旧档')
    if 'boundary' in item:
        raise ValueError('v2不能混用旧boundary；请明确区分personality与plot_constraints')
    for key in ('facts', 'plot_constraints'):
        entries = item.get(key)
        if not isinstance(entries, list):
            raise ValueError(f'v2的{key}必须是字符串数组（可为空）')
        for entry in entries:
            _text(entry, f'v2的{key}条目')
    _text(item.get('personality'), 'v2的personality')
    _v2_identity(item)
    _v2_text(item)
    return True


def _render(value, level=3):
    if isinstance(value, dict):
        return '\n'.join(f'{"#" * min(level, 6)} {key}\n\n{_render(item, level + 1)}'
                         for key, item in value.items() if item not in (None, '', [], {}))
    if isinstance(value, list):
        return '\n'.join('- ' + _render(item, level + 1) for item in value)
    return str(value)


def _publish(root, files):
    """Validate the whole set before writing; do not replace author documents."""
    targets = {name: _path(root, name) for name in files}
    for name, path in targets.items():
        if path.exists() and (not path.is_file() or path.read_text(encoding='utf-8-sig') != files[name]):
            raise ValueError(f'已有资料 {name} 已保留；请复用资料或选择完整准备，不自动覆盖')
    staged, created = [], []
    try:
        for name, path in targets.items():
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.short-', suffix='.tmp', dir=path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(files[name])
            staged.append((Path(temporary), path))
        for temporary, path in staged:
            os.replace(temporary, path)
            created.append(path)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def render_world(root, data):
    if not isinstance(data, dict) or any(not isinstance(data.get(key), dict) for key in DIMENSIONS):
        raise ValueError('轻量世界资料必须包含六个分类对象；不相关分类可为空对象')
    if not data['core_laws'] or not data['space_time']:
        raise ValueError('轻量世界资料缺少核心规则或时间地点')
    if len(_json(data)) > 18000:
        raise ValueError('世界资料过大，请选择完整准备；没有截断资料')
    sections = ['# 短篇世界基础', '']
    for key, title in DIMENSIONS.items():
        if data[key]:
            sections.extend([f'## {title}', '', _render(data[key]), ''])
    files = {f'world/{key}.json': _json(data[key]) for key in DIMENSIONS}
    files['meta/world_foundation.md'] = '\n'.join(sections).rstrip() + '\n'
    _publish(root, files)


def render_characters(root, data):
    characters = data.get('characters') if isinstance(data, dict) else None
    if not isinstance(characters, list) or not 1 <= len(characters) <= 10:
        raise ValueError('轻量角色资料须含1—10位相关角色')
    if len(_json(data)) > 22000:
        raise ValueError('角色资料过大，请选择完整准备；没有截断资料')
    names, profiles, voices, bases, voice_records = set(), ['# 角色档案', ''], ['# 角色声音锚', ''], [], []
    for item in characters:
        if not isinstance(item, dict):
            raise ValueError('角色必须是对象')
        name = _text(item.get('name'), '人物姓名')
        if name in names or len(name) > 60 or re.search(r'[\x00-\x1f/\\<>:"|?*#]', name) or name in {'.', '..'}:
            raise ValueError('人物姓名重复或包含不安全字符')
        names.add(name)
        v2 = _card_v2(item)
        base = {'name': name}
        profiles.extend([f'## {name}', ''])
        if v2:
            base.update({key: item[key] for key in ('card_schema', 'facts', 'personality', 'plot_constraints')})
            profiles.extend(['### 已确认事实', ''])
            profiles.extend('- ' + fact for fact in item['facts'])
            profiles.extend(['', '### 性格与关系', '', '- 性格倾向：' + item['personality']])
        for key, label in [('role', '身份'), ('want', '当前欲望'), ('fear', '顾虑'),
                           ('boundary', '价值底线'), ('contradiction', '内在矛盾')]:
            if v2 and key == 'boundary':
                continue
            value = item.get(key)
            if key == 'boundary' and isinstance(value, list):
                if not value:
                    raise ValueError(f'轻量准备缺少{name}的{label}')
                display = '；'.join(_text(entry, f'{name}的{label}') for entry in value)
            else:
                display = _text(value, f'{name}的{label}')
            base[key] = value
            profiles.append(f'- {label}：{display}')
        facts = item.get('facts', [])
        if not isinstance(facts, list):
            raise ValueError('已确认事实必须是数组')
        if 'facts' in item and not v2:
            for fact in facts:
                _text(fact, '已确认事实')
            base['facts'] = facts
            profiles.extend('- 已确认事实：' + fact for fact in base['facts'])
        relationships = item.get('relationships')
        if not isinstance(relationships, list):
            raise ValueError(f'{name}缺少关系资料')
        for relation in relationships:
            if not isinstance(relation, dict):
                raise ValueError('关系条目格式无效')
            who, dynamic = _text(relation.get('with'), '关系对象'), _text(relation.get('dynamic'), '关系处境')
            profiles.append(f'- 与{who}：{dynamic}')
        base['relationships'] = relationships
        profiles.append('')
        if v2:
            profiles.extend(['### 作者情节边界', ''])
            profiles.extend('- ' + constraint for constraint in item['plot_constraints'])
            profiles.append('')
        voice = item.get('voice')
        if not isinstance(voice, dict):
            raise ValueError(f'{name}缺少声音资料')
        baseline = _text(voice.get('baseline'), f'{name}的说话依据')
        contexts, avoid = voice.get('by_relationship', []), voice.get('avoid', [])
        if not isinstance(contexts, list) or not isinstance(avoid, list):
            raise ValueError(f'{name}缺少情境化声音或表达边界')
        voices.extend([f'## {name}', '', '表达倾向（非固定台词）：' + baseline, ''])
        for context in contexts:
            if not isinstance(context, dict):
                raise ValueError('声音情境条目格式无效')
            who, guidance = _text(context.get('with'), '谈话对象/情境'), _text(context.get('guidance'), '声音指导')
            voices.append(f'- 关系情境参考（可随情境调整），面对{who}：{guidance}')
        for boundary in avoid:
            voices.append('- 旧档表达约束（原文保留）：' + _text(boundary, '表达边界'))
        for key, label in [('preferences', '表达倾向（非固定台词）'),
                           ('when_adaptable', '可随情境调整'), ('boundaries', '明确表达边界')]:
            entries = voice.get(key, [])
            if not isinstance(entries, list):
                raise ValueError(f'{name}的{label}必须是数组')
            for entry in entries:
                if key == 'when_adaptable' and isinstance(entry, dict):
                    if set(entry) != {'condition', 'reaction'}:
                        raise ValueError('可随情境调整条目必须包含condition和reaction')
                    entry = _text(entry['condition'], '适用情境') + '：' + _text(entry['reaction'], '可变化的反应')
                voices.append(f'- {label}：' + _text(entry, label))
        voices.append('')
        bases.append(base)
        voice_records.append({'name': name, **voice})
    _publish(root, {'meta/character_profiles.md': '\n'.join(profiles).rstrip() + '\n',
                    'meta/character_voice.md': '\n'.join(voices).rstrip() + '\n',
                    'cache/character/skeleton.json': _json({'characters': bases}),
                    'cache/character/voice.json': _json({'characters': voice_records})})


def prepare_context(root, chapter):
    if chapter != '0001':
        raise ValueError('轻量正文准备仅支持独立短篇首章；请使用完整流程')
    if _path(root, f'story/{chapter}/chapter.md').exists():
        raise ValueError('已有正文已保留；请通过返修或重新生成流程处理')
    sources = {}
    for relative in (*REQUIRED, *OPTIONAL):
        path = _path(root, relative)
        if not path.is_file():
            if relative in REQUIRED:
                raise ValueError(f'缺少 {relative}，请先完成准备')
            continue
        value = path.read_text(encoding='utf-8-sig')
        if relative in REQUIRED and not value.strip():
            raise ValueError(f'缺少有效资料 {relative}')
        if len(value) > 24000:
            raise ValueError(f'{relative} 超出轻量完整上下文范围，请选择完整准备；未截断')
        sources[relative] = value
    context = '\n\n'.join(f'## {name}\n\n{text}' for name, text in sources.items())
    project_path = _path(root, '.novel-project.json')
    if project_path.is_file():
        project = json.loads(project_path.read_text(encoding='utf-8-sig'))
        values = project.get('values', {})
        context += '\n\n## 作者确认要求\n' + '\n'.join(
            str(values.get(key) or '') for key in ('premise', 'source_idea', 'advisor_guidance', 'human_intent', 'world_intent'))
    if len(context) > 80000:
        raise ValueError('资料总量超过轻量完整上下文范围，请使用完整准备；未截断任何证据')
    guide = sources['outline/near_term_outline.md']
    world_state = sources.get('meta/current_world.md') or sources['meta/world_foundation.md']
    character_state = sources.get('meta/current_characters.md') or sources['meta/character_profiles.md']
    _publish(root, {'cache/short/production_context.md': '# 独立短篇写作上下文\n\n' + context + '\n',
                    f'story/{chapter}/single_chapter_guide.md': guide,
                    f'story/{chapter}/world_state.md': '# 生成前世界基线\n\n' + world_state,
                    f'story/{chapter}/world_events.md': '# 本章事件状态\n\n本章尚未发生；按大纲待写，不能把计划当成已确认事实。\n',
                    f'story/{chapter}/character_state_long.md': '# 生成前人物基线\n\n' + character_state,
                    f'story/{chapter}/character_minor.md': sources['meta/character_profiles.md'],
                    f'story/{chapter}/character_profiles_trimmed.md': sources['meta/character_profiles.md'],
                    f'story/{chapter}/world_foundation_trimmed.md': sources['meta/world_foundation.md'],
                    'cache/se/se_output.json': _json({'chapter_number': chapter, 'planned_only': True,
                                                    'source': 'outline/near_term_outline.md', 'guide': guide})})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['world', 'characters', 'context'])
    parser.add_argument('--input')
    parser.add_argument('--chapter', default='0001')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.action == 'context':
        prepare_context(root, args.chapter)
        print('<WF_VAR>short_context_file:cache/short/production_context.md</WF_VAR>')
    else:
        if not args.input:
            parser.error('--input is required')
        data = json.loads(_path(root, args.input).read_text(encoding='utf-8-sig'))
        (render_world if args.action == 'world' else render_characters)(root, data)
    print(json.dumps({'status': 'completed', 'action': args.action}, ensure_ascii=False))


if __name__ == '__main__':
    main()
