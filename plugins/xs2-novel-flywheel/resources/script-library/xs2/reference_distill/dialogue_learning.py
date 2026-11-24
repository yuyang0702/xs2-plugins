"""Verified source dialogue for analysis; quotes never become writing instructions."""
import hashlib
import json
import re
from pathlib import Path


MAX_EXCHANGE_SPAN = 1400
CONTEXT_MARGIN = 300
SOURCE_BOUNDARY = re.compile(r"^===== SOURCE (?:CHAPTER|FILE).*?=====$", re.M)
QUOTED_SPEECH = re.compile(r'“[^“”]*”|「[^「」]*」|『[^『』]*』|"[^"\n]*"')
SPEECH_VERB = r'(?:说|问|道|答|喊|嘀咕|反问|反驳|抱怨|低语|开口|冷笑)'
TAG_LIMIT = 160
TAG_BREAK = '\r\n。！？!?；;：:“”「」『』"'
LEADING_TAG = re.compile(rf'(?P<tag>[^{TAG_BREAK}]+?)(?P<end>[：:，,])$')
TRAILING_TAG = re.compile(rf'^[，, \t]*(?P<tag>[^{TAG_BREAK}，,]+?)(?P<end>[。！？.!?，,]|(?=[\r\n])|\Z)')
SPEECH_MODIFIER = (
    r'(?:轻声|低声|高声|大声|小声|厉声|沉声|冷冷地|愣愣地|忽然|突然|又|也|才|接着|'
    r'没好气地|恶狠狠地|咬牙(?:切齿)?|鄙夷|怒喝|找补|指着[我你他她]|'
    r'嘴上|闷闷地|这样|缓缓地|慢慢地|轻轻地|重重地|笑着)'
)
ADDRESSEE = r'(?:(?!说|问|道|答|喊|叫|请|让|听|转述)[^\W\d_]){1,12}?'
SPEECH_PREDICATE = re.compile(
    rf'(?:(?:对着?|朝着?|向){ADDRESSEE})?{SPEECH_MODIFIER}*'
    rf'(?:{SPEECH_VERB}|[问答][我你他她]|告诉我|回应|插话|打断)(?:道|了)?'
)
# These actions can precede a speech predicate without introducing a new
# grammatical subject. Unrecognized continuations stay tentative.
CONTINUED_ACTION = re.compile(
    r'(?:这才|才|连忙|突然|忽然|又|也|死死|缓缓|轻轻|重重)*'
    r'(?:惊觉|收敛|移开|闭(?:了闭)?眼|气极反笑|抬眼|皱眉|摇头|点头|回过头|'
    r'盯着|看向|擦了|(?:一时|有点)(?:发蒙|蒙|愣|怔|茫然)|'
    r'(?:将|把)[^\s，,。！？!?；;：:]{1,12}?(?:攥在|握在|放在|放下))[^，,。！？!?；;：:]{0,30}'
)
COLON_PREDICATE = re.compile(
    r'(?:也?生气|抓狂|(?:声音|语气)(?:变了|一沉|转柔|转冷)|'
    r'心情(?:似乎|仿佛|显然)?(?:有[些所]|一点点)?(?:好转|低落|平静下来)|'
    r'强迫自己(?:镇定|冷静)下来|'
    rf'指着{ADDRESSEE}|挑了挑眉)'
)
NARRATOR_LABEL = re.compile(r'叙述者|叙事者|视角人物|主人公|主角')
UNRESOLVED_PRONOUNS = {'你', '你们', '他', '她', '它', '他们', '她们', '它们', '对方', '那个人'}
SUBJECT_QUALIFIER = re.compile(r'^[^\W\d_]{1,16}?(?:里的|中的|里头的|口的|边的|旁的|那头的|这头的)')
SUBJECT_SWITCH = re.compile(r'(?:看向|看见|盯着|听见?|让|催|逼|问|叫|说|喊|请|告诉)')


def dialogue_context(raw, start, end, chapter_range=None):
    lower_bound, upper_bound = chapter_range or (0, len(raw))
    lower = max(lower_bound, start - MAX_EXCHANGE_SPAN)
    upper = min(upper_bound, end + MAX_EXCHANGE_SPAN)
    return {'source_start': lower, 'source_end': upper,
            'before': raw[lower:start], 'after': raw[end:upper]}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _text(value, label, limit=400):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'对白样本{label}为空或超长')
    return value.strip()


