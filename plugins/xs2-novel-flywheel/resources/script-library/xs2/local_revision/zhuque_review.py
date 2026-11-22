"""Map Zhuque's labels onto the exact chapter supplied to the local editor."""
import hashlib
import json
from pathlib import Path
import re
from bisect import bisect_left, bisect_right
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ENDPOINT = "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"
GUIDANCE = (
    "通读原稿，再回看 attention 中 AI 或疑似 AI 片段及其上下文。每个条目用段号和首尾短引文定位。"
    "reference_paragraphs 是同篇完全落在人工标签内的段号，可按叙述者、说话人、视角与本场用途选择，"
    "体会何时直说、略去或展开，以及人物会注意什么。保留本场事实和信息先后，自行构思，勿照搬参考中的台词、道具或句式。"
    "若人物在替作者念方案，也可试另一种完整讲法。冷叙述、长独白、技术规程都可能正合本书。"
    "具体读感支持才提出改动，标签只提示位置；可保留原稿，候选公开正文中勿提检测。"
)

REWRITE_GUIDANCE = (
    "rewrite_units 是本轮全量必改清单。通读原稿上下文，从本篇 reference_paragraphs 或 reference_excerpts "
    "为每项选择适合说话人、叙述视角和作用的已通过参考，允许多项选同一参考。逐项以自己的语言重述，保留"
    "原意、事实、数字、人物关系、笑点、因果和相邻句的衔接。片段边界可能在一句话中间。"
    "每个 id 提交一项 rewrites，填 id、reference_id、replacement。原稿未标记的文字由程序照录。"
    "不得跳项、只改标点、删空或添加点评。不规定句长、口语比例或修辞手法。"
)


def words(text):
    return ''.join(c for c in text if c.isalnum())


def rewrite_units(body, paragraphs, rows, spans):
    raw_rows = {row['id']: row['text'] for row in paragraphs(body)}
    units = []
    for row in rows:
        raw = raw_rows[row['id']]
        offsets = [m.start() for m in re.finditer(r'\r\n|.', raw, re.S)] + [len(raw)]
        for index, (a,b,label) in enumerate(spans, 1):
            first, last = max(a,row['start']), min(b,row['end'])
            if not label or first >= last:
                continue
            pos = offsets[first-row['start']]
            old = raw[pos:offsets[last-row['start']]]
            if words(old):
                # revision_patch counts overlapping matches, including one that starts
                # before the label and extends into it (e.g. the second 哈哈 in 哈哈哈).
                occurrence = 1
                match_start = raw.find(old)
                while 0 <= match_start < pos:
                    occurrence += 1
                    match_start = raw.find(old, match_start + 1)
                units.append({'id': f"{row['id']}-s{index}", 'paragraph_id': row['id'],
                              'old': old, 'occurrence': occurrence})
    return units


def compile_rewrites(report, payload):
    units = report['rewrite_units']
    items = payload.get('rewrites', [])
    by_id = {r['id']:r for r in items}
    expected = {u['id'] for u in units}
    if len(by_id) != len(items) or set(by_id) != expected or payload.get('edits') != []:
        raise ValueError('必改清单须完整且逐项提交；缺失 '+', '.join(sorted(expected-set(by_id)))+'。仅用 rewrites，edits 填空数组。')
    allowed = set(report['reference_paragraphs']) | set(report['reference_excerpts'])
    edits = []
    for u in units:
        item = by_id[u['id']]
        new = item['replacement']
        if item.get('reference_id') not in allowed:
            raise ValueError(u['id']+' 须选择本篇已通过检测的参考编号。')
        if not isinstance(new,str) or not words(new) or words(new)==words(u['old']):
            raise ValueError(u['id']+' 尚未换一种说法，请保留原意重新表达。')
        if any(words(p) in words(new) for p in u.get('lieflat_review', {}).get('mandatory_phrases', []) if words(p)):
            raise ValueError(u['id']+' 仍照录了去 AI 味检测标记的表达，请保留信息并换一种说法。')
        edits.append({'paragraph_id':u['paragraph_id'], 'old':u['old'], 'occurrence':u['occurrence'], 'replacement':new})
    return edits


def check_coverage(report, edits):
    changed = {(e['paragraph_id'],e['old'],e.get('occurrence',1)) for e in edits
               if words(e['replacement']) and words(e['replacement']) != words(e['old'])}
    missing = [u['id'] for u in report['rewrite_units'] if (u['paragraph_id'],u['old'],u['occurrence']) not in changed]
    if missing:
        raise ValueError('必改片段仍沿用原说法，须重新表达：'+', '.join(missing))


