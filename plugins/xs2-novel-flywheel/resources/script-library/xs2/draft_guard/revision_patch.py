"""Apply exact-source local revisions without regenerating untouched prose."""
import hashlib
import json
import re


PROSE_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def digest(text):return hashlib.sha256(text.encode()).hexdigest()


def length_edit_budget(source_word_count,bounds):
    if bounds is None:return {'source_word_count':source_word_count,'target_configured':False}
    lower,upper=bounds
    suggested=source_word_count if lower<=source_word_count<=upper else (lower+upper)//2
    return {'source_word_count':source_word_count,'target_minimum':lower,'target_maximum':upper,
        'net_change_minimum':lower-source_word_count,'net_change_maximum':upper-source_word_count,
        'suggested_result_word_count':suggested,'suggested_net_change':suggested-source_word_count}


def paragraphs(body):
    rows=[]
    for match in re.finditer(r'\S(?:.*?\S)?(?=\r?\n\s*\n|\s*\Z)',body,re.S):
        rows.append({'id':f'p{len(rows)+1:04d}','text':match[0],'sha256':digest(match[0]),'start':match.start(),'end':match.end()})
    return rows


def exact_evidence(source,quotes):
    error='重规划冲突缺少冻结原文和逐字证据'
    if not isinstance(quotes,list) or not quotes:raise ValueError(error)
    rows={row['id']:row for row in paragraphs(source)}
    anchored=re.compile(r'(?P<first>p[0-9]{4,})(?:[—–-](?P<last>p[0-9]{4,}))?(?:（[^\r\n）]*）)?[：:]\r?\n(?P<quote>.+)',re.S)
    result=[]
    for raw in quotes:
        if not isinstance(raw,str) or not raw.strip():raise ValueError(error)
        if raw in source:
            result.append(raw);continue
        label=anchored.fullmatch(raw)
        if label:
            first=rows.get(label['first']);last=rows.get(label['last'] or label['first'])
            if not first or not last or first['start']>last['start']:raise ValueError(error)
            passage=source[first['start']:last['end']]
            if passage.replace('\r\n','\n')!=label['quote'].replace('\r\n','\n'):raise ValueError(error)
        else:
            pattern=r'\r?\n'.join(re.escape(line) for line in raw.replace('\r\n','\n').split('\n'))
            match=re.search(pattern,source)
            if not match:raise ValueError(error)
            passage=match[0]
        result.append(passage)
    return result


PRESERVATION_GUIDANCE=(
    '逐组对读冻结原文和应用全部补丁后的候选稿。先说这组改动改善什么，再核对该组是否伤到已有的接话、'
    '人物声音、动作因果、有效意象或收束。change_reviews 每项按所属组判断 preservation。'
    'preserved 或 lost 须用 source_excerpt 逐字引冻结原文中有效的部分，并用 candidate_excerpt 引候选中'
    '同一作用的位置。完全删失且无承接才可留空。改写或迁移后的同一作用可以保留。'
    '只有本组没有触及原有有效表达时才填 not_applicable，两个引文字段留空并说明原因。'
    '一组补丁即使解决了原问题，只要损失已有作用，仍须在 preservation 标 lost。'
)

GROWTH_GUIDANCE = (
    '需要补篇幅时，先选一个确实缺了反应、决定、行动后果或必要信息的位置。先看前后已让读者知道什么，'
    '再用新的现场动作、接话或可见后果补足缺口。已有物件变化、人物态度或动作已能传达的意思，'
    '别再用旁白换一种说法。有效的短接话要留。不同作用的改动尽量各用一个小补丁，必须联动的沿用同一个 group_id。'
    '字数仍不足且没有可写实的内容时，按现有篇幅冲突流程处理。'
)

GROWTH_REVIEW_GUIDANCE = (
    '先按整组给 change_reviews，再对 growth_edit_indices 中每项补丁填 added_text_reviews。'
    '逐字摘取值得保留的新增内容放进 useful，可为空。即使整组 improved，也逐句检查新增内容是否又解释了前面'
    '的行动、景物或意思。每处多余内容单独写进 repetitions，previous 引当前候选中更早的依据，'
    'quote 只引本项补丁新增的多余句或分句，reason 说明两处具体重复了什么。'
    '推进决定、改变下一句对白或行动的短句可以有用。判断看读者得到的内容和后续反应。'
    '没有这类问题就填 repetitions=[]。有待复核的增写问题，按原编号在 issue_outcomes 中逐项填 resolved 或 remaining，'
    '用当前候选受影响位置的逐字引文说明多余内容已处理且有用内容仍在。'
)