def _rules(value, label):
    if not isinstance(value, list) or not 1 <= len(value) <= 6:
        raise ValueError(f'对白样本{label}须为非空数组')
    return [_text(item, label) for item in value]


def _tag_subjects(tag, start, proof, expected, speaker, *, colon, literal):
    # Walk back from the speech predicate. An explicit subject after a comma
    # supersedes the subject of the preceding action.
    continuation = []
    for clause in reversed(list(re.finditer(r'[^，,]+', tag))):
        text = clause[0].lstrip()
        position = start + clause.end() - len(text)
        if proof is None or proof['source_start'] <= position:
            qualifier = SUBJECT_QUALIFIER.match(text) if not literal else None
            prefix = qualifier[0] if qualifier and not SUBJECT_SWITCH.search(qualifier[0]) else ''
            for identity in expected:
                subject = prefix + identity if prefix and text.startswith(prefix + identity) else identity
                if not text.startswith(subject) or (speaker and subject != speaker and not subject.endswith('的' + speaker)):
                    continue
                predicate = text[len(subject):].strip()
                actions = [predicate, *reversed(continuation)]
                if any(not CONTINUED_ACTION.fullmatch(action) for action in actions[:-1]):
                    continue
                last = actions[-1]
                if SPEECH_PREDICATE.fullmatch(last) or (
                    colon and (COLON_PREDICATE.fullmatch(last) or len(actions) == 1 and not last)
                ):
                    yield subject
        continuation.append(text.strip())


def _adjacent_tags(raw, quote, lower, upper):
    start = max(lower, quote.start() - TAG_LIMIT)
    before = raw[start:quote.start()].rstrip()
    # A comma can reintroduce a split utterance after its speech tag.
    match = LEADING_TAG.search(before)
    if match:
        position = start + match.start('tag')
        complete = position > start or position == 0 or raw[position - 1] in TAG_BREAK
        if complete and (match['end'] in '：:' or before[:match.start()].endswith(('，」', '，”', '，』', ',"'))):
            yield match['tag'], position, match['end'] in '：:'

    end = min(upper, quote.end() + TAG_LIMIT)
    following = raw[quote.end():end]
    after = following.lstrip()
    match = TRAILING_TAG.match(after)
    if not match:
        return
    gap = len(following) - len(after)
    on_next_line = '\n' in following[:gap]
    if not match['end'] and (on_next_line or (match.end() == len(after) and end < len(raw))):
        return
    rest = after[match.end():].lstrip()
    if (on_next_line or match['end'] in ('，', ',')) and rest[:1] in ('“', '「', '『', '"'):
        if quote.group()[-2:-1] not in ('，', ','):
            return
    yield match['tag'], quote.end() + gap + match.start('tag'), False


def _verified_speaker(raw, quotes, proof, speaker, speaker_label, source_speaker, lower, upper):
    # New replies supply the original subject. Archived replies can still be
    # checked using their literal name/role or a marked first-person narrator.
    expected = [source_speaker or speaker or speaker_label]
    if not (source_speaker or speaker) and speaker_label and NARRATOR_LABEL.search(speaker_label):
        expected.append('我')
    expected = [identity for identity in expected if identity not in UNRESOLVED_PRONOUNS]
    verified = []
    for quote in quotes:
        subjects = set()
        for tag, start, colon in _adjacent_tags(raw, quote, lower, upper):
            tag = tag.rstrip()
            if proof and start + len(tag) > proof['source_end']:
                continue
            subjects.update(_tag_subjects(tag, start, proof, expected, speaker, colon=colon,
                                          literal=source_speaker is not None))
        if len(subjects) != 1:
            return None
        verified.append(subjects.pop())
    return verified[0] if all(subject == verified[0] for subject in verified) else None


def _has_speech_tag(raw, quote, lower, upper):
    line_start = raw.rfind('\n', lower, quote.start()) + 1
    line_start = max(lower, line_start)
    before = raw[line_start:quote.start()]
    starts_line = not before.strip()
    if starts_line and line_start > lower:
        before = raw[lower:line_start].rstrip().rsplit('\n', 1)[-1]
    if re.search(rf'{SPEECH_VERB}(?:我|他|她|道|了)?[：:][ \t]*$', before):
        return True
    line_end = raw.find('\n', quote.end(), upper)
    after = raw[quote.end():upper if line_end < 0 else line_end]
    after_pattern = rf'^[，, \t]*[^，,。？！!?；;：“”「」『』"\s]{{1,24}}?{SPEECH_VERB}'
    if re.match(after_pattern + r'(?:[。！？，,.!?：:]|[ \t]*$)', after):
        return True
    if starts_line and not after.strip() and line_end >= 0:
        following = raw[line_end + 1:upper].lstrip().split('\n', 1)[0]
        return bool(re.fullmatch(after_pattern + r'[。！？.!?][ \t]*', following))
    return False


