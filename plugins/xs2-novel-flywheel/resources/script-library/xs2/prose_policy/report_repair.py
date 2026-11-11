"""Narrow report repair requests; semantic conclusions are never manufactured."""
import copy


def fields(reason):
    text=str(reason)
    if any(token in text for token in ('已采用阅读目标未逐项验收','阅读目标编号未知或重复','阅读目标缺少真实判断','阅读目标验收引文不在当前正文','阅读目标派生问题与实际判断不符','阅读目标问题编号与模型问题冲突')):return ['reading_checks']
    if '原有实质问题未逐项复核' in text or '问题解决情况缺少' in text:return ['issue_outcomes']
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
