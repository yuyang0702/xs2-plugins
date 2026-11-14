"""Allocate logical scenes to worker slots and validate drafts before publication."""
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
_ALLOCATION_SPEC = importlib.util.spec_from_file_location(
    'multi_scene_allocation', Path(__file__).with_name('scene_allocation.py'))
allocation_policy = importlib.util.module_from_spec(_ALLOCATION_SPEC)
_ALLOCATION_SPEC.loader.exec_module(allocation_policy)
_CONTINUITY_SPEC = importlib.util.spec_from_file_location('multi_scene_continuity',Path(__file__).with_name('continuity_contract.py'))
continuity_policy = importlib.util.module_from_spec(_CONTINUITY_SPEC)
_CONTINUITY_SPEC.loader.exec_module(continuity_policy)
_BOOK_SPEC=importlib.util.spec_from_file_location('scene_book_contract',Path(__file__).resolve().parents[1]/'prose_policy/book_contract.py')
book_policy=importlib.util.module_from_spec(_BOOK_SPEC);_BOOK_SPEC.loader.exec_module(book_policy)

WRITERS = ('agent_aw', 'agent_dw', 'agent_iw', 'agent_dsw', 'agent_tw', 'agent_si')
WEIGHTS = allocation_policy.LEGACY_WEIGHTS
_QUOTES = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"')
_FIRST = re.compile(r'(?m)(?:^\s*|[。！？!?；;：:]\s*)(?:我(?:们)?|俺|咱(?:们)?)(?=[\u3400-\u9fff\s])')
_SLOT = re.compile(r'\[SLOT(?:_|\s|\])', re.I)