def _checked_quote(value, checked_proof, speech, *, complete=False):
    text = _text(value.get('text'), '原句', 300)
    proof = checked_proof(value.get('evidence'))
    excerpt = proof['excerpt']
    offset = excerpt.find(text)
    if offset < 0 or excerpt.find(text, offset + 1) >= 0:
        raise ValueError('对白原句须在所选证据中准确且唯一出现')
    start = proof['source_start'] + offset
    end = start + len(text)
    quote = next((q for q in speech if (q.start() < start and end < q.end())
                  or (q.start() == start and end == q.end())), None)
    if quote is None:
        raise ValueError('对白证据不是可核对的直接引语，无法确认时请省略样本')
    quoted_text = quote.group()[1:-1]
    if start == quote.start():
        text = quoted_text.strip()
        start += 1 + len(quoted_text) - len(quoted_text.lstrip())
        end = start + len(text)
    if not text or (complete and text != quoted_text.strip()):
        raise ValueError('对白片段须为一整段可核对的直接引语')
    return {'text': text, 'source_start': start, 'source_end': end}, quote


def _checked_non_dialogue_quotes(entries, omitted, speech, raw, lower, upper, checked_proof):
    if not isinstance(entries, list) or len(entries) > 12:
        raise ValueError('对白样本的非对白引号须为至多12项的数组')
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('非对白引号须为对象')
        evidence = entry.get('evidence')
        proof = checked_proof(evidence)
        matched = [q for q in speech if proof['source_start'] <= q.start() and q.end() <= proof['source_end']]
        if len(matched) != 1 or matched[0] not in omitted:
            raise ValueError('非对白证据须对应交谈中一个尚未选用的完整引号')
        quote = matched[0]
        # A supplied reason cannot turn clearly attributed speech into narration.
        if _has_speech_tag(raw, quote, lower, upper):
            raise ValueError('对白样本不能跳过中间回应')
        omitted.remove(quote)
        reason = entry.get('reason', evidence.get('reason'))
        result.append({'evidence': proof, 'reason': _text(reason, '非对白判断依据')})
    if omitted:
        raise ValueError('对白样本不能跳过中间回应')
    return result


