"""Generate short-fiction proposals and assess openings without the adviser's pitch."""
import json
import random
import re

from .configuration import parse_configuration


CANDIDATE_PROMPT = (
    '这次是短篇选题。请给出恰好三个原创候选，题材、主角困境和冲突来源确实不同。'
    '作者明确限定题材时，在允许范围内给出不同的子题材和冲突，尊重已有事实和本书有效风格。'
    '每个opening写约180至280字的小说正文，篇幅接近，直接让人物遇到眼下的事。'
    '用人物当下注意到的动作、对白和物件承载压力，确数只在影响人物选择、因果或语气时进入正文。'
    '让读者看见谁在做什么、什么已经变了。可以留悬念，不写书名、简介、推荐话或独立导语。'
    'premise说明主角、欲望和障碍；choice与cost写眼前的两难和代价；middle写选择造成的后果如何逼出下一步；'
    'ending写主角如何处理后果并兑现开场的期待。根据给定目标篇幅给出可收束的故事，避免堆反转、靠背景说明填字数。'
    '只输出JSON：{"candidates":[{"title":"标题","genre":"具体题材","opening":"开头正文",'
    '"premise":"故事梗概","choice":"眼前的选择","cost":"选择的代价","middle":"中段的因果推进","ending":"结尾的收束"}]}。'
)

BLIND_PROMPT = (
    '你是独立试读者。输入只有匿名编号和小说开头。按实际想继续阅读的程度将全部开头排序，最想读的排第一。'
    '先看是否能理解眼下的处境，哪处人物反应或矛盾让你真的想看下一段。'
    '悬念和安静场景都可以留住读者，不能因题材、段落位置或刺激程度直接加分。'
    '每项逐字摘录一小段当前开头作证，具体说它如何吸引你或在哪儿让你犹豫，再写最想知道的一件事。'
    '不用数字打分。只输出JSON：{"ranking":[{"id":"所给编号","excerpt":"连续逐字引文",'
    '"reason":"追读或犹豫的具体理由","question":"往下读想知道什么"}]}。'
)

LENGTH_PROMPT = (
    '你是短篇编辑。独立判断每个候选按所给正文字数能否写成一篇完整小说。'
    '检查开场的选择能否造成中段的新处境，人物是否必须再行动，以及结尾是否兑现开场的期待。'
    '有具体可写的中段并能收束用fits，需要靠反复解释或重复冲突填篇幅用too_thin，需要大幅删线才能收束用too_broad。'
    'reason指出判断的因果依据，development写具体可写的中段事件及其收束，risk指出最可能拖慢或撑不住的位置。'
    '评估现有方案，勿把自己另补的情节当成候选已有的优势。'
    '只输出JSON：{"assessments":[{"id":"所给编号","verdict":"fits|too_thin|too_broad",'
    '"reason":"篇幅判断依据","development":"可写的中段和结尾","risk":"节奏风险"}]}。'
)


def target_words(project):
    if 'target_word_count' in (project.get('configured_fields') or []):
        value = (project.get('values') or {}).get('target_word_count')
        text = json.dumps({'reply': '目标', 'suggestions': [{'key': 'target_word_count', 'value': value}]})
        _, suggestions = parse_configuration(text, 'short')
        if suggestions:
            return suggestions[0]['value']
    return '10000'


def reference_guidance(catalog):
    """Only abstract techniques are useful before a specific topic is chosen."""
    return [{'来源': library['name'], '可借鉴的写法': [
        {'写法': row.get('title') or row.get('mechanism'), '迁移提示': row.get('guidance', '')[:240]}
        for kind in ('style_choices', 'candidates', 'conflict_choices')
        for row in library['candidates'].get(kind, [])[:3]
    ]} for library in catalog[:4]]


def _rows(reply, key):
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', reply.strip())
    data = json.loads(raw)
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'{key} 必须是对象列表')
    return rows


def _texts(row, limits):
    for key, limit in limits.items():
        value = row.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f'{key} 缺失或超出长度')
    return {key: row[key].strip() for key in limits}


def parse_candidates(reply):
    rows = [_texts(row, {'title': 120, 'genre': 100, 'opening': 1200, 'premise': 1000,
                         'choice': 600, 'cost': 600, 'middle': 1200, 'ending': 1000})
            for row in _rows(reply, 'candidates')]
    if len(rows) != 3 or any(len({row[key] for row in rows}) != 3
                             for key in ('title', 'genre', 'opening', 'premise')):
        raise ValueError('须交出三个不同题材与开头')
    return [{'id': f'topic-{index}', **row} for index, row in enumerate(rows, 1)]


def blind_input(candidates):
    ordered = random.sample(candidates, k=len(candidates))
    lookup = {chr(65 + index): row for index, row in enumerate(ordered)}
    return lookup, {'openings': [{'id': key, 'opening': row['opening']} for key, row in lookup.items()]}


def _cover(rows, ids):
    if len(rows) != len(ids) or {row['id'] for row in rows} != set(ids):
        raise ValueError('每个给定编号须恰好出现一次')


def parse_ranking(reply, lookup):
    rows = [_texts(row, {'id': 30, 'excerpt': 240, 'reason': 800, 'question': 400})
            for row in _rows(reply, 'ranking')]
    _cover(rows, lookup)
    for row in rows:
        candidate = lookup[row['id']]
        if row['excerpt'] not in candidate['opening']:
            raise ValueError(f'{row["id"]} 的引文须逐字出自所评开头')
        row['id'] = candidate['id']
    return rows


def parse_assessments(reply, candidates):
    rows = [_texts(row, {'id': 30, 'verdict': 30, 'reason': 800, 'development': 1000, 'risk': 600})
            for row in _rows(reply, 'assessments')]
    _cover(rows, {row['id'] for row in candidates})
    if any(row['verdict'] not in {'fits', 'too_thin', 'too_broad'} for row in rows):
        raise ValueError('须明确判断各个候选能否按目标篇幅收束')
    return rows


def assemble(candidates, ranking, assessments, target):
    by_id = {row['id']: row for row in candidates}
    reviews = {row['id']: row for row in assessments}
    winner = next((row for row in ranking if reviews[row['id']]['verdict'] == 'fits'), None)
    preferred = by_id[ranking[0]['id']]['title']
    reply = f'盲读最想继续看《{preferred}》。'
    if winner:
        chosen = by_id[winner['id']]
        reply += f'综合推荐《{chosen["title"]}》。{reviews[chosen["id"]]["reason"]}'
    else:
        reply += '这轮没有候选通过篇幅评估，可以参考各题的具体风险继续改。'
    return {'reply': reply, 'topic_selection': {'target_words': target, 'candidates': candidates,
            'ranking': ranking, 'assessments': assessments, 'recommended_id': winner['id'] if winner else None}}
