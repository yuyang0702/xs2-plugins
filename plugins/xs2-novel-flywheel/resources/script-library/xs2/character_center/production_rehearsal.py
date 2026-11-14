"""Build short, isolated role rehearsals from a chapter's accepted scene plan."""
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re

from .cards import SOURCES, inventory, source_path
from .dependencies import sibling
from .edits import atomic
from .states import add_state, chapter_id


DIRECTOR_RULES = (
    '\n给每人能站得住的处境：此刻在忙什么，眼前这人和自己有什么旧账或默契，有什么话只愿对这个人说。'
    '用档案支持当下的愿望、犹豫和关系；有冲突的愿望可以同时保留。不指定开口顺序、应答策略、口癖或台词。'
    'scene 中的转折和知识边界仅供导演分配资料，不能把转折当作已发生的事实。'
    '已有场景仅作衔接背景，不把整份记录转抄成公共开场。没有明确依据的秘密与背景留空。'
)
REVIEW = '''核对这一小段能否成为正式写手的素材。三类都要检查，只退回有实际影响的问题：
question_pileup：盯住人物此刻非问不可的事。一个话轮连续盘查几件互相独立的事，或者不给对方回应的机会就换着问，把读者需要知道的资料问成清单，要退回。关注不同问题的实际作用，不数问号。同一顾虑自然追问、急迫情况下确实要连续确认、符合人物与场合的审问都可以成立。返修保留最先要问的事，其余看下一轮反应或留在动作里。
unsupported_commitment：对照 scene、cards 与 prior_scenes，检查台词把未经确认的交付时间、金额、约定、保证或他人表态说成已经确定的事，或者擅自新增会改变剧情责任的承诺。已有的意向或答应做一件事，不自动包含交期或其他条款。导演分配和本轮试演的重复说法不能自证。区分已确认的承诺与提议、猜测、条件、书中明确允许的撒谎，以及场景本来就要发生的决定。确有依据并且当场有用的期限或数字可保留。问题理由写清楚冒出了什么，以及现有事实只支持到哪一步。
voice_or_knowledge：对照既定性格、声线、人物当下所知和关系。检查导演给的开场、个人资料有没有泄露隐情或后续事件，也核对可见言行有没有越界、替读者解释双方已知的事，或把不同人说成一样。沉默、普通应声、说一半收住和过会儿再开口都可以成立。没有公开反应也可以。
只回 JSON {"question_pileup":[],"unsupported_commitment":[],"voice_or_knowledge":[]}，三项均须提供。每个问题用 {"turn":1,"quote":"该轮连续原文","reason":"为何有问题","repair":"保留原有剧情的局部改法"}，turn 是 turns 中从 1 开始的序号。前两类只引台词，第三类可引台词或动作，如问题在导演资料则用 turn:0 并引用 public_start 或 assigned_roles 原文。每类每轮合并为一条。引文逐字连续，保留标点；只引能定位问题的片段。'''
ACTOR_REPAIRS = {
    'question_pileup': '按你此刻最想弄明白的事接话。其余等对方回应后再决定要不要问。',
    'unsupported_commitment': '只说你此刻确实知道的约定。没有确认的期限、保证或条款留在未定状态。',
    'voice_or_knowledge': '按你知道的事和你们平时的距离重新反应。眼前不必说给对方听的话可以留着。',
}
WRITER_NOTE = (
    '以下是按本书人物档案完成的分角色试演。按场景编号使用：吸收人物自己的词、反应与言外之意，'
    '把有用的交锋和动作写进小说。按本书已采用的风格处理叙述和描写，保留场景卡的事件与结局、'
    '人物所知和关系边界。人物可以不开口，一人多说，隔着动作再接回来。眼前能看到的事可以留给叙述，'
    '双方已懂的话留在话外。扩写对白时，一个人此刻非问不可的事先问，后续随对方反应走。'
    '交期、保证与约定按已有事实或本场安排，未定的条件留在未定状态。'
    '试演为空时允许静场；不用补齐轮次、解释没说的话或复刻试演记录。'
)
PERFORM = '''这会儿你就是 role.name。你面前是个你认识的人，手上有自己的事。先用自己的话想一刹那：眼前什么最碍事，你想让那个人做什么，你有什么不想被他听出来。用自己的档案、过往和关系来决定，不给角色贴标签，也不用把这些都说完。
own_book_profile 是你的档案与已确认的声线，own_private_beat 是你刚才留在心里的那一点念头。只有 role.knowledge、共同开场和已经公开的动作或话属于此刻所知。允许误会或犹豫，别凭空确定别人的心思、发明新经历、代别人说话或预演结局。
把自己放在这两个人平时相处的距离上。熟人之间可以少说一截；紧张时也可能说得比平时多。有人说着说着改口，有人先把手上的事做完，有人只听。说普通话、方言或书中语言都按这个人平常在这个对象面前怎么说。无需刻意加口头禅、笑话、停顿或小动作；双方都明白的事可以留在话外。精确数字只在此刻确实有用时才说。
如果有 retry_lines，那是你自己上一遍试演要重来的原话或动作。按这一遍的现场反应和给出的方向重新演；上一遍的事这次尚未发生。
只回 JSON {"speech":"你实际说出口的话","action":"你实际做出、对方看得见的动作","private_beat":"你此刻没说出的想法，用第一人称短句，可为空","wants_reply":false}。台词和动作可都留空，表示这一刻你的沉默里也没有可观察动作。短句、半句话、自然多说几句都可以。仅当公开的一句话或动作确实给对话对象留下了还需要回应的事时，才把 wants_reply 设为 true。'''