def normalize_dialogue_samples(samples, window, raw, resolve_evidence):
    if samples is None:
        return []
    if not isinstance(samples, list) or len(samples) > 3:
        raise ValueError('每条写法的对白样本须为至多3项的数组')
    if not samples:
        return []
    result = []
    core_start, core_end = window['source_start'], window['source_end']
    evidence_window = window
    if 'dialogue_context' in window:
        context = dialogue_context(raw, core_start, core_end, window.get("chapter_range"))
        if window['dialogue_context'] != context:
            raise ValueError('对白窗口语境与参考资料快照不一致')
        evidence_window = {**window, 'source_start': context['source_start'], 'source_end': context['source_end']}
    lower, upper = evidence_window['source_start'], evidence_window['source_end']
    # Scan complete lines before enforcing the visible bounds. Starting in the
    # middle of a line can mistake a straight closing quote for an opening quote.
    scan_start = raw.rfind('\n', 0, lower) + 1
    scan_end = raw.find('\n', upper)
    if scan_end < 0:
        scan_end = len(raw)
    markers = [(match.start(), match.end()) for match in SOURCE_BOUNDARY.finditer(raw, scan_start, scan_end)]
    speech = []
    for start, end in zip([scan_start, *(stop for _, stop in markers)],
                          [*(begin for begin, _ in markers), scan_end]):
        speech.extend(quote for quote in QUOTED_SPEECH.finditer(raw, start, end)
                      if lower <= quote.start() < quote.end() <= upper)

    def checked_proof(value):
        start, end, excerpt, _ = resolve_evidence(value, evidence_window, raw)
        return {'source_start': start, 'source_end': end, 'excerpt': excerpt}

    source_hash = hashlib.sha256(raw.encode()).hexdigest()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('对白样本必须为对象')
        turns = sample.get('turns')
        if not isinstance(turns, list) or not 2 <= len(turns) <= 8:
            raise ValueError('对白样本须有2至8个按原文排列的连续回应')
        checked = []
        quotes = []
        for turn in turns:
            if not isinstance(turn, dict):
                raise ValueError('对白轮次必须为对象')
            speaker_label = _text(turn['speaker_label'], '说话人标签', 80) if 'speaker_label' in turn else None
            speaker = _text(turn['speaker'], '说话人', 80) if 'speaker' in turn else None
            source_speaker = _text(turn['source_speaker'], '说话人原文称呼', 80) if 'source_speaker' in turn else None
            if not (speaker or speaker_label or source_speaker):
                raise ValueError('对白轮次须有可核对的说话人或暂定角色标签')
            segmented = 'segments' in turn
            segments = turn.get('segments', [turn])
            if (not isinstance(segments, list) or (segmented and not 2 <= len(segments) <= 8)
                    or any(not isinstance(segment, dict) for segment in segments)):
                raise ValueError('对白片段须为2至8项的对象数组')
            evidence = []
            turn_quotes = []
            for segment in segments:
                location, quote = _checked_quote(segment, checked_proof, speech, complete=segmented)
                if quotes and quote.start() < quotes[-1].end():
                    raise ValueError('对白轮次须按原文顺序且不能重叠')
                quotes.append(quote)
                turn_quotes.append(quote)
                evidence.append(location)
            if segmented and ('text' in turn or 'evidence' in turn):
                legacy, _ = _checked_quote(turn, checked_proof, speech)
                if legacy != evidence[0]:
                    raise ValueError('对白轮次的首段原句与原有证据不一致')
            record = {'speaker': speaker or speaker_label or source_speaker, **evidence[0],
                      'intent': _text(turn.get('intent'), '回应作用')}
            if speaker_label is not None:
                record['speaker_label'] = speaker_label
            if segmented:
                record['segments'] = evidence
            for field, label in (('trigger', '触发'), ('reaction', '后续反应')):
                proof_key = field + '_evidence'
                if field not in turn and proof_key not in turn:
                    continue
                record[field] = _text(turn.get(field), label)
                proof = checked_proof(turn.get(proof_key))
                if ((field == 'trigger' and proof['source_start'] >= turn_quotes[0].start())
                        or (field == 'reaction' and proof['source_end'] <= turn_quotes[-1].end())):
                    raise ValueError(f'对白样本{label}证据须来自该轮前后对应的原文')
                record[proof_key] = proof
            attribution_proof = None
            attribution = None
            if 'attribution' in turn or 'attribution_evidence' in turn:
                attribution = turn.get('attribution')
                if attribution not in ('observed', 'tentative'):
                    raise ValueError('对白说话人归属须为 observed 或 tentative')
                record['attribution'] = attribution
                if attribution == 'observed' or 'attribution_evidence' in turn:
                    attribution_proof = checked_proof(turn.get('attribution_evidence'))
                    record['attribution_evidence'] = attribution_proof
            grounded = None
            if attribution == 'observed' or (attribution is None and speaker and source_speaker is None):
                grounded = _verified_speaker(raw, turn_quotes, attribution_proof, speaker, speaker_label,
                                             source_speaker, lower, upper)
            if grounded:
                record['speaker'] = grounded
            else:
                record['attribution'] = 'tentative'
                if not (speaker or speaker_label):
                    record['speaker_label'] = source_speaker
            checked.append(record)
        if len({t['speaker'] for t in checked}) < 2:
            raise ValueError('对白样本须包含不同人物的回应')
        first, last = quotes[0].start(), quotes[-1].end()
        if last - first > MAX_EXCHANGE_SPAN:
            raise ValueError('对白轮次跨度过大，请选取同一次交谈')
        if not any(q.start() < core_end and q.end() > core_start for q in quotes):
            raise ValueError('对白样本至少有一轮须与当前窗口相交')
        if any(first < stop and begin < last for begin, stop in markers):
            raise ValueError('对白轮次须来自同一个来源单元')
        omitted = {q for q in speech if first <= q.start() and q.end() <= last} - set(quotes)
        non_dialogue = _checked_non_dialogue_quotes(sample.get('non_dialogue_quotes', []), omitted, speech,
                                                    raw, lower, upper, checked_proof)

        # Bind the same exchange to the same context even when reanalyzed in an
        # overlapping window. Import markers bound distinct source units.
        scene_start = max(0, first - CONTEXT_MARGIN)
        scene_end = min(len(raw), last + CONTEXT_MARGIN)
        boundary_start = raw.rfind('\n', 0, scene_start) + 1
        boundary_end = raw.find('\n', scene_end)
        for mark in SOURCE_BOUNDARY.finditer(raw, boundary_start, len(raw) if boundary_end < 0 else boundary_end):
            if mark.end() <= first:
                scene_start = max(scene_start, mark.end())
            elif mark.start() >= last:
                scene_end = min(scene_end, mark.start())
                break
        begin = raw.find('\n', scene_start, first) if scene_start else -1
        begin = begin + 1 if begin >= 0 else scene_start
        stop = raw.rfind('\n', last, scene_end) if scene_end < len(raw) else -1
        stop = stop if stop >= 0 else scene_end
        context = raw[begin:stop]
        if any('speaker' in turn and record['speaker'] not in context for turn, record in zip(turns, checked)):
            raise ValueError('对白说话人缺少邻近原文依据，不能猜测人物姓名')
        annotations = [t[key] for t in checked
                       for key in ('trigger_evidence', 'reaction_evidence', 'attribution_evidence') if key in t]
        annotations.extend(item['evidence'] for item in non_dialogue)
        relationship_proof = None
        if 'relationship_evidence' in sample:
            relationship_proof = checked_proof(sample['relationship_evidence'])
            annotations.append(relationship_proof)
        if any(not scene_start <= p['source_start'] < p['source_end'] <= scene_end for p in annotations):
            raise ValueError('对白分析证据须位于同一次交谈的邻近语境')
        turn_ids = []
        for turn in checked:
            positions = [turn['source_start'], turn['source_end'], turn['speaker']]
            if 'segments' in turn:
                positions.append([(s['source_start'], s['source_end']) for s in turn['segments'][1:]])
            turn_ids.append(positions)
        identity = [source_hash, turn_ids]
        tentative = any(t.get('attribution') == 'tentative' for t in checked)
        record = {'sample_id': 'dialogue-' + _digest(identity)[:24],
                  'source_sha256': identity[0],
                  'status': 'context_tentative' if tentative else 'context_verified',
                  'scene_type': _text(sample.get('scene_type'), '场景'),
                  'relationship': _text(sample.get('relationship'), '关系分析'),
                  'turns': checked, 'context': {'source_start': begin, 'source_end': stop, 'text': context},
                  'transferable_moves': _rules(sample.get('transferable_moves'), '可迁移方法'),
                  'limits': _rules(sample.get('limits'), '使用边界')}
        if relationship_proof:
            record['relationship_evidence'] = relationship_proof
        if non_dialogue:
            record['non_dialogue_quotes'] = non_dialogue
        if record['sample_id'] not in {r['sample_id'] for r in result}:
            result.append(record)
    return result


