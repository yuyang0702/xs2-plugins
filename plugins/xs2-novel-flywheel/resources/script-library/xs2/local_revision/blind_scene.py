"""Deterministic replay of anonymous scene ballots against exact writer patches."""
import difflib
import hashlib
import hmac
import json
import re
from itertools import zip_longest


def sentences(text):
    # Keep terminators and whitespace with the text they belong to, including CRLF.
    return re.findall(r'.+?(?:[。！？!?]+[”’」』）]*\s*|(?:\r?\n)+|\Z)', text, re.S)


def alternatives(old, new):
    a, b = sentences(old), sentences(new)
    for tag, i, j, k, l in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            yield ''.join(a[i:j]), ''.join(b[k:l])
        else:
            yield from zip_longest(a[i:j], b[k:l], fillvalue='')


def scene_ranges(rows, windows):
    headings = [i for i, row in enumerate(rows) if re.fullmatch(
        r'(?:#{1,6}\s*)?(?:[0-9]{1,3}|[一二三四五六七八九十]{1,3}|第[一二三四五六七八九十百0-9]+[场节幕])',
        row['text'].strip().splitlines()[0])]
    if len(headings) > 1:
        starts = [0, *headings[1:]]
    else:
        starts = [0, *[int(w['first'][1:])-1 for w in windows[1:]]]
    return [rows[start:end] for start, end in zip(starts, [*starts[1:], len(rows)])]


CREATIVE = re.compile(
    r'重新(?:写|表述|表达|措辞)|重写|改写|(?:改换|更换|换)(?:一?[种个])?(?:表达(?:方式)?|表述|说法|措辞|写法)'
    r'|(?:加强|加深|增强|突出|强化|写足|写出).{0,6}?(?:情绪|情感|张力)'
    r'|(?:情绪|情感|张力).{0,5}(?:更强|更足|更浓|加强|拉满)')
MINIMAL = re.compile(r'校错|纠错|校对|勘误|错别字|改错字|删重|去重|尽(?:量|可能)少(?:动|改)|最小(?:改动|修改)|少动原文')
QUOTED = r'「[^」\n]*」|“[^”\n]*”|"[^"\n]*"'
CLAUSE = re.compile(r'(?:(?:' + QUOTED + r')|[^。；;\n，,「“"])+')
NEGATED = re.compile(r'(?:不(?:再|要|用|必|需(?:要)?)?|别|无需|禁止)(?:大幅|全部|整体|刻意)?\s*$')


def tie_policy(feedback, rows):
    """Only author directives establish intent. Quoted prose locates a directive."""
    default, by_paragraph = 'original', {}
    for match in CLAUSE.finditer(feedback):
        clause = match.group()
        instruction = re.sub(QUOTED, ' ', clause)
        requests = list(CREATIVE.finditer(instruction))
        if not requests and not MINIMAL.search(instruction):
            continue
        creative = any(not NEGATED.search(instruction[:r.start()]) for r in requests)
        mode = 'creative' if creative and not MINIMAL.search(instruction) else 'original'
        ids = set(re.findall(r'p\d{4,}(?!\d)', instruction))
        for first, last in re.findall(r'(p\d{4,})\s*[至到~—-]\s*(p\d{4,})', instruction):
            ids.update(row['id'] for row in rows if first <= row['id'] <= last)
        for quote in re.findall(QUOTED, clause):
            hits = [row['id'] for row in rows if quote[1:-1] and quote[1:-1] in row['text']]
            if len(hits) == 1:
                ids.update(hits)
        for first, last in re.findall(r'第(\d+)(?:[至到~—-](?:第)?(\d+))?段', instruction):
            ids.update(row['id'] for row in rows[int(first)-1:int(last or first)])
        if rows and re.search(r'首段|第一段', instruction):
            ids.add(rows[0]['id'])
        if rows and re.search(r'末段|最后一段', instruction):
            ids.add(rows[-1]['id'])
        if ids:
            by_paragraph.update(dict.fromkeys(ids, mode))
        elif not re.search(QUOTED, clause):
            default = mode
    return {'default': default, 'paragraphs': by_paragraph}