def growth_indices(edits, *, include_mixed=False):
    def size(value):
        return sum(character.isalnum() for character in value)

    def mixed_replacement(edit):
        # A cut can add a whole thought while removing more text elsewhere.
        # Use the boundaries to request semantic review, not to judge its effect.
        def clauses(text):
            return [part.strip(' \t“”\"‘’') for part in re.split(r'[。！？!?；;\r\n]+', text) if size(part)]

        after = clauses(edit['replacement'])
        if len(after) < 2:
            return False
        before = clauses(edit['old'])
        return any(after.count(part) > before.count(part)
                   and edit['replacement'].count(part) > edit['old'].count(part) for part in set(after))

    return [index for index, edit in enumerate(edits)
            if size(edit['replacement']) > size(edit['old']) or (include_mixed and mixed_replacement(edit))]


def _scoped_paragraph(source_row, edits):
    local = [{**edit, 'paragraph_id': 'p0001'} for edit in edits if edit['paragraph_id'] == source_row['id']]
    text = source_row['text']
    return _splice(text, local, _patch_spans(text, local))


def _frozen_offset(spans, edits, offset):
    delta = 0
    for start, end, index in spans:
        left = start + delta
        right = left + len(edits[index]['replacement'])
        if offset < left:
            break
        if offset < right:
            return start
        delta += right - left - (end - start)
    return offset - delta


def bind_scene_goal(source, edits, candidate, issue, offset, *, assign_id=False):
    """Bind an independently evidenced line to the immutable patch paragraph."""
    focus = issue['scene_focus']
    spans = sorted(_patch_spans(source, edits))
    reconstructed = _splice(source, edits, spans)
    if (reconstructed != candidate and reconstructed.strip() != candidate) or not candidate.startswith(focus['quote'],offset):
        raise ValueError('整场表达问题与当前补丁候选不一致')
    padding = len(reconstructed)-len(reconstructed.lstrip()) if reconstructed != candidate else 0
    original = _frozen_offset(spans, edits, offset+padding)
    rows = paragraphs(source)
    row = next((row for row in rows if row['start'] <= original < row['end']), None)
    if row is None:
        raise ValueError('整场表达问题无法定位到冻结段落')
    before = _scoped_paragraph(row, edits)
    supporting = {}
    for quote in issue['excerpts']:
        if focus['quote'] in quote:
            continue
        occurrences = list(re.finditer(re.escape(quote), candidate))
        if occurrences:
            match = min(occurrences, key=lambda part: abs(part.start()-offset))
            position = _frozen_offset(spans, edits, match.start()+padding)
            for region in rows:
                if region['start'] <= position < region['end'] and region['id'] != row['id']:
                    supporting[region['id']] = _scoped_paragraph(region, edits)
                    break
    anchor = {'paragraph_id':row['id'], 'before':before, 'supporting':supporting}
    preserve = {quote: candidate.count(quote) for quote in focus.get('preserve', [])}
    goal = {**issue, 'paragraph_id':row['id'], 'scene_anchor':anchor, 'scene_preserve_counts':preserve}
    if assign_id:
        identity = json.dumps([digest(source), row['id'], focus['quote'], focus.get('occurrence',1)],ensure_ascii=False)
        goal['id'] = 'scene-line-'+digest(identity)[:16]
    return goal


def _adjacent_scene_regions(rows, paragraph_id, edits):
    index = int(paragraph_id[1:])
    regions = []
    for direction in (-1,1):
        number = index + direction
        while (row := rows.get(f'p{number:04}')) is not None:
            region = _scoped_paragraph(row, edits)
            if region.strip():
                regions.append(region)
                break
            number += direction
    return regions