def options(root):
    path = Path(root) / 'zhuque-options.json'
    if not path.exists():
        return {'enabled': False}
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('朱雀设置须位于本书目录。')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
        raise ValueError('本书朱雀检测开关无效。')
    reference = data.get('reference_text','')
    if not isinstance(reference,str):
        raise ValueError('同文通过稿须为文本。')
    return {'enabled':True,'reference_text':reference} if data['enabled'] else {'enabled':False}


def detector_input(body):
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    start = re.match(r"^\ufeff?(?:\#[ \t]+[^\n]*\n)?\s*", normalized).end()
    return normalized,start,normalized[start:].rstrip()


def text_digest(body):
    return hashlib.sha256(detector_input(body)[2].encode()).hexdigest()


def analyze(body, paragraphs, key_path):
    normalized,start,text = detector_input(body)
    result = {"text_sha256": hashlib.sha256(text.encode()).hexdigest(), "is_merge": False}
    try:
        key = Path(key_path).read_text(encoding="utf-8-sig").strip()
        if not key or not text:
            raise ValueError("missing input")
        req = Request(ENDPOINT, data=json.dumps({"text": text, "is_merge": False}).encode(),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urlopen(req, timeout=18) as response:
            data = json.load(response)
        if data.get("status") != "success":
            raise ValueError("unsuccessful detection")
        ratios = data["labels_ratio"]
        if not all(isinstance(ratios[k], (int, float)) and 0 <= ratios[k] <= 1 for k in ("0", "1", "2")):
            raise ValueError("invalid ratios")
        spans = []
        cursor = 0
        for segment in data["segment_labels"]:
            fragment = segment["text"]
            left, right = segment["position"]
            if not fragment or segment["label"] not in (0, 1, 2):
                raise ValueError("invalid segment")
            if not (cursor <= left < right <= len(text) and text[left:right] == fragment):
                left = text.find(fragment, cursor)
                if left < 0 or text[cursor:left].strip():
                    raise ValueError("unmapped segment")
                right = left + len(fragment)
            spans.append((start + left, start + right, segment["label"]))
            cursor = right
        if not spans or text[cursor:].strip() or any(normalized[a:b].strip() for a,b in
                zip([start]+[s[1] for s in spans[:-1]], [s[0] for s in spans])):
            raise ValueError("empty detection")
        rows = paragraphs(normalized)
        attention, references = [], []
        covered = {}
        row_starts = [row["start"] for row in rows]
        row_ends = [row["end"] for row in rows]
        for left, right, label in spans:
            ids = []
            for row in rows[bisect_right(row_ends, left):bisect_left(row_starts, right)]:
                a, b = max(left,row["start"]), min(right,row["end"])
                if a >= b:
                    continue
                ids.append(row["id"])
                covered.setdefault(row["id"], []).append((a,b,label))
            if label and ids:
                fragment = normalized[left:right].strip()
                attention.append({"first": ids[0], "last": ids[-1], "label": "AI" if label == 1 else "疑似 AI",
                                  "opening": fragment[:20], "ending": fragment[-20:]})
        for row in rows:
            intervals = covered.get(row["id"], [])
            if intervals and all(label == 0 for _,_,label in intervals):
                cursor = row["start"]
                for left,right,_ in intervals:
                    if normalized[cursor:left].strip():
                        break
                    cursor = right
                else:
                    if not normalized[cursor:row["end"]].strip():
                        references.append(row["id"])
        # Offer nearby material from either side. The author can use any of the
        # fully human-labelled paragraphs when another voice is a better match.
        by_id = {row["id"]: row["text"] for row in rows}
        numbers = [int(pid[1:]) for pid in references]
        examples = {}
        for target in attention:
            first, last = int(target["first"][1:]), int(target["last"][1:])
            left, right = bisect_left(numbers, first), bisect_right(numbers, last)
            nearby = references[max(0,left-1):left] + references[right:right+1]
            target["nearby_references"] = nearby
            for pid in nearby:
                examples[pid] = by_id[pid][:120]
        if not references:
            for index,(a,b,label) in enumerate(spans,1):
                if label == 0 and words(normalized[a:b]):
                    examples[f'h{index}'] = normalized[a:b][:160]
        return {**result, "status": "success", "trial_version": 2, "labels_ratio": ratios, "segments": len(spans),
                "attention": attention, "reference_paragraphs": references, "reference_excerpts": examples,
                "rewrite_units": rewrite_units(body, paragraphs, rows, spans)}
    except HTTPError as exc:
        reason = f"HTTP {exc.code}"
    except (OSError, URLError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        reason = type(exc).__name__
    return {**result, "status": "unavailable", "reason": reason}
