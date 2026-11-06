"""Plan chapter budgets and validate the six scene drafts before manuscript publication."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import uuid

_LENGTH_SPEC = importlib.util.spec_from_file_location(
    'multi_scene_length', Path(__file__).resolve().parents[1] / 'console_service/length_quality.py')
length = importlib.util.module_from_spec(_LENGTH_SPEC)
_LENGTH_SPEC.loader.exec_module(length)

WRITERS = ('agent_aw', 'agent_dw', 'agent_iw', 'agent_dsw', 'agent_tw', 'agent_si')
WEIGHTS = (14, 16, 17, 20, 19, 14)
_QUOTES = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"')
_FIRST = re.compile(r'(?m)(?:^\s*|[。！？!?；;：:]\s*)(?:我(?:们)?|俺|咱(?:们)?)(?=[\u3400-\u9fff\s])')
_SLOT = re.compile(r'\[SLOT(?:_|\s|\])', re.I)


def budgets(target):
    bounds = length.target_range(target)
    if not bounds or bounds[0] < len(WRITERS):
        raise ValueError('多写手需要至少六实字的有效章节字数目标')
    def distribute(total):
        cumulative = [0]
        for weight in WEIGHTS:
            cumulative.append(cumulative[-1] + weight)
        return [total * b // 100 - total * a // 100 for a, b in zip(cumulative, cumulative[1:])]
    lo = [1 + value for value in distribute(bounds[0] - len(WRITERS))]
    # Allocate extra room independently to keep every interval monotonic.
    hi = [a + b for a, b in zip(lo, distribute(bounds[1] - bounds[0]))]
    return lo, hi


def paragraphs(body):
    return [line.strip() for line in body.splitlines() if line.strip()]


def insertion_point(body):
    parts = paragraphs(body)
    if len(parts) > 1:
        split = len(parts) // 2
        return '\n\n'.join(parts[:split]), '\n\n'.join(parts[split:])
    # Some providers send an entire scene on one line. Keep speech intact.
    quoted = [match.span() for match in _QUOTES.finditer(body)]
    boundaries = [match.end() for match in re.finditer(r'[。！？!?]', body)
                  if match.end() < len(body)
                  and not any(start < match.end() <= end for start, end in quoted)]
    if boundaries:
        split = min(boundaries, key=lambda pos: abs(pos - len(body) // 2))
        return body[:split].rstrip(), body[split:].lstrip()


def scene_text(raw):
    raw = raw.strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw = raw.partition('\n')[2].removesuffix('```').strip()
    if raw.startswith(('{', '[')):
        try:
            data = json.loads(raw)
        except ValueError:
            return ''
        if not isinstance(data, dict) or set(data) != {'body'} or not isinstance(data['body'], str):
            return ''
        return data['body']
    return raw


def duplicates(body, previous):
    def grams(line):
        text = ''.join(c for c in line.casefold() if c.isalnum())
        return {text[i:i+4] for i in range(len(text)-3)} if len(text) >= 28 else set()
    seen = [group for paragraph in previous if (group := grams(paragraph))]
    for paragraph in paragraphs(body):
        group = grams(paragraph)
        if group and any(len(group & prior) / len(group | prior) >= .78 for prior in seen):
            return True
        if group:
            seen.append(group)
    return False


def scene_problem(body, minimum, maximum, pov):
    if not isinstance(body, str) or not body.strip():
        return '[scene_empty] 请在 body 字段提供本场完整正文。'
    if _SLOT.search(body) or r'\n\n' in body or re.search(r'(?m)^#{1,6}\s|^\s*```', body):
        return '[scene_markup] 只交付该场景正文，移除槽位、标题和转义残留。'
    if duplicates(body, []):
        return '[scene_duplicate] 本场出现重复段落，删掉重复并展开不同的行动和后果。'
    if pov == 'third_person' and _FIRST.search(_QUOTES.sub(' ', body)):
        return '[scene_pov] 在引号外出现第一人称叙述。使用既定第三人称焦点，保留正常对白。'
    actual = length.count_prose(body)
    if actual < minimum or actual > maximum + 50:
        detail = ('展开已有交涉、动作和人物取舍，禁止靠回顾前场凑字。' if actual < minimum
                  else '压缩重复解释，保留本场动作和后果。')
        return f'[scene_length] 本场实测 {actual} 实字，要求 {minimum}—{maximum} 实字。{detail}'
    return None


def validate(bodies, target, pov):
    """Return the offending scene and safe retry feedback, or None."""
    lo, hi = budgets(target)
    if len(bodies) != len(WRITERS):
        raise ValueError('场景数与写手数不一致')
    previous = []
    counts = [length.count_prose(body) for body in bodies]
    for i, body in enumerate(bodies):
        issue = scene_problem(body, lo[i], hi[i], pov)
        if issue:
            return i, issue
        if duplicates(body, previous):
            return i, '[scene_duplicate] 场景含与已有段落高度重复的内容。从自己的入场点继续，删除复述并写出本场的具体行动和后果。'
        previous.extend(paragraphs(body))
    total = sum(counts)
    if total < sum(lo) or total > sum(hi):
        short = total < sum(lo)
        index = max(range(len(counts)), key=lambda i: (lo[i] - counts[i]) if short else (counts[i] - hi[i]))
        delta = (sum(lo) if short else sum(hi)) - total
        edge = max(1, counts[index] + delta)
        wanted = f'至少 {edge}' if short else f'至多 {edge}'
        return index, f'[chapter_length] 全章实测 {total} 实字，目标 {target}。本场现为 {counts[index]}，请调整到{wanted}实字，保持情节边界。'
    return None


def validate_plan(data):
    rows = data.get('scenes') if isinstance(data, dict) else None
    keys = ('entry', 'turn', 'exit', 'knowledge')
    if (not isinstance(data, dict) or not isinstance(data.get('focus'), str)
            or not data['focus'].strip() or not isinstance(rows, list) or len(rows) != len(WRITERS)
            or any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != i
                   or any(not isinstance(row.get(key), str) or not row[key].strip() for key in keys)
                   for i, row in enumerate(rows, 1))):
        raise ValueError('[scene_plan] 必须提供焦点人物和六张按序编号的场景卡，每张都有入场、变化、交棒和知识边界。')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, data):
    length.atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def expansion_retry(directory, index, guard, minimum, maximum, issue=''):
    actual = length.count_prose(guard['before'] + '\n\n' + guard['after'])
    low, high = minimum - actual, maximum - actual
    feedback = f'上次新增片段未采用：{issue}\n只重写新增部分，原段落仍由插件保留。\n' if issue else ''
    length.atomic_text(directory / f'retry-{index}.md', (
        feedback + f'【本场局部扩写】已有正文实测 {actual} 字。只返回新增正文，至少 {low}、最多 {high} 实字。'
        '它将由插件插入原段落之间。写出插入位置尚未发生的现场行动和反应，'
        '保持焦点、事件顺序和交棒。不增加证据或改写结果，不复述两侧原文，不写出标记。\n\n'
        f'【插入点前的原文】\n{guard["before"]}\n\n【插入点后的原文】\n{guard["after"]}\n'))


def reset_scene(directory, index, minimum, maximum, reason):
    """Explicit recovery for a stopped scene; keep accepted siblings and audit the old seed."""
    if index not in range(1, len(WRITERS) + 1):
        raise ValueError('无效场景编号')
    brief = read_json(directory / f'brief-{index}.json')
    names = [f'expansion-{index}.json', f'validated-{index}.json', f'scene-{index}.txt', f'retry-{index}.md']
    previous = {name: (directory / name).read_text(encoding='utf-8-sig')
                for name in names if (directory / name).is_file()}
    archive = length.safe_path(directory, f'rejected/scene-{index}-{uuid.uuid4().hex}.json')
    save_json(archive, {'reason': reason, 'files': previous})
    for name in names[:3]:
        (directory / name).unlink(missing_ok=True)
    brief.update(minimum=minimum, maximum=maximum, draft_target=(minimum + maximum) // 2)
    save_json(directory / f'brief-{index}.json', brief)
    length.atomic_text(directory / f'retry-{index}.md', (
        '【本场重写】上轮场景未通过，旧稿仅归档，不参与本次正文。只重写本场完整正文。'
        'entry 中的事已经发生，不再重新演一遍；从 turn 的新动作开始，写到 exit 即停。'
        f'本场范围 {minimum}—{maximum} 实字。此前失败原因：{reason}。\n'
        '本次唯一交付范围（全篇资料仅用于核实事实，不能扩大本场范围）：\n'
        + json.dumps(brief, ensure_ascii=False, indent=2) + '\n'))


def accept_scene_attempt(directory, index, incoming, minimum, maximum, pov):
    """On a short scene, keep the existing ending and ask only for a new passage."""
    guard_path = directory / f'expansion-{index}.json'
    retry_path = directory / f'retry-{index}.md'
    guard = read_json(guard_path) if guard_path.is_file() else None
    if not isinstance(incoming, str) or not incoming.strip():
        return '[scene_empty] 请返回本次要求的正文。'
    incoming = incoming.strip()
    body = '\n\n'.join([guard['before'], incoming, guard['after']]) if guard else incoming
    issue = scene_problem(body, minimum, maximum, pov)
    if issue is None:
        save_json(directory / f'validated-{index}.json', {'body': body})
        return None
    actual = length.count_prose(body)
    if not issue.startswith('[scene_length]') or actual >= minimum:
        if guard:
            expansion_retry(directory, index, guard, minimum, maximum, issue)
        return issue
    insertion = insertion_point(body)
    if not insertion:
        return issue
    before, after = insertion
    save_json(guard_path, {'before': before, 'after': after})
    low = minimum - actual
    expansion_retry(directory, index, {'before': before, 'after': after}, minimum, maximum)
    return f'[scene_length] 本场正文实测 {actual}，缺少至少 {low} 实字。请按新增片段指令续写指定位置。'


def retry(node, reason):
    print(f'<WF_REJECT_UPSTREAM target="{node}">{reason}</WF_REJECT_UPSTREAM>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'plan', 'scene', 'assemble', 'reset-scene'))
    parser.add_argument('--target', required=True)
    parser.add_argument('--pov', choices=('first_person', 'third_person'), required=True)
    parser.add_argument('--scene', type=int, choices=range(1, len(WRITERS) + 1))
    parser.add_argument('--reason', default='场景返修后仍未通过，重新按本场边界交付')
    args = parser.parse_args()
    root = Path.cwd()
    task = os.environ.get('TASK_ID', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task):
        raise ValueError('场景产物需要有效任务标识')
    relative = f'cache/multi/{task}'
    directory = length.safe_path(root, relative)
    lo, hi = budgets(args.target)
    if args.action == 'reset-scene':
        if args.scene is None:
            parser.error('--scene is required for scene recovery')
        reset_scene(directory, args.scene, lo[args.scene - 1], hi[args.scene - 1], args.reason)
    elif args.action == 'prepare':
        save_json(directory / 'budgets.json', [
            {'id': i, 'minimum': a, 'maximum': b} for i, (a, b) in enumerate(zip(lo, hi), 1)])
        for key, value in {'multi_dir': relative, 'multi_budgets': f'{relative}/budgets.json'}.items():
            print(f'<WF_VAR>{key}:{value}</WF_VAR>')
    elif args.action == 'plan':
        try:
            plan = read_json(directory / 'plan.json')
            validate_plan(plan)
        except ValueError:
            retry('agent_nw', '[scene_plan] 返回 focus 和六个编号 1—6 的完整场景卡，按约定填齐字段。')
            return
        for i, row in enumerate(plan['scenes'], 1):
            brief = {**row, 'focus': plan['focus'], 'minimum': lo[i - 1], 'maximum': hi[i - 1],
                     'draft_target': (lo[i - 1] + hi[i - 1]) // 2}
            name = f'brief-{i}.json'
            save_json(directory / name, brief)
            print(f'<WF_VAR>multi_brief_{i}:{relative}/{name}</WF_VAR>')
            retry_name = f'retry-{i}.md'
            length.atomic_text(directory / retry_name, '')
            print(f'<WF_VAR>multi_retry_{i}:{relative}/{retry_name}</WF_VAR>')
    elif args.action == 'scene':
        if args.scene is None:
            parser.error('--scene is required for the scene check')
        raw = (directory / f'scene-{args.scene}.txt').read_text(encoding='utf-8-sig')
        i = args.scene - 1
        problem = accept_scene_attempt(directory, args.scene, scene_text(raw), lo[i], hi[i], args.pov)
        if problem:
            retry(WRITERS[i], problem)
    else:
        bodies = []
        for i, writer in enumerate(WRITERS, 1):
            data = read_json(directory / f'validated-{i}.json')
            body = data.get('body') if isinstance(data, dict) else None
            if not isinstance(body, str) or not body.strip():
                retry(writer, '[scene_empty] 请在 body 字段提供本场完整正文。')
                return
            bodies.append(body.strip())
        error = validate(bodies, args.target, args.pov)
        if error:
            index = error[0] + 1
            save_json(directory / f'expansion-{index}.json', None)
            length.atomic_text(directory / f'retry-{index}.md', '')
            retry(WRITERS[error[0]], error[1])
            return
        save_json(length.safe_path(root, 'cache/si/chapter.json'), {'body': '\n\n'.join(bodies)})


if __name__ == '__main__':
    main()
