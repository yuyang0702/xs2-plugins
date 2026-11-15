"""Optional reading suggestions from references selected for the book."""
import copy
import hashlib
import json
from pathlib import Path

QUESTIONS={
    'opening_promise':'开篇提出了什么值得继续阅读的问题或期待，是否有本书风格下的具体依据？',
    'information_release':'信息显露、误判与后续理解是否有正文依据，是否遵守本书叙述权限？',
    'relationship_progression':'人物选择、关系或情绪是否发生了有依据的变化？',
    'payoff':'前文核心期待是否按本篇范围得到回应，余味是否与本书选择一致？',
    'voice':'叙述口吻是否具体且符合本书声音，是否保留有作用的心理、议论、回环或留白？',
    'custom':'本书选择的阅读目标是否由当前正文支持？'}
GUIDANCE=('reading_contract里的蒸馏阅读目标是参考。reading_checks可省略，或只对有实际阅读价值的条目留言。'
    '每项交goal_id、status(pass/revise/not_applicable)、priority(low/medium/high)、excerpts、reason、style_basis。'
    'pass/revise须引当前正文。revise只产生建议；未使用参考写法不影响验收。若另有实质问题，用当前原文独立说明其损害。'
    '区分作者、人物、叙述者和读者的信息；有意不可靠叙述、慢热或无反转本身不是错误。'
    '不固定第一人称、句长、反转数量、高潮或段长，不在正文复述检查项。')


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def definitions(items):
    if not isinstance(items,list) or len(items)>8:raise ValueError('阅读目标须为至多8项的数组')
    result=[]
    for row in items:
        if not isinstance(row,dict) or set(row)-{'dimension','intent','planning_question','acceptance_question','limits'}:raise ValueError('阅读目标包含未知字段')
        if row.get('dimension') not in QUESTIONS:raise ValueError('阅读目标维度无效')
        if any(not isinstance(row.get(k),str) or not row[k].strip() or len(row[k])>800 for k in ('intent','planning_question','acceptance_question')):raise ValueError('阅读目标缺少可迁移目标、规划问题或验收问题')
        limits=row.get('limits',[])
        if not isinstance(limits,list) or any(not isinstance(v,str) or not v.strip() or len(v)>800 for v in limits):raise ValueError('阅读目标使用边界无效')
        value={**row,'limits':limits}
        if value not in result:result.append(copy.deepcopy(value))
    return result


def abstract_definitions(items,source_texts):
    """Apply the same source-copy boundary before normalization and adaptation."""
    rows=definitions(items)
    for row in rows:
        for value in [row['intent'],row['planning_question'],row['acceptance_question'],*row['limits']]:
            if any(value[i:i+20] in source for source in source_texts for i in range(max(0,len(value)-19))):
                raise ValueError('阅读目标包含连续20字来源原文，请抽象后再迁移')
    return rows


def for_book(root):
    root=Path(root).resolve();active=root/'learning/active.json'
    if not active.is_file():return None
    entry=json.loads(active.read_text(encoding='utf-8-sig'));relative=entry.get('blueprint_path','');path=(root/relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root/'learning/blueprints'):raise ValueError('采用蓝图路径无效')
    blueprint=json.loads(path.read_text(encoding='utf-8-sig'))
    if digest(blueprint)!=entry.get('blueprint_sha256'):raise ValueError('本书已采用蓝图变化，阅读目标未生效')
    selected=blueprint.get('selected_candidate_ids',[]);mechanisms=blueprint.get('mechanisms',[])
    if not any(row.get('reading_objectives') for row in mechanisms):return None # Legacy blueprints need no new identity fields.
    if selected!=[r.get('candidate_id') for r in mechanisms] or len(set(selected))!=len(selected):raise ValueError('采用目标与显式选择记录不一致')
    objectives=[]
    for item in mechanisms:
        if item.get('dimension') == 'topic':
            continue
        for row in definitions(item.get('reading_objectives',[])):
            objectives.append({'id':'reading-'+digest([item['candidate_id'],row])[:20],**row,
                'source_candidate_id':item['candidate_id'],'application_scope':item.get('application_scope') or ['general']})
            if item.get('dimension'):
                objectives[-1]['source_dimension'] = item['dimension']
    return {'schema':1,'blueprint_sha256':entry['blueprint_sha256'],'objectives':objectives,
        'boundary':'阅读目标是作者选择的效果和核对依据，不是原作剧情、本书已发生事实或统一文风。'} if objectives else None


def public(contract):
    return {'schema':1,'objectives':[{'id':g['id'],'dimension':g['dimension'],'question':QUESTIONS[g['dimension']],
        'application_scope':g.get('application_scope',['general'])} for g in contract.get('objectives',[])
        if g['dimension']!='custom' and not g.get('source_dimension')]}


def schema(excerpt=None):
    return {'type':'array','items':{'type':'object','required':['goal_id','status','priority','excerpts','reason','style_basis'],
        'properties':{'goal_id':{'type':'string','minLength':1},'status':{'enum':['pass','revise','not_applicable']},
            'priority':{'enum':['low','medium','high']},'excerpts':{'type':'array','items':copy.deepcopy(excerpt or {'type':'string','minLength':1})},
            'reason':{'type':'string','minLength':1},'style_basis':{'type':'string','minLength':1}},'additionalProperties':False}}


