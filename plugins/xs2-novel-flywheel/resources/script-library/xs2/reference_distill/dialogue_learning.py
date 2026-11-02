"""Verified source dialogue for analysis; quotes never become writing instructions."""
import hashlib
import json
import re
from pathlib import Path


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


def normalize_dialogue_samples(samples, window, raw, resolve_evidence):
    if samples is None:
        return []
    if not isinstance(samples, list) or len(samples) > 3:
        raise ValueError('每条写法的对白样本须为至多3项的数组')
    result = []
    speech = list(re.compile(r'“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"').finditer(
        raw, window['source_start'], window['source_end']))
    source_hash = hashlib.sha256(raw.encode()).hexdigest()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('对白样本必须为对象')
        turns = sample.get('turns')
        if not isinstance(turns, list) or not 2 <= len(turns) <= 8:
            raise ValueError('对白样本须有2至8个按原文排列的连续回应')
        checked = []
        for turn in turns:
            if not isinstance(turn, dict):
                raise ValueError('对白轮次必须为对象')
            speaker = _text(turn.get('speaker'), '说话人', 80)
            text = _text(turn.get('text'), '原句', 300)
            start, end, excerpt, _ = resolve_evidence(turn.get('evidence'), window, raw)
            offset = excerpt.find(text)
            if offset < 0 or excerpt.find(text, offset + 1) >= 0:
                raise ValueError('对白原句须在所选证据中准确且唯一出现')
            start += offset; end = start + len(text)
            # Model-selected text must actually occur inside quoted speech.
            if not any(q.start() < start and end < q.end() for q in speech):
                raise ValueError('对白证据不是可核对的直接引语，无法确认时请省略样本')
            if checked and start < checked[-1]['source_end']:
                raise ValueError('对白轮次须按原文顺序且不能重叠')
            checked.append({'speaker': speaker, 'text': text, 'source_start': start,
                            'source_end': end, 'intent': _text(turn.get('intent'), '回应作用')})
        if len({t['speaker'] for t in checked}) < 2:
            raise ValueError('对白样本须包含不同人物的回应')
        first, last = checked[0]['source_start'], checked[-1]['source_end']
        if last - first > 1400:
            raise ValueError('对白轮次跨度过大，请选取同一次交谈')
        # Preserve real surrounding text on both sides, with source offsets.
        # Expand to line boundaries when possible instead of clipping a line.
        lower, upper = max(0, first - 300), min(len(raw), last + 300)
        begin = raw.find('\n', lower, first) if lower else -1
        begin = begin + 1 if begin >= 0 else lower
        stop = raw.rfind('\n', last, upper) if upper < len(raw) else -1
        stop = stop if stop >= 0 else upper
        context = raw[begin:stop]
        if any(t['speaker'] not in context for t in checked):
            raise ValueError('对白说话人缺少邻近原文依据，不能猜测人物姓名')
        # All intervening direct utterances must be represented, not just the
        # two convenient lines selected around a contradictory response.
        intervening = [q for q in speech if q.start() >= first - 1 and q.end() <= last + 1]
        if any(not any(t['source_start'] >= q.start() and t['source_end'] <= q.end()
                       for t in checked) for q in intervening):
            raise ValueError('对白样本不能跳过中间回应')
        identity = [source_hash,
                    [(t['source_start'], t['source_end'], t['speaker']) for t in checked]]
        record = {'sample_id': 'dialogue-' + _digest(identity)[:24],
                  'source_sha256': identity[0], 'status': 'context_verified',
                  'scene_type': _text(sample.get('scene_type'), '场景'),
                  'relationship': _text(sample.get('relationship'), '关系分析'),
                  'turns': checked, 'context': {'source_start': begin, 'source_end': stop, 'text': context},
                  'transferable_moves': _rules(sample.get('transferable_moves'), '可迁移方法'),
                  'limits': _rules(sample.get('limits'), '使用边界')}
        if record['sample_id'] not in {r['sample_id'] for r in result}:
            result.append(record)
    return result


def combine_samples(items):
    result = {}
    def proof(s):
        return [s.get('source_sha256'),s.get('context'),
                [{k:t.get(k) for k in ('speaker','text','source_start','source_end')} for t in s['turns']]]
    def annotation(s):
        return {'scene_type':s.get('scene_type'),'relationship':s.get('relationship'),
                'turn_intents':[t.get('intent') for t in s['turns']],
                'transferable_moves':s.get('transferable_moves'),'limits':s.get('limits')}
    for item in items:
        for sample in item.get('dialogue_samples', []):
            key=sample['sample_id']
            if key not in result:
                result[key]={**sample,'analysis_variants':list(sample.get('analysis_variants',[annotation(sample)]))}
            else:
                if proof(result[key]) != proof(sample):raise ValueError('同一对白样本的来源证据冲突')
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
    selected = set(blueprint.get('selected_candidate_ids', []))
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
        lines.extend([f"## 本章对白：{item['character_name']}与{item['interlocutor']}",
                      '适用场景：'+item['scene_type'], item['guidance'],
                      '仅在上述人物、关系和实际场景相符时使用；随对方的前后回应调整，不把参考方法写成固定台词。', ''])
    if document['items']:
        lines.extend([f"对白适配：本章可用{receipt['applied']}项，待补语境{receipt['pending']}项，其他章节或已变化依据{receipt['skipped']}项。",
                      '待适配和依据已变化的条目不作为人物事实或本章对白规则。', ''])
    return lines, receipt
