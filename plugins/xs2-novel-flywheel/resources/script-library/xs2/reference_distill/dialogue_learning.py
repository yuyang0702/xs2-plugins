"""Verified source dialogue for analysis; quotes never become writing instructions."""
import hashlib
import json
import re
from pathlib import Path


MAX_EXCHANGE_SPAN = 1400
CONTEXT_MARGIN = 300
SOURCE_BOUNDARY = re.compile(r"^===== SOURCE (?:CHAPTER|FILE).*?=====$", re.M)
QUOTED_SPEECH = re.compile(r'“[^“”]*”|「[^「」]*」|『[^『』]*』|"[^"\n]*"')


def dialogue_context(raw, start, end):
    lower = max(0, start - MAX_EXCHANGE_SPAN)
    upper = min(len(raw), end + MAX_EXCHANGE_SPAN)
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


def _explicit_speaker(raw, quote, speaker, proof):
    line_start = raw.rfind('\n', 0, quote.start()) + 1
    line_end = raw.find('\n', quote.end())
    if line_end < 0:
        line_end = len(raw)
    who = re.escape(speaker)
    # An explicit subject whose turn starts after the name and a colon, or a
    # same-line speech tag following the quote, can support the attribution.
    before_pattern = rf'(?:^|[。？！!?；;”」』])[ \t]*({who})[^，,。！？!?；;：“”「」『』:]{{0,30}}[:：][ \t]*$'
    after_pattern = rf'^[，, \t]*({who})(?:低声|轻声|大声|小声|又|接着|才)?(?:说|问|道|答|喊|嘀咕|反问)(?:[。！？，,.!?]|[ \t]*$)'
    before = re.search(before_pattern, raw[line_start:quote.start()])
    after = re.search(after_pattern, raw[quote.end():line_end])
    return any(match and (not proof or proof['source_start'] <= offset + match.start(1)
                          and offset + match.end(1) <= proof['source_end'])
               for match, offset in ((before, line_start), (after, quote.end())))


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
        context = dialogue_context(raw, core_start, core_end)
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
            speaker = _text(turn.get('speaker'), '说话人', 80)
            text = _text(turn.get('text'), '原句', 300)
            proof = checked_proof(turn.get('evidence'))
            start, excerpt = proof['source_start'], proof['excerpt']
            offset = excerpt.find(text)
            if offset < 0 or excerpt.find(text, offset + 1) >= 0:
                raise ValueError('对白原句须在所选证据中准确且唯一出现')
            start += offset
            end = start + len(text)
            quote = next((q for q in speech if q.start() < start and end < q.end()), None)
            if quote is None:
                raise ValueError('对白证据不是可核对的直接引语，无法确认时请省略样本')
            if quotes and quote.start() < quotes[-1].end():
                raise ValueError('对白轮次须按原文顺序且不能重叠')
            quotes.append(quote)
            record = {'speaker': speaker, 'text': text, 'source_start': start,
                      'source_end': end, 'intent': _text(turn.get('intent'), '回应作用')}
            for field, label in (('trigger', '触发'), ('reaction', '后续反应')):
                proof_key = field + '_evidence'
                if field not in turn and proof_key not in turn:
                    continue
                record[field] = _text(turn.get(field), label)
                proof = checked_proof(turn.get(proof_key))
                if ((field == 'trigger' and proof['source_start'] >= quote.start())
                        or (field == 'reaction' and proof['source_end'] <= quote.end())):
                    raise ValueError(f'对白样本{label}证据须来自该轮前后对应的原文')
                record[proof_key] = proof
            attribution_proof = None
            if 'attribution' in turn or 'attribution_evidence' in turn:
                attribution = turn.get('attribution')
                if attribution not in ('observed', 'tentative'):
                    raise ValueError('对白说话人归属须为 observed 或 tentative')
                record['attribution'] = attribution
                if attribution == 'observed' or 'attribution_evidence' in turn:
                    attribution_proof = checked_proof(turn.get('attribution_evidence'))
                    record['attribution_evidence'] = attribution_proof
            if not _explicit_speaker(raw, quote, speaker, attribution_proof):
                record['attribution'] = 'tentative'
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
        if len(quotes) != sum(first <= q.start() and q.end() <= last for q in speech):
            raise ValueError('对白样本不能跳过中间回应')

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
        if any(t['speaker'] not in context for t in checked):
            raise ValueError('对白说话人缺少邻近原文依据，不能猜测人物姓名')
        annotations = [t[key] for t in checked
                       for key in ('trigger_evidence', 'reaction_evidence', 'attribution_evidence') if key in t]
        relationship_proof = None
        if 'relationship_evidence' in sample:
            relationship_proof = checked_proof(sample['relationship_evidence'])
            annotations.append(relationship_proof)
        if any(not scene_start <= p['source_start'] < p['source_end'] <= scene_end for p in annotations):
            raise ValueError('对白分析证据须位于同一次交谈的邻近语境')
        identity = [source_hash,
                    [(t['source_start'], t['source_end'], t['speaker']) for t in checked]]
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
        if record['sample_id'] not in {r['sample_id'] for r in result}:
            result.append(record)
    return result


def combine_samples(items):
    result = {}
    def proof(s):
        return [s.get('source_sha256'),s.get('context'),
                [{k:t.get(k) for k in ('speaker','text','source_start','source_end')} for t in s['turns']]]
    def annotation(s):
        response = {'scene_type':s.get('scene_type'),'relationship':s.get('relationship'),
                'turn_intents':[t.get('intent') for t in s['turns']],
                'transferable_moves':s.get('transferable_moves'),'limits':s.get('limits')}
        annotations = [{key: value for key, value in turn.items()
                        if key in ('trigger', 'reaction', 'attribution', 'trigger_evidence',
                                   'reaction_evidence', 'attribution_evidence')} for turn in s['turns']]
        if any(annotations):
            response['turn_annotations'] = annotations
            response['status'] = s.get('status')
        if 'relationship_evidence' in s:
            response['relationship_evidence'] = s['relationship_evidence']
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
