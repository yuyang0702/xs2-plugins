"""Stable, explicit style/conflict choices; source evidence never becomes instructions."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path


DIMENSION_SCOPES = {
    'structure': ('story-plan', 'outline'),
    'voice': ('character', 'mvp', 'polish'),
    'topic': ('novel-advisor',),
    'case': ('novel-advisor', 'story-plan', 'outline', 'mvp'),
    'pacing': ('outline', 'mvp'),
    'layout': ('mvp', 'export'),
    'expression': ('mvp', 'polish'),
}
DIMENSION_NAMES = {'structure': '结构', 'voice': '语感', 'topic': '选题', 'case': '案例写法',
                   'pacing': '节奏', 'layout': '排版', 'expression': '表达习惯'}


def mechanism_scopes(item):
    scopes = item.get('scopes') or ()
    dimension = item.get('dimension')
    if not dimension:
        return tuple(scopes)
    supported = DIMENSION_SCOPES[dimension]
    return tuple(stage for stage in supported if stage in scopes) or supported


def active_blueprint(root):
    root = Path(root).resolve()
    active = root / 'learning/active.json'
    if not active.is_file():
        return {}, {}
    if not active.resolve().is_relative_to(root):
        raise ValueError('采用记录越出本书工作区')
    entry = json.loads(active.read_text(encoding='utf-8-sig'))
    relative = Path(entry['blueprint_path'])
    target = (root / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root / 'learning/blueprints'):
        raise ValueError('采用蓝图路径无效')
    blueprint = json.loads(target.read_text(encoding='utf-8-sig'))
    if fingerprint(blueprint) != entry['blueprint_sha256']:
        raise ValueError('创作蓝图被修改，请重新确认')
    return entry, blueprint


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(filter(None, (text(item) for item in value)))
    return ""


def reference_choices(data):
    """IDs ignore evidence/window changes, but distinguish source and rule meaning."""
    source = data.get("source") or {}
    result = {}
    for kind, key in (("style", "style_observations"), ("conflict", "conflict_patterns")):
        choices = []
        for item in data.get(key, []):
            if not isinstance(item, dict):
                continue
            origin = item.get("source") or source
            meaningful = {k: v for k, v in item.items() if k not in {"evidence", "confidence", "source", "choice_id", "support_count"}}
            identifier = kind + "-" + fingerprint([origin.get("text_sha256"), meaningful])[:24]
            if any(choice["choice_id"] == identifier for choice in choices):
                continue
            guidance = text(item.get("transfer_guidance") or item.get("adaptation_guidance"))
            choices.append({**item, "choice_id": identifier, "kind": kind, "source": origin,
                            "title": text(item.get("name") or item.get("rule")) or ("风格特点" if kind == "style" else "冲突递进"),
                            "transfer_guidance": guidance,
                            "requires_adaptation": not bool(guidance) or kind == "conflict"})
        result[kind + "_choices"] = choices
    result["reference_choices_sha256"] = fingerprint([result["style_choices"], result["conflict_choices"]])
    return result


def with_reference_choices(data):
    return {**data, **reference_choices(data)}


# The planner chooses from this book's adapted guidance. Source evidence, source
# character names and the advisor's raw report do not belong to this projection.
def catalog(blueprint, mode=None):
    options = []
    for group, identifier, field in (('mechanisms', 'candidate_id', 'transfer_guidance'),
                                      ('styles', 'choice_id', 'guidance'), ('conflicts', 'choice_id', 'guidance')):
        for row in blueprint.get(group, []):
            scopes = row.get('application_scope') or ['general']
            if isinstance(scopes, str):
                scopes = [scopes]
            if mode and 'general' not in scopes and mode not in scopes:
                continue
            if group == 'mechanisms' and not set(mechanism_scopes(row)).intersection({'outline', 'mvp', 'polish'}):
                continue
            guidance = text(row.get(field))
            if guidance:
                options.append({'id': row.get(identifier) or fingerprint(row), 'kind': group, 'guidance': guidance,
                                'limits': text(row.get('constraints') or row.get('limits'))})
    return options


def read_book(root, name):
    root = Path(root).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('参考筛选资料越出本书工作区')
    return target.read_text(encoding='utf-8-sig') if target.is_file() else ''


def chapter_section(text, chapter):
    """Extract only the current chapter, including nested scene headings."""
    headings = list(re.finditer(r'^([#]{1,6})[ \t]+([^\n]+)', text, re.M))
    sections = []
    active_level = None
    for index, heading in enumerate(headings):
        level = len(heading[1])
        if active_level is not None and level <= active_level:
            active_level = None
        number = re.match(r'(?:第\s*)?(\d+)\s*章\b', heading[2])
        if not number or active_level is not None:
            continue
        active_level = level
        if int(number[1]) == int(chapter):
            end = next((later.start() for later in headings[index+1:] if len(later[1]) <= len(heading[1])), len(text))
            sections.append(text[heading.start():end].strip())
    return '\n\n'.join(sections)


def terms(value):
    result = set(re.findall(r'[a-z0-9]{2,}', value.lower()))
    for span in re.findall(r'[\u3400-\u9fff]+', value):
        result.update(span[i:i+2] for i in range(len(span)-1))
    return result.difference({'人物', '本章', '场景', '本书', '选择', '短篇', '故事', '结尾', '情节', '使用', '读者'})


def ranked(options, signals):
    query = terms(signals)
    return sorted(((len(query & terms(row['guidance'])), row) for row in options),
                  key=lambda pair: -pair[0])


def project_scope(root):
    project = json.loads(read_book(root, '.novel-project.json') or '{}')
    values = project.get('values', {})
    mode = 'short_full' if project.get('mode') == 'short' else values.get('conflict_plan_mode')
    return mode, values


def chapter_instruction(root, chapter, values):
    feedback = values.get('author_feedback_file')
    if (not feedback or not chapter or chapter != str(values.get('chapter_number') or '0001').zfill(4)
            or not read_book(root, feedback)):
        return None
    entry = Path(__file__).resolve().parents[1] / 'local_revision/local_revision.py'
    spec = importlib.util.spec_from_file_location('reference_author_feedback', entry)
    local = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(local)
    authored, _, _ = local.feedback_layers(root, feedback)
    return {'chapter': chapter, 'text': authored} if authored.strip() else None


def planner_options(root, signals, chapter=None):
    active, blueprint = active_blueprint(root)
    mode, values = project_scope(root)
    author = {key: values[key] for key in ('premise', 'human_intent', 'world_intent', 'style_intent', 'chapter_ending_mode')
              if values.get(key)}
    instruction = chapter_instruction(root, chapter, values)
    if instruction:
        author['chapter_instruction'] = instruction
    options = catalog(blueprint, mode)
    if len(options) > 18:
        options = [row for _, row in ranked(options, signals + '\n' + '\n'.join(map(str, author.values())))[:18]]
    return {'blueprint_sha256': active.get('blueprint_sha256'), 'author': author, 'options': options}


def validate_ids(ids, options):
    if (not isinstance(ids, list) or any(not isinstance(key, str) for key in ids)
            or len(set(ids)) != len(ids) or len(ids) > 3 or not set(ids) <= {row['id'] for row in options}):
        raise ValueError('每章可选零至三项参考，编号须取自本次规划的候选且不重复')
    return ids


def chapter_selection(root, chapter, blueprint):
    """Return this chapter's own plan, or a conservative match for historical outlines."""
    if not re.fullmatch(r'\d{4}', chapter):
        raise ValueError('参考筛选需要四位章节编号')
    mode, values = project_scope(root)
    options = catalog(blueprint, mode)
    allowed = {row['id'] for row in options}
    plan = json.loads(read_book(root, f'planning/chapters/{chapter}.json') or '{}')
    if 'reference_ids' in plan:
        return [key for key in plan['reference_ids'] if key in allowed], 'chapter_plan'
    section = chapter_section(read_book(root, 'outline/near_term_outline.md'), chapter)
    if not plan:
        outline = json.loads(read_book(root, 'cache/no/near_term.json') or '{}')
        selection = outline.get('reference_selections', {}).get(chapter)
        # An explicit omission lasts until this chapter is replanned, including
        # when the author subsequently edits a location or line in its outline.
        if selection and selection.get('reference_ids') == []:
            return [], 'outline'
        if selection and selection.get('chapter_text') and selection['chapter_text'] in section:
            return [key for key in selection['reference_ids'] if key in allowed], 'outline'
    signals = [section, *(str(plan.get(key) or '') for key in
                          ('title', 'intent', 'goal', 'choice', 'conflict', 'turn', 'emotion', 'outcome'))]
    if mode == 'short_full':
        signals.extend(str(values.get(key) or '') for key in ('premise', 'human_intent', 'source_idea', 'chapter_ending_mode'))
        signals.append(read_book(root, 'meta/story_plan.md'))
        if not section:
            signals.append(read_book(root, 'outline/near_term_outline.md'))
    shortlist = [row['id'] for score, row in ranked(options, '\n'.join(signals)) if score][:3]
    return shortlist, 'scene_match'


def selected_guidance(root, chapter):
    _, blueprint = active_blueprint(root)
    if not blueprint:
        return []
    picked, _ = chapter_selection(root, chapter, blueprint)
    return [row['guidance'] for row in catalog(blueprint) if row['id'] in picked and row['kind'] in ('styles', 'conflicts')]