def combine_samples(items):
    result = {}
    def proof(s):
        return [s.get('source_sha256'),s.get('context'),
                [{k:t.get(k) for k in ('speaker','text','source_start','source_end','segments')} for t in s['turns']]]
    def annotation(s):
        response = {'scene_type':s.get('scene_type'),'relationship':s.get('relationship'),
                'turn_intents':[t.get('intent') for t in s['turns']],
                'transferable_moves':s.get('transferable_moves'),'limits':s.get('limits')}
        annotations = [{key: value for key, value in turn.items()
                        if key in ('speaker_label', 'trigger', 'reaction', 'attribution', 'trigger_evidence',
                                   'reaction_evidence', 'attribution_evidence')} for turn in s['turns']]
        if any(annotations):
            response['turn_annotations'] = annotations
            response['status'] = s.get('status')
        if 'relationship_evidence' in s:
            response['relationship_evidence'] = s['relationship_evidence']
        if 'non_dialogue_quotes' in s:
            response['non_dialogue_quotes'] = s['non_dialogue_quotes']
        return response
    for item in items:
        for sample in item.get('dialogue_samples', []):
            key=sample['sample_id']
            if key not in result:
                result[key]={**sample,'analysis_variants':list(sample.get('analysis_variants',[annotation(sample)]))}
            else:
                if proof(result[key]) != proof(sample):raise ValueError('同一对白样本的来源证据冲突')
                # A competing attribution remains visible as tentative during
                # review and cannot authorize automatic scene adaptation.
                if result[key].get('status') == 'context_verified' and sample.get('status') == 'context_tentative':
                    result[key] = {**sample, 'analysis_variants': result[key]['analysis_variants']}
                for variant in sample.get('analysis_variants',[annotation(sample)]):
                    if variant not in result[key]['analysis_variants']:result[key]['analysis_variants'].append(variant)
    return list(result.values())


