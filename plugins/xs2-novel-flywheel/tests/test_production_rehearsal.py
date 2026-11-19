"""Production scene actors receive isolated, book-specific inputs."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from test_character_center import book, service  # noqa: F401
from test_multi_scene import PLUGIN


CLEAN_REVIEW = {'question_pileup': [], 'unsupported_commitment': [], 'voice_or_knowledge': []}
CLEAN_OPENING = {'voice_or_knowledge': []}


@pytest.mark.parametrize(('writer', 'slot', 'compact'), [('agent_sw', 0, True), ('agent_aw', 1, False)])
@pytest.mark.parametrize('outcome', ['corrected', 'rejected', 'invalid', 'multiple', 'unlocated'])
def test_formal_writer_never_uses_an_unverified_opening(book, service, writer, slot, compact, outcome):
    from importlib import import_module

    rehearsal = import_module(service.__package__ + '.production_rehearsal')
    directory = book / 'cache/multi/task-knowledge'
    directory.mkdir(parents=True)
    reveal = '有人替活人承接恶念'
    identity = '活人其实是师父'
    brief = {'id': 1, 'entry': '两人赶到桥下，来历尚未查明。',
             'turn': f'阿杏用术查明{reveal}。', 'knowledge': f'查完以后阿杏才知道{reveal}。',
             'exit': '两人仍不知道活人是谁。', 'rehearsal_cast': ['阿杏', '掌柜']}
    (directory / 'plan.json').write_text(json.dumps({'scenes': [brief]}), encoding='utf-8')
    if slot:
        (directory / f'brief-{slot}.json').write_text(json.dumps(brief), encoding='utf-8')
        (directory / f'handoff-{slot}.json').write_text(json.dumps({'previous_scenes': [{'body': identity}]}),
                                                       encoding='utf-8')
    profile = book / 'meta/character_profiles.md'
    profile.write_text(profile.read_text(encoding='utf-8').replace('旧识', f'旧识\n- 剧情限制：{identity}'),
                       encoding='utf-8')
    opening = {'public_start': '两人在桥下。', 'roles': [
        {'name': '阿杏', 'knowledge': '眼前的事还没查清', 'goal': '找线索', 'voice': '熟人面前有事直说'},
        {'name': '掌柜', 'knowledge': '阿杏正要查看桥脚', 'goal': '帮她看着路', 'voice': '话少'},
    ]}
    spoiled = opening | {'roles': [opening['roles'][0] | {'knowledge': reveal, 'goal': identity}, opening['roles'][1]]}
    issue = {'turn': 0, 'quote': reveal, 'reason': '这要等查完才能知道。', 'repair': '保留查清前的状态。'}
    corrected = outcome in ('corrected', 'multiple', 'unlocated')
    calls = {}

    async def call(step, system, packet, parse):
        calls[step] = json.loads(packet)
        if step.endswith('director'):
            reply = opening if step == 'retake-director' and corrected else spoiled
        elif step.endswith('opening-review'):
            if outcome == 'invalid':
                reply = {}
            else:
                issues = [] if step == 'retake-opening-review' and corrected else [issue]
                if issues and outcome == 'multiple':
                    issues.append(issue | {'quote': identity})
                if issues and outcome == 'unlocated':
                    issues = [issue | {'quote': '剧情安排中的说明，非导演原文'}]
                reply = {'voice_or_knowledge': issues}
        elif step.endswith('review'):
            reply = CLEAN_REVIEW
        else:
            reply = {'speech': '你先看住路。', 'action': '', 'private_beat': '', 'wants_reply': False}
        return parse(json.dumps(reply, ensure_ascii=False))

    execution = service.prepare_rehearsal(book, 'task-knowledge', writer, '0001', directory, slot, '', call,
                                          model_identity='test-model', compact=compact)
    if corrected or compact:
        path, count = asyncio.run(execution)
        assert count == (1 if corrected else 0)
        if compact:
            assert reveal in (book / path).read_text(encoding='utf-8')  # The prose writer still needs the full plan.
    else:
        with pytest.raises(rehearsal.VoiceReviewError if outcome == 'rejected' else ValueError):
            asyncio.run(execution)
    assert not any(step.startswith('actor-') for step in calls)
    assert calls['director']['scene'] == {'entry': brief['entry']}
    assert 'prior_scenes' not in calls['director']
    assert calls['opening-review']['scene']['turn'] == brief['turn']
    if slot:
        assert calls['opening-review']['prior_scenes'] == [identity]
    if corrected:
        steps = list(calls)
        assert steps.index('retake-opening-review') < steps.index('retake-actor-1')
        assert reveal not in str(calls['retake-director'])
        assert identity not in str(calls['retake-actor-1'])
        assert calls['retake-actor-1']['observable_turns'] == []
        assert calls['retake-actor-1']['role']['knowledge'] == opening['roles'][0]['knowledge']
    else:
        assert not any('actor-' in step for step in calls)


def test_role_protocol_accepts_one_fenced_json_object_and_retains_strict_validation(service):
    from importlib import import_module

    rehearsal = import_module(service.__package__ + '.production_rehearsal')
    protocol = rehearsal._role_protocol()
    assert protocol._object('```json\n{"speech":"回去。"}\n```', ('speech',)) == {'speech': '回去。'}
    for reply in ('说明\n```json\n{"speech":"回去。"}\n```',
                  '```json\n{"speech":"走。","speech":"留。"}\n```',
                  '```json\n{"action":"转身。"}\n```'):
        with pytest.raises(ValueError):
            protocol._object(reply, ('speech',))


@pytest.mark.parametrize('response', ['silent', 'reply'])
def test_roles_can_pass_or_return_to_their_own_private_intent(book, service, response):
    from importlib import import_module

    module = import_module(service.__package__ + '.production_rehearsal')
    brief = {'id': 1, 'entry': '阿杏和掌柜在门边', 'rehearsal_cast': ['阿杏', '掌柜']}
    calls = {}
    replies = {'director': {'public_start': '雨打在门口', 'roles': [
        {'name': '阿杏', 'knowledge': '门洞在漏雨', 'goal': '留住作坊', 'voice': '有事先问'},
        {'name': '掌柜', 'knowledge': '门外有人', 'goal': '守门', 'voice': '话少'},
    ]}, 'opening-review': CLEAN_OPENING,
        'actor-1': {'speech': '', 'action': '', 'private_beat': '我还没想好要不要留下', 'wants_reply': False},
        'actor-2': {'speech': '' if response == 'silent' else '你还走吗？', 'action': '',
                    'private_beat': '我开不了口留她', 'wants_reply': response == 'reply'},
        'actor-3': {'speech': '等雨停吧。', 'action': '', 'private_beat': '拖一会儿', 'wants_reply': False},
        'review': CLEAN_REVIEW}

    async def call(step, system, packet, parse):
        calls[step] = json.loads(packet)
        return parse(json.dumps(replies[step], ensure_ascii=False))

    result = asyncio.run(module.run(book, '0001', [brief], '', call))
    assert calls['actor-2']['observable_turns'] == []
    assert '我还没想好' not in str(calls['actor-2'])
    if response == 'reply':
        assert calls['actor-3']['own_private_beat'] == '我还没想好要不要留下'
        assert '我开不了口留她' not in str(calls['actor-3'])
        assert [turn['name'] for turn in result[0]['turns']] == ['掌柜', '阿杏']
    else:
        assert 'actor-3' not in calls
        assert result[0]['turns'] == []
    assert 'private_beat' not in str(calls['review']) + str(result)


def test_production_scene_uses_own_card_and_prior_observable_action(book, service):
    from importlib import import_module

    module = import_module(service.__package__ + '.production_rehearsal')
    book.joinpath('meta/character_voice_adaptations.md').write_text(
        '## 本次采用适配\n### 阿杏\n遇到老熟人先问顾虑。\n### 掌柜\n把话含在嘴里。\n', encoding='utf-8')
    book.joinpath('learning').mkdir()
    book.joinpath('learning/context.md').write_text('让动作先于解释', encoding='utf-8')
    briefs = [
        {'id': 1, 'entry': '她掀开铺帘', 'turn': '独自等雨停', 'rehearsal_cast': []},
        {'id': 2, 'entry': '两人对着漏雨的桌角', 'turn': '阿杏劝掌柜先挪柜台',
         'exit': '结局只给写手', 'knowledge': '掌柜不知道她想租下铺子',
         'rehearsal_cast': ['阿杏', '掌柜']},
    ]
    calls = []

    async def call(step, system, packet, parse):
        calls.append((step, json.loads(packet)))
        replies = {
            'director': {'public_start': '桌角漏雨', 'roles': [
                {'name': '阿杏', 'knowledge': '见到雨线', 'goal': '留住作坊，先救柜台', 'voice': '遇到老熟人先问顾虑'},
                {'name': '掌柜', 'knowledge': '柜台脚泡湿', 'goal': '怕门被堵', 'voice': '把话含在嘴里'},
            ]},
            'opening-review': CLEAN_OPENING,
            'actor-1': {'speech': '怕挡门？', 'action': '托住柜台一角', 'private_beat': '', 'wants_reply': True},
            'actor-2': {'speech': '', 'action': '把门撑开', 'private_beat': '', 'wants_reply': False},
            'review': CLEAN_REVIEW,
        }
        return parse(json.dumps(replies[step], ensure_ascii=False))

    result = asyncio.run(module.run(book, '0001', briefs, 'learning/context.md', call))
    assert len(result) == 1 and result[0]['scene_id'] == 2
    assert [step for step, _ in calls] == ['director', 'opening-review', 'actor-1', 'actor-2', 'review']
    director, opening_review, first, second, review = [packet for _, packet in calls]
    assert '让动作先于解释' in str(director)
    assert '留住作坊' in str(director['cards']['阿杏'])
    assert '遇到老熟人先问顾虑' in director['cards']['阿杏']['adopted_voice']
    assert opening_review['scene']['exit'] == review['scene']['exit'] == '结局只给写手'
    assert '结局只给写手' not in str((director, first, second))
    assert '留住作坊' in str(first['role']) and '遇到老熟人先问顾虑' in str(first['role'])
    assert '留住作坊' not in str(second) and '把话含在嘴里' in str(second['role'])
    assert '怕门被堵' not in str(first)
    assert first['observable_turns'] == []
    assert second['observable_turns'] == [{'name': '阿杏', 'speech': '怕挡门？', 'action': '托住柜台一角'}]
    assert 'role' not in result[0] and 'goal' not in str(result)


def test_followup_reaches_the_other_character_and_stops_on_a_resolved_turn(book, service):
    from importlib import import_module

    rehearsal = import_module(service.__package__ + '.production_rehearsal')
    brief = {'id': 1, 'entry': '雨水倒灌', 'rehearsal_cast': ['阿杏', '掌柜']}
    director = {'public_start': '铺里有水', 'roles': [
        {'name': '阿杏', 'knowledge': '脚下有水', 'goal': '弄明白水从哪来', 'voice': '不肯吃亏'},
        {'name': '掌柜', 'knowledge': '门开着', 'goal': '别让人滑到', 'voice': '先把人拉开'},
    ]}
    lines = ['门开着？', '敞着呢。', '那水怎么从地里冒？', '先上凳子。']
    calls = {}

    async def call(step, system, packet, parse):
        calls[step] = json.loads(packet)
        if step == 'director':
            reply = director
        elif step == 'opening-review':
            reply = CLEAN_OPENING
        elif step == 'review':
            reply = CLEAN_REVIEW
        else:
            turn = int(step.rsplit('-', 1)[-1])
            reply = {'speech': lines[turn - 1], 'action': '', 'private_beat': '', 'wants_reply': turn < 4}
        return parse(json.dumps(reply, ensure_ascii=False))

    results = asyncio.run(rehearsal.run(book, '0001', [brief], '', call))
    assert [row['speech'] for row in results[0]['turns']] == lines
    assert calls['actor-4']['role']['name'] == '掌柜'
    assert calls['actor-4']['observable_turns'][-1]['speech'] == lines[2]
    assert list(calls)[-2:] == ['actor-4', 'review']


def test_writer_receives_source_bound_reaction_evidence(service):
    from importlib import import_module

    rehearsal = import_module(service.__package__ + '.production_rehearsal')
    turns = [{'name':'阿杏','speech':'门缝进水了。','action':''},
             {'name':'掌柜','speech':'踩凳子。','action':'把矮凳踢到跟前'}]
    report = CLEAN_REVIEW | {'reaction': {'trigger_turn': 1, 'response_turn': 2, 'reason': '听见进水就先护人。'}}
    issues, reaction = rehearsal._assess_handoff(report, turns, '', {})
    assert not issues
    assert reaction['trigger'] == turns[0] and reaction['response'] == turns[1]
    wrong = report | {'reaction': report['reaction'] | {'reason': '掌柜喊「快开窗」。'}}
    assert rehearsal._assess_handoff(wrong, turns, '', {})[1] is None
    report['reaction']['response_turn'] = 4
    assert rehearsal._assess_handoff(report, turns, '', {})[1] is None


def test_short_writer_gets_scene_progression_and_reviewed_reaction_without_full_rehearsal(book, service):
    directory = book / 'cache/multi/task-short'
    directory.mkdir(parents=True)
    (directory / 'plan.json').write_text(json.dumps({'focus': '阿杏', 'plan_reason': '内部场数说明', 'scenes': [
        {'id': 1, 'entry': '门缝进水', 'turn': '掌柜先救人', 'exit': '两人守着窗边',
         'knowledge': '阿杏只能看见门缝', 'rehearsal_cast': ['阿杏', '掌柜'], 'budget_reason': '内部篇幅说明'},
        {'id': 2, 'entry': '水退到门外', 'turn': '他们轮流出去探路', 'exit': '阿杏带走备用钥匙',
         'knowledge': '两人都看到水退了'},
    ]}, ensure_ascii=False), encoding='utf-8')
    replies = {
        'director': {'public_start': '门缝进水', 'roles': [
            {'name': '阿杏', 'knowledge': '门缝以下是水', 'goal': '别滑倒', 'voice': '话少'},
            {'name': '掌柜', 'knowledge': '门边没有垫子', 'goal': '护住人', 'voice': '急而直接'},
        ]},
        'opening-review': CLEAN_OPENING,
        'actor-1': {'speech': '门缝进水了。', 'action': '', 'private_beat': '这次真冷', 'wants_reply': False},
        'actor-2': {'speech': '踩凳子。', 'action': '把矮凳踢到跟前', 'private_beat': '', 'wants_reply': True},
        'actor-3': {'speech': '还得等老板开灯。', 'action': '', 'private_beat': '', 'wants_reply': False},
        'review': CLEAN_REVIEW | {'reaction': {'trigger_turn': 1, 'response_turn': 2,
                                              'reason': '听见进水就先护人。'}},
    }

    async def call(step, system, packet, parse):
        return parse(json.dumps(replies[step], ensure_ascii=False))

    path, count = asyncio.run(service.prepare_rehearsal(book, 'task-short', 'agent_sw', '0001',
                              directory, 0, '', call, model_identity='test-model', compact=True))
    assert count == 1
    full = (directory / 'r-agent_sw.md').read_text(encoding='utf-8')
    brief = (book / path).read_text(encoding='utf-8')
    assert '还得等老板开灯。' in full and '还得等老板开灯。' not in brief
    assert '内部篇幅说明' not in brief and '内部场数说明' not in brief
    assert '这次真冷' not in brief
    for evidence in ('阿杏只能看见门缝', '两人守着窗边', '阿杏带走备用钥匙',
                     '门缝进水了。', '把矮凳踢到跟前', '听见进水就先护人。'):
        assert evidence in brief
    assert '开口前共同看见或听见' in brief
    assert '别滑倒' in brief and '护住人' in brief


def test_short_writer_lists_a_scene_event_once_and_keeps_its_distinct_facts(book, service):
    directory = book / 'cache/multi/task-event-brief'
    directory.mkdir(parents=True)
    plan = {'focus': '守门人第一人称', 'scenes': [
        {'id': 1, 'entry': '登记台只剩最后一张表。', 'turn': '我查出号码不符，于是暂停放行。',
         'exit': '暂停放行；登船名单仍未封存。',
         'knowledge': '暂停放行。持牌者听了我的解释才知道名单上是另一个人。'},
        {'id': 2, 'entry': '放行仍处于暂停状态。', 'turn': '我只答应替她问一句。',
         'exit': '她仍需在原处等待。', 'knowledge': '同事尚不知我已经答应。'},
    ], 'continuity': {'events': [
        {'id': 'e1', 'scene': 1, 'after': [], 'expected_state': 'acted',
         'description': '核对后发现号码有误，并暂停放行。', 'source_quote': '合同留存的逐字依据。'},
        {'id': 'e2', 'scene': 2, 'after': ['e1'], 'expected_state': 'committed',
         'description': '我只答应替她问一句；当场没有人离开队伍。', 'source_quote': '只供核验。'},
    ]}}
    plan_path = directory / 'plan.json'
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')

    async def call(*args):
        pytest.fail('没有适用的角色试演')

    path, count = asyncio.run(service.prepare_rehearsal(book, 'task-event-brief', 'agent_sw', '0001',
                              directory, 0, '', call, model_identity='test-model', compact=True))
    compact = (book / path).read_text(encoding='utf-8')
    view = json.loads(compact[compact.index('{'):])
    assert count == 0
    assert compact.count('暂停放行') == 1
    assert compact.count('我只答应替她问一句') == 1
    for fact in ('登船名单仍未封存', '持牌者听了我的解释才知道名单上是另一个人',
                 '放行仍处于暂停状态', '同事尚不知我已经答应', '当场没有人离开队伍'):
        assert fact in compact
    events = {row['id']: row for row in view['跨场连续性']['events']}
    assert events['e1']['expected_state'] == 'acted'
    assert events['e2']['expected_state'] == 'committed' and events['e2']['after'] == ['e1']
    assert '合同留存的逐字依据' not in compact and '只供核验' not in compact
    assert json.loads(plan_path.read_text(encoding='utf-8')) == plan


def test_short_writer_projects_the_source_bound_outline_to_a_separate_context(book, service):
    directory = book / 'cache/multi/task-outline'
    directory.mkdir(parents=True)
    plan = {'scenes': [{'id': 1, 'turn': '阿杏推开小门。没找到执照，于是暂停放行。只有老板回来才交钥匙。'}],
            'continuity': {'events': [
                {'id': 'open', 'scene': 1, 'description': '阿杏推开小门。', 'source_quote': '阿杏推开小门。'},
                {'id': 'pause', 'scene': 1, 'expected_state': 'acted', 'after': ['open'],
                 'description': '没找到执照；暂停放行。', 'source_quote': '天色已晚，没找到执照，只能暂停放行。'},
            ]}}
    (directory / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    relative = 'cache/short/task-outline.md'
    source = book / relative
    source.parent.mkdir(parents=True)
    outline = ('# 独立短篇写作上下文\n\n## 本章大纲\n\n### 第1章\n'
               '- **情节摘要**：阿杏推开小门。守门人此时听不见里面的声音。天色已晚，没找到执照，只能暂停放行。\n'
               '- **世界时间推进**：从晌午到入夜。\n\n'
               '## 作者确认要求\n\n- **情节摘要**：阿杏推开小门。\n\n'
               '## 文风\n\n保留没说完的句子。\n')
    source.write_text(outline, encoding='utf-8')

    async def call(*args):
        pytest.fail('没有适用的角色试演')

    brief, _ = asyncio.run(service.prepare_rehearsal(book, 'task-outline', 'agent_sw', '0001', directory, 0,
                                                    '', call, model_identity='test-model', compact=True))
    path, scene_path = service.prepare_writer_context(book, directory.relative_to(book).as_posix(), relative, brief)
    writer = (book / path).read_text(encoding='utf-8')
    scenes = (book / scene_path).read_text(encoding='utf-8')
    assert path != relative
    assert scene_path != brief
    assert source.read_text(encoding='utf-8') == outline
    assert '- **情节摘要**：守门人此时听不见里面的声音。' in writer
    assert '## 作者确认要求\n\n- **情节摘要**：阿杏推开小门。' in writer
    assert '从晌午到入夜' in writer and '保留没说完的句子' in writer
    assert (writer + scenes).count('暂停放行') == 1
    assert '只能暂停放行' in scenes and '天色已晚' in writer
    assert '只有老板回来才交钥匙' in scenes


@pytest.mark.parametrize('cast', [[], ['阿杏', '未知'], ['阿杏', '同名']])
def test_missing_or_ambiguous_cards_do_not_create_generic_characters(book, service, cast):
    from importlib import import_module

    module = import_module(service.__package__ + '.production_rehearsal')
    call = AsyncMock()
    result = asyncio.run(module.run(book, '0001', [{'id': 1, 'rehearsal_cast': cast}], '', call))
    assert result == []
    call.assert_not_awaited()


def test_retry_reuses_finished_calls_but_reassesses_rewritten_exchange(book, service):
    directory = book / 'cache/multi/task-retry'
    directory.mkdir(parents=True)
    brief = {'id': 1, 'entry': '门缝漏风', 'rehearsal_cast': ['阿杏', '掌柜']}
    (directory / 'plan.json').write_text(json.dumps({'scenes': [brief]}), encoding='utf-8')
    calls = []
    director = {'public_start': '门缝漏风', 'roles': [
        {'name': '阿杏', 'knowledge': '门开着', 'goal': '进屋', 'voice': '问清缘由'},
        {'name': '掌柜', 'knowledge': '有人进来', 'goal': '守着柜台', 'voice': '话少'},
    ]}

    async def call(step, system, packet, parse):
        calls.append(step)
        if step == 'actor-2' and calls.count(step) == 1:
            raise TimeoutError
        replies = {'director': director, 'retake-director': director,
                   'opening-review': CLEAN_OPENING, 'retake-opening-review': CLEAN_OPENING,
                   'review': CLEAN_REVIEW | {'voice_or_knowledge': [{
                       'turn': 2, 'quote': '门开着？', 'reason': '掌柜这句话和阿杏一个口气。',
                       'repair': '直接把门让开。'}]},
                   'retake-review': CLEAN_REVIEW}
        if step in replies:
            reply = replies[step]
        elif step == 'retake-actor-2':
            reply = {'speech': '', 'action': '让开门口', 'private_beat': '', 'wants_reply': False}
        else:
            reply = {'speech': '门开着？', 'action': '', 'private_beat': '', 'wants_reply': False}
        return parse(json.dumps(reply, ensure_ascii=False))

    def prepare():
        return asyncio.run(service.prepare_rehearsal(
            book, 'task-retry', 'agent_sw', '0001', directory, 0, '', call, model_identity='test-model'))

    with pytest.raises(TimeoutError):
        prepare()
    relative, count = prepare()
    count_before_replay = len(calls)
    assert prepare() == (relative, count)
    assert len(calls) == count_before_replay
    assert calls.count('director') == calls.count('actor-1') == 1
    assert 'retake-review' in calls
    handoff = (book / relative).read_text(encoding='utf-8')
    assert count == 1 and '让开门口' in handoff and '一个口气' not in handoff


@pytest.mark.parametrize('review_result', ['retake', 'still_wrong', 'compact_fallback', 'compact_unavailable',
                                          'invented_quote', 'missing_check'])
def test_voice_audit_binds_dialogue_repairs_to_public_lines(book, service, review_result):
    from importlib import import_module

    module = import_module(service.__package__ + '.production_rehearsal')
    brief = {'id': 1, 'entry': '作坊漏雨，客人问能不能上门看看；双方尚未约好时间。',
             'rehearsal_cast': ['阿杏', '掌柜']}
    director = {'public_start': '两人在门口接雨水。', 'roles': [
        {'name': '阿杏', 'knowledge': '作坊漏雨', 'goal': '挪盆子', 'voice': '熟人之间说话省事'},
        {'name': '掌柜', 'knowledge': '客人问能不能来', 'goal': '守住这门生意', 'voice': '想答应又怕担不起'},
    ]}
    pileup = '谁找你？你回了什么？你答应几点？'
    commitment = '我答应今晚去。'
    report = CLEAN_REVIEW | {
        'question_pileup': [{'turn': 1, 'quote': pileup, 'reason': '一口气问三个不同的事。',
                             'repair': '先问影响眼下决定的事。'}],
        'unsupported_commitment': [{'turn': 2, 'quote': commitment, 'reason': '作者设定明确未约好时间。',
                                    'repair': '保留客人已有的请求。'}],
    }
    if review_result == 'invented_quote':
        report['unsupported_commitment'][0]['quote'] = '我答应明早去。'
    if review_result == 'missing_check':
        del report['unsupported_commitment']
    calls = {}

    async def call(step, system, packet, parse):
        calls[step] = json.loads(packet)
        if step == 'retake-director' and review_result == 'compact_unavailable':
            raise ValueError('两次返回无效结构')
        if step.endswith('director'):
            reply = director
        elif step.endswith('opening-review'):
            reply = CLEAN_OPENING
        elif step == 'review' or (step == 'retake-review' and review_result in ('still_wrong', 'compact_fallback')):
            reply = report
        elif step == 'retake-review':
            reply = CLEAN_REVIEW
        else:
            speech = {'actor-1': pileup, 'actor-2': commitment, 'retake-actor-1': '回人家了？',
                      'retake-actor-2': '她问能不能来，我手都没擦。'}[step]
            if review_result in ('still_wrong', 'compact_fallback') and step.startswith('retake-'):
                speech = pileup if step.endswith('1') else commitment
            reply = {'speech': speech, 'action': '', 'private_beat': '心里的话', 'wants_reply': False}
        return parse(json.dumps(reply, ensure_ascii=False))

    eligibility = {'required': False} if review_result in ('compact_fallback', 'compact_unavailable') else {}
    task = module.run(book, '0001', [brief], '', call, **eligibility)
    if review_result in ('invented_quote', 'missing_check'):
        with pytest.raises(ValueError):
            asyncio.run(task)
        assert 'retake-actor-1' not in calls
    elif review_result == 'still_wrong':
        with pytest.raises(module.VoiceReviewError):
            asyncio.run(task)
        assert 'retake-review' in calls
    elif review_result == 'compact_fallback':
        assert asyncio.run(task) == []
        assert 'retake-review' in calls
    elif review_result == 'compact_unavailable':
        assert asyncio.run(task) == []
        assert 'retake-director' in calls and 'retake-review' not in calls
    else:
        result = asyncio.run(task)
        assert [turn['speech'] for turn in result[0]['turns']] == ['回人家了？', '她问能不能来，我手都没擦。']
        assert pileup in str(calls['retake-actor-1'])
        assert commitment not in str(calls['retake-actor-1'])
        assert commitment in str(calls['retake-actor-2'])
        assert '心里的话' not in str(calls['review'])


def test_both_formal_writer_paths_read_rehearsals_before_request_budget():
    from src.workflow.definition import WorkflowDef

    raw = json.loads((PLUGIN / 'resources/workflows/mvp/definition.json').read_text(encoding='utf-8'))
    assert WorkflowDef.from_dict(raw).validate() == []
    edges = {(row['source'], row['target']) for row in raw['edges']}
    nodes = {row['id']: row for row in raw['nodes']}
    full_single_writer = next(v['default'] for v in raw['variables'] if v['key']=='single_writer_context')
    for writer in ('agent_aw', 'agent_dw', 'agent_iw', 'agent_dsw', 'agent_tw', 'agent_si', 'agent_sw'):
        rehearsal = f'rehearse_{writer}'
        budget = f'script_budget_{writer}'
        assert (rehearsal, budget) in edges and (budget, writer) in edges
        variable = f'rehearsal_{writer}'
        assert nodes[rehearsal]['node_params']['writer_node'] == writer
        assert '{{' + variable + '}}' in nodes[writer]['first_message']
        prompt = nodes[writer]['first_message']
        if writer == 'agent_sw':
            assert '{{single_writer_context}}' in prompt
            prompt += full_single_writer
        assert '{{pp_learning_context}}' in prompt


@pytest.mark.parametrize('failure', ['knowledge', 'long_reply', 'provider', 'changed_plan'])
def test_allocated_multi_writer_continues_only_with_verified_scene_material(book, service, failure):
    from hashlib import sha256

    directory = book / 'cache/multi/task-fallback'
    directory.mkdir(parents=True)
    scene = {'id': 1, 'entry': '拦车之前。', 'turn': '听明白后赔礼。', 'exit': '绳子解开。',
             'knowledge': '此时才明白先前的后果。', 'rehearsal_cast': ['阿杏', '掌柜']}
    plan_file = directory / 'plan.json'
    plan_file.write_text(json.dumps({'scenes': [scene]}), encoding='utf-8')
    (directory / 'brief-2.json').write_text(json.dumps(dict(scene, slot=2)), encoding='utf-8')
    (directory / 'allocation.json').write_text(json.dumps({
        'plan_sha256': sha256(plan_file.read_bytes()).hexdigest(),
        'scenes': [{'scene_id': 1, 'slot': 2}]}), encoding='utf-8')
    if failure == 'changed_plan':
        plan_file.write_text(json.dumps({'scenes': [dict(scene, entry='另外一个开场。')]}), encoding='utf-8')

    calls = []

    async def call(step, system, packet, parse):
        calls.append((step, json.loads(packet)))
        if failure == 'provider':
            raise ConnectionError('offline')
        if step.endswith('director'):
            return parse({'public_start': '柜台前', 'roles': [
                {'name': name, 'knowledge': '已经知道结局', 'goal': '认错', 'voice': '话少'}
                for name in ['阿杏', '掌柜']]})
        if step.endswith('opening-review'):
            return parse({'voice_or_knowledge': [] if failure == 'long_reply' else [
                {'quote': '已经知道结局', 'reason': '此事尚未发生', 'repair': '开场只想拦车'}]})
        return parse({'speech': '话' * 241, 'action': '', 'private_beat': '', 'wants_reply': False})

    result = service.prepare_rehearsal(book, 'task-fallback', 'agent_dw', '0001', directory, 2, '',
                                       call, model_identity='test-model')
    if failure == 'provider':
        with pytest.raises(ConnectionError):
            asyncio.run(result)
        return
    if failure == 'changed_plan':
        with pytest.raises(ValueError, match='两次未通过'):
            asyncio.run(result)
        assert not (directory / 'r-agent_dw.md').exists()
        return
    path, count = asyncio.run(result)
    assert count == 0
    handoff = (book / path).read_text(encoding='utf-8')
    assert '拦车之前' in handoff and '已经知道结局' not in handoff
    if failure == 'knowledge':
        assert '开场只想拦车' in str(dict(calls)['retake-director'])
        assert len(calls) == 4
