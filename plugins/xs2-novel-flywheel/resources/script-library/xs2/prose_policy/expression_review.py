"""Ground expression judgements in current prose and the book's chosen style."""
import copy

DIMENSIONS=('semantic_increment','constraint_transcription','imagery_function','dialogue_function','ending_function','voice_alignment')
CATEGORIES=('action_dilation','object_inventory','scripted_dialogue','semantic_redundancy',
            'generic_imagery','explanatory_psychology','ending_overstatement','constraint_transcription','voice_flattening')

GUIDANCE='''逐项提交expression_checks，每项包含dimension、status(pass/issue/not_applicable)、excerpts、reason、style_basis、issue_ids。
维度：semantic_increment核对相邻动作、对白、心理、比喻与总结是否重复同一信息；constraint_transcription核对后台账本、选择分析或修订意见是否被直译进正文；imagery_function判断意象与此人此景的关系；dialogue_function判断对话在当前交流中的作用；ending_function判断结尾是否再次解释已完成的选择；voice_alignment核对本书声线与修改前的有效表达。
每项解释实际阅读作用，并联系本书风格。pass也给当前原文依据，不能只说本书允许就免检；issue必须指向实际issues编号，并说明已成立的信息、此处是否有新变化及影响。无对应内容才用not_applicable，voice_alignment始终适用。引用可选当前evidence_catalog编号。
有意回环、议论、心理、技术说明、华丽意象、全知与安静场景可以成立。比喻多、语句整齐或出现某个词不构成问题；风格允许也不能为同义复述自动免责。不要以第三方检测分数、禁词、标点或固定句长判断质量。
检查解决问题的净效果：补动机不能变成替人物答辩，补技术因果不能变成完整科普，删去重复不能换成同义说明或无关动作填回。保留充分的读者理解依据，不能为含蓄隐去真实争点。'''


def schema(excerpt_schema=None):
    excerpt=excerpt_schema or {'type':'string','minLength':1}
    return {'type':'array','minItems':len(DIMENSIONS),'maxItems':len(DIMENSIONS),'items':{
        'type':'object','required':['dimension','status','excerpts','reason','style_basis','issue_ids'],
        'properties':{'dimension':{'enum':list(DIMENSIONS)},'status':{'enum':['pass','issue','not_applicable']},
            'excerpts':{'type':'array','items':copy.deepcopy(excerpt)},'reason':{'type':'string','minLength':1},
            'style_basis':{'type':'string','minLength':1},'issue_ids':{'type':'array','items':{'type':'string','minLength':1},'uniqueItems':True}},
        'additionalProperties':False}}


def validate_checks(report,body,required=False):
    if 'expression_checks' not in report:
        if required:raise ValueError('表达验收缺少逐维度原文与文风依据')
        return []
    rows=report['expression_checks']
    if not isinstance(rows,list) or len(rows)!=len(DIMENSIONS):raise ValueError('表达验收维度缺失或重复')
    resolved={r.get('issue_id') for r in report.get('blind_resolutions',[]) if isinstance(r,dict)}
    issues=[*report.get('issues',[]),*report.get('expression_review',{}).get('issues',[]),
            *[r for r in report.get('blind_review',{}).get('issues',[]) if r.get('id') not in resolved]]
    known={r.get('id') for r in issues if isinstance(r,dict) and isinstance(r.get('id'),str)}
    seen=set()
    for row in rows:
        if (not isinstance(row,dict) or row.get('dimension') not in DIMENSIONS or row['dimension'] in seen
                or row.get('status') not in ('pass','issue','not_applicable')
                or any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('reason','style_basis'))):
            raise ValueError('表达验收缺少有效维度、阅读作用或本书风格依据')
        seen.add(row['dimension']);quotes=row.get('excerpts');ids=row.get('issue_ids')
        if (not isinstance(quotes,list) or any(not isinstance(q,str) or not q.strip() or q not in body for q in quotes)
                or (row['status']!='not_applicable' and not quotes)):
            raise ValueError('表达验收引文不在当前正文，不能用风格标签代替原文依据')
        if row['dimension']=='voice_alignment' and row['status']=='not_applicable':raise ValueError('本书声线核对不能跳过')
        if (not isinstance(ids,list) or any(not isinstance(k,str) for k in ids) or len(ids)!=len(set(ids))
                or any(k not in known for k in ids) or (row['status']=='issue')!=bool(ids)):
            raise ValueError('表达验收问题编号不存在或与维度结论不一致')
    return copy.deepcopy(rows)
