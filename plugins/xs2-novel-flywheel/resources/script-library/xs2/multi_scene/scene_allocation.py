"""Logical scene plans and reference draft allocations, independent of worker slots."""
import hashlib
import json

MAX_SLOTS = 6
LEGACY_WEIGHTS = (14, 16, 17, 20, 19, 14)


def weighted_bounds(bounds, weights):
    if (not isinstance(weights, (list, tuple)) or not 1 <= len(weights) <= MAX_SLOTS
            or any(type(w) is not int or not 1 <= w <= 100 for w in weights)
            or not bounds or bounds[0] < len(weights)):
        raise ValueError('场景权重须为1—100的正整数，场数不能超过六个执行槽')
    total_weight = sum(weights)
    def distribute(total):
        result, used = [], 0
        for weight in weights:
            result.append(total * (used + weight) // total_weight - total * used // total_weight)
            used += weight
        return result
    lower = [1 + n for n in distribute(bounds[0] - len(weights))]
    upper = [a + b for a, b in zip(lower, distribute(bounds[1] - bounds[0]))]
    return lower, upper


def validate_plan(data):
    rows = data.get('scenes') if isinstance(data, dict) else None
    fields = ('entry', 'turn', 'exit', 'knowledge')
    if (not isinstance(data, dict) or not isinstance(data.get('focus'), str) or not data['focus'].strip()
            or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SLOTS
            or any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != i
                   or any(not isinstance(row.get(k), str) or not row[k].strip() for k in fields)
                   for i, row in enumerate(rows, 1))):
        raise ValueError('[scene_plan] 提供1—6个连续编号的场景及入场、变化、交棒和知识边界')
    for row in rows:
        names = row.get('rehearsal_cast', [])
        if (not isinstance(names, list) or len(names) not in (0, 2, 3)
                or any(not isinstance(name, str) or not name.strip() for name in names)
                or len(set(names)) != len(names)):
            raise ValueError('[scene_plan] 试演名单为空或含两到三位不重复的出场人物')
    current = 'plan_reason' in data or any('weight' in r or 'budget_reason' in r for r in rows)
    if not current:
        if len(rows) != MAX_SLOTS:
            raise ValueError('[scene_plan] 新分场须提供场数理由、相对权重与篇幅理由')
        return True  # An explicit historical six-scene plan remains readable.
    if (not isinstance(data.get('plan_reason'), str) or not data['plan_reason'].strip()
            or any(type(r.get('weight')) is not int or not 1 <= r['weight'] <= 100
                   or not isinstance(r.get('budget_reason'), str) or not r['budget_reason'].strip() for r in rows)):
        raise ValueError('[scene_plan] 新分场须逐项提供正整数权重和具体篇幅理由')
    return False


def allocate_plan(data, bounds, plan_sha, sources_sha=''):
    legacy = validate_plan(data)
    weights = list(LEGACY_WEIGHTS) if legacy else [row['weight'] for row in data['scenes']]
    lower, upper = weighted_bounds(bounds, weights)
    slots = list(range(1, len(weights))) + [MAX_SLOTS]
    rows = []
    for i, (slot, a, b, weight) in enumerate(zip(slots, lower, upper, weights), 1):
        rows.append({'slot': slot, 'scene_id': i, 'weight': weight,
                     'nominal_minimum': a, 'nominal_maximum': b,
                     'minimum': max(1, (a * 65 + 99) // 100) if legacy else 1,
                     'maximum': (b * 165 + 99) // 100, 'draft_target': (a + b) // 2,
                     'budget_reason': data['scenes'][i-1].get('budget_reason', '历史六场预算'),
                     'is_final': i == len(weights)})
    return {'schema': 1, 'legacy': legacy, 'scene_count': len(rows), 'target_range': list(bounds),
            'plan_sha256': plan_sha, 'scenes': rows,
            **({'sources_sha256':sources_sha} if 'continuity' in data else {})}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scene_brief(plan, row):
    return {**plan['scenes'][row['scene_id']-1],
            **{key:value for key,value in row.items() if key != 'scene_id'}, 'focus':plan['focus'],
            **({'continuity':plan['continuity']} if 'continuity' in plan else {})}


def read_allocation(directory, bounds):
    file = directory / 'allocation.json'
    if not file.is_file():
        plan_file = directory / 'plan.json'
        if plan_file.is_file() and not validate_plan(json.loads(plan_file.read_text(encoding='utf-8-sig'))):
            raise ValueError('当前分场缺少已确认篇幅分配，不能作为历史六场继续')
        return None
    actual = json.loads(file.read_text(encoding='utf-8-sig'))
    plan_file = directory / 'plan.json'
    data = json.loads(plan_file.read_text(encoding='utf-8-sig'))
    expected = allocate_plan(data, bounds, digest(plan_file),digest(directory/'planning-sources.md') if 'continuity' in data else '')
    if actual != expected:
        raise ValueError('分场或篇幅分配已有变化，不能复用旧正文，请创建新任务')
    for row in expected['scenes']:
        brief = directory / f"brief-{row['slot']}.json"
        if not brief.is_file() or json.loads(brief.read_text(encoding='utf-8-sig')) != scene_brief(data,row):
            raise ValueError('场景卡已有变化或缺失，不能复用原分场绑定')
    return actual
