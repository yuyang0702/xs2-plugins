"""Compare direct scene writing with two-character rehearsal in the workbench."""
import asyncio
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
from random import SystemRandom
from time import perf_counter


DIRECTOR = '''你负责给两名角色分发开场试演资料。输入是小说资料。只回 JSON：
{"public_start":"开口之前两人都能在现场看到或听到的状况","roles":[{"name":"原名","knowledge":"此人此刻知道的事实和当下注意到的东西","goal":"此刻想要什么、打算怎样开口","voice":"在这段关系里的口气和回避方式"}]}
两名角色各一条。把共有情况和个人所知分开。逐人的资料只从其视角写；隐秘动机只给本人。仅编排开场，把后续事件、作者预定结局、对手隐情和未发生的反应留在场外。不得提前指定台词。用书中已采纳风格和对白适配决定角色声音。'''

ACTOR = '''你只扮演 role.name。用这人的所知、眼前的事情、正在忙的动作和与对方的关系作出这一次反应。角色资料里的确数优先留在心里，只有当场非说不可才开口；已经听懂的数字不用再念一遍。
public_start 是共同开场，observable_turns 是已发生且你能看到或听到的试演。接住具体的话或动作；可以停顿、岔开或先忙手上的事。让没说尽的部分留在话外。对方的语言和动作由对方决定。按本书表达倾向和本人的口气自然说话；对白只在人物有理由说时开口，精确明细有叙事作用才出现。
只回 JSON {"speech":"自己说的原话","action":"自己可被对方看到的动作"}。各至多 120 字，可以留空一项，不写内心和未来。'''

WRITER = '''本次调用仅写一张场景卡内的正文。以 scene_card 和 ending 为唯一当场情节，按 question 的篇幅和创作说明执行。保持本书叙述权限、已采纳写法、对白适配及人物声音。背景资料用来核对，章节已有文字仅作上下文。正文必须落实 ending，保留有用的精确数字；让动作、对白和叙述跟着视角人物当下的注意。如果有 rehearsal，可以吸收其中有因果、有口气的反应，自由取舍并写成小说，结局仍按场景卡。正文只交纯 JSON 对象 {"text":"带自然分段的小说正文"}，不用标题或代码围栏。'''

BLIND = '''你是本次独立盲读者，只读两段匿名小说正文。只依据正文比较对白读感，可以并列。不猜作者或写作方式。分别判断人物口气能否区分、上一句和眼前动作是否推动下一句、对白是否替读者解释道理、哪处有自然的幽默或回避。记录两版实际落到的结局以及是否一致。
只回 JSON {"preferred":"较自然版本的匿名标签，或 tie","reason":"具体比较","endings":"两版读到的结局","readings":{"匿名标签":{"voice":"口气差异","exchange":"接话、动作和当下注意力","strengths":[{"quote":"连续逐字引自该版的原文","comment":"为何自然"}],"stiffness":[{"quote":"连续逐字引自该版的原文","comment":"为何生硬"}]}}}。
两个标签都要填写，每组引文至多两条，找不到可给空数组。引文保留原字、标点和空格，不添引号或省略号。'''