def scene_outcome_problem(source, edits, candidate, goal, outcome):
    """Check the reviewed location and explicit keep quotes, leaving style to the reviewer."""
    key = goal['id']
    quotes = outcome.get('excerpts')
    if (outcome.get('id') != key or not _text(outcome.get('reason')) or not isinstance(quotes, list)
            or not quotes or any(not _text(quote) or quote not in candidate for quote in quotes)):
        raise ValueError('整场表达返修缺少原编号或当前候选的逐字证据')
    status = outcome.get('status')
    if status not in ('resolved','remaining','not_applicable'):
        raise ValueError('整场表达返修结论无效')
    if status == 'remaining':
        return key+' 仍需复核：'+outcome['reason']
    if any(candidate.count(quote) < count for quote, count in goal['scene_preserve_counts'].items()):
        return key+' 缺少明确要求保留的接话或指令。'
    rows = {row['id']: row for row in paragraphs(source)}
    anchor = goal['scene_anchor']
    paragraph_id = anchor['paragraph_id']
    scope = _scoped_paragraph(rows[paragraph_id], edits)
    target = goal['scene_focus']['quote']
    target_in_proof = any(target in quote and quote in scope for quote in quotes)
    if status == 'not_applicable':
        regions = [scope, *_adjacent_scene_regions(rows, paragraph_id, edits)]
        regions += [_scoped_paragraph(rows[key], edits) for key in anchor.get('supporting', {})]
        if target_in_proof and any(quote not in target and target not in quote and quote in region
                                   for quote in quotes for region in regions):
            return ''
        raise ValueError('保留原句的复核须引原句和另一处当场依据')
    if scope == anchor['before']:
        if target_in_proof:
            for supporting_id, before in anchor.get('supporting', {}).items():
                current = _scoped_paragraph(rows[supporting_id], edits)
                if any(quote in current and quote not in before for quote in quotes):
                    return ''
        return key+' 原定位未处理。'
    if scope.count(target) >= anchor['before'].count(target) and not (
            target_in_proof and any(quote in scope and quote not in anchor['before'] for quote in quotes)):
        return key+' 原句仍在，须举证它在改过的上下文中有现场作用。'
    if scope.strip():
        regions = [scope]
    else:
        regions = _adjacent_scene_regions(rows, paragraph_id, edits)
    if not any(region.strip() and (quote in region or region in quote) for quote in quotes for region in regions):
        raise ValueError('整场表达返修须引用原编号位置或删句后的相邻候选原文')
    return ''


def review_additions(source, edits, reviews, *, include_mixed=False):
    """Turn separately grounded repetition findings into stable repair goals."""
    expected = set(growth_indices(edits, include_mixed=include_mixed))
    if reviews is None and not expected:
        return []
    if not isinstance(reviews, list) or any(not isinstance(row, dict) for row in reviews):
        raise ValueError('增写复查须逐项提交 added_text_reviews')
    indices = [row.get('edit_index') for row in reviews]
    if any(type(index) is not int for index in indices) or set(indices) != expected or len(indices) != len(expected):
        raise ValueError('增写复查编号须覆盖 growth_edit_indices 中的每项补丁')
    if not reviews:
        return []
    spans = _patch_spans(source, edits)
    by_index = {}
    delta = 0
    for start, end, index in sorted(spans):
        by_index[index] = start + delta
        delta += len(edits[index]['replacement']) - (end - start)
    source_digest = digest(source)
    candidate = apply_patches(source, {'source_sha256': source_digest, 'edits': edits})
    rows = {row['id']: row for row in paragraphs(source)}
    issues = {}
    for row in reviews:
        index = row['edit_index']
        edit = edits[index]
        after = edit['replacement']
        useful, repetitions = row.get('useful'), row.get('repetitions')
        if (not isinstance(useful, list) or not isinstance(repetitions, list)
                or any(not _text(quote) or after.count(quote) <= edit['old'].count(quote) for quote in useful)):
            raise ValueError('增写的有效部分须逐字引新增文字')
        for repetition in repetitions:
            if not isinstance(repetition, dict):
                raise ValueError('增写复述须逐字引用前文和新增句')
            previous, quote, reason = (repetition.get(key) for key in ('previous', 'quote', 'reason'))
            if (not all(map(_text, (previous, quote, reason)))
                    or after.count(quote) <= edit['old'].count(quote)
                    or previous not in candidate[:by_index[index] + after.rfind(quote)]
                    or any(quote in keep or keep in quote for keep in useful)):
                raise ValueError('增写复述须逐字引用较早依据和新增的多余句，并与有效新增内容分开')
            paragraph_id = edit['paragraph_id']
            scope = _scoped_paragraph(rows[paragraph_id], edits)
            if scope.count(quote) <= rows[paragraph_id]['text'].count(quote):
                raise ValueError('增写复述须逐字定位到本段的新增文字')
            anchor = json.dumps([source_digest, paragraph_id, quote], ensure_ascii=False)
            issue_id = 'addition-' + digest(anchor)[:16]
            issues[issue_id] = {
                'id': issue_id, 'category': 'post_action_restatement', 'paragraph_id': paragraph_id,
                'source': 'added_text_review', 'edit_index': index, 'excerpts': [previous, quote],
                'reason': reason, 'preserve': list(dict.fromkeys(useful)),
                'original_count': rows[paragraph_id]['text'].count(quote),
                'goal': '处理第二处引文的重复解释，保留第一处的表达作用和本项列出的有效增写。'
            }
    return list(issues.values())


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def merge_addition_issues(prior, findings):
    retained = {row['id']: row for row in prior}
    for row in findings:
        retained.setdefault(row['id'], row)
    return list(retained.values())


