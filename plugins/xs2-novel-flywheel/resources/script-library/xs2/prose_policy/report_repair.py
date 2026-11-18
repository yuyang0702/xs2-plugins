"""Narrow report repair requests; semantic conclusions are never manufactured."""
import copy


def fields(reason):
    text=str(reason)
    if any(token in text for token in ('阅读参考意见须为数组','阅读目标编号未知或重复','阅读目标缺少真实判断','阅读目标验收引文不在当前正文','阅读目标派生问题与实际判断不符','阅读目标问题编号与模型问题冲突')):return ['reading_checks']
    if any(token in text for token in ('原有实质问题未逐项复核','问题解决情况缺少','整场表达返修',
                                       '保留原句的复核')):return ['issue_outcomes']
    if '表达验收' in text or '本书声线核对' in text:return ['expression_checks']
    if '改动复核' in text or '局部改动都须独立核对' in text or '改动净效果缺少' in text:return ['change_reviews']
    return []


def request(report,context,reason):
    selected=fields(reason)
    if not selected:return None
    return {'protocol':'targeted-report-repair-v1','review_input_sha256':context['review_input_sha256'],
        'allowed_fields':selected,'previous_actual_report':copy.deepcopy(report),'error':str(reason),
        'instruction':'仅补审allowed_fields；其他字段逐字保留。仍须引用当前候选并核对真实目标ID，不能猜证据、改成pass或替换全文。若有效部分也有实质错误，应明确请求完整复审，不能隐改。'}


def verify(report,repair,context):
    if repair['review_input_sha256']!=context['review_input_sha256']:raise ValueError('局部补审来源变化，旧报告不能复用')
    allowed=set(repair['allowed_fields']);prior=repair['previous_actual_report']
    if {k:v for k,v in report.items() if k not in allowed}!={k:v for k,v in prior.items() if k not in allowed}:
        raise ValueError('局部补审改动了未授权复用字段，需要完整独立复审')


def exchange_request(report, source_sha256, exchanges):
    """Recover only objectively misfiled evidence; leave any uncertain group to the critic."""
    review = report['exchange_review']
    owners = {turn_id: key for key, group in exchanges.items() for turn_id in group['turn_ids']}
    retained = {}
    affected = set()
    misfiled = []
    for row in review['revisions']:
        key = row['exchange_id']
        if row['phase'] != 'later':
            retained[key] = row
            continue
        turns = row.get('turns') or []
        ids = [item.get('turn_id') for item in turns if isinstance(item, dict)]
        groups = {owners.get(turn_id) for turn_id in ids if isinstance(turn_id, str)}
        if groups == {key}:
            retained[key] = row
            continue
        misfiled.append(row)
        affected.update({key, *groups} & exchanges.keys())
        if len(groups) == 1 and None not in groups and len(ids) == len(turns) >= 2:
            actual = next(iter(groups))
            original = exchanges[actual]['turn_ids']
            start = original.index(ids[0])
            if original[start:start+len(ids)] == ids and row['target_turn'] in range(len(ids)) and start+row['target_turn'] >= 2:
                if actual in retained or any(other['exchange_id'] == actual for other in review['revisions']):
                    continue
                retained[actual] = {**row, 'exchange_id': actual}
    if not misfiled:
        return None
    passed = [key for key in review['passed'] if key not in affected]
    missing = [key for key in exchanges if key not in retained and key not in passed]
    return {'source_sha256': source_sha256, 'previous_actual_report': copy.deepcopy(report),
            'retained': {'passed': passed, 'revisions': list(retained.values())},
            'recheck': {key: exchanges[key]['turn_ids'] for key in missing}, 'misfiled': misfiled}


def apply_exchange_retry(report, repair, source_sha256):
    if repair['source_sha256'] != source_sha256:
        raise ValueError('对白报告的冻结原文已有变化，不能套用旧补审')
    incoming = report['exchange_review']
    recheck = repair['recheck']
    retained = repair['retained']
    return {**repair['previous_actual_report'], 'exchange_review': {
        **repair['previous_actual_report']['exchange_review'],
        'passed': retained['passed'] + [key for key in incoming['passed'] if key in recheck],
        'revisions': retained['revisions'] + [row for row in incoming['revisions'] if row['exchange_id'] in recheck],
    }}