def _object(reply, keys):
    def unique(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError('结果有重复字段。')
        return obj

    value = json.loads(reply, object_pairs_hook=unique) if isinstance(reply, str) else reply
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('结果字段不完整。')
    return value


def _text(value, maximum, *, optional=False):
    if not isinstance(value, str) or '\x00' in value or len(value) > maximum or not (optional or value.strip()):
        raise ValueError('结果文字为空或超出长度。')
    return value.strip()


def _director(reply, names):
    value = _object(reply, ('public_start', 'roles'))
    raw_roles = value['roles']
    if not isinstance(raw_roles, list) or len(raw_roles) != len(names):
        raise ValueError('导演须为每位人物提供一份独立资料。')
    roles = {}
    for raw in raw_roles:
        row = _object(raw, ('name', 'knowledge', 'goal', 'voice'))
        name = row['name']
        if not isinstance(name, str) or name not in names or name in roles:
            raise ValueError('导演资料的姓名须和出场人物一致。')
        roles[name] = {key: _text(val, 1400) for key, val in row.items()}
    return _text(value['public_start'], 1200), roles


def _turn(reply):
    result = {key: _text(value, 120, optional=True)
              for key, value in _object(reply, ('speech', 'action')).items()}
    if not any(result.values()):
        raise ValueError('人物至少有一句话或一个可观察的动作。')
    return result


def _draft(reply):
    return _text(_object(reply, ('text',))['text'], 12000)


@lru_cache(maxsize=1)
def _editing_resources():
    root = Path(__file__).resolve().parents[1]
    modules = []
    for name in ('prose_policy/precision_policy', 'draft_guard/revision_patch'):
        spec = importlib.util.spec_from_file_location(name.rsplit('/', 1)[-1], root / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def precision_guidance():
    return _editing_resources()[0].DEFAULT_PROSE


async def accept_precision(text, context, writer_system, call):
    precision, patches = _editing_resources()
    style = context.get('book_style', {})
    for attempt in range(3):
        paragraphs = patches.paragraphs(text)
        candidates = precision.review_candidates(text, paragraphs)
        if not candidates:
            return text
        expected = {row['paragraph_id']: row['details'] for row in candidates}
        indexed = {row['id']: row['text'] for row in paragraphs}

        def review(reply):
            rows = _object(reply, ('checks',))['checks']
            if not isinstance(rows, list) or len(rows)!=len(expected):
                raise ValueError('确数验收必须覆盖全部候选段落。')
            seen, corrections = set(), []
            for row in rows:
                record = _object(row, ('paragraph_id','remove','reason'))
                key, removed = record['paragraph_id'], record['remove']
                if (not isinstance(key, str) or key not in expected or key in seen
                        or not isinstance(removed, list) or any(item not in expected[key] for item in removed)):
                    raise ValueError('确数验收应使用候选段号和逐字数值。')
                seen.add(key)
                _text(record['reason'], 600)
                if removed:
                    corrections.append(record)
            return corrections

        decision = await call('你负责成稿的确数验收。' + precision.DEFAULT_PROSE + '\n' + precision.COUNTERFACTUAL + '\n' +
            '逐段把确数遮住再读，重复交代同一个事实应省去。若规模和交期可以靠现有资源和现场紧迫性表达，'
            '普通接单对白连同重复回应里的确数都应列为返修。留用时要说清读者具体会失去什么。'
            '场景卡和书中既有事实只用来理解。只回纯 JSON {"checks":[{"paragraph_id":"原段号","remove":["候选中要删的逐字数值和单位"],"reason":"保留或去掉的具体原因"}]}。'
            '每个候选段落必须正好一条，整段全保留时 remove=[]。',
            {'paragraphs': indexed, 'candidates': candidates, 'book_style': style, 'question': context.get('question','')}, review)
        if not decision:
            return text
        if attempt == 2:
            raise ValueError('确数返修后仍有需要修改的数字，未通过场景验收。')

        def revise(reply):
            edits = _object(reply, ('edits',))['edits']
            revised = patches.apply_patches(text, {'source_sha256': patches.digest(text), 'edits': edits},
                                            protected_phrases=style.get('protected_phrases', ()))
            precision.check_removed(text, revised, [(indexed[row['paragraph_id']], row['remove']) for row in decision])
            return revised

        text = await call(writer_system + '\n本次只做已定位的确数返修。' + precision.DEFAULT_PROSE +
            '修好受影响的对白和紧邻衔接，保持人物、视角、结局和其他正文。只回纯 JSON '
            '{"edits":[{"paragraph_id":"原段号","old":"指定段中连续逐字原文","occurrence":1,"replacement":"修后文字"}]}。',
            {'paragraphs': indexed, 'targets': decision, 'book_style': style, 'question': context.get('question','')}, revise)


def _blind(reply, texts):
    value = _object(reply, ('preferred', 'reason', 'endings', 'readings'))
    if value['preferred'] not in (*texts, 'tie'):
        raise ValueError('盲读偏好须为提供的匿名标签或 tie。')
    readings = _object(value['readings'], texts)
    for label, body in texts.items():
        reading = _object(readings[label], ('voice', 'exchange', 'strengths', 'stiffness'))
        for field in ('voice', 'exchange'):
            reading[field] = _text(reading[field], 700)
        for field in ('strengths', 'stiffness'):
            quotes = reading[field]
            if not isinstance(quotes, list) or len(quotes) > 2:
                raise ValueError('每组最多两条原文引证。')
            for item in quotes:
                example = _object(item, ('quote', 'comment'))
                quote = _text(example['quote'], 360)
                if quote not in body:
                    raise ValueError(f'盲读对版本{label}的引文必须连续逐字匹配正文。')
                example.update(quote=quote, comment=_text(example['comment'], 500))
    return {**value, 'reason': _text(value['reason'], 1200), 'endings': _text(value['endings'], 700)}


async def compare(task, writer, call, progress):
    async def request(system, user, parse):
        return await call(system, json.dumps(user, ensure_ascii=False), parse)

    async def measured(system, user, parse):
        started = perf_counter()
        result = await request(system, user, parse)
        return result, round(perf_counter() - started, 2)

    target, context = task['target'], task['rehearsal']
    names = [person['name'] for person in context['selected_cards']]
    system = writer['system'] + '\n\n【场景试读交付约定】\n' + WRITER + '\n' + precision_guidance()

    async def rehearse():
        ((public, roles), director_seconds) = await measured(DIRECTOR, context, lambda reply: _director(reply, names))
        turns, turn_seconds = [], []
        for name in names * 2:
            progress(f'角色试演第 {len(turns) + 1} 轮 · {name}…')
            turn, seconds = await measured(ACTOR, {'role': roles[name], 'public_start': public,
                                                  'observable_turns': turns}, _turn)
            turns.append({'name': name, **turn})
            turn_seconds.append(seconds)
        progress('主写手正在把试演写成小说正文…')
        candidate, seconds = await measured(system, context | {'rehearsal': turns}, _draft)
        return candidate, public, roles, [row | {'seconds': elapsed} for row, elapsed in zip(turns, turn_seconds)], director_seconds, seconds

    progress('分场写手正在直接试写，导演正在准备角色资料…')
    stages = await asyncio.gather(measured(system, context, _draft), rehearse(), return_exceptions=True)
    for stage in stages:
        if isinstance(stage, BaseException):
            raise stage
    (baseline, direct_seconds), (candidate, public, roles, turns, director_seconds, write_seconds) = stages
    progress('两版正在验收确数和复核局部返修…')
    checked_at = perf_counter()
    validated = await asyncio.gather(accept_precision(baseline, context, writer['system'], request),
                                     accept_precision(candidate, context, writer['system'], request), return_exceptions=True)
    for version in validated:
        if isinstance(version, BaseException):
            raise version
    baseline, candidate = validated
    precision_seconds = round(perf_counter() - checked_at, 2)
    progress('独立读者正在匿名比较两版对白…')
    labels = ['甲', '乙']
    SystemRandom().shuffle(labels)
    label_map = dict(zip(labels, ('baseline', 'candidate')))
    drafts = {'baseline': baseline, 'candidate': candidate}
    texts = {label: drafts[label_map[label]] for label in ('甲', '乙')}
    report, blind_seconds = await measured(BLIND, {'texts': texts}, lambda reply: _blind(reply, texts))
    return {key: target[key] for key in ('chapter', 'character_ids', 'scene')} | {
        'baseline': baseline, 'candidate': candidate, 'checks': [],
        'rehearsal': {'writer': writer['label'], 'public_start': public, 'roles': list(roles.values()),
                      'turns': turns,
                      'blind': report | {'labels': label_map},
                      'timings': {'direct': direct_seconds, 'director': director_seconds,
                                  'write': write_seconds, 'precision': precision_seconds, 'blind': blind_seconds}},
    }