def profile_samples(candidates, budget=10000):
    selected = []
    for candidate in candidates:
        for sample in candidate.get('dialogue_samples', []):
            record = {**sample, 'candidate_id': candidate['candidate_id']}
            size = len(json.dumps(record, ensure_ascii=False))
            if size <= budget:
                selected.append(record); budget -= size
    return selected


def render_adaptations(root, blueprint, scope, chapter=None):
    receipt = {'applied':0, 'pending':0, 'skipped':0}
    path = root/'learning/dialogue_adaptations.json'
    if not path.exists():return [], receipt
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('对白适配记录越出本书工作区')
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if document.get('schema') != 'xs2.book.dialogue_adaptations.v1' or not isinstance(document.get('items'), list):
        raise ValueError('本书对白适配记录无效')
    selected = {identifier for kind in ('candidate', 'style', 'conflict')
                for identifier in blueprint.get(f'selected_{kind}_ids', [])}
    project_file = root/'.novel-project.json'
    project = json.loads(project_file.read_text(encoding='utf-8-sig')) if project_file.is_file() else {}
    def positioning(value):
        return _digest({key:value.get('values', {}).get(key, '')
                        for key in ('premise', 'genre', 'narrative_pov', 'conflict_plan_mode', 'human_intent')})
    lines = []
    if chapter is not None and not re.fullmatch(r'\d{4}', chapter):
        raise ValueError('对白适配章节编号须为四位数字')
    for item in document['items']:
        if not isinstance(item, dict):raise ValueError('对白适配条目无效')
        if item.get('reference_id') not in selected:
            receipt['skipped'] += 1;continue
        if item.get('status') == 'pending_context':
            receipt['pending'] += 1;continue
        position = positioning(project)
        if not project_file.is_file():
            history_path = root/'learning/assistant-history.json'
            if not history_path.resolve().is_relative_to(root.resolve()):raise ValueError('顾问定位依据越出本书工作区')
            history = json.loads(history_path.read_text(encoding='utf-8-sig')) if history_path.is_file() else {}
            entry = next((e for e in history.get('entries', []) if isinstance(e, dict)
                          and e.get('id') == item.get('advisor_entry_id')), None)
            if not entry or _digest(entry) != item.get('advisor_sha256'):
                receipt['skipped'] += 1;continue
            position = positioning(entry.get('configuration_base', {}))
        if (item.get('status') != 'matched' or scope not in {'mvp','polish'} or chapter is None
                or item.get('chapter') != chapter or position != item.get('positioning_sha256')):
            receipt['skipped'] += 1;continue
        hashes = item.get('input_hashes')
        if not isinstance(hashes, dict) or not hashes or item.get('scene_path') not in hashes:
            raise ValueError('对白适配缺少人物或场景依据校验')
        stale = False
        for relative, expected in hashes.items():
            if not isinstance(relative, str):raise ValueError('对白适配依据路径无效')
            source = root/relative
            if not source.resolve().is_relative_to(root.resolve()):raise ValueError('对白适配依据越出本书工作区')
            current = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
            stale |= current != expected
        if stale:
            receipt['skipped'] += 1;continue
        if not all(isinstance(item.get(key), str) and item[key].strip()
                   for key in ('character_name','interlocutor','scene_type','guidance')):
            raise ValueError('对白适配指导不完整')
        receipt['applied'] += 1
        receipt.setdefault('matches', []).append({key: item[key] for key in
                                                  ('reference_id', 'sample_id', 'chapter', 'scene_path')})
        lines.extend([f"## 本章对白参考：{item['character_name']}与{item['interlocutor']}",
                      '适用场景：'+item['scene_type'], item['guidance'],
                      '仅在上述人物、关系和实际场景相符时使用；随对方的前后回应调整，不把参考方法写成固定台词。', ''])
    if document['items']:
        lines.extend([f"对白适配：本章可用{receipt['applied']}项，待补语境{receipt['pending']}项，其他章节或已变化依据{receipt['skipped']}项。",
                      '待适配和依据已变化的条目不作为人物事实或本章对白规则。', ''])
    return lines, receipt
