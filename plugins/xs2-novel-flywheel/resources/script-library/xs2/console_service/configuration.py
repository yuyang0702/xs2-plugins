"""Validated, optional planning suggestions; never executable model actions."""
import json
import re

FIELD_LABELS = {
    'premise': '故事创意', 'genre': '题材', 'narrative_pov': '叙事视角',
    'target_word_count': '正文目标字数', 'words_per_chapter': '每章字数',
    'estimated_length': '预计篇幅', 'world_direction': '世界观方向',
    'conflict_plan_mode': '冲突规划范围', 'conflict_point_count': '冲突点数量',
    'foreshadowing_count': '伏笔数量', 'human_intent': '本章想写什么',
    'world_intent': '世界发生的变化',
}


def advisor_catalog(catalog):
    """A source index for planning; detailed evidence is reserved for review."""
    fields = {'candidate_id', 'choice_id', 'mechanism', 'title', 'kind', 'layer', 'scopes',
              'application_scope', 'target_pov', 'source_pov', 'pov_compatibility', 'risk_flags'}
    result = []
    for library in catalog:
        source = library.get('candidates', {})
        profile = library.get('profile', {})
        if not isinstance(source, dict):
            continue
        choices = {}
        for key in ('candidates', 'style_choices', 'conflict_choices'):
            choices[key] = []
            for item in source.get(key, []):
                compact = {key: value for key, value in item.items() if key in fields}
                guidance = item.get('transfer_guidance') or item.get('adaptation_guidance')
                if isinstance(guidance, str):
                    compact['guidance'] = guidance[:600]
                choices[key].append(compact)
        result.append({'library_id': library['library_id'], 'name': library.get('name', ''),
                       'source_description': {key: profile[key] for key in ('genre', 'word_count', 'source_pov')
                                              if isinstance(profile, dict) and isinstance(profile.get(key), (str, int))},
                       'candidates': choices})
    return result


def parse_configuration(text: str, mode: str) -> tuple[str, list[dict]]:
    raw = text.strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('reply'), str) or not data['reply'].strip():
        raise ValueError('missing readable answer')
    items = data.get('suggestions', [])
    if not isinstance(items, list):
        raise ValueError('invalid suggestions')
    accepted = {}
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        key, value = item.get('key'), item.get('value')
        if key not in FIELD_LABELS or not isinstance(value, (str, int)) or isinstance(value, bool):
            continue
        value = str(value).strip()
        if not value or len(value) > 6000:
            continue
        if key == 'narrative_pov' and value not in {'first_person', 'third_person'}:
            continue
        if key == 'estimated_length':
            if value[0] not in {'短', '中', '长'}:
                continue
            value = value[0]
        if key == 'conflict_plan_mode' and value not in (
            {'short_full'} if mode == 'short' else {'serial_opening', 'serial_arc', 'serial_chapter'}
        ):
            continue
        if key in {'conflict_point_count', 'foreshadowing_count'} and (
            not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 50
        ):
            continue
        if key in {'target_word_count', 'words_per_chapter'}:
            match = re.fullmatch(r'(\d{2,6})(?:\s*[-～—]\s*(\d{2,6}))?', value)
            if not match:
                continue
            low, high = int(match[1]), int(match[2] or match[1])
            if not 100 <= low <= high <= 100000:
                continue
            value = f'{low}-{high}' if match[2] else str(low)
        reason = item.get('reason', '')
        accepted[key] = {'key': key, 'label': FIELD_LABELS[key], 'value': value,
                         'reason': reason[:1600] if isinstance(reason, str) else ''}
    return data['reply'].strip(), list(accepted.values())