def review_addition_outcomes(source, edits, issues, outcomes, *, candidate=None):
    """Check the original ID, changed text and retained useful text on retry."""
    if not issues and outcomes is None:
        return []
    by_id = {issue['id']: issue for issue in issues}
    if not isinstance(outcomes, list) or any(not isinstance(row, dict) or not _text(row.get('id')) for row in outcomes):
        raise ValueError('增写返修须按原编号逐条复核')
    if {row['id'] for row in outcomes} != set(by_id) or len(outcomes) != len(by_id):
        raise ValueError('增写返修须按原编号逐条复核')
    if candidate is None:
        candidate = apply_patches(source, {'source_sha256': digest(source), 'edits': edits})
    rows = {row['id']: row for row in paragraphs(source)}
    remaining = []
    for row in outcomes:
        issue = by_id[row['id']]
        scope = _scoped_paragraph(rows[issue['paragraph_id']], edits)
        quotes = row.get('excerpts')
        if (row.get('status') not in ('resolved', 'remaining') or not _text(row.get('reason'))
                or not isinstance(quotes, list) or not quotes
                or any(not _text(quote) or quote not in candidate for quote in quotes)
                or not any(quote in scope for quote in quotes)):
            raise ValueError('增写返修的原编号缺少当前受影响段落的逐字复核依据')
        if (row['status'] == 'remaining' or scope.count(issue['excerpts'][1]) > issue['original_count']
                or any(quote not in scope for quote in issue['preserve'])):
            remaining.append({**issue, 'recheck_reason': row['reason']})
    return remaining


def _preservation_lost(review, source, candidate):
    if not isinstance(review,dict):
        raise ValueError('改动复核缺少有效表达的保留判断')
    status=review.get('status')
    before,after,reason=(review.get(key) for key in ('source_excerpt','candidate_excerpt','reason'))
    if (status not in ('preserved','lost','not_applicable')
            or not isinstance(reason,str) or not reason.strip()
            or not isinstance(before,str) or not isinstance(after,str)
            or (status=='not_applicable' and (before or after))
            or (status!='not_applicable' and (not before.strip() or before not in source))
            or (status=='preserved' and not after.strip())
            or (after and (not after.strip() or after not in candidate))):
        raise ValueError('改动复核缺少冻稿与当前候选中的有效表达保留依据')
    return status=='lost'


