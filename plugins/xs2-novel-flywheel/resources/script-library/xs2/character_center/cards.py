"""Project explicitly labelled Markdown values without altering unknown text."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

from .dependencies import sibling


SOURCES = {'meta/character_profiles.md': 'profile', 'meta/character_voice.md': 'voice'}
LABELS = {
    'overview': '身份 社会身份 出身阶层 所属势力 真名',
    'motivation': '当前欲望 顾虑 价值底线 内在矛盾 性格参考 骨架性格参考 深化性格参考 '
                  '表层目标 深层欲望 恐惧 信念 冲突元素 可能走向',
    'facts': '已确认事实 体现的规则 被塑造的规则',
    'plan': '成长方向 堕落方向 关键抉择',
    'voice': '核心声音定位 表达倾向 表达倾向（非固定台词） 长短句偏好 停顿习惯 常用句式 '
             '表达习惯 关注点与情绪表达 不会使用的表达 对话示例 已有惯用表达（不要求重复） '
             '愤怒时 紧张时 撒谎时 可随情境调整 明确表达边界 旧档表达约束（原文保留） 认知偏差',
}
GROUPS = {label: group for group, labels in LABELS.items() for label in labels.split()}
AI_FIELDS = set(
    '核心声音定位 表达倾向 表达倾向（非固定台词） 长短句偏好 停顿习惯 常用句式 '
    '表达习惯 关注点与情绪表达 愤怒时 紧张时 撒谎时 可随情境调整'.split()
)
HEADING = re.compile(r'^ {0,3}(#{3,4})\s+(.+?)(?:\s+#+)?$')
FIELD = re.compile(r'^ {0,3}(?:[-+*] |[>] )?(?:\*\*(?P<bold>[^*：:]+)\*\*[：:]'
                   r'|\*\*(?P<bold_inside>[^*：:]+)[：:]\*\*|(?P<label>[^*：:]+?)[：:])'
                   r'[ \t]*(?P<value>\S.*?)[ \t]*$')
RELATION = re.compile(r'^(?:关系情境参考（可随情境调整），)?面对(.+)$')
TABLE_HEADERS = ['对象', '关系', '意义', '隐藏张力', '默认态度']
PROTECTED = {'已确认事实': 'facts', '作者情节边界': 'constraints'}
HEADINGS = set(GROUPS) | set(PROTECTED) | {
    '性格与关系', '世界烙印', '世界位置', '世界观锚点', '内在构造', '核心信念', '核心欲望',
    '深层恐惧', '秘密', '个人价值倾向（依当前情境理解）', '不可触碰的底线', '创伤与矛盾',
    '关键创伤', '内在矛盾', '人际与弧线', '关系网络', '弧线潜能', '情绪下可能的表达（依当前情境）',
}


def workspace(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('作品工作区不存在。')
    return root


def source_path(root, relative):
    target = root / relative
    if target.resolve() != target:
        raise ValueError('不能通过链接访问人物资料。')
    return target


def digest(data):
    return sha256(data).hexdigest()


def _name(title):
    # Match the published numbered/alias headings, using the remaining exact
    # spelling. Never match a person via an alias or normalized similarity.
    title = re.sub(r'^\d+[.、)]\s*', '', title.strip().strip('*_`').strip())
    return re.sub(r'\s*(?:（[^（）]+）|\([^()]+\))$', '', title).strip() or title


def _relation(target, text, source_id, section_id, provenance, *, nature='', meaning='', tension='', attitude=''):
    return dict(target=target, target_id=None, text=text, nature=nature, meaning=meaning, tension=tension,
                attitude=attitude, source_id=source_id, section_id=section_id, provenance=provenance)


def _lines(raw, start):
    """Skip fenced examples but retain their exact location in the raw card."""
    fence = None
    for line in raw.splitlines(keepends=True):
        clean = line.rstrip('\r\n')
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)', clean)
        if match:
            marker, rest = match.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            yield clean, start
        start += len(line)


def _fields(source, card, card_id, closed):
    sections, ranges, relations = [], {}, []
    headings = {}
    count = Counter()
    table = False
    for line, offset in _lines(card['body'], card['body_start']):
        match = HEADING.fullmatch(line)
        if match:
            level = len(match[1])
            headings = {key: label for key, label in headings.items() if key < level}
            headings[level] = match[2]
            table = False
            continue
        hierarchy = tuple(headings.values())
        current = next(reversed(headings.values()), '')
        protected = next((PROTECTED[title] for title in hierarchy if title in PROTECTED), '')
        if not protected and any(title not in HEADINGS for title in hierarchy):
            continue
        if current == '关系网络' and line.startswith('|') and line.endswith('|'):
            columns = [part.strip() for part in re.split(r'(?<!\\)\|', line[1:-1])]
            if columns == TABLE_HEADERS:
                table = True
            elif table and len(columns) == 5 and columns[0] and not re.fullmatch(r'[:\s-]+', columns[0]):
                target, nature, meaning, tension, attitude = [part.replace(r'\|', '|') for part in columns]
                relations.append(_relation(target, line, source['source_id'], None, 'profile',
                                           nature=nature, meaning=meaning, tension=tension, attitude=attitude))
            continue
        match = FIELD.fullmatch(line)
        label, value, value_start = '', '', 0
        if match:
            label = (match['bold'] or match['bold_inside'] or match['label']).strip()
            value, value_start = match['value'], match.start('value')
        voice_prose = current in {'核心声音定位', '表达倾向（非固定台词）', '可随情境调整',
                                 '明确表达边界', '旧档表达约束（原文保留）', '认知偏差'}
        if (not match or (voice_prose and label not in GROUPS and not RELATION.fullmatch(label))) and line.strip() \
                and not line.lstrip().startswith(('#', '|')):
            label = current if current in GROUPS and source['kind'] == 'voice' else ''
            if protected and line.startswith('- '):
                label = next(title for title, group in PROTECTED.items() if group == protected)
            if label:
                value = line.strip().removeprefix('- ').strip()
                value_start = line.index(value) if value else 0
        if not value or value == '—':
            continue
        relation = RELATION.fullmatch(label) if source['kind'] == 'voice' else re.fullmatch(r'与(.+)', label)
        group = protected or ('relationships' if relation else GROUPS.get(label))
        if not group:
            continue
        if source['kind'] == 'voice' and group not in {'voice', 'relationships'}:
            continue
        if group == 'plan' and current != '弧线潜能':
            continue
        if protected and label not in PROTECTED:
            # Facts/constraints may contain a colon as part of their prose.
            label = next(title for title, kind in PROTECTED.items() if kind == protected)
            value = line.strip().removeprefix('- ').strip()
            value_start = line.index(value)
        key = '/'.join((*hierarchy, label))
        count[key] += 1
        identity = digest(f'{card_id}:{key}:{count[key]}'.encode())[:24]
        editable = bool(closed and group not in {'facts', 'constraints'} and not relation
                        and label not in {'身份', '真名', '社会身份', '出身阶层', '所属势力',
                                          '旧档表达约束（原文保留）', '明确表达边界', '价值底线', '不会使用的表达'})
        row = dict(id=identity, source_id=source['source_id'], source_revision=source['revision'], group=group,
                   label=label, text=value, editable=editable,
                   ai_editable=editable and source['kind'] == 'voice' and label in AI_FIELDS,
                   line=source['raw'].count('\n', 0, offset) + 1)
        start = offset + value_start
        sections.append(row)
        ranges[identity] = (start, start + len(value))
        if relation and not protected:
            relations.append(_relation(relation[1], value, source['source_id'], identity, source['kind'],
                                       nature=value if source['kind'] == 'profile' else ''))
    return sections, ranges, relations


def inventory(root, documents=None):
    voice = sibling('voice_support')
    if documents is None:
        paths = {source: source_path(root, source) for source in SOURCES}
        documents = {source: path.read_bytes() if path.is_file() else None for source, path in paths.items()}
    sources, by_source, warnings = [], {}, []
    for source_id, kind in SOURCES.items():
        data = documents[source_id]
        source = dict(source_id=source_id, kind=kind, status='present' if data is not None else 'missing',
                      revision=digest(data) if data is not None else None, raw=(data or b'').decode('utf-8-sig'))
        sources.append(source)
        closed = True
        try:
            parsed = voice._sections(source['raw'], require_closed_fences=True)
        except ValueError:
            parsed, closed = voice._sections(source['raw']), False
            warnings.append(f'{source_id} 的代码块未闭合，仅可查看。')
        if not parsed and source['raw']:
            warnings.append(f'{source_id} 未找到可识别的人物标题，请查看原文。')
        by_source[kind] = [(source, card, voice._id(kind, index, card['title']), closed)
                           for index, card in enumerate(parsed)]
    profiles, voices = by_source['profile'], by_source['voice']
    profile_count = Counter(_name(item[1]['title']) for item in profiles)
    voice_count = Counter(_name(item[1]['title']) for item in voices)
    unique_voice = {_name(item[1]['title']): item for item in voices if voice_count[_name(item[1]['title'])] == 1}
    people, ranges, merged = [], {}, set()
    for item in profiles + voices:
        source, card, identity, closed = item
        if identity in merged:
            continue
        name = _name(card['title'])
        ambiguous = profile_count[name] > 1 or voice_count[name] > 1
        paired = [item]
        if source['kind'] == 'profile' and not ambiguous and name in unique_voice:
            paired.append(unique_voice[name])
            merged.add(unique_voice[name][2])
        person = dict(id=identity, name=name, title=card['title'], status='legacy', warnings=[], sections=[],
                      relationships=[], states=[], planned_arcs=[], raw=[])
        for document, part, part_id, well_formed in paired:
            person['raw'].append(dict(source_id=document['source_id'], title=part['title'], text=part['body']))
            if not ambiguous:
                sections, offsets, relations = _fields(document, part, part_id, well_formed)
                person['sections'].extend(sections)
                person['relationships'].extend(relations)
                ranges.update(offsets)
        if ambiguous:
            person['warnings'].append('姓名重复，无法唯一匹配人物，保留原文。')
        elif person['sections'] or person['relationships']:
            person['status'] = 'structured'
            person['planned_arcs'] = [row for row in person['sections'] if row['group'] == 'plan']
        else:
            person['warnings'].append('未识别出可结构化的字段，请查看原文。')
        people.append(person)
    revision = voice._revision(root, {Path(name).name: data for name, data in documents.items()})
    return dict(revision=revision, characters=people, sources=sources, warnings=warnings), ranges, documents


def link_relations(people):
    counts = Counter(person['name'] for person in people)
    ids = {person['name']: person['id'] for person in people if counts[person['name']] == 1}
    for person in people:
        for relation in person['relationships']:
            relation['target_id'] = ids.get(relation['target'])