def _guarded_rejection(message):
    spec=importlib.util.spec_from_file_location('plugin_rejection_transport',Path(__file__).resolve().parents[1]/'production_guard/rejections.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.emit(message)

def budgets(target, weights=None):
    return allocation_policy.weighted_bounds(length.target_range(target), WEIGHTS if weights is None else weights)


def paragraphs(body):
    return [line.strip() for line in body.splitlines() if line.strip()]


def draft_scene_limits(lo, hi):
    # Allocation is a drafting guide. Final reader/export gates retain the book target.
    return [max(1, (n * 65 + 99) // 100) for n in lo], [(n * 165 + 99) // 100 for n in hi]


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


def scene_problem(body, minimum, maximum, pov, book_contract=None):
    if not isinstance(body, str) or not body.strip():
        return '[scene_empty] 请在 body 字段提供本场完整正文。'
    if _SLOT.search(body) or r'\n\n' in body or re.search(r'(?m)^#{1,6}\s|^\s*```', body):
        return '[scene_markup] 只交付该场景正文，移除槽位、标题和转义残留。'
    if book_contract is None and duplicates(body, []):
        return '[scene_duplicate] 本场出现重复段落，删掉重复并展开不同的行动和后果。'
    if book_contract is None and pov == 'third_person' and _FIRST.search(_QUOTES.sub(' ', body)):
        return '[scene_pov] 在引号外出现第一人称叙述。使用既定第三人称焦点，保留正常对白。'
    actual = length.count_prose(body)
    if actual < minimum or actual > maximum + 50:
        detail = ('展开已有交涉、动作和人物取舍，禁止靠回顾前场凑字。' if actual < minimum
                  else '压缩重复解释，保留本场动作和后果。')
        return f'[scene_length] 本场实测 {actual} 实字，要求 {minimum}—{maximum} 实字。{detail}'
    return None


def validate(bodies, target, pov, allocation=None, book_contract=None):
    """Return the offending scene and safe retry feedback, or None."""
    if allocation is None:
        nominal_lo, nominal_hi = budgets(target)
        lo, hi = draft_scene_limits(nominal_lo, nominal_hi)
        targets = [(a+b)//2 for a,b in zip(nominal_lo,nominal_hi)]
    else:
        rows = allocation['scenes']
        nominal_lo = [r['nominal_minimum'] for r in rows]
        nominal_hi = [r['nominal_maximum'] for r in rows]
        lo, hi = [r['minimum'] for r in rows], [r['maximum'] for r in rows]
        targets = [r['draft_target'] for r in rows]
    if len(bodies) != len(lo):
        raise ValueError('正文场景数与已确认分场不一致')
    previous = []
    counts = [length.count_prose(body) for body in bodies]
    for i, body in enumerate(bodies):
        issue = scene_problem(body, lo[i], hi[i], pov, book_contract=book_contract)
        if issue:
            return i, issue
        if book_contract is None and duplicates(body, previous):
            return i, '[scene_duplicate] 场景含与已有段落高度重复的内容。从自己的入场点继续，删除复述并写出本场的具体行动和后果。'
        previous.extend(paragraphs(body))
    total = sum(counts)
    draft_min, draft_max = (sum(nominal_lo) * 90 + 99) // 100, sum(nominal_hi) * 145 // 100
    if total < draft_min or total > draft_max:
        short = total < draft_min
        candidates = [i for i in range(len(counts)) if counts[i] < hi[i]+50] if short else [i for i in range(len(counts)) if counts[i] > lo[i]]
        index = max(candidates, key=lambda i: (targets[i] - counts[i]) if short else (counts[i] - targets[i]))
        delta = (draft_min if short else draft_max) - total
        # Repair one scene at a time without contradicting its acceptance limit.
        edge = min(hi[index]+50, max(lo[index], counts[index] + delta))
        wanted = f'至少 {edge}' if short else f'至多 {edge}'
        return index, f'[chapter_length] 初稿实测 {total}，初稿范围 {draft_min}—{draft_max} 实字。本场现为 {counts[index]}，请调整到{wanted}实字，保持情节边界。成品目标 {target} 仍在润色后验收。'
    return None


def validate_plan(data):
    allocation_policy.validate_plan(data)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, data):
    length.atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def planning_sources(root, chapter, policy_runtime='', task_id=None):
    """Freeze book facts from current effective sources, never another scene's guesses."""
    policy = None
    if (root/'.novel-project.json').is_file():
        spec=importlib.util.spec_from_file_location('scene_source_policy',Path(__file__).resolve().parents[1]/'prose_policy/prose_policy.py')
        policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    parts=[]
    common=policy.runtime_common(root,policy_runtime,task_id=task_id) if policy and policy_runtime.strip() else 'cache/story-support/context.md'
    common_file=length.safe_path(root,common)
    if common_file.is_file():parts.append('## 已确认前文与本章采用方案\n'+common_file.read_text(encoding='utf-8-sig'))
    for name in ('meta/continuity_constraints.md','meta/world_foundation.md','meta/character_profiles.md',
                 'meta/story_plan.md','outline/near_term_outline.md',f'story/{chapter}/single_chapter_guide.md'):
        file=length.safe_path(root,name)
        if file.is_file():
            text=policy.effective_text(root,name) if policy else file.read_text(encoding='utf-8-sig')
            parts.append(f'## {name}\n{text}')
    project=root/'.novel-project.json'
    if project.is_file():
        values=read_json(project).get('values',{})
        parts.append('## 作者当前要求\n'+'\n'.join(str(values.get(k) or '') for k in ('premise','human_intent','world_intent','advisor_guidance')))
    parts.append(book_policy.prompt(book_policy.resolve(root)))
    entry=Path(__file__).resolve().parents[1]/'composition_plan/composition_plan.py'
    spec=importlib.util.spec_from_file_location('scene_composition_budget',entry)
    composer=importlib.util.module_from_spec(spec);spec.loader.exec_module(composer)
    quota=composer.current(root,chapter)
    if quota:parts.append('## 已独立审核的篇幅与阅读作用规划（意图，不是已发生事实）\n'+json.dumps(quota['plan'],ensure_ascii=False,indent=2))
    return '\n\n'.join(parts)


def write_handoffs(directory,plan,allocation):
    if 'continuity' not in plan:return
    accepted={};allocation_sha=allocation_policy.digest(directory/'allocation.json')
    for row in allocation['scenes']:
        slot=row['slot'];file=directory/f'validated-{slot}.json'
        if not file.is_file():continue
        value=read_json(file);raw=directory/f'scene-{slot}.txt'
        if (value.get('allocation_sha256')!=allocation_sha or not raw.is_file()
                or value.get('source_sha256')!=allocation_policy.digest(raw)):
            raise ValueError('前场正文已有变化或未按当前分场校验，不能交接旧正文')
        accepted[row['scene_id']]=value['body']
    for row in allocation['scenes']:
        save_json(directory/f"handoff-{row['slot']}.json",{'scene_id':row['scene_id'],'continuity':plan['continuity'],
            'book_contract':read_json(directory/'book-contract.json') if (directory/'book-contract.json').is_file() else None,
            'previous_scenes':[{'scene_id':i,'body':body} for i,body in accepted.items() if i<row['scene_id']],
            'instruction':'前场原文只说明实际衔接，不得覆盖冻结事实；发现冲突要纠正，不能照错续写。不得提前写后场，也不重复介绍已成立信息。'})


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
    brief.update(minimum=minimum, maximum=maximum,
                 draft_target=brief.get('draft_target', (minimum + maximum) // 2))
    save_json(directory / f'brief-{index}.json', brief)
    length.atomic_text(directory / f'retry-{index}.md', (
        '【本场重写】上轮场景未通过，旧稿仅归档，不参与本次正文。只重写本场完整正文。'
        'entry 中的事已经发生，不再重新演一遍；从 turn 的新动作开始，写到 exit 即停。'
        f'本场范围 {minimum}—{maximum} 实字。此前失败原因：{reason}。\n'
        '本次唯一交付范围（全篇资料仅用于核实事实，不能扩大本场范围）：\n'
        + json.dumps(brief, ensure_ascii=False, indent=2) + '\n'))


def full_scene_retry(directory, index, issue):
    brief = read_json(directory / f'brief-{index}.json')
    length.atomic_text(directory / f'retry-{index}.md', (
        '【本场完整返修】只重新交付本场完整场景，不返回新增片段，不附上旧稿。'
        f'上次未采用原因：{issue}\n'
        'entry 已经发生，从 turn 的新动作开始，到 exit 停止；不要重演前场或提前写后场。'
        '预算留有初稿余量，按 draft_target 展开行动和后果，避免为凑字重复解释。\n'
        + json.dumps(brief, ensure_ascii=False, indent=2) + '\n'))


def accept_full_scene_attempt(directory, index, incoming, minimum, maximum, pov, allocation_sha='', source_sha='', book_contract=None):
    issue = scene_problem(incoming, minimum, maximum, pov, book_contract=book_contract)
    if issue is None:
        record = {'body': incoming.strip()}
        if allocation_sha:
            record['allocation_sha256'] = allocation_sha
        if source_sha:
            record['source_sha256'] = source_sha
        save_json(directory / f'validated-{index}.json', record)
        return None
    archive = length.safe_path(directory, f'rejected/scene-{index}-{uuid.uuid4().hex}.json')
    save_json(archive, {'reason': issue, 'body': incoming})
    (directory / f'validated-{index}.json').unlink(missing_ok=True)
    full_scene_retry(directory, index, issue)
    return issue


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
    _guarded_rejection(f'<WF_REJECT_UPSTREAM target="{node}">{reason}</WF_REJECT_UPSTREAM>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'plan', 'scene', 'assemble', 'reset-scene', 'skip-scene', 'check-plan'))
    parser.add_argument('--target', required=True)
    parser.add_argument('--pov', choices=('first_person', 'third_person'), required=True)
    parser.add_argument('--scene', type=int, choices=range(1, len(WRITERS) + 1))
    parser.add_argument('--reason', default='场景返修后仍未通过，重新按本场边界交付')
    parser.add_argument('--chapter',default='0001')
    parser.add_argument('--policy-runtime',default='')
    args = parser.parse_args()
    root = Path.cwd()
    task = os.environ.get('TASK_ID', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task):
        raise ValueError('场景产物需要有效任务标识')
    relative = f'cache/multi/{task}'
    directory = length.safe_path(root, relative)
    current_profile=book_policy.freeze(root,task)['contract']
    profile_file=directory/'book-contract.json'
    profile=read_json(profile_file) if profile_file.is_file() else None
    if profile is not None and profile!=current_profile:raise ValueError('本书文风或世界规则已有变化，请新建任务')
    bounds = length.target_range(args.target)
    if not bounds:
        raise ValueError('多写手需要有效整章字数目标')
    allocation = allocation_policy.read_allocation(directory, bounds) if args.action not in {'prepare', 'plan'} else None
    rows = {row['slot']: row for row in allocation['scenes']} if allocation else {}
    if allocation:
        lo = [rows[i]['minimum'] if i in rows else 1 for i in range(1, 7)]
        hi = [rows[i]['maximum'] if i in rows else 1 for i in range(1, 7)]
    elif args.action not in {'prepare', 'plan'}:
        nominal_lo, nominal_hi = budgets(args.target)
        lo, hi = draft_scene_limits(nominal_lo, nominal_hi)
    if args.action == 'check-plan':
        if not allocation:
            raise ValueError('缺少本次已确认分场，不能继续写作')
        write_handoffs(directory,read_json(directory/'plan.json'),allocation)
    elif args.action == 'skip-scene':
        if args.scene is None or not allocation or args.scene in rows:
            raise ValueError('只可跳过本次已确认分场中未启用的执行槽')
    elif args.action == 'reset-scene':
        if args.scene is None:
            parser.error('--scene is required for scene recovery')
        if allocation and args.scene not in rows:
            raise ValueError('该执行槽未启用，不是本次分场中的场景')
        reset_scene(directory, args.scene, lo[args.scene - 1], hi[args.scene - 1], args.reason)
    elif args.action == 'prepare':
        if not re.fullmatch(r'\d{4}',args.chapter):raise ValueError('章节编号无效')
        save_json(profile_file,current_profile)
        source_text=planning_sources(root,args.chapter,args.policy_runtime,task_id=task)
        source_file=directory/'planning-sources.md'
        if source_file.exists() and source_file.read_text(encoding='utf-8')!=source_text:
            raise ValueError('规划依据已有变化，请创建新任务')
        length.atomic_text(source_file,source_text)
        quote_file=directory/'planning-sources-model.md'
        quote_view=continuity_policy.planning_quote_view(source_text)
        if quote_file.exists() and quote_file.read_text(encoding='utf-8-sig')!=quote_view:
            raise ValueError('分场引用编号已有变化，请创建新任务')
        length.atomic_text(quote_file,quote_view)
        save_json(directory / 'planning-budget.json', {'chapter_minimum': bounds[0], 'chapter_maximum': bounds[1],
            'max_scenes': len(WRITERS), 'allocation': '先按已有事件确定1—6场，再给相对权重和篇幅理由；不预分六份预算。'})
        outputs = {'multi_dir': relative, 'multi_budgets': f'{relative}/planning-budget.json'}
        outputs['multi_sources']=f'{relative}/planning-sources-model.md'
        outputs.update({f'multi_active_{i}': 'no' for i in range(1, 6)})
        for key, value in outputs.items():
            print(f'<WF_VAR>{key}:{value}</WF_VAR>')
    elif args.action == 'plan':
        plan_file=directory/'plan.json'
        source_file=directory/'planning-sources.md'
        quote_file=directory/'planning-sources-model.md'
        sources=source_file.read_text(encoding='utf-8-sig') if source_file.is_file() else ''
        if quote_file.is_file() and quote_file.read_text(encoding='utf-8-sig')!=continuity_policy.planning_quote_view(sources):
            raise ValueError('分场引用编号和冻结资料不一致，请创建新任务')
        try:
            raw_plan = read_json(plan_file)
            plan = raw_plan
            validate_plan(plan)
            if 'continuity' in plan:
                if quote_file.is_file():
                    plan={**plan,'continuity':continuity_policy.bind_planning_quotes(plan['continuity'],sources)}
                continuity_policy.validate_contract(plan['continuity'],sources,len(plan['scenes']))
        except ValueError as exc:
            from html import escape
            retry('agent_nw', '[scene_plan] 返回有效场景卡及有资料原文支持、金额与余款可复算的continuity契约。'+escape(str(exc),quote=False))
            return
        allocation_file = directory / 'allocation.json'
        if plan != raw_plan:
            if allocation_file.is_file():
                raise ValueError('已有分场绑定，不能重新换算引用编号')
            save_json(plan_file,plan)
        accepted = allocation_policy.allocate_plan(plan, bounds, allocation_policy.digest(plan_file),
            allocation_policy.digest(source_file) if 'continuity' in plan else '')
        if allocation_file.is_file() and read_json(allocation_file) != accepted:
            raise ValueError('已确认分场或篇幅分配已有变化，请创建新任务，不能复用旧场景')
        # Check every existing brief before publishing anything. A rejected legacy
        # re-plan must leave its old task readable without a half-written allocation.
        for row in accepted['scenes']:
            existing = directory / f"brief-{row['slot']}.json"
            if existing.is_file() and read_json(existing) != allocation_policy.scene_brief(plan, row):
                raise ValueError('已确认或历史场景卡已有变化，请创建新任务')
        if not allocation_file.is_file():
            save_json(allocation_file, accepted)
        for row in accepted['scenes']:
            slot = row['slot']
            brief = allocation_policy.scene_brief(plan, row)
            name = f'brief-{slot}.json'
            save_json(directory / name, brief)
            print(f'<WF_VAR>multi_brief_{slot}:{relative}/{name}</WF_VAR>')
            retry_name = f'retry-{slot}.md'
            if not (directory / retry_name).is_file():
                length.atomic_text(directory / retry_name, '')
            print(f'<WF_VAR>multi_retry_{slot}:{relative}/{retry_name}</WF_VAR>')
        active = {row['slot'] for row in accepted['scenes']}
        for slot in range(1, 6):
            print(f'<WF_VAR>multi_active_{slot}:{"yes" if slot in active else "no"}</WF_VAR>')
        print(f'<WF_VAR>multi_scene_count:{accepted["scene_count"]}</WF_VAR>')
        print(f'<WF_VAR>multi_plan_file:{relative}/plan.json</WF_VAR>')
        write_handoffs(directory,plan,accepted)
        if 'continuity' in plan:
            for row in accepted['scenes']:
                print(f'<WF_VAR>multi_handoff_{row["slot"]}:{relative}/handoff-{row["slot"]}.json</WF_VAR>')
    elif args.action == 'scene':
        if args.scene is None:
            parser.error('--scene is required for the scene check')
        if allocation and args.scene not in rows:
            raise ValueError('该执行槽未启用，不是本次分场中的场景')
        raw = (directory / f'scene-{args.scene}.txt').read_text(encoding='utf-8-sig')
        i = args.scene - 1
        problem = accept_full_scene_attempt(directory, args.scene, scene_text(raw), lo[i], hi[i], args.pov,
            allocation_policy.digest(directory / 'allocation.json') if allocation else '',
            allocation_policy.digest(directory / f'scene-{args.scene}.txt') if allocation else '',book_contract=profile)
        if problem:
            retry(WRITERS[i], problem)
    else:
        bodies = []
        slots = [r['slot'] for r in allocation['scenes']] if allocation else list(range(1, 7))
        for i in slots:
            writer = WRITERS[i-1]
            accepted_file = directory / f'validated-{i}.json'
            data = read_json(accepted_file) if accepted_file.is_file() else None
            if allocation:
                allocation_sha = allocation_policy.digest(directory / 'allocation.json')
                if data is not None and (not isinstance(data, dict) or data.get('allocation_sha256') != allocation_sha):
                    raise ValueError('已接受场景未绑定当前分场与篇幅分配，不能复用')
                source = directory / f'scene-{i}.txt'
                if not source.is_file():
                    retry(writer, '[scene_empty] 缺少本次启用场景的原始交付，请交付本场。')
                    return
                raw = source.read_text(encoding='utf-8-sig')
                source_sha = allocation_policy.digest(source)
                # A host upstream retry may leave the scene validator completed.
                # Revalidate replaced or reset drafts here before trusting its cache.
                if data is None or data.get('source_sha256') != source_sha or data.get('body') != scene_text(raw).strip():
                    issue = accept_full_scene_attempt(directory, i, scene_text(raw), lo[i-1], hi[i-1], args.pov,
                        allocation_sha, source_sha,book_contract=profile)
                    if issue:
                        retry(writer, issue)
                        return
                    data = read_json(accepted_file)
            if not (directory / f'validated-{i}.json').is_file():
                retry(writer, '[scene_empty] 缺少本次启用场景的有效正文，请交付本场。')
                return
            body = data.get('body') if isinstance(data, dict) else None
            if not isinstance(body, str) or not body.strip():
                retry(writer, '[scene_empty] 请在 body 字段提供本场完整正文。')
                return
            bodies.append(body.strip())
        error = validate(bodies, args.target, args.pov, allocation=allocation,book_contract=profile)
        if error:
            index = slots[error[0]]
            full_scene_retry(directory, index, error[1])
            retry(WRITERS[index-1], error[1])
            return
        save_json(length.safe_path(root, 'cache/si/chapter.json'), {'body': '\n\n'.join(bodies)})


if __name__ == '__main__':
    main()
