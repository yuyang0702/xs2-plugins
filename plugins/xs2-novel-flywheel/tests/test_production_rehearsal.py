"""Production scene actors receive isolated, book-specific inputs."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from test_character_center import book, service  # noqa: F401
from test_multi_scene import PLUGIN


CLEAN_REVIEW = {'question_pileup': [], 'unsupported_commitment': [], 'voice_or_knowledge': []}


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
    ]}, 'actor-1': {'speech': '', 'action': '', 'private_beat': '我还没想好要不要留下', 'wants_reply': False},
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
                {'name': '阿杏', 'knowledge': '见到雨线', 'goal': '先救柜台', 'voice': '先问后动'},
                {'name': '掌柜', 'knowledge': '柜台脚泡湿', 'goal': '怕门被堵', 'voice': '说得慢'},
            ]},
            'actor-1': {'speech': '怕挡门？', 'action': '托住柜台一角', 'private_beat': '', 'wants_reply': True},
            'actor-2': {'speech': '', 'action': '把门撑开', 'private_beat': '', 'wants_reply': False},
            'review': CLEAN_REVIEW,
        }
        return parse(json.dumps(replies[step], ensure_ascii=False))

    result = asyncio.run(module.run(book, '0001', briefs, 'learning/context.md', call))
    assert len(result) == 1 and result[0]['scene_id'] == 2
    assert [step for step, _ in calls] == ['director', 'actor-1', 'actor-2', 'review']
    director, first, second, _ = [packet for _, packet in calls]
    assert '让动作先于解释' in str(director)
    assert '结局只给写手' not in str(calls)
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