CONFIGURATION_PROMPT = (
    '本次用户选择了“分析并完善设置”。根据用户想法给出一个推荐方案并说明理由，'
    '同时输出可填写参数。先尊重用户明确要求和已有设定，不预设必须使用蒸馏。'
    '只输出JSON对象：{"reply":"面向作者阅读的中文Markdown建议",'
    '"suggestions":[{"key":"参数名","value":"字符串值","reason":"推荐理由"}]}。'
    'reply须回答字数、视角、世界观方向、冲突递进和伏笔如何适配此创意，'
    '人物应有欲望、弱点、独立选择和关系代价，不能只充当剧情工具。'
    '建议参数仅限：' + ', '.join(FIELD_LABELS) + '。'
    'narrative_pov只能first_person/third_person；字数用纯数字或3000-4000格式。'
    '短篇target_word_count指整篇字数，冲突范围只能short_full；'
    '长篇target_word_count指当前一章，每章字数建议与之协调；estimated_length只能短/中/长，'
    '具体全书规模或短篇字数在reply解释，短篇通常填短，'
    '冲突范围只能serial_opening/serial_arc/serial_chapter，须说明覆盖前几章或当前卷。'
    '冲突与伏笔数量须为0至50整数，数量以因果推进所需为准，不能机械堆叠。'
    'world_direction是供建立世界观步骤使用的方向草稿，不是已经存在的正式档案。'
    'human_intent/world_intent仅在具体本章目标明确时建议，不用整本书规划代替每章意图。'
    '不要输出目录、文件路径、执行命令、章号、写法选择或修改作品类型。'
    '填写由页面执行，只能说推荐/建议；不得宣称已填写或已生成正文。'
    '已有正文、世界观、人物或已确定方向的作品应沿用事实，改变核心设定时指出需要作者另行调整。'
)


ADVISOR_PROMPT = CONFIGURATION_PROMPT.replace('本次用户选择了“分析并完善设置”。', '本次用户正在与小说顾问讨论方向。') + (
    '本次是正式创作前的小说顾问交流，优先判断这本书写什么、主要看点是什么、适合怎么写。'
    '除reply和suggestions外，JSON还必须包含advisor_sections对象，其四个核心键均为中文Markdown字符串：'
    'direction（推荐的故事方向，具体主角、目标与故事起点，可给少量备选并明确推荐），'
    'hook（核心看点和读者期待，人物的独立欲望与选择），'
    'writing（字数、视角、节奏、因果递进冲突与伏笔，解释为什么适合），'
    'risks（创意薄弱处、规则矛盾、风格适配风险与处理建议）。'
    '此外，如果写法库中有相关内容，还应包含三个推荐清单（JSON结构，可选）：'
    'mechanism_recommendations（推荐的写法机制，JSON结构：'
    '{"adopted_from_library":[{"library_id":"来源ID","candidate_id":"机制ID","mechanism":"机制名","usage_in_story":"本书具体用法","priority":"HIGH","chapter_placement":"第几章"}],'
    '"new_mechanisms":[{"mechanism":"原创机制名","reason":"推荐理由","synergy_with":["关联机制"],"priority":"MEDIUM"}],'
    '"avoid_combinations":[{"a":"机制A","b":"机制B","reason":"不适合组合的原因"}]}），'
    'style_recommendations（推荐的文风选择，JSON结构：'
    '{"adopted_styles":[{"library_id":"来源ID","choice_id":"风格ID","style":"风格名称","reason":"适配理由","usage_in_story":"具体场景","priority":"HIGH"}],'
    '"avoid_styles":[{"style":"风格名称","reason":"不适合的原因"}]}），'
    'conflict_recommendations（推荐的冲突模式，JSON结构：'
    '{"adopted_conflicts":[{"library_id":"来源ID","choice_id":"冲突ID","conflict":"冲突名称","reason":"适配理由","usage_in_story":"本书展开方式","priority":"HIGH"}],'
    '"avoid_conflicts":[{"conflict":"冲突名称","reason":"不适合的原因"}]})。'
    '推荐时只能从写法来源目录的实际条目中选择，机制推荐必须包含原样library_id和candidate_id，'
    '文风和冲突推荐必须包含原样library_id和choice_id；名称使用该条目的mechanism/title，不得按近义词猜测来源。'
    '例如机制条目：{"library_id":"来源ID","candidate_id":"机制ID","mechanism":"机制原名","usage_in_story":"本书用法"}；'
    '风格条目使用style和choice_id，冲突条目使用conflict和choice_id。目录为空时采用清单为空，可在new_mechanisms提出原创建议。'
    'reply先直接回应用户最新问题或追问，再给简短结论；四个分区补充相应细节，避免重复全文。'
    '初次方向判断保持精炼：reply约100字，四个分区合计约1500字；参数理由简短。'
    '不要把用户整份设定抄进建议参数，原始设定会另外完整传给创作流程。'
    '用户还没想好时也要给可讨论的具体方向，不以缺少题材或字数参数为由拒绝分析。'
    '如存在影响方向的关键缺口，最多追问一到两个问题，并说明目前采用的暂定假设。'
    '既有设定可提出澄清和修改建议，不得悄悄换掉用户的核心概念。'
    '页面默认值不代表用户偏好，以明确输入和configured_fields为准。'
    '涉及科学设定时区分小说假设和现实已证实知识，不将虚构机制称为已证实事实。'
    '本次仅提出方案，必须等用户采用后才填写参数，不声称已经采用、保存正式档案或开始生成正文。'
)


