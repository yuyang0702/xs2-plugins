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


def packet(source, edits, windows, seed, patches, *, required=False):
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
    return packet, decoder


def select(public, decoder, edits, report, *, keep_on_tie=()):
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
        selected[sid] = (base, set(flip))
    result = []
    for i, edit in enumerate(edits):
        sid, original, parts = decoder[i]
        base, flip = selected[sid]
        if base == 'tie':
            if public.get('reading_task') == 'meaning_preservation' or i in keep_on_tie:
                result.append(edit)
            continue
        replacement = ''.join(left if (base == original) != (key in flip) else right for key,left,right in parts)
        if replacement != edit['old']:
            result.append({**edit,'replacement':replacement})
    return result
