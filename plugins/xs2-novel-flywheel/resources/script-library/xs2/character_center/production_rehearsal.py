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
    '\n以各人的既定性格、声线、关系与当前处境为准。用当场可做的事区分角色的目的，'
    '用措辞、话的长短、停顿、回避和是否开口区分声线，不强派口癖。'
    'scene 中的转折和知识边界仅供导演分配资料，不能把转折当作已发生的事实。'
    '已有场景仅作衔接背景，不把整份记录转抄成公共开场。没有明确依据的秘密与背景留空。'
)
REVIEW = '''核对这一小段试演能否成为正式写手的素材。逐个对照既定性格、声线、人物所知与当下关系，核对分配的个人资料是否暴露他人秘密或后续事件。
如果人物为了推进剧情突然变性格、凭空知道秘密、两人说话像同一个人或用对白完整背诵道理，指出具体哪位、哪句偏离和档案依据。
允许沉默、打断、岔开、间接回答、忙手上的事，以及符合人物的幽默；不能只靠固定口癖和统一的小动作区分声音。
只有明显偏离才退回，不要求不同角色每句话都刻意制造反差。不改剧情。只回 JSON {"accepted":true,"reason":"具体理由"}。'''
WRITER_NOTE = (
    '以下是按本书人物档案完成的分角色试演。按场景编号使用：吸收人物自己的词、反应与言外之意，'
    '把有用的交锋和动作写进小说。按本书已采用的风格处理叙述和描写，保留场景卡的事件与结局、'
    '人物所知和关系边界。试演是表达素材，发生过的正文和已确认资料仍然优先。不写角色扮演记录。'
)
ACTOR_RULES = ('\nown_book_profile 是你自己的档案和已确认的声线。只有属于 role.knowledge 或现场已公开的事实才能当作此刻已知；'
               '个人档案中可能有作者留给后文的内容。照着人物的性格作出选择，用当下自然的词句，不复述档案或照搬其中的例句。')


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


def _assessment(reply):
    protocol = _role_protocol()
    result = protocol._object(reply, ('accepted', 'reason'))
    if type(result['accepted']) is not bool:
        raise ValueError('声线审核必须明确给出通过或返修。')
    return result['accepted'], protocol._text(result['reason'], 700)


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
        for take in range(2):
            turns = []
            prefix = 'retake-' if take else ''
            for index, name in enumerate(names, 1):
                role = {**roles[name], 'own_book_profile': cards[name]}
                # Feedback may mention other characters' secrets. It stays with the director/reviewer.
                packet = {'role': role, 'public_start': public, 'observable_turns': list(turns)}
                turn = await request(f'{prefix}actor-{index}', protocol.ACTOR + ACTOR_RULES, packet, protocol._turn)
                turns.append({'name': name, **turn})
            accepted, note = await request(f'{prefix}review', REVIEW, {
                'scene': scene, 'cards': cards, 'public_start': public, 'turns': turns,
                'assigned_roles': roles,
            }, _assessment)
            if accepted:
                rehearsals.append({'scene_id': scene_id, 'opening': scene['entry'], 'turns': turns})
                break
            if not take:
                public, roles = await request('retake-director', director_prompt, director_input | {'review': note}, parse_roles)
        else:
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