def packet(source, edits, windows, seed, patches, *, required=False, policy=None):
    """Only the public packet goes to the reader. Decoder entries never do."""
    rows = patches.paragraphs(source)
    ranges = scene_ranges(rows, windows)
    uid = lambda value: hmac.new(seed.encode(), value.encode(), hashlib.sha256).hexdigest()
    order = sorted(range(len(ranges)), key=lambda pos: uid(str(pos)))
    first = int(uid('first'), 16) % 2
    old_a = {pos: (rank + first) % 2 == 0 for rank, pos in enumerate(order)}
    public, decoder, by_paragraph = [], {}, {}
    for index, edit in enumerate(edits):
        by_paragraph.setdefault(edit['paragraph_id'], []).append(index)
    for pos, section in enumerate(ranges):
        sid = f'S{pos+1}'
        is_a = old_a[pos]
        def pair(left, right):
            return {'A': left, 'B': right} if is_a else {'A': right, 'B': left}
        a, b, cards = [], [], []
        for row in section:
            a.append(row['text'])
            b.append(patches._scoped_paragraph(row, edits))
            for i in by_paragraph.get(row['id'], []):
                parts = []
                for left, right in alternatives(edits[i]['old'], edits[i]['replacement']):
                    key = None
                    if left != right:
                        key = f'{sid}.{len(cards)+1}'
                        cards.append({'id': key, **pair(left, right)})
                    parts.append((key, left, right))
                decoder[i] = (sid, 'A' if is_a else 'B', parts)
        public.append({'id': sid, **pair('\n\n'.join(a), '\n\n'.join(b)), 'choices': cards})
    tag = uid(json.dumps(public, ensure_ascii=False, sort_keys=True))[:16]
    packet = {'ballot': tag, 'scenes': public}
    if required:
        packet['reading_task'] = 'meaning_preservation'
    elif policy and any(policy['paragraphs'].get(e['paragraph_id'], policy['default']) == 'creative' for e in edits):
        packet['reading_task'] = 'creative_equivalence'
    return packet, decoder


def select(public, decoder, edits, report, *, keep_on_tie=(), required_indices=(), policy=None):
    if report.get('ballot') != public['ballot']:
        raise ValueError('请填写本张票面给出的 ballot。')
    votes = report.get('scenes')
    if not isinstance(votes, list) or len(votes) != len(public['scenes']):
        raise ValueError('每场均须交一张选票。')
    ballots = {v['id']: v for v in votes}
    selected = {}
    for scene in public['scenes']:
        sid = scene['id']
        v = ballots.get(sid, {})
        base = v.get('prefer')
        flip = v.get('exceptions')
        keys = {card['id'] for card in scene['choices']}
        if base not in ('A','B','tie') or not isinstance(flip,list) or len(set(flip))!=len(flip) or set(flip)-keys:
            raise ValueError(f'{sid} 须选 A、B 或 tie，exceptions 仅列本场需要反选的句子编号。')
        if base == 'tie' and flip:
            raise ValueError(f'{sid} 选 tie 时 exceptions 应为空。')
        for field in ('voice_quote','redundant_quote','reason'):
            value = v.get(field)
            required = field == 'reason' or (field == 'voice_quote' and base != 'tie')
            if not isinstance(value,str) or (required and not value.strip()):
                raise ValueError(f'{sid} 缺少 {field}。')
            if field!='reason' and value not in scene['A'] and value not in scene['B']:
                raise ValueError(f'{sid} 的 {field} 须逐字引本场某一版的一小段连续原文。')
        equivalent = False
        if base == 'tie' and keys and public.get('reading_task') == 'creative_equivalence':
            if any(type(v.get(key)) is not bool for key in ('same_meaning', 'same_voice')):
                raise ValueError(f'{sid} 平票须分别核对 same_meaning 和 same_voice。')
            equivalent = v['same_meaning'] and v['same_voice']
        selected[sid] = (base, set(flip), equivalent)
    result = []
    for i, edit in enumerate(edits):
        sid, original, parts = decoder[i]
        base, flip, equivalent = selected[sid]
        if base == 'tie' and policy and public.get('reading_task') != 'meaning_preservation':
            mode = policy['paragraphs'].get(edit['paragraph_id'], policy['default'])
            if mode == 'creative' and equivalent:
                result.append(edit)
            continue
        if i in required_indices:
            result.append(edit)
            continue
        if base == 'tie':
            if public.get('reading_task') == 'meaning_preservation' or i in keep_on_tie:
                result.append(edit)
            continue
        replacement = ''.join(left if (base == original) != (key in flip) else right for key,left,right in parts)
        if replacement != edit['old']:
            result.append({**edit,'replacement':replacement})
    return result