def parse_advisor(text: str, mode: str, catalog=None) -> tuple[str, list[dict], dict[str, str | dict]]:
    reply, suggestions = parse_configuration(text, mode)
    raw = re.sub(r'^```(?:json)?\s*', '', text.strip())
    raw = re.sub(r'\s*```$', '', raw)
    data = json.loads(raw)
    sections = data.get('advisor_sections')
    keys = ('direction', 'hook', 'writing', 'risks')
    if not isinstance(sections, dict) or any(
        not isinstance(sections.get(key), str) or not sections[key].strip() or len(sections[key]) > 14000
        for key in keys
    ):
        raise ValueError('missing adviser sections')
    result = {key: sections[key].strip() for key in keys}

    # 提取 mechanism_recommendations (可选字段)
    mechanism_recs = sections.get('mechanism_recommendations')
    if isinstance(mechanism_recs, (dict, str)):
        if isinstance(mechanism_recs, str):
            try:
                mechanism_recs = json.loads(mechanism_recs)
            except (json.JSONDecodeError, TypeError):
                mechanism_recs = None
        if isinstance(mechanism_recs, dict):
            result['mechanism_recommendations'] = mechanism_recs

    # 提取 style_recommendations (可选字段)
    style_recs = sections.get('style_recommendations')
    if isinstance(style_recs, (dict, str)):
        if isinstance(style_recs, str):
            try:
                style_recs = json.loads(style_recs)
            except (json.JSONDecodeError, TypeError):
                style_recs = None
        if isinstance(style_recs, dict):
            result['style_recommendations'] = style_recs

    # 提取 conflict_recommendations (可选字段)
    conflict_recs = sections.get('conflict_recommendations')
    if isinstance(conflict_recs, (dict, str)):
        if isinstance(conflict_recs, str):
            try:
                conflict_recs = json.loads(conflict_recs)
            except (json.JSONDecodeError, TypeError):
                conflict_recs = None
        if isinstance(conflict_recs, dict):
            result['conflict_recommendations'] = conflict_recs

    if catalog is not None:
        _validate_source_recommendations(result, catalog)
    return reply, suggestions, result


def _validate_source_recommendations(sections, catalog):
    """A model may recommend catalog IDs, but cannot create source identities."""
    for section, selected_key, source_key, id_key, label, title in (
        ('mechanism_recommendations', 'adopted_from_library', 'candidates', 'candidate_id', 'mechanism', 'mechanism'),
        ('style_recommendations', 'adopted_styles', 'style_choices', 'choice_id', 'style', 'title'),
        ('conflict_recommendations', 'adopted_conflicts', 'conflict_choices', 'choice_id', 'conflict', 'title'),
    ):
        group = sections.get(section, {})
        selected = group.get(selected_key, []) if isinstance(group, dict) else []
        if not isinstance(selected, list) or len(selected) > 40:
            raise ValueError('invalid reference recommendations')
        available = {}
        for library in catalog:
            data = library.get('candidates', {})
            for candidate in data.get(source_key, []) if isinstance(data, dict) else []:
                key = (library.get('library_id'), candidate.get(id_key))
                if key in available:
                    raise ValueError('ambiguous catalog source')
                available[key] = candidate
        seen = set()
        for item in selected:
            if not isinstance(item, dict):
                raise ValueError('invalid reference recommendation')
            key = (item.get('library_id'), item.get(id_key))
            if key not in available or key in seen or not all(isinstance(value, str) and value for value in key):
                raise ValueError('unknown or duplicate reference source')
            seen.add(key)
            item[label] = available[key].get(title, item.get(label, ''))
