"""Compact transport, full quality judgments and exact source-bound audit evidence."""
import copy

PROTOCOL='local-review-v2'
HASHES=('candidate_sha256','book_contract_sha256','review_input_sha256')
SEMANTIC={'compatible','issues','expression_review','expression_checks','change_reviews','issue_outcomes'}


def expand(raw,context):
    if not isinstance(raw,dict):raise ValueError('审稿回复须为对象')
    if 'protocol' not in raw:return copy.deepcopy(raw)
    if raw['protocol']!=PROTOCOL or set(raw)-{'reading_checks'}!=(SEMANTIC|{'protocol'}):
        raise ValueError('精简审稿缺少语义判断或夹带绑定字段，不能自动补判')
    result=copy.deepcopy(raw);result.pop('protocol')
    expression=result['expression_review']
    if isinstance(expression,dict) and 'issues' not in expression:
        checks=result['expression_checks']
        if (expression.get('verdict')!='pass' or not isinstance(checks,list) or not checks
                or any(not isinstance(row,dict) or row.get('status') not in ('pass','not_applicable')
                       or row.get('issue_ids')!=[] for row in checks)):
            raise ValueError('表达问题列表缺失，只有明确通过且逐项没有问题时才可省略')
        expression['issues']=[]
    result.update({k:context[k] for k in HASHES})
    if not isinstance(result['change_reviews'],list):raise ValueError('须逐项审查改动')
    for row in result['change_reviews']:
        if not isinstance(row,dict) or set(row)!={'edit_index','effect','reason'}:raise ValueError('改动复核缺少判断、理由或索引')
        i=row['edit_index']
        if type(i) is not int or not 0<=i<len(context['edits']):raise ValueError('改动复核索引越界')
        edit=context['edits'][i];row.update(before_excerpt=edit['old'],after_excerpt=edit['replacement'])
    return result


def schema(legacy):
    if 'anyOf' in legacy:
        legacy=next(arm for arm in legacy['anyOf'] if 'protocol' in arm.get('properties',{}))
    compact=copy.deepcopy(legacy)
    if 'protocol' not in compact['properties']:
        for key in HASHES:compact['properties'].pop(key)
        compact['properties']['protocol']={'const':PROTOCOL}
        compact['required']=[k for k in compact['required'] if k not in HASHES]+['protocol']
        row=compact['properties']['change_reviews']['items']
        for key in ('before_excerpt','after_excerpt'):row['properties'].pop(key)
        row['required']=['edit_index','effect','reason']
    expression=compact['properties']['expression_review']
    expression['required']=[key for key in expression['required'] if key!='issues']
    compact['if']={'properties':{'expression_review':{'not':{'required':['issues']}}}}
    compact['then']={'properties':{
        'expression_review':{'properties':{'verdict':{'const':'pass'}}},
        'expression_checks':{'items':{'properties':{
            'status':{'enum':['pass','not_applicable']},'issue_ids':{'maxItems':0}}}},
    }}
    return compact
