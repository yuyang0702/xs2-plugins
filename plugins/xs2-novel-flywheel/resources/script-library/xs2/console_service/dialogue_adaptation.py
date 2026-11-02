"""Book-grounded dialogue mappings. Legacy references require no migration."""
import hashlib
import json
import re


DIALOGUE_PATH = 'learning/dialogue_adaptations.json'
POSITION_KEYS = ('premise', 'genre', 'narrative_pov', 'conflict_plan_mode', 'human_intent')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def positioning(project):
    return fingerprint({key: project.get('values', {}).get(key, '') for key in POSITION_KEYS})


def _annotations(sample):
    return {'scene_type':sample.get('scene_type'), 'relationship':sample.get('relationship'),
            'turn_intents':[t.get('intent') for t in sample['turns']],
            'transferable_moves':sample.get('transferable_moves'), 'limits':sample.get('limits')}


def _proof(sample):
    return [sample.get('source_sha256'), sample.get('context'),
            [{k:t.get(k) for k in ('speaker','text','source_start','source_end')} for t in sample['turns']]]


def source_samples(item):
    identifier = item.get('candidate_id') or item.get('choice_id')
    candidate = item.get('candidate', {})
    profile = item.get('library', {}).get('profile', {})
    values = candidate.get('dialogue_samples', [])
    profiles = profile.get('dialogue_samples', [])
    if not isinstance(values, list) or not isinstance(profiles, list):
        raise ValueError('来源对白样本格式无效，请重新分析')
    values = [*values, *(s for s in profiles if isinstance(s, dict) and s.get('candidate_id') == identifier)]
    source = candidate.get('source') or item.get('library', {}).get('candidates', {}).get('source', {})
    checked = {}
    for sample in values:
        if (not isinstance(sample, dict) or sample.get('status') != 'context_verified'
                or sample.get('source_sha256') != source.get('text_sha256')):
            raise ValueError('对白样本与所选来源身份不符')
        context = sample.get('context', {});turns = sample.get('turns', [])
        begin, end, text = context.get('source_start'), context.get('source_end'), context.get('text')
        if (type(begin) is not int or type(end) is not int or not isinstance(text, str)
                or begin < 0 or end - begin != len(text) or len(text) > 2200
                or not isinstance(turns, list) or not 2 <= len(turns) <= 8):
            raise ValueError('对白样本缺少可回查的前后语境')
        previous = begin
        for turn in turns:
            a, b = turn.get('source_start'), turn.get('source_end')
            if (type(a) is not int or type(b) is not int or not begin <= previous <= a < b <= end
                    or text[a-begin:b-begin] != turn.get('text')
                    or not isinstance(turn.get('speaker'), str) or turn['speaker'] not in text):
                raise ValueError('来源对白轮次或说话人无法核对')
            previous = b
        if len({t['speaker'] for t in turns}) < 2:
            raise ValueError('来源对白缺少双方回应')
        key = sample.get('sample_id')
        if not isinstance(key, str) or not key.startswith('dialogue-'):
            raise ValueError('来源对白样本编号无效')
        comparable = {k:v for k,v in sample.items() if k != 'candidate_id'}
        if key in checked:
            if _proof(checked[key]) != _proof(comparable):
                raise ValueError('同一对白样本的来源证据相互冲突')
            variants = checked[key].setdefault('analysis_variants', [_annotations(checked[key])])
            for variant in comparable.get('analysis_variants', [_annotations(comparable)]):
                if variant not in variants:variants.append(variant)
        else:
            checked[key] = {**comparable, 'analysis_variants':list(comparable.get('analysis_variants', [_annotations(comparable)]))}
    return list(checked.values())


def _scene_in_chapter(text, evidence, chapter, project):
    markers = list(re.finditer(r'^\s*(?:#{1,6}[ \t]*)?(?:第\s*)?([0-9]+)\s*章[^\n]*', text, re.M))
    if not markers:
        return project.get('mode') == 'short' and chapter == '0001'
    for index, marker in enumerate(markers):
        end = markers[index+1].start() if index+1 < len(markers) else len(text)
        if int(marker[1]) == int(chapter) and evidence in text[marker.start():end]:return True
    return False


def assert_abstract(text, samples):
    if any(text[i:i+20] in s['context']['text'] for s in samples for i in range(max(0, len(text)-19))):
        raise ValueError('对白适配指导包含原作连续台词或叙述，请提炼方法后重新采用')