def validate_checks(report,body,contract):
    if contract is None:return []
    expected={g['id']:g for g in contract.get('objectives',[])};rows=report.get('reading_checks',[])
    if not isinstance(rows,list):raise ValueError('阅读参考意见须为数组')
    seen=set();issues=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('goal_id') not in expected or row['goal_id'] in seen:raise ValueError('阅读目标编号未知或重复')
        seen.add(row['goal_id'])
        if (row.get('status') not in ('pass','revise','not_applicable') or row.get('priority') not in ('low','medium','high')
                or any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('reason','style_basis'))):raise ValueError('阅读目标缺少真实判断、原因或本书风格依据')
        quotes=row.get('excerpts')
        if (not isinstance(quotes,list) or any(not isinstance(q,str) or not q.strip() or q not in body for q in quotes)
                or (row['status']!='not_applicable' and not quotes)):raise ValueError('阅读目标验收引文不在当前正文')
        if row['status']=='revise':
            goal=expected[row['goal_id']]
            issues.append({'id':'reading-issue-'+row['goal_id'],'source':'reading_contract','kind':'expression',
                'location':goal.get('dimension','reading'),'priority':'low','excerpts':quotes,
                'impact':row['reason'],'goal':goal.get('intent') or goal.get('question') or '按本书目标调整阅读作用。'})
    return issues


def without_unrequested_checks(report, contract):
    """Discard optional model notes when this book supplied no reference goals."""
    if (isinstance(report,dict) and 'reading_checks' in report
            and not (contract or {}).get('objectives')):
        return {key:value for key,value in report.items() if key!='reading_checks'}
    return report


def delivered_candidates(root, chapter, contract):
    if not contract:
        return []
    root = Path(root).resolve()
    body = root / f'story/{chapter}/chapter.md'
    if not body.is_file() or not body.resolve().is_relative_to(root):
        return []
    body_sha = hashlib.sha256(body.read_bytes()).hexdigest()
    delivered = []
    for stage in ('mvp', 'polish'):
        path = root / f'learning/receipts/chapters/{chapter}/{stage}.json'
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        receipt = json.loads(path.read_text(encoding='utf-8-sig'))
        if (receipt.get('chapter') != chapter or
                receipt.get('body_sha256') != body_sha or
                receipt.get('blueprint_sha256') != contract['blueprint_sha256']):
            continue
        delivered.extend(receipt.get('candidate_ids', []))
        delivered.extend(row['reference_id'] for row in receipt.get('dialogue', {}).get('matches', []))
    return list(dict.fromkeys(delivered))


def legacy_book_view(book):
    if not book.get('reading_contract'):
        return book
    contract = book['reading_contract']
    objectives = [goal for goal in contract['objectives'] if not goal.get('source_dimension')]
    if len(objectives) == len(contract['objectives']):
        return book
    view = {key: value for key, value in book.items() if key != 'reading_contract'}
    if objectives:
        view['reading_contract'] = {**contract, 'objectives': objectives}
    return view


def application_receipt(root, chapter, body, report, contract):
    """Distinguish a delivered suggestion from an effect located in current prose."""
    delivered = delivered_candidates(root, chapter, contract)
    if not delivered:
        return None
    validate_checks(report, body, contract)
    comments = {row['goal_id']: row for row in report.get('reading_checks', [])}
    items = []
    for candidate in delivered:
        matches = [comments[goal['id']] for goal in contract['objectives']
                   if goal['source_candidate_id'] == candidate and goal['id'] in comments]
        evidence = list(dict.fromkeys(quote for row in matches if row['status'] == 'pass'
                                     for quote in row['excerpts']))
        status = 'observed' if evidence else ('reviewed' if matches else 'unreviewed')
        items.append({'candidate_id': candidate, 'status': status, 'excerpts': evidence})
    return {'chapter': chapter, 'blueprint_sha256': contract['blueprint_sha256'], 'items': items}


def apply(report,body,contract):
    if contract is None:return report
    result=copy.deepcopy(report);generated=validate_checks(result,body,contract);by_id={r['id']:r for r in generated};kept=[]
    for row in result.get('issues',[]):
        if row.get('source')=='reading_contract':
            expected=by_id.get(row.get('id'))
            if not expected or any(row.get(k)!=v for k,v in expected.items() if k!='priority'):raise ValueError('阅读目标派生问题与实际判断不符')
        else:
            if row.get('id') in by_id:raise ValueError('阅读目标问题编号与模型问题冲突')
            kept.append(row)
    result['issues']=kept+generated
    return advisory_report(result)


def advisory_report(report):
    """Read previously saved reports under the current reference policy."""
    if not isinstance(report,dict):return report
    issues=report.get('issues')
    if not isinstance(issues,list):return report
    def from_reference(row):
        return isinstance(row,dict) and row.get('kind')=='expression' and (
            row.get('source')=='reading_contract' or row.get('source')=='blind_review'
            and str(row.get('id','')).startswith('blind-reading-issue-'))
    if not any(from_reference(row) for row in issues):return report
    result={**report,'issues':[{**row,'priority':'low'} if from_reference(row) else row for row in issues]}
    if (result.get('verdict')=='revise'
            and all(isinstance(row,dict) and row.get('priority')=='low' for row in result['issues'])
            and all(result.get(key,{}).get('verdict','pass')=='pass' for key in ('fact_review','expression_review'))):
        result['verdict']='pass'
        if result.get('quality_verdict')=='revise':result['quality_verdict']='pass'
    return result