class VoiceReviewError(ValueError):
    pass


@lru_cache(maxsize=1)
def _role_protocol():
    path = Path(__file__).resolve().parents[1] / 'console_service/role_rehearsal.py'
    spec = importlib.util.spec_from_file_location('production_role_protocol', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cards(root):
    policy = sibling('prose_policy')
    documents = {}
    for name in SOURCES:
        text = policy.effective_text(root, name)
        documents[name] = text.encode() if text else None
    view, _, _ = inventory(root, documents)
    counts = Counter(person['name'] for person in view['characters'])
    return view, counts


def roster(root):
    """Exact eligible names for the scene planner, including readable older cards."""
    view, counts = _cards(root)
    return [person['name'] for person in view['characters']
            if counts[person['name']] == 1 and any(card['text'].strip() for card in person['raw'])]


def _adopted_voices(text):
    voices, character = {}, ''
    for line in text.splitlines():
        if re.match(r'^#{1,2}\s', line):
            character = ''
        elif line.startswith('### '):
            character = line[4:].strip()
            voices[character] = []
        elif character and line.strip() and not line.lstrip().startswith('<!--'):
            voices[character].append(line)
    return {key: '\n'.join(lines).strip() for key, lines in voices.items()}


def _assessment(reply, turns, public, roles):
    protocol = _role_protocol()
    result = protocol._object(reply, ACTOR_REPAIRS)
    issues = []
    for kind, rows in result.items():
        if not isinstance(rows, list):
            raise ValueError('声线审核每类须返回问题数组，每轮每类至多一条。')
        seen = set()
        for raw in rows:
            row = protocol._object(raw, ('turn', 'quote', 'reason', 'repair'))
            index = row['turn']
            first = 0 if kind == 'voice_or_knowledge' else 1
            if type(index) is not int or not first <= index <= len(turns) or index in seen:
                raise ValueError('声线问题须定位到实际话轮，同类问题不得重复。')
            if index == 0:
                evidence = [public, *(card[key] for card in roles.values() for key in ('knowledge', 'goal', 'voice'))]
                name = ''
            else:
                turn = turns[index - 1]
                name = turn['name']
                fields = ('speech', 'action') if kind == 'voice_or_knowledge' else ('speech',)
                evidence = [turn[key] for key in fields]
            quote = protocol._text(row['quote'], 240)
            if not any(quote in text for text in evidence):
                raise ValueError('声线返修引文须逐字出自对应资料、台词或可见动作。')
            seen.add(index)
            issues.append({
                'kind': kind, 'name': name, 'quote': quote, 'turn': index,
                'reason': protocol._text(row['reason'], 240), 'repair': protocol._text(row['repair'], 240),
            })
    return issues


def _performance(reply):
    protocol = _role_protocol()
    value = protocol._object(reply, ('speech', 'action', 'private_beat', 'wants_reply'))
    public = {key: protocol._text(value[key], 240, optional=True) for key in ('speech', 'action')}
    private = protocol._text(value['private_beat'], 240, optional=True)
    follow_up = value['wants_reply']
    if type(follow_up) is not bool or (follow_up and not any(public.values())):
        raise ValueError('续接须由实际说出的话或可观察动作触发。')
    return public, private, follow_up


def _cast(brief, people):
    names = brief.get('rehearsal_cast', [])
    if (not isinstance(names, list) or not 2 <= len(names) <= 3
            or any(not isinstance(name, str) or name not in people for name in names)
            or len(set(names)) != len(names)):
        return []
    return names


async def run(root, chapter, briefs, style_path, call, *, prior_scenes=()):
    if not any(brief.get('rehearsal_cast') for brief in briefs):
        return []
    chapter = chapter_id(chapter)
    policy = sibling('prose_policy')
    view, counts = _cards(root)
    add_state(root, view, chapter)
    people = {person['name']: person for person in view['characters'] if counts[person['name']] == 1
              and any(card['text'].strip() for card in person['raw'])}
    voices = _adopted_voices(policy.effective_text(root, 'meta/character_voice_adaptations.md'))
    style = {'book': policy.effective_text(root, 'meta/style_profile.md')[:4000],
             'preference': policy.effective_context(root, chapter)['instructions'],
             'adopted': _file(root, style_path)[:4000]}
    protocol = _role_protocol()
    rehearsals = []
    for brief in briefs:
        names = _cast(brief, people)
        if not names:
            continue
        scene = {key: str(brief.get(key, ''))[:1200] for key in ('entry', 'turn', 'knowledge')}
        cards = {}
        for name in names:
            person = people[name]
            cards[name] = {
                'card': [item['text'].strip()[:2400] for item in person['raw']],
                'confirmed_state': [state for state in person['states'] if state['chapter'] < chapter][-1:],
                'adopted_voice': voices.get(name, '')[:1500],
            }
        scene_id = brief['id']

        async def request(step, system, packet, parse):
            return await call(step, system, json.dumps(packet, ensure_ascii=False), parse)

        director_prompt = protocol.DIRECTOR.replace('两名', '这些').replace('两人', '在场人') + DIRECTOR_RULES
        director_input = {'scene': scene, 'cards': cards, 'style': style, 'prior_scenes': prior_scenes}

        def parse_roles(reply):
            return protocol._director(reply, names)

        public, roles = await request('director', director_prompt, director_input, parse_roles)
        issues = []
        for take in range(2):
            turns = []
            private_beats = {}
            prefix = 'retake-' if take else ''

            async def perform(index, name):
                role = {**roles[name], 'own_book_profile': cards[name]}
                packet = {'role': role, 'public_start': public, 'observable_turns': list(turns),
                          'own_private_beat': private_beats.get(name, '')}
                retry_lines = [{'quote': item['quote'], 'direction': ACTOR_REPAIRS[item['kind']]}
                               for item in issues if item['name'] == name]
                if retry_lines:
                    packet['retry_lines'] = retry_lines
                turn, private, follow_up = await request(f'{prefix}actor-{index}', PERFORM, packet, _performance)
                private_beats[name] = private
                if any(turn.values()):
                    turns.append({'name': name, **turn})
                return follow_up

            follow_up = False
            for index, name in enumerate(names, 1):
                follow_up = await perform(index, name)
            # Give an unresolved final exchange one more chance without
            # requiring a full second round or an open-ended conversation.
            if follow_up:
                await perform(len(names) + 1, names[0])
            issues = await request(f'{prefix}review', REVIEW, {
                'scene': scene, 'cards': cards, 'prior_scenes': prior_scenes, 'public_start': public,
                'turns': turns, 'assigned_roles': roles,
            }, lambda reply: _assessment(reply, turns, public, roles))
            if not issues:
                rehearsals.append({'scene_id': scene_id, 'opening': scene['entry'], 'turns': turns})
                break
            if not take:
                public, roles = await request('retake-director', director_prompt, director_input | {'review': issues},
                                              parse_roles)
        else:
            note = '；'.join(f'{item["name"] or "导演"}「{item["quote"]}」：{item["reason"]}' for item in issues)
            raise VoiceReviewError(f'场景 {scene_id} 的人物试演两次未通过声线审核：{note}')
    return rehearsals


def _file(root, relative):
    if not relative:
        return ''
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('人物试演资料越出作品工作区。')
    return path.read_text(encoding='utf-8-sig') if path.is_file() else ''


async def prepare(root, task_id, writer_id, chapter, directory, slot, style_path, call, *, model_identity):
    """Reuse each completed model step on retries of the same inputs."""
    root = Path(root).resolve()
    directory = (root / directory).resolve()
    if (not re.fullmatch(r'[\w-]{1,80}', task_id) or not re.fullmatch(r'agent_[a-z]+', writer_id)
            or directory != root / 'cache' / 'multi' / task_id):
        raise ValueError('分角色试演缺少有效任务和分场目录。')
    plan = json.loads(_file(root, directory / 'plan.json'))
    if slot:
        brief = json.loads(_file(root, directory / f'brief-{slot}.json'))
        briefs = [brief]
        handoff = _file(root, directory / f'handoff-{slot}.json')
        previous = json.loads(handoff).get('previous_scenes', []) if handoff else []
        prior = [item['body'][-1400:] for item in previous[-2:]]
    else:
        briefs, prior = plan['scenes'], []

    cache = directory / f'r-{writer_id}'
    attempt_path = source_path(root, cache / 'attempt')
    generation = int(_file(root, attempt_path) or 0)

    # Only completed, validated replies can be reused on a transport retry.
    async def cached_call(step, system, packet, parse):
        signature = sha256(f'{model_identity}\0{generation}\0{step}\0{system}\0{packet}'.encode()).hexdigest()
        target = source_path(root, cache / f'{signature[:24]}.json')
        if target.is_file():
            record = json.loads(_file(root, target))
            if record['sha256'] == signature:
                return parse(record['reply'])

        def capture(raw):
            result = parse(raw)
            atomic(target, json.dumps({'sha256': signature, 'reply': raw}, ensure_ascii=False).encode())
            return result

        return await call(step, system, packet, capture)

    try:
        result = await run(root, chapter, briefs, style_path, cached_call, prior_scenes=prior)
    except VoiceReviewError:
        # An explicit failed quality gate needs a fresh performance on retry.
        atomic(attempt_path, str(generation + 1).encode())
        raise
    path = source_path(root, directory / f'r-{writer_id}.md')
    document = WRITER_NOTE + '\n\n' + json.dumps(result, ensure_ascii=False, indent=2) if result else ''
    atomic(path, document.encode())
    return path.relative_to(root).as_posix(), len(result)