def validate_situations(voice, accepted, characters, book_files, project=None):
    sources = {}
    for item in accepted:
        identifier = item.get('candidate_id') or item.get('choice_id')
        for sample in source_samples(item):sources[(identifier, sample['sample_id'])] = sample
    raw = voice.get('dialogue_situations', [])
    if not isinstance(raw, list) or len(raw) > 16:
        raise ValueError('对白关系场景适配须为至多16项的数组')
    result = [];seen = set()
    name = voice['character_name']
    assert_abstract(voice['guidance'], list(sources.values()))
    for item in raw:
        if not isinstance(item, dict):raise ValueError('对白关系场景适配须为对象')
        key = (item.get('reference_id'), item.get('sample_id'))
        if key not in sources or key[0] not in voice.get('reference_ids', []):
            raise ValueError('对白适配引用了未采用或未关联本人的来源样本')
        identity = (*key, item.get('interlocutor'), item.get('chapter'), item.get('scene_path'), item.get('scene_evidence'))
        if identity in seen:raise ValueError('对白场景适配重复')
        seen.add(identity)
        base = {'reference_id':key[0], 'sample_id':key[1], 'source_sha256':sources[key]['source_sha256']}
        if item.get('status') == 'pending_context':
            reason = item.get('reason')
            if not isinstance(reason, str) or not 6 <= len(reason.strip()) <= 500:
                raise ValueError('待适配对白必须说明缺少的关系或场景依据')
            result.append({**base, 'status':'pending_context', 'reason':reason.strip()})
            continue
        if item.get('status') != 'matched':raise ValueError('对白适配状态无效')
        partner = item.get('interlocutor')
        if partner not in characters or partner == name:
            raise ValueError('对白适配的交谈对象须为另一位本书已有角色')
        relationship = item.get('relationship_evidence')
        if (not isinstance(relationship, str) or len(relationship.strip()) < 4
                or not any(relationship in characters[p] and (partner if p==name else name) in relationship
                           for p in (name, partner))):
            raise ValueError('对白双方关系缺少人物档案中的明确依据')
        path = item.get('scene_path');evidence = item.get('scene_evidence');chapter = item.get('chapter')
        allowed = isinstance(path, str) and (path.startswith('outline/') or path == 'meta/story_plan.md'
                  or bool(re.fullmatch(r'story/\d{4}/chapter\.md', path)))
        if (not allowed or path not in book_files or not isinstance(evidence, str)
                or not 6 <= len(evidence.strip()) <= 1500 or evidence not in book_files[path]
                or not re.fullmatch(r'\d{4}', str(chapter))
                or name not in evidence or partner not in evidence):
            raise ValueError('对白适用场景缺少本书双方实际交谈的原文依据')
        if path.startswith('story/') and path.split('/')[1] != chapter:
            raise ValueError('对白场景所属章节不一致')
        if not path.startswith('story/') and not _scene_in_chapter(book_files[path], evidence, chapter, project or {}):
            raise ValueError('对白大纲证据不属于指定章节，无法确认时须标为pending_context')
        guidance = item.get('guidance');scene_type = item.get('scene_type')
        if (not isinstance(guidance, str) or not 12 <= len(guidance.strip()) <= 1500
                or not isinstance(scene_type, str) or not 2 <= len(scene_type.strip()) <= 100):
            raise ValueError('对白适配缺少本书场景的具体用法')
        assert_abstract(guidance, list(sources.values()))
        result.append({**base, 'status':'matched', 'interlocutor':partner,
                       'relationship_evidence':relationship, 'scene_path':path, 'scene_evidence':evidence,
                       'chapter':chapter, 'scene_type':scene_type.strip(), 'guidance':guidance.strip()})
    return result


def require_coverage(accepted, voices, characters):
    if not characters:return
    required = {item.get('candidate_id') or item.get('choice_id') for item in accepted if source_samples(item)}
    covered = {s['reference_id'] for v in voices for s in v.get('dialogue_situations', [])}
    if required - covered:
        raise ValueError('采用对白样本前须提供有依据的关系场景适配，或明确标为pending_context')


def build_adaptations(root, project, voices, previous=None, advisor_entry=None):
    previous = previous or {'schema':'xs2.book.dialogue_adaptations.v1', 'items':[]}
    if previous.get('schema') != 'xs2.book.dialogue_adaptations.v1' or not isinstance(previous.get('items'), list):
        raise ValueError('已有对白适配记录无效，不能覆盖')
    items = list(previous['items'])
    for voice in voices:
        for situation in voice.get('dialogue_situations', []):
            files = ['meta/character_profiles.md', 'cache/sync/characters.json']
            if situation.get('status') == 'matched':files.append(situation['scene_path'])
            hashes = {}
            for relative in files:
                path = root/relative
                if not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError('对白适配依据越出本书工作区')
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            record = {**situation, 'character_name':voice['character_name'],
                      'profile_evidence':voice['profile_evidence'], 'input_hashes':hashes,
                      'positioning_sha256':positioning(project)}
            if not (root/'.novel-project.json').is_file():
                if not isinstance(advisor_entry, dict) or not advisor_entry.get('id'):
                    raise ValueError('无项目文件的作品须保留本次已验证的顾问定位依据')
                record['advisor_entry_id'] = advisor_entry['id']
                record['advisor_sha256'] = fingerprint(advisor_entry)
            record['adaptation_id'] = 'dialogue-adaptation-' + fingerprint(record)[:24]
            def same_case(old):
                common = ('reference_id','sample_id','character_name')
                if any(old.get(k) != record.get(k) for k in common):return False
                if record['status']=='matched' and old.get('status')=='pending_context':return True
                return all(old.get(k)==record.get(k) for k in ('status','interlocutor','chapter','scene_path','scene_evidence'))
            items = [old for old in items if not same_case(old)]
            items.append(record)
    return {'schema':'xs2.book.dialogue_adaptations.v1', 'items':items}
