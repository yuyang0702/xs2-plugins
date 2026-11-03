"""Project confirmed state using the hash and text of the original chapter."""
from collections import Counter
import re

from .cards import _relation, source_path
from .dependencies import sibling


SNAPSHOT = {'location', 'physical', 'resources', 'emotion', 'goal', 'knowledge', 'misbelief', 'current_state'}
DRIVES = {'goal', 'bottom_line', 'desire', 'want', 'fear', 'current_goal', 'motivation'}
RELATIONSHIP = {'target', 'change', 'nature', 'status', 'meaning_to_character', 'hidden_tension', 'default_attitude'}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _string(value):
    return value if isinstance(value, str) else ''


def _fields(value, allowed, *, lists=()):
    if not isinstance(value, dict):
        raise ValueError('人物状态需要明确的键值结构。')
    fields = {}
    for key in allowed & value.keys():
        item = value[key]
        if isinstance(item, str) or (key in lists and isinstance(item, list)
                                    and all(isinstance(member, str) for member in item)):
            fields[key] = item
        elif item is not None:
            raise ValueError('人物状态字段格式无效。')
    return fields


def _project_row(row):
    list_keys = ('resources', 'knowledge', 'misbelief')
    state = _fields(row.get('snapshot', {}), SNAPSHOT, lists=list_keys)
    drives = _fields(row.get('drives', {}), DRIVES)
    attitude = _fields(row, {'knowledge', 'misbelief'}, lists=list_keys) | state
    relationships = row.get('relationships', [])
    if not isinstance(relationships, list):
        raise ValueError('人物关系状态格式无效。')
    relations = [_fields(relation, RELATIONSHIP) for relation in relationships]
    if any(not relation.get('target', '').strip() for relation in relations):
        raise ValueError('人物关系缺少目标。')
    return dict(snapshot=state, drives=drives, knowledge=attitude.get('knowledge', []),
                beliefs=attitude.get('misbelief', []), relationships=relations)


def chapter_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}', value) or int(value) < 1:
        raise ValueError('请输入有效章节号。')
    return f'{int(value):04d}'


def _evidence(root, chapter, row, valid, story):
    origin = _string(row.get('source_chapter'))
    if origin not in valid or origin > chapter:
        return None
    source_id = f'story/{origin}/chapter.md'
    try:
        body = source_path(root, source_id).read_bytes().decode('utf-8-sig')
        quote = story.validated_evidence(row.get('evidence'), body, '正文证据不符')
        quotes = quote if isinstance(quote, list) else [quote]
        if not all(item in body for item in quotes):
            return None
    except (ValueError, OSError):
        return None
    return dict(source_id=source_id, source_chapter=origin, evidence=quote)


def add_state(root, view, chapter=''):
    story = sibling('story_support')
    chapter = chapter_id(chapter) if chapter else ''
    snapshots, stale = story.confirmed(root)
    valid = {row['chapter'] for row in snapshots}
    chapter = chapter or max(valid, default='')
    view.update(chapter=chapter, chapters=sorted(valid), stale_chapters=stale, world_facts=[])
    counts = Counter(item['name'] for item in view['characters'])
    people = {item['name']: item for item in view['characters'] if counts[item['name']] == 1}
    for document in snapshots:
        number = document['chapter']
        if number > chapter:
            break
        rows = _rows(document.get('characters'))
        occurrences = Counter(_string(row.get('name')) for row in rows)
        for row in rows:
            name = _string(row.get('name'))
            if name not in people or occurrences[name] != 1 or not (proof := _evidence(root, number, row, valid, story)):
                continue
            try:
                projected = _project_row(row)
            except ValueError:
                continue
            if any(projected.values()):
                people[name]['states'].append(dict(chapter=number, **proof, **projected))
        facts = []
        for row in _rows(_mapping(document.get('world')).get('facts')):
            if _string(row.get('description')) and (proof := _evidence(root, number, row, valid, story)):
                facts.append(dict(description=row['description'], **proof))
        view['world_facts'] = facts
    for person in people.values():
        if not person['states']:
            continue
        state = person['states'][-1]
        for row in state['relationships']:
            nature = _string(row.get('nature') or row.get('status'))
            person['relationships'].append(_relation(
                row['target'], _string(row.get('change')) or nature, state['source_id'], None, 'confirmed_state',
                nature=nature, meaning=_string(row.get('meaning_to_character')),
                tension=_string(row.get('hidden_tension')), attitude=_string(row.get('default_attitude'))))