def review_changes(edits, changes, *, source=None, candidate=None, accept_equivalent=()):
    if not isinstance(changes,list) or len(changes)!=len(edits):
        raise ValueError('每项局部改动都须独立核对净效果')
    seen=set();issues=[]
    for row in changes:
        index=row.get('edit_index') if isinstance(row,dict) else None
        if type(index) is not int or not 0<=index<len(edits) or index in seen:
            raise ValueError('改动复核编号缺失或重复')
        seen.add(index)
        edit=edits[index]
        before,after=row.get('before_excerpt'),row.get('after_excerpt')
        if (row.get('effect') not in ('improved','equivalent','regressed')
                or not isinstance(row.get('reason'),str) or not row['reason'].strip()
                or not isinstance(before,str) or not before or before not in edit['old']
                or not isinstance(after,str)
                or (edit['replacement'] and (not after or after not in edit['replacement']))
                or (not edit['replacement'] and after)):
            raise ValueError('改动净效果缺少原句与替换文本依据')
        if source is not None and 'preservation' in row and _preservation_lost(row['preservation'],source,candidate):
            review=row['preservation']
            issues.append({**row,'reason':review['reason'],'before_excerpt':review['source_excerpt']})
        elif row['effect']!='improved' and not (row['effect']=='equivalent' and index in accept_equivalent):
            issues.append(row)
    return issues


def _patch_spans(source, edits):
    if not isinstance(edits,list):raise ValueError('局部修订edits须为数组；无须修改可为空')
    rows={r['id']:r for r in paragraphs(source)};spans=[]
    for index,edit in enumerate(edits):
        if (not isinstance(edit,dict) or not {'paragraph_id','old','occurrence','replacement'}<=set(edit)
            or set(edit)-{'paragraph_id','old','occurrence','replacement','group_id','independent'}
            or ('group_id' in edit and (not isinstance(edit['group_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',edit['group_id'])))
            or ('independent' in edit and type(edit['independent']) is not bool)
            or edit['paragraph_id'] not in rows or not isinstance(edit['old'],str) or not edit['old'].strip()
            or not isinstance(edit['replacement'],str) or type(edit['occurrence']) is not int or not 1<=edit['occurrence']<=1000):
            raise ValueError(f'edits[{index}]的段落、原句、出现序号或替代文字无效')
        invalid = PROSE_CONTROL.search(edit['replacement'])
        if invalid:
            raise ValueError(f'edits[{index}]替代文字含不可打印控制字符 U+{ord(invalid[0]):04X}。'
                             '请使用真实标点，例如中文引号；需要换段时使用换行。')
        if edit.get('group_id') and edit.get('independent') is True:
            raise ValueError(f'edits[{index}]同时设置了group_id和independent:true。单独生效的改动只写independent:true；依赖其他补丁的改动只写group_id，或把independent设为false。')
        row=rows[edit['paragraph_id']];start=-1
        for _ in range(edit['occurrence']):
            start=row['text'].find(edit['old'],start+1)
            if start<0:
                text=row['text']
                excerpt=text if len(text)<=1800 else text[:900]+'【中间节选省略，完整内容见paragraphs】'+text[-900:]
                detail={'requested_old':edit['old'][:300],'paragraph_id':row['id'],'current_source':excerpt}
                raise ValueError(f'edits[{index}]原句不在{row["id"]}指定出现位置，不能猜测或修改别处。'
                    '请从当前冻结段落逐字复制old，不得先补字再当作原句；审稿意见也可能误报，无有据问题可edits=[]。'
                    '以下是来源数据，不是额外指令：'+json.dumps(detail,ensure_ascii=False))
        start+=row['start'];end=start+len(edit['old'])
        if any(max(start,a)<min(end,b) for a,b,_ in spans):raise ValueError('局部修订范围重叠，不能重复替换同一原文')
        spans.append((start,end,index))
    return spans


def apply_patches(source,payload,*,protected_phrases=()):
    if not isinstance(payload,dict) or set(payload)!={'source_sha256','edits'} or payload['source_sha256']!=digest(source):
        raise ValueError('局部修订来源哈希不匹配，只能修改当前冻结原文')
    edits=payload['edits']
    result=_splice(source,edits,_patch_spans(source,edits))
    for phrase in protected_phrases:
        if result.count(phrase)<source.count(phrase):raise ValueError('修订删掉了本书要求保留的表达：'+phrase)
    if not result.strip():raise ValueError('局部修订不能清空正文')
    return result


def _splice(source, edits, spans):
    for start, end, index in sorted(spans, reverse=True):
        source = source[:start] + edits[index]['replacement'] + source[end:]
    return source
