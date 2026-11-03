"""Plugin-owned deterministic manuscript length evidence and correction budgets."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

LENGTH_REPAIR_STRATEGY = 'fragment-v6'

METRIC = '正文实字：中文按汉字、英文和数字按词；标题、标点、空白不计'
_HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134a]')
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_TITLE = re.compile(r'^第[一二三四五六七八九十百千零〇两0-9]+[章回节卷](?:\s|[·：:、.]).*$|^第[一二三四五六七八九十百千零〇两0-9]+[章回节卷]$')


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('字数检查路径超出本书工作区')
    return path


def chapter_number(chapter):
    if not re.fullmatch(r'[0-9]{4}', str(chapter)) or str(chapter) == '0000':
        raise ValueError('字数检查需要四位有效章节号')
    return str(chapter)


def count_prose(text):
    lines, first = [], True
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if re.match(r'^#{1,6}\s', value) or (first and _TITLE.fullmatch(value)):
            continue
        first = False
        lines.append(value)
    prose = '\n'.join(lines)
    return len(_HAN.findall(prose)) + len(_WORD.findall(prose))


def target_range(target):
    value = str(target or '').strip()
    if not value:
        return None
    value = re.sub(r'^(?:约|大约)\s*', '', value)
    value = re.sub(r'\s*(?:字|实字|汉字)$', '', value)
    match = re.fullmatch(r'(\d+)\s*(?:[-—–~～至]\s*(\d+))?', value)
    if not match:
        raise ValueError('目标字数须为数字或数字范围，例如5000或4800-5200')
    lower, upper = int(match[1]), int(match[2] or match[1])
    if not 1 <= lower <= upper <= 200000:
        raise ValueError('目标字数范围无效')
    if not match[2]:
        lower, upper = max(1, int(lower * .96)), max(1, int(upper * 1.04))
    return lower, upper


def resolve_target(root, target):
    if str(target or '').strip():
        return target_range(target)
    project = safe_path(root, '.novel-project.json')
    if project.is_file():
        data = json.loads(project.read_text(encoding='utf-8-sig'))
        return target_range(data.get('values', {}).get('target_word_count', ''))
    return None


def assess(root, chapter, target=''):
    chapter = chapter_number(chapter)
    body = safe_path(root, f'story/{chapter}/chapter.md')
    if not body.is_file():
        raise ValueError('缺少本章正文，无法核对实际字数')
    raw = body.read_bytes()
    actual = count_prose(raw.decode('utf-8-sig'))
    bounds = resolve_target(root, target)
    result = {'chapter_number': chapter, 'metric': METRIC, 'actual': actual,
              'body_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'unconfigured'}
    if bounds is not None:
        lower, upper = bounds
        result.update(lower=lower, upper=upper, add_at_least=max(0, lower - actual),
                      cut_at_least=max(0, actual - upper),
                      status='short' if actual < lower else 'long' if actual > upper else 'pass')
    return result


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.length-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def guidance(result):
    lines = ['# 本章字数实测与改写预算', '', result['metric'],
             f"当前正文实测 {result['actual']} 实字；正文指纹 {result['body_sha256']}。"]
    if result['status'] == 'unconfigured':
        lines.append('本书未配置明确字数，沿用现有篇幅，不新加限制。')
    else:
        lines.append(f"最终范围 {result['lower']}—{result['upper']} 实字，建议靠近 {(result['lower'] + result['upper']) // 2} 实字。")
        if result['status'] == 'short':
            lines.append(f"当前不足，至少净增加 {result['add_at_least']} 实字；若删掉重复内容，还须补足相同字数。不能继续把完整正文压缩成梗概。")
        elif result['status'] == 'long':
            lines.append(f"当前超出，至少净减少 {result['cut_at_least']} 实字；压缩重复解释和重复手续，保留承重场景及结局。")
        else:
            lines.append('篇幅已在范围内；润色保留必要场景，不大幅压缩或膨胀。')
        lines.extend(['增加内容应展开已有场景的交涉往返、可观察行动、具体阻碍、人物反应和选择后果；不得凭空增加关键事实、证人或支线灌水。',
                      '人物事实与前后因果优先，原有作者返修意见仍须落实。输出完整正文，不能输出改写计划或字数声明。',
                      '标点、空白、标题和声称“已有五千字”都不能补足正文实字，后续由插件重新计数；不得用复制段落凑数。'])
    return '\n'.join(lines) + '\n'


def prepare_guidance(root, chapter, target=''):
    result = assess(root, chapter, target)
    relative = f'cache/quality/{chapter}/length_context.md'
    atomic_text(safe_path(root, relative), guidance(result))
    atomic_text(safe_path(root, f'quality/length/{chapter}.json'), json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return relative


def gate_report(root, chapter, target, report):
    result = assess(root, chapter, target)
    if report.get('body_sha256') and report['body_sha256'] != result['body_sha256']:
        raise ValueError('读者报告绑定的正文已变化，请重新评估')
    gated = copy.deepcopy(report)
    gated['length_check'] = result
    if result['status'] in {'short', 'long'}:
        if gated.get('verdict') != 'reject':
            gated['verdict'] = 'revise'
        issue = {'code': 'length_out_of_range', 'location': '整篇正文实测字数', 'priority': 'high',
                 'impact': f"实测 {result['actual']} 实字，目标 {result['lower']}—{result['upper']}；模型通过判断不能替代实际计数。",
                 'goal': guidance(result)}
        gated['issues'] = [item for item in gated.get('issues', []) if item.get('code') != 'length_out_of_range'] + [issue]
    return gated


def original_feedback(root, state):
    """Unwrap only our unchanged feedback, never an author-edited document."""
    prior = str(state.get('values', {}).get('author_feedback_file') or '').strip()
    managed = state.get('lengthRepairFeedback', {})
    number = chapter_number(str(state.get('values', {}).get('chapter_number', '0001')).zfill(4))
    if (isinstance(managed, dict) and managed.get('chapter_number') == number
            and managed.get('path') == prior):
        previous = safe_path(root, prior)
        if previous.is_file() and hashlib.sha256(previous.read_bytes()).hexdigest() == managed.get('sha256'):
            source = managed.get('source_path')
            if not isinstance(source, str):
                raise ValueError('字数返修原始意见记录无效，不能忽略作者意见')
            prior = source
    if prior and not safe_path(root, prior).is_file():
        raise ValueError('已有返修意见缺失，不能在字数校正时忽略')
    return prior


def correction_feedback(root, state, result):
    number = chapter_number(result['chapter_number'])
    count = int(state.get('lengthRepairCount') or 0) + 1
    cycle = max(0, int(state.get('readerRepairCount') or 0))
    folder = f"quality/length-repairs/{number}/cycle-{cycle:02d}/{LENGTH_REPAIR_STRATEGY}/attempt-{count:02d}-{result['body_sha256'][:12]}"
    if state.get('writerModel') or 'lengthRepairModel' in state:
        profile = hashlib.sha256(str(state.get('writerModel') or '').encode('utf-8')).hexdigest()[:12]
        folder += '/model-' + profile
    body = safe_path(root, f'story/{number}/chapter.md')
    if hashlib.sha256(body.read_bytes()).hexdigest() != result['body_sha256']:
        raise ValueError('字数检查后正文已变化，请重新核对')
    before = safe_path(root, folder + '/before.md')
    if before.exists() and before.read_bytes() != body.read_bytes():
        raise ValueError('字数校正备份已存在且内容不同，已保留')
    before.parent.mkdir(parents=True, exist_ok=True)
    if not before.exists():
        before.write_bytes(body.read_bytes())
    text = guidance(result)
    prior = original_feedback(root, state)
    source_bytes = b''
    if prior:
        prior_file = safe_path(root, prior)
        if not prior_file.is_file():
            raise ValueError('已有返修意见缺失，不能在字数校正时忽略')
        source_bytes = prior_file.read_bytes()
        text += '\n## 继续遵守的既有返修意见\n\n' + source_bytes.decode('utf-8-sig')
    relative = folder + '/instructions.md'
    atomic_text(safe_path(root, relative), text)
    evidence = {**result, 'feedback_source_file': prior}
    atomic_text(safe_path(root, folder + '/evidence.json'), json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    return {'path': relative, 'source_path': prior, 'chapter_number': number, 'strategy': LENGTH_REPAIR_STRATEGY,
            'source_sha256': hashlib.sha256(source_bytes).hexdigest() if prior else '',
            'sha256': hashlib.sha256(safe_path(root, relative).read_bytes()).hexdigest()}



def prepare_execution(root, chapter, target='', scope='content', *, policy_runtime='', task_id=None):
    """Freeze the current body and both feedback sources before the final editor."""
    relative = prepare_guidance(root, chapter, target)
    outputs = {'length_context_file': relative, 'polish_pass': 'content', 'length_execution_context': '',
               'length_expected_body_sha': '', 'length_commit_guard': '', 'length_commit_guard_sha': '', 'length_execution_system': ''}
    if scope != 'length_only':
        return outputs
    state_file = safe_path(root, '.novel-project.json')
    if not state_file.is_file():
        return outputs
    state = json.loads(state_file.read_text(encoding='utf-8-sig'))
    number = chapter_number(str(state.get('values', {}).get('chapter_number', '0001')).zfill(4))
    receipt = state.get('lengthRepairFeedback') or {}
    prior = str(state.get('values', {}).get('author_feedback_file') or '').strip()
    if (number != chapter or not isinstance(receipt, dict) or not prior
            or receipt.get('chapter_number') != chapter or receipt.get('path') != prior):
        return outputs
    feedback = safe_path(root, prior)
    if not feedback.is_file():
        raise ValueError('字数返修意见缺失，不能继续旧底稿')
    managed_same = hashlib.sha256(feedback.read_bytes()).hexdigest() == receipt.get('sha256')
    source = receipt.get('source_path')
    if not isinstance(source, str):
        raise ValueError('字数返修原始意见记录无效')
    source_file = safe_path(root, source) if source else None
    if source_file is not None and not source_file.is_file():
        raise ValueError('原作者意见缺失，不能继续旧底稿')
    source_sha = hashlib.sha256(source_file.read_bytes()).hexdigest() if source_file else ''
    source_same = 'source_sha256' in receipt and source_sha == receipt['source_sha256']
    if not managed_same and not source_same and source:
        raise ValueError('作者同时修改了原始意见与字数反馈，请先确认合并；没有忽略任何一份意见')
    if not managed_same:
        return outputs  # The task already points at the full author-edited managed file.
    if not source_same:
        outputs['author_feedback_file'] = source or prior
        return outputs
    result = assess(root, chapter, target)
    body_path = f'story/{chapter}/chapter.md'
    body = safe_path(root, body_path).read_bytes()
    if hashlib.sha256(body).hexdigest() != result['body_sha256']:
        raise ValueError('字数定向返修前正文已变化，请重新核对')
    binding = {'chapter_number': chapter, 'author_feedback_file': prior, 'receipt': receipt,
               'narrative_pov': state.get('values', {}).get('narrative_pov', 'third_person')}
    story_context_path = 'cache/story-support/context.md'
    identity_data = binding
    if policy_runtime:
        import importlib.util
        entry = Path(__file__).resolve().parents[1] / "prose_policy/prose_policy.py"
        spec = importlib.util.spec_from_file_location("xs2_length_prose_policy", entry)
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        story_context_path = policy.runtime_common(root, policy_runtime, task_id=task_id)
        identity_data = {**binding, "effective_context": story_context_path}
    identity = hashlib.sha256(json.dumps(identity_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    folder = f"cache/quality/{chapter}/focused/{result['body_sha256'][:12]}-{identity[:12]}"
    base = folder + '/length_base.json'
    context = folder + '/execution.md'
    guard_path = folder + '/commit_guard.json'
    atomic_text(safe_path(root, base), json.dumps({'body': body.decode('utf-8-sig')}, ensure_ascii=False, indent=2) + '\n')
    previous_path = safe_path(root, f'quality/length/{chapter}-last-attempt.json')
    previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.is_file() else {}
    previous_range = previous.get('expanded_span_range') if previous.get('accepted') and previous.get('body_sha256') == result['body_sha256'] else None
    fragment = fragment_anchor(body, result, previous_range)
    system_path = folder + '/fragment_system.md'
    system = ('本次是插件控制的局部片段字数修复。你只返回JSON对象，body字段只能包含指定原段落的扩写或精简替换文本，允许保留选定原段原句。'
              '绝不能返回整章、选定段落以外的旧正文、插入锚或计划。整章由插件按冻结锚合成。遵守既定人物事实、视角、语言与原作者约束。'
              '此局部输出契约优先于通常完整正文输出要求。')
    atomic_text(safe_path(root, system_path), system)
    instruction = fragment_instructions(body, fragment, result)
    # This is the focused writer's entire user message, not an appendix to the
    # normal full-chapter rewrite request. All sources below are frozen below.
    author = safe_path(root, source).read_text(encoding='utf-8-sig') if source else ''
    delivery = '执行要求：按上述意见修改完整正文，不以计划代替正文；维护既定事实、人物、视角与本书风格。只处理本章，短篇收束全文，长篇普通章不提前完结全书。读者复评要检查修改是否落实，独立判断，不因采用方案而默认通过。'
    author = '\n'.join(line for line in author.splitlines() if line.strip() != delivery)
    shared_file = safe_path(root, story_context_path)
    shared_bytes = shared_file.read_bytes() if shared_file.is_file() else None
    shared = shared_bytes.decode('utf-8-sig') if shared_bytes is not None else ''
    instruction += ('\n【当前正文；仅供定位与查重，不得交付整章】\n' + body.decode('utf-8-sig')
                    + '\n【原始作者约束；本次只在局部片段内落实】\n' + author
                    + '\n【叙事视角】\n' + str(binding['narrative_pov'])
                    + '\n【已确认背景；计划不等于已发生或人物已知】\n' + focused_shared_context(shared))
    previous_attempt = safe_path(root, f'quality/length/{chapter}-last-attempt.json')
    if previous_attempt.is_file():
        previous_result = json.loads(previous_attempt.read_text(encoding='utf-8'))
        if previous_result.get('body_sha256') == result['body_sha256'] and previous_result.get('rejection_reason'):
            instruction += '\n上次片段未采纳原因：' + previous_result['rejection_reason'] + '\n'
    atomic_text(safe_path(root, context), instruction)
    outputs.update(polish_pass='length_only', pl_body_file=base, critique_file='', reader_report_file='',
                   length_execution_context=context, length_execution_system=system_path,
                   length_expected_body_sha=result['body_sha256'])
    files = {body_path: result['body_sha256'], prior: receipt['sha256'],
             base: hashlib.sha256(safe_path(root, base).read_bytes()).hexdigest(),
             context: hashlib.sha256(safe_path(root, context).read_bytes()).hexdigest(),
             system_path: hashlib.sha256(safe_path(root, system_path).read_bytes()).hexdigest()}
    if source:
        files[source] = receipt['source_sha256']
    if shared_bytes is not None:
        files[story_context_path] = hashlib.sha256(shared_bytes).hexdigest()
    else:
        story_context_path = ''
    guard = {'body_path': body_path, 'story_context_path': story_context_path, 'body_sha256': result['body_sha256'], 'files': files,
             'state_binding': binding, 'outputs': outputs, 'fragment': fragment, 'assessment': result, 'semantic_review_required': True}
    atomic_text(safe_path(root, guard_path), json.dumps(guard, ensure_ascii=False, indent=2) + '\n')
    outputs['length_commit_guard'] = guard_path
    outputs['length_commit_guard_sha'] = hashlib.sha256(safe_path(root, guard_path).read_bytes()).hexdigest()
    return outputs


def confirm_execution(root, chapter, expected_sha, guard_path, guard_sha, accepted_body_sha=None):
    """Check the existing snapshot; never replace it with a newly edited base."""
    if not guard_path or not expected_sha or not guard_sha:
        raise ValueError('字数定向快照缺少校验凭证，请重新发起返修')
    file = safe_path(root, guard_path)
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != guard_sha:
        raise ValueError('字数定向快照已变化，未执行旧底稿')
    guard = json.loads(file.read_text(encoding='utf-8'))
    if guard.get('body_sha256') != expected_sha or guard.get('body_path') != f'story/{chapter}/chapter.md':
        raise ValueError('字数定向正文凭证不匹配')
    for relative, digest in guard['files'].items():
        bound = safe_path(root, relative)
        if relative == guard['body_path'] and accepted_body_sha:
            digest = accepted_body_sha
        if not bound.is_file() or hashlib.sha256(bound.read_bytes()).hexdigest() != digest:
            raise ValueError('正文或作者意见在字数定向准备后已变化，请重新发起返修')
    state = json.loads(safe_path(root, '.novel-project.json').read_text(encoding='utf-8-sig'))
    current = {'chapter_number': str(state.get('values', {}).get('chapter_number', '0001')).zfill(4),
               'author_feedback_file': str(state.get('values', {}).get('author_feedback_file') or '').strip(),
               'receipt': state.get('lengthRepairFeedback') or {}}
    if 'narrative_pov' in guard['state_binding']:
        current['narrative_pov'] = state.get('values', {}).get('narrative_pov', 'third_person')
    if current != guard['state_binding']:
        raise ValueError('作者反馈选择在字数定向准备后已变化，请重新发起返修')
    return {**guard['outputs'], 'length_commit_guard': guard_path, 'length_commit_guard_sha': guard_sha}



def fragment_anchor(raw, result, exclude_range=None):
    text = raw.decode('utf-8')
    paragraphs = [(m.start(1), m.end(1), m.end(), m.group(1))
                  for m in re.finditer(r'([\s\S]+?)(?:\r?\n[ \t]*\r?\n|\Z)', text) if m.group(1).strip()]
    if result['status'] == 'long':
        prose = [item for item in paragraphs if count_prose(item[3].lstrip('\ufeff')) > 0]
        if not prose:
            raise ValueError('没有可安全局部替换的正文段落')
        start, end, _, paragraph = max(prose, key=lambda item: count_prose(item[3]))
        if start == 0 and text.startswith('\ufeff'):
            start = 1
            paragraph = text[start:end]
        return {'kind': 'replace', 'start': len(text[:start].encode('utf-8')),
                'end': len(text[:end].encode('utf-8')), 'old_span_sha256': hashlib.sha256(paragraph.encode('utf-8')).hexdigest()}
    if result.get('lower', 0)-result.get('actual', 0) > 400:
        return expansion_window(raw, result, paragraphs, exclude_range)
    prose = [item for item in paragraphs if count_prose(item[3].lstrip('\ufeff')) > 0]
    if not prose:
        raise ValueError('没有可安全扩写的原正文段落')
    bounded = [item for item in prose if count_prose(item[3]) <= 400
               and not (item[0] <= (1 if text.startswith('\ufeff') else 0) and item[1] == len(text))]
    if not bounded:
        bounded = [(match.start(), match.end(), match.end(), match.group())
                   for match in re.finditer(r'[^。！？!?\r\n]+[。！？!?][”"’]*', text)
                   if 0 < count_prose(match.group()) <= 400 and match.end()-match.start() < len(text)]
    if not bounded:
        raise ValueError('没有400实字内的安全局部原段或完整句子，未改写整章')
    def outside_previous(item):
        start = len(text[:item[0]].encode('utf-8')); end = len(text[:item[1]].encode('utf-8'))
        return not exclude_range or end <= exclude_range[0] or start >= exclude_range[1]
    fresh = [item for item in bounded if outside_previous(item)]
    if not fresh:
        fresh = [(match.start(), match.end(), match.end(), match.group())
                 for match in re.finditer(r'[^。！？!?\r\n]+[。！？!?][”"’]*', text)
                 if 0 < count_prose(match.group()) <= 400 and match.end()-match.start() < len(text)
                 and outside_previous((match.start(), match.end()))]
    if not fresh:
        raise ValueError('上次扩写范围外没有安全局部原段或完整句子，未重复扩写旧区域')
    middle = [item for item in fresh if len(text)*.2 <= (item[0]+item[1])/2 <= len(text)*.8]
    options = middle or fresh
    dialogue = [item for item in options if any(mark in item[3] for mark in ['“','”','"'])]
    start, end, _, paragraph = min(dialogue or options, key=lambda item: abs((item[0]+item[1])/2-len(text)/2))
    if start == 0 and text.startswith('\ufeff'):
        start = 1
    selected = text[start:end].encode('utf-8')
    return {'kind': 'expand', 'start': len(text[:start].encode('utf-8')), 'end': len(text[:end].encode('utf-8')),
            'old_span_sha256': hashlib.sha256(selected).hexdigest()}


def expansion_window(raw, result, paragraphs, exclude_range):
    """Freeze neighboring original paragraphs sized for the requested growth."""
    text = raw.decode('utf-8')
    gap = result['lower']-result['actual']
    maximum = min(1600, int(result['actual']*.45))
    # Leave source room for the adjacent response/result instead of stopping
    # at the first quota-sized line in the middle of an existing exchange.
    wanted = min(maximum, (gap+1)//2 + min(200, (gap+9)//10))
    segments, current = [], []
    for item in paragraphs:
        start, end = len(text[:item[0]].encode('utf-8')), len(text[:item[1]].encode('utf-8'))
        heading = re.search(r'(?m)^\s*(?:#{1,6}\s+|第[^\r\n]{0,20}[章节卷幕回](?:\s|[·：:])|(?:[-*_＊]\s*){3,}$)', item[3])
        blocked = heading or (exclude_range and start < exclude_range[1] and end > exclude_range[0])
        if blocked:
            if current: segments.append(current)
            current = []
        elif count_prose(item[3].lstrip('\ufeff')):
            current.append(item)
    if current: segments.append(current)
    windows = []
    for segment in segments:
        for index, first in enumerate(segment):
            for last in segment[index:]:
                selected = text[first[0]:last[1]].lstrip('\ufeff')
                count = count_prose(selected)
                if count > maximum: break
                if count:
                    windows.append((first, last, count))
                if count >= wanted: break
    if not windows:
        raise ValueError('没有不跨场景或上次扩写范围的安全局部窗口，未改写整章')
    suitable = [window for window in windows if window[2] >= wanted]
    pool = suitable or windows
    # Start at the existing central interaction, then include its following
    # statements/actions/results rather than inventing events after a greeting.
    def score(window):
        first, _, count = window
        position = (first[0]+first[1])/2
        dialogue = any(mark in first[3] for mark in ['“','”','"'])
        return ((0 if .2*len(text) <= position <= .8*len(text) else 1),
                (0 if dialogue else 1), abs(position-len(text)/2), count)
    if not suitable:
        largest = max(window[2] for window in pool)
        pool = [window for window in pool if window[2] == largest]
    first, last, count = min(pool, key=score)
    start, end = first[0], last[1]
    if start == 0 and text.startswith('\ufeff'): start = 1
    net_upper = result['upper']-result['actual']
    if not suitable or count < (gap+1)//2: net_upper = min(net_upper, 2*count)
    return {'kind': 'expand', 'start': len(text[:start].encode('utf-8')), 'end': len(text[:end].encode('utf-8')),
            'old_span_sha256': hashlib.sha256(text[start:end].encode('utf-8')).hexdigest(),
            'selection_mode': 'contiguous_window', 'source_actual': count,
            'requested_net_lower': min(gap, net_upper), 'requested_net_upper': net_upper}


def focused_shared_context(shared):
    """Project established sources, excluding draft copies and future plans."""
    result = []
    state = re.search(r'(?m)^## 已确认的动态状态\s*$', shared)
    boundary = re.search(r'(?m)^## 本书依据与最近正文\s*$', shared)
    if state and boundary and state.start() < boundary.start():
        result.append(shared[state.start():boundary.start()])
    markers = list(re.finditer(r'(?m)^### (?:meta|story)/[^\r\n]+|^## 用户已采用的本章计划[^\r\n]*', shared))
    for index, marker in enumerate(markers):
        if marker.group().strip() in ('### meta/world_foundation.md', '### meta/character_profiles.md', '### meta/character_voice.md'):
            result.append(shared[marker.start():markers[index+1].start() if index+1 < len(markers) else len(shared)])
    return '\n'.join(result)


def fragment_instructions(raw, fragment, result):
    start, end = fragment['start'], fragment['end']
    before = raw[max(0, start-1500):start].decode('utf-8', errors='ignore')
    after = raw[end:end+1500].decode('utf-8', errors='ignore')
    if fragment['kind'] == 'expand':
        selected = raw[start:end].decode('utf-8')
        old_count = count_prose(selected)
        requested_lower = fragment.get('requested_net_lower', result['lower']-result['actual'])
        requested_upper = fragment.get('requested_net_upper', result['upper']-result['actual'])
        budget = f"全章仍需净增{result['lower']-result['actual']}实字。本次只请求净增{requested_lower}—{requested_upper}实字。选定原段{old_count}实字；扩写后body预算{old_count+requested_lower}—{old_count+requested_upper}实字。只要净增加且不超全章上限，即使不足下限也可提交有效部分，下次补剩余缺口。"
        action = '仅做字数局部扩写：body返回下面冻结原段的完整扩写替换文本，可以保留原段原句；不在已完成事件之间发明新事件。保持原段关键事实、结果、信息取得与先后顺序，展开当时已有的行动、回应、感受；不得搬来原段外已经发生或稍后才发生的事件。'
        if fragment.get('selection_mode') == 'contiguous_window':
            action += '本次选定的是连续多段原文窗口：可以展开窗口内已经存在的完整行动、交涉、验品或交易过程及其回应与结果，保持原有信息取得和时序，不把其中已写事实误当禁写项；不得重演窗口外的事件。'
    else:
        selected = raw[start:end].decode('utf-8')
        budget = f"当前全章{result['actual']}实字、目标{result['lower']}—{result['upper']}。仅压缩下方选定段落，净减少至少{result['actual']-result['upper']}实字；不允许把整章当作替换段。"
        action = '仅做字数局部替换：body只返回下方选定段落的精简替换文本，保留该段承重事实与因果，其余正文由插件原样保留。'
    return ('# 局部片段执行契约\n'+action+'\n'+budget+
            '\n保持已修复事实、人物选择和结局，不新增关键事实、证人或支线，不复制选定原段以外的段落凑数。当前整章只供参考，不得返回整章；body仅为选定原段的完整替换文本。\n'
            +'【插入/替换前文】\n'+before+'\n【仅需替换的段落；补写时为空】\n'+selected+'\n【插入/替换后文】\n'+after+'\n')


def _atomic_body(path, raw, check):
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.fragment-', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        check()
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def focused_commit(root, chapter, expected_sha, guard_path, guard_sha, task_id, review_binding="", review_binding_sha="", review_result=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(task_id)):
        raise ValueError('字数片段提交缺少有效任务编号')
    model_review_text = review_result if isinstance(review_result, str) and review_result.strip() else None
    folder = f'quality/length-attempts/{chapter}/{task_id}'
    receipt_path = folder + '/receipt.json'
    existing = safe_path(root, receipt_path)
    if existing.is_file():
        previous = json.loads(existing.read_text(encoding='utf-8'))
        if previous.get('task_id') != task_id or previous.get('guard_sha256') != guard_sha or previous.get('input_body_sha256') != expected_sha:
            raise ValueError('片段提交任务凭证冲突，已保留历史')
        confirm_execution(root, chapter, expected_sha, guard_path, guard_sha, previous['body_sha256'])
        if previous.get('review_binding_sha'):
            fragment_review_decision(root, task_id, guard_sha, review_binding, review_binding_sha, model_review_text, previous.get('review_sha256'))
        return {'length_attempt_receipt': receipt_path, 'length_attempt_receipt_sha': hashlib.sha256(existing.read_bytes()).hexdigest()}
    confirm_execution(root, chapter, expected_sha, guard_path, guard_sha)
    guard = json.loads(safe_path(root, guard_path).read_text(encoding='utf-8'))
    semantic_reason, review_sha = ('', '')
    if guard.get('semantic_review_required'):
        semantic_reason, review_sha = fragment_review_decision(root, task_id, guard_sha, review_binding, review_binding_sha, model_review_text)
    raw = safe_path(root, guard['body_path']).read_bytes()
    candidate_raw = safe_path(root, 'cache/pp/body.json').read_bytes()
    candidate_path = folder + '/candidate.json'
    atomic_text(safe_path(root, candidate_path), candidate_raw.decode('utf-8-sig'))
    rejected = ''
    try:
        if semantic_reason:
            raise ValueError(semantic_reason)
        data = json.loads(candidate_raw)
        fragment_text = data.get('body') if isinstance(data, dict) else None
        if not isinstance(fragment_text, str) or not fragment_text.strip():
            raise ValueError('片段为空或缺少body字符串')
        fragment_text = fragment_text.strip()
        spec = guard['fragment']; start, end = spec['start'], spec['end']
        if hashlib.sha256(raw[start:end]).hexdigest() != spec['old_span_sha256']:
            raise ValueError('冻结的局部锚发生变化')
        old = raw.decode('utf-8-sig')
        if spec['kind'] == 'insert':
            normalized = re.sub(r'\s+', '', fragment_text)
            original = re.sub(r'\s+', '', old)
            paragraphs = [re.sub(r'\s+', '', part) for part in re.split(r'\r?\n\s*\r?\n', old)]
            if normalized in original or original in normalized or any(len(part) >= 20 and part in normalized for part in paragraphs):
                raise ValueError('片段重复原正文，未采纳复制段落')
            newline = b'\r\n' if b'\r\n' in raw else b'\n'
            payload = fragment_text.encode('utf-8')
            addition = ((newline*2 if raw and not raw.endswith(newline*2) else b'') + payload
                        if start == len(raw) else payload + newline*2)
            merged = raw[:start] + addition + raw[end:]
        else:
            if spec['kind'] == 'expand':
                normalized = re.sub(r'\s+', '', fragment_text)
                selected = re.sub(r'\s+', '', raw[start:end].decode('utf-8'))
                outside = raw[:start].decode('utf-8-sig') + '\n\n' + raw[end:].decode('utf-8')
                paragraphs = [re.sub(r'\s+', '', part) for part in re.split(r'\r?\n\s*\r?\n', outside)]
                if any(len(part) >= 20 and part not in selected and part in normalized for part in paragraphs):
                    raise ValueError('扩写重复选定原段以外的正文，未采纳复制段落')
            merged = raw[:start] + fragment_text.encode('utf-8') + raw[end:]
        actual = count_prose(merged.decode('utf-8-sig'))
        assessment = guard['assessment']; prior_actual = assessment['actual']
        if assessment['status'] == 'short' and (actual <= prior_actual or actual > assessment['upper']):
            raise ValueError('合成后未净增或超过目标上限')
        if assessment['status'] == 'long' and (actual >= prior_actual or actual < assessment['lower']):
            raise ValueError('合成后未净减或低于目标下限')
    except (ValueError, TypeError, KeyError) as error:
        rejected = str(error)
        merged = raw
        actual = count_prose(raw.decode('utf-8-sig'))
    def check():
        confirm_execution(root, chapter, expected_sha, guard_path, guard_sha)
        if guard.get('semantic_review_required'):
            fragment_review_decision(root, task_id, guard_sha, review_binding, review_binding_sha, model_review_text, review_sha)
    check()
    if not rejected:
        _atomic_body(safe_path(root, guard['body_path']), merged, check)
    receipt = {'task_id': task_id, 'chapter_number': chapter, 'strategy': LENGTH_REPAIR_STRATEGY,
               'operation': guard['fragment']['kind'],
               'expanded_span_range': [guard['fragment']['start'], guard['fragment']['start']+len(fragment_text.encode('utf-8'))] if not rejected and guard['fragment']['kind'] == 'expand' else None,
               'expanded_span_sha256': hashlib.sha256(fragment_text.encode('utf-8')).hexdigest() if not rejected and guard['fragment']['kind'] == 'expand' else '',
               'candidate_path': candidate_path, 'candidate_sha256': hashlib.sha256(safe_path(root, candidate_path).read_bytes()).hexdigest(),
               'input_body_sha256': expected_sha, 'body_sha256': hashlib.sha256(merged).hexdigest(),
               'guard_sha256': guard_sha, 'review_binding_sha': review_binding_sha, 'review_sha256': review_sha, 'accepted': not bool(rejected), 'actual': actual, 'rejection_reason': rejected,
               'status': ('rejected' if rejected else 'accepted' if guard['assessment']['lower'] <= actual <= guard['assessment']['upper'] else 'accepted_partial')}
    atomic_text(existing, json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    atomic_text(safe_path(root, f'quality/length/{chapter}-last-attempt.json'), json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    return {'length_attempt_receipt': receipt_path, 'length_attempt_receipt_sha': hashlib.sha256(existing.read_bytes()).hexdigest()}


def verify_focused_attempt(root, chapter, task, node):
    outputs = node.get('outputs') or {}
    relative = outputs.get('length_attempt_receipt')
    if not relative or not outputs.get('length_attempt_receipt_sha'):
        raise ValueError('片段任务缺少真实尝试凭证')
    file = safe_path(root, relative)
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != outputs['length_attempt_receipt_sha']:
        raise ValueError('片段任务尝试凭证已变化')
    receipt = json.loads(file.read_text(encoding='utf-8'))
    body = safe_path(root, f'story/{chapter}/chapter.md')
    candidate = safe_path(root, receipt['candidate_path'])
    if (receipt.get('task_id') != task.get('task_id') or receipt.get('chapter_number') != chapter
            or not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != receipt['candidate_sha256']
            or hashlib.sha256(body.read_bytes()).hexdigest() != receipt['body_sha256']
            or count_prose(body.read_text(encoding='utf-8-sig')) != receipt['actual']):
        raise ValueError('片段尝试与本次任务或当前正文不匹配')
    if not isinstance(receipt.get('accepted'), bool):
        raise ValueError('片段尝试缺少采纳状态')
    return receipt


def prepare_fragment_review(root, chapter, expected_sha, guard_path, guard_sha, task_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(task_id)):
        raise ValueError('片段审查缺少任务编号')
    confirm_execution(root, chapter, expected_sha, guard_path, guard_sha)
    guard = json.loads(safe_path(root, guard_path).read_text(encoding='utf-8'))
    raw = safe_path(root, 'cache/pp/body.json').read_bytes()
    candidate = json.loads(raw)
    if not isinstance(candidate, dict) or not isinstance(candidate.get('body'), str):
        raise ValueError('候选缺少body片段')
    source = guard['state_binding']['receipt'].get('source_path') or ''
    shared_path = guard.get('story_context_path') or ''
    shared_raw = safe_path(root, shared_path).read_bytes() if shared_path else b''
    if shared_path and hashlib.sha256(shared_raw).hexdigest() != guard['files'][shared_path]:
        raise ValueError('共享故事上下文已变化，不能审查未绑定资料')
    context = {'story_support_context': shared_raw.decode('utf-8-sig'), 'candidate': candidate['body'], 'current_body': safe_path(root, guard['body_path']).read_text(encoding='utf-8-sig'),
               'operation': guard['fragment']['kind'],
               'selected_text': safe_path(root, guard['body_path']).read_bytes()[guard['fragment']['start']:guard['fragment']['end']].decode('utf-8'),
               'insertion_context': safe_path(root, guard['outputs']['length_execution_context']).read_text(encoding='utf-8'),
               'author_feedback': safe_path(root, source).read_text(encoding='utf-8-sig') if source else '',
               'narrative_pov': guard['state_binding'].get('narrative_pov', 'third_person')}
    folder = f'quality/length-attempts/{chapter}/{task_id}'
    input_path, report_path, binding_path = folder+'/review-input.json', folder+'/semantic-review.json', folder+'/review-binding.json'
    input_text = json.dumps(context, ensure_ascii=False, indent=2)+'\n'
    input_sha = hashlib.sha256(input_text.encode('utf-8')).hexdigest()
    binding = {'task_id': task_id, 'guard_sha256': guard_sha, 'candidate_sha256': hashlib.sha256(raw).hexdigest(),
               'input_path': input_path, 'input_sha256': input_sha,
               'report_path': report_path}
    file = safe_path(root, binding_path)
    text = json.dumps(binding, ensure_ascii=False, indent=2)+'\n'
    if file.is_file() and file.read_text(encoding='utf-8') != text:
        raise ValueError('同任务片段审查输入已变化，已保留原凭证')
    input_file = safe_path(root, input_path)
    if input_file.is_file() and input_file.read_bytes() != input_text.encode('utf-8'):
        raise ValueError('同任务原审查上下文已保留，不能覆盖不同输入')
    if not input_file.is_file():
        atomic_text(input_file, input_text)
    if not file.is_file():
        atomic_text(file, text)
    return {'fragment_review_input': input_path, 'fragment_review_report_path': report_path,
            'fragment_review_binding': binding_path, 'fragment_review_binding_sha': hashlib.sha256(file.read_bytes()).hexdigest()}


def fragment_review_decision(root, task_id, guard_sha, binding_path, binding_sha, expected_review_text=None, expected_raw_sha=None):
    if not binding_path or not binding_sha:
        raise ValueError('片段缺少提交前语义审查凭证')
    file = safe_path(root, binding_path)
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != binding_sha:
        raise ValueError('片段语义审查输入凭证已变化')
    binding = json.loads(file.read_text(encoding='utf-8'))
    input_file = safe_path(root, binding['input_path'])
    if (binding['task_id'] != task_id or binding['guard_sha256'] != guard_sha
            or hashlib.sha256(safe_path(root, 'cache/pp/body.json').read_bytes()).hexdigest() != binding['candidate_sha256']
            or not input_file.is_file() or hashlib.sha256(input_file.read_bytes()).hexdigest() != binding['input_sha256']):
        raise ValueError('候选或审查上下文不再匹配，未发布')
    context = json.loads(input_file.read_text(encoding='utf-8'))
    report_file = safe_path(root, binding['report_path'])
    report_sha = hashlib.sha256(report_file.read_bytes()).hexdigest()
    normalized = expected_review_text.replace('\r\n', '\n').replace('\r', '\n') if isinstance(expected_review_text, str) else None
    if normalized is None or report_file.read_text(encoding='utf-8') != normalized:
        raise ValueError('片段语义审查文件与本任务真实模型输出不匹配，未发布')
    if expected_raw_sha is not None and report_sha != expected_raw_sha:
        raise ValueError('片段语义审查文件在提交期间已变化，未发布')
    report = json.loads(report_file.read_text(encoding='utf-8'))
    compatible, issues = report.get('compatible'), report.get('issues')
    if not isinstance(compatible, bool) or not isinstance(issues, list) or compatible == bool(issues):
        raise ValueError('片段语义审查结论与问题列表不一致')
    reasons = []
    source = context['current_body']+'\n'+context['author_feedback']+'\n'+context.get('story_support_context', '')
    for issue in issues:
        if (not isinstance(issue, dict) or issue.get('category') not in {'new_fact','pov','continuity','repetition'}
                or any(not isinstance(issue.get(key), str) or not issue[key].strip() for key in ['candidate_quote','source_quote','reason'])
                or issue['candidate_quote'] not in context['candidate'] or issue['source_quote'] not in source):
            raise ValueError('语义审查引用未与候选及原文逐字对应，不能据此发布或伪造通过')
        reasons.append(issue['category']+': '+issue['reason'])
    return ('语义审查未通过：'+'；'.join(reasons) if reasons else ''), report_sha
