"""Book-owned composition budgets; plans are intent, never prose or history."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parents[1]



def _guarded_rejection(message):
    spec=importlib.util.spec_from_file_location('plugin_rejection_transport',Path(__file__).resolve().parents[1]/'production_guard/rejections.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.emit(message)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


support=load('composition_support',HERE/'story_support/story_support.py')
book=load('composition_book',HERE/'prose_policy/book_contract.py')
model_packet=load('composition_model_view',HERE/'prose_policy/context_packet.py')


def identity(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def intent(root):
    values=support.load(root,'.novel-project.json',{}).get('values',{})
    return {k:values.get(k,'') for k in ('chapter_number','target_word_count','author_feedback_file','human_intent','world_intent')}


def feedback_layers(root):
    path=intent(root)['author_feedback_file']
    local=load('composition_feedback_layers',HERE/'local_revision/local_revision.py')
    author,advice,guards=local.feedback_layers(root,path)
    if not advice and path:guards[path]=support.digest(root,path)
    selected=sorted(p for p in guards if not p.endswith('/automatic-origin.json'))
    return author,advice,selected


def policy(root):
    value=support.load(root,'meta/length_policy.json')
    if value is None:return None
    if not isinstance(value,dict) or value.get('schema')!=1 or value.get('ownership') not in ('author','planner'):
        raise ValueError('篇幅归属契约无效')
    for key in ('minimum','maximum'):
        if key in value and (type(value[key]) is not int or not 1<=value[key]<=200000):raise ValueError('作者篇幅边界无效')
    if value.get('minimum',1)>value.get('maximum',200000):raise ValueError('作者篇幅边界反序')
    return value


def folder(task):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',task):raise ValueError('篇幅规划任务编号无效')
    return f'cache/composition/{task}'


def code_profile():
    resources=HERE.parent.parent
    scripts=[Path(__file__),*sorted((HERE/'local_revision').glob('*.py')),*sorted((HERE/'prose_policy').glob('*.py'))]
    paths={'script-library/xs2/'+p.relative_to(HERE).as_posix():p for p in scripts}
    locator=load('composition_resources',HERE/'production_guard/production_guard.py')
    configs={name:locator.resource(HERE,name) for name in ('agents.json','prompts.json','workflows/mvp/definition.json','workflows/polish/definition.json')}
    return identity({name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in {**paths,**configs}.items()})


def reuse_key(request):
    data={k:v for k,v in request.items() if k not in ('task_id','request_digest','source_hashes')}
    data['source_hashes']={p:h for p,h in request['source_hashes'].items()
        if p!='.novel-project.json' and not p.startswith('cache/book-contract/')}
    return identity(data)


def runtime_profile(root):
    guard = load('composition_runtime_profile', HERE/'production_guard/production_guard.py')
    return guard.reuse_profile(root, ('agent_composition_plan', 'agent_composition_review'))


def remaining_slots(project):
    # New books persist an unstarted cursor as JSON null. Treat it like the
    # missing cursor, while retaining existing numeric/string batch semantics.
    limit=project.get('autoChapterLimit')
    started=project.get('autoChapterStarted')
    return max(0,int(9999 if limit is None else limit)-int(1 if started is None else started)+1)


def macro_guard(root):
    project=support.load(root,'.novel-project.json',{})
    progress=support.load(root,'observability/report.json',{}).get('progress',{})
    return {'target':support.load(root,'meta/longrun_contract.json',{}).get('target_new_characters'),
        'accepted':progress.get('accepted_new_characters'),
        'slots':remaining_slots(project)}


def effective(root,chapter,task=''):
    quota=current(root,chapter)
    if task and support.safe(root,folder(task)+'/reuse.json').is_file():
        receipt=support.serial()._signed_output(root,folder(task)+'/reuse.json')
        support.verify(root,receipt['source_hashes'])
        if receipt.get('code_profile')!=code_profile():raise ValueError('规划复用的代码或提示词版本已有变化')
        if receipt.get('runtime_profile')!=runtime_profile(root):raise ValueError('规划复用的实际模型或提示词已有变化')
        if receipt.get('macro_guard')!=macro_guard(root):raise ValueError('规划复用的全书实际进度已有变化')
        if not quota or identity(quota)!=receipt['quota_digest']:raise ValueError('复用的已批准篇幅已有变化')
    return {'target_word_count':f"{quota['minimum']}-{quota['maximum']}",
        'words_per_chapter':f"{quota['minimum']}-{quota['maximum']}"} if quota else {}


def sources(root,chapter):
    paths={'.novel-project.json',f'story/{chapter}/chapter.md',f'story/{chapter}/reader_report.json',f'planning/chapters/{chapter}.json',
        f'planning/composition-conflicts/{chapter}.json',
        'meta/length_policy.json','meta/longrun_contract.json','meta/narrative_contract.json','meta/serial_contract.json',
        *support.CHECKPOINT_FILES}
    state=support.load(root,'.novel-project.json',{});feedback=state.get('values',{}).get('author_feedback_file') or ''
    if feedback:
        if not support.safe(root,feedback).is_file():raise ValueError('原作者意见文件缺失')
        paths.add(feedback)
        origin=(Path(feedback).parent/'automatic-origin.json').as_posix()
        paths.add(origin)
        data=support.load(root,origin,{})
        if data.get('origin')=='automatic' and data.get('feedback_sha256')==support.digest(root,feedback):
            for row in data.get('retained_feedback_sources',[]):
                if support.digest(root,row['source_id'])!=row['sha256']:raise ValueError('原作者意见来源变化，旧自动建议不能用于规划')
                paths.add(row['source_id'])
    return {p:support.digest(root,p) for p in sorted(paths)}


def prepare(root,chapter,task,target,ownership='inherit'):
    quality=load('composition_quality',HERE/'console_service/length_quality.py')
    ownership={'沿用本书':'inherit','作者硬性范围':'author','按内容规划':'planner'}.get(ownership,ownership)
    if ownership not in ('inherit','author','planner'):raise ValueError('未知篇幅归属选项')
    if ownership!='inherit':
        previous_policy_sha=support.digest(root,'meta/length_policy.json')
        old=policy(root) or {'schema':1}
        if old.get('ownership')!=ownership:
            selected={**old,'ownership':ownership,'origin':'book_workflow_choice'}
            def check_policy():
                if support.digest(root,'meta/length_policy.json')!=previous_policy_sha:raise ValueError('作者篇幅归属并发变化')
                # P0 output CAS protects this deliberately changed file before and
                # after replay; it cannot also be an unchanged-source guard.
                return {}
            support.archive_store().publish_views(root,lambda write:write(root,'meta/length_policy.json',selected),
                check_policy)
    chapter=quality.chapter_number(chapter);config=policy(root)
    if config is None and book.resolve(root).get('reading_contract'):config={'schema':1,'ownership':'author','origin':'adopted_reading_goals'}
    if config is None:return {'enabled':False}
    values=support.load(root,'.novel-project.json',{}).get('values',{})
    hashes=sources(root,chapter);feedback=values.get('author_feedback_file') or ''
    author,advice,selected=feedback_layers(root)
    frozen=book.freeze(root,task)
    for path in (frozen['path'],frozen['prompt_file']):hashes[path]=support.digest(root,path)
    progress=support.load(root,'observability/report.json',{}).get('progress',{})
    project=support.load(root,'.novel-project.json',{})
    total=support.load(root,'meta/longrun_contract.json',{}).get('target_new_characters')
    request={'schema':1,'enabled':True,'chapter':chapter,'task_id':task,'policy':config,
        'macro_guard':macro_guard(root),
        'reuse_profile':{'code':code_profile(),'runtime':runtime_profile(root),'models':{k:v for k,v in project.items() if 'model' in k.lower()},
            'scope':{'mode':project.get('mode'),**{k:values.get(k) for k in
                ('conflict_plan_mode','chapter_ending_mode','writer_type','preparation_mode','estimated_length','learning_context')}}},
        'intent':intent(root),
        'nominal_target':target,'author_range':list(quality.target_range(target)) if target and
            (config['ownership']=='author' or target!=values.get('target_word_count','')) else None,
        'book_contract':frozen['contract'],'source_hashes':hashes,
        'body':support.read(root,f'story/{chapter}/chapter.md'),'reader_report':support.load(root,f'story/{chapter}/reader_report.json'),
        'chapter_plan':support.load(root,f'planning/chapters/{chapter}.json'),
        'author_feedback':author,'automatic_revision_advice':advice,'authored_selection':selected,
        'book_target':total,'macro_budget':{'target_new_prose':total,'accepted_new_prose':progress.get('accepted_new_characters'),
            'remaining_chapter_slots':remaining_slots(project),
            'note':'基线不计入新增目标；当前章尚未验收，未写部分继续承担余量，不按固定单章均值填充。'},
        'conflict':support.load(root,f'planning/composition-conflicts/{chapter}.json')}
    request['model_transport']='composition-view-v1'
    request['request_digest']=identity(request)
    path=folder(task)+'/request.json';old=support.load(root,path)
    if old and old!=request:raise ValueError('已冻结的篇幅规划来源变化，请创建新任务')
    if old:return old
    reuse_path=folder(task)+'/reuse.json';quota_path=f'planning/length/{chapter}.json'
    if support.safe(root,reuse_path).is_file():
        receipt=support.serial()._signed_output(root,reuse_path);effective(root,chapter,task)
        if receipt['reuse_key']!=reuse_key(request):raise ValueError('复用任务的规划依赖已有变化')
        return {'enabled':False,'reused':True,'quota_task_id':receipt['quota_task_id']}
    if support.safe(root,quota_path).is_file():
        # Signature errors are fatal. Legitimate changed dependencies are misses.
        signed=support.serial()._signed_output(root,quota_path)
        try:quota=current(root,chapter)
        except ValueError:quota=None
        if quota and signed.get('reuse_key')==reuse_key(request):
            receipt={'schema':1,'task_id':task,'quota_task_id':quota['task_id'],'quota_digest':identity(quota),
                'reuse_key':reuse_key(request),'source_hashes':hashes,'code_profile':code_profile(),
                'runtime_profile':request['reuse_profile']['runtime'],'macro_guard':macro_guard(root)}
            support.archive_store().publish_views(root,lambda write:write(root,reuse_path,receipt),
                lambda:(support.verify(root,hashes) or hashes))
            return {'enabled':False,'reused':True,'quota_task_id':quota['task_id']}
    support.write(root,path,request);return request


def validate_plan(request,plan):
    if plan.get('request_digest')!=request['request_digest']:raise ValueError('篇幅规划来源指纹不匹配')
    if plan.get('status')!='ready':raise ValueError('篇幅与本章范围存在冲突，须重新规划或确认作者范围：'+str(plan.get('reason','')))
    lo,hi=plan.get('minimum'),plan.get('maximum')
    if type(lo) is not int or type(hi) is not int or not 1<=lo<=hi<=200000:raise ValueError('规划篇幅无效')
    config=request['policy'];hard=request.get('author_range')
    if (hard and (lo,hi)!=tuple(hard)) or lo<config.get('minimum',1) or hi>config.get('maximum',200000):
        raise ValueError('不得改变作者明确的篇幅边界')
    rows=plan.get('segments')
    if not isinstance(rows,list) or not rows:raise ValueError('规划缺少有阅读作用的分段')
    ids=[]
    for row in rows:
        if any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('id','purpose','development')):
            raise ValueError('分段须说明阅读作用及如何发展，不能只改词或重复结论')
        if type(row.get('minimum')) is not int or type(row.get('maximum')) is not int or not 1<=row['minimum']<=row['maximum']:
            raise ValueError('分段篇幅无效')
        ids.append(row['id'])
    total_min,total_max=sum(r['minimum'] for r in rows),sum(r['maximum'] for r in rows)
    if len(set(ids))!=len(ids):raise ValueError('分段编号重复')
    if hard:
        if not lo<=total_min<=total_max<=hi:raise ValueError('分段建议预算须在作者整篇边界内，不能缩改作者范围或越界')
    elif total_min!=lo or total_max!=hi:raise ValueError('分段篇幅总和与章节配额不一致')
    expected={g['id'] for g in request['book_contract'].get('reading_contract',{}).get('objectives',[])}
    goals=plan.get('goal_plans',[])
    if (not isinstance(goals,list) or len(goals)!=len(expected) or {r.get('goal_id') for r in goals}!=expected):raise ValueError('规划须逐项覆盖本书已采用阅读目标')
    for row in goals:
        if (row.get('status') not in ('planned','not_applicable') or not isinstance(row.get('basis'),str) or not row['basis'].strip()
                or not isinstance(row.get('segment_ids'),list) or len(set(row['segment_ids']))!=len(row['segment_ids'])
                or not set(row['segment_ids'])<=set(ids)):raise ValueError('阅读目标缺少本书依据或有效分段')
        if row['status']=='planned' and (not row['segment_ids'] or any(not isinstance(row.get(k),str) or not row[k].strip() for k in ('reader_start','reader_end'))):raise ValueError('阅读目标须说明读者认知或期待如何发展')
    return plan


def prior_revision(request):
    """Carry diagnostics as pending material, never as author rules or facts."""
    conflict=request.get('conflict') or {};report=conflict.get('review_report') or {}
    candidate=conflict.get('rejected_candidate')
    if (not isinstance(candidate,str) or report.get('compatible') is not True
            or conflict.get('source_sha256')!=request['source_hashes'].get(f"story/{request['chapter']}/chapter.md")
            or report.get('book_contract_sha256')!=book.digest(request['book_contract'])):return None
    if report.get('candidate_sha256')!=hashlib.sha256(candidate.encode()).hexdigest():
        raise ValueError('待复核候选与历史诊断来源不符')
    evidence=load('composition_previous_evidence',HERE/'multi_scene/audit_evidence.py')
    resolved=evidence.resolve_report(report,candidate)
    issues=[r for r in (resolved.get('expression_review') or {}).get('issues',[]) if r.get('priority') in ('medium','high')]
    return {'task_id':conflict.get('task_id'),'source_sha256':conflict['source_sha256'],
        'book_contract_sha256':report['book_contract_sha256'],'candidate':candidate,
        'candidate_sha256':report['candidate_sha256'],'remaining_issues':issues,
        'note':'上一轮未验收材料；可参考已有改进和剩余诊断，但不是事实档案、作者新要求或通过凭据。按当前原稿、每书契约和本轮预算重新核验。'}


def accept(root,task,plan,review):
    request=support.load(root,folder(task)+'/request.json')
    if identity({k:v for k,v in request.items() if k!='request_digest'})!=request['request_digest']:raise ValueError('冻结规划请求已有变化')
    if request['intent']!=intent(root):raise ValueError('作者篇幅、章节或意见选择变化，不能发布旧规划')
    if request.get('reuse_profile',{}).get('code') not in (None,code_profile()):raise ValueError('规划请求的代码或提示词版本已有变化')
    if 'runtime' in request.get('reuse_profile',{}) and request['reuse_profile']['runtime'] != runtime_profile(root):
        raise ValueError('规划请求的实际模型或提示词已有变化')
    if request.get('macro_guard') is not None and request['macro_guard']!=macro_guard(root):raise ValueError('全书实际进度变化，规划须重新核对')
    support.verify(root,request['source_hashes']);validate_plan(request,plan)
    if (review.get('request_digest')!=request['request_digest'] or review.get('plan_digest')!=identity(plan)
            or review.get('verdict')!='approve' or review.get('scope_preserved') is not True or review.get('length_feasible') is not True):
        raise ValueError('独立篇幅规划复查未通过或来源不符')
    checks=review.get('checks',[]);ids=[r['id'] for r in plan['segments']]
    if (len(checks)!=len(ids) or {r.get('segment_id') for r in checks}!=set(ids)
            or any(r.get('develops_function') is not True or not r.get('style_basis') or not r.get('reason') for r in checks)):
        raise ValueError('各段阅读作用或本书风格依据未通过独立复查')
    if book.resolve(root)!=request['book_contract']:raise ValueError('本书规则在规划时变化')
    expected={g['id'] for g in request['book_contract'].get('reading_contract',{}).get('objectives',[])}
    goals=review.get('goal_checks',[])
    if (not isinstance(goals,list) or len(goals)!=len(expected) or {r.get('goal_id') for r in goals}!=expected
            or any(r.get('supported') is not True or not isinstance(r.get('reason'),str) or not r['reason'].strip()
                or not isinstance(r.get('style_basis'),str) or not r['style_basis'].strip() for r in goals)):raise ValueError('阅读目标规划缺少独立复查的本书风格与依据')
    number=request['chapter'];path=f'planning/length/{number}.json'
    stable={p:h for p,h in request['source_hashes'].items() if p in support.CHECKPOINT_FILES or p in (
        'meta/length_policy.json','meta/narrative_contract.json',f'planning/chapters/{number}.json')}
    if feedback_layers(root)[2]!=request['authored_selection']:raise ValueError('原作者意见来源分类变化')
    for source_id in request['authored_selection']:stable[source_id]=request['source_hashes'][source_id]
    quota={'schema':1,'chapter':number,'task_id':task,'minimum':plan['minimum'],'maximum':plan['maximum'],
        'plan':plan,'review':review,'request_digest':request['request_digest'],'stable_sources':stable,
        'book_contract_sha256':support.archive_store().contract(root,persistent=True),
        'author_intent':{k:v for k,v in request['intent'].items() if k in ('target_word_count','human_intent','world_intent')},
        'authored_selection':request['authored_selection'],'prior_revision':prior_revision(request),'reuse_key':reuse_key(request)}
    if expected:quota['reading_contract_sha256']=identity(request['book_contract']['reading_contract'])
    def guards():
        support.verify(root,request['source_hashes']);return request['source_hashes']
    support.archive_store().publish_views(root,lambda write:write(root,path,quota),guards)
    return quota


def current(root,chapter):
    reading=book.resolve(root).get('reading_contract')
    if policy(root) is None and not reading:return None
    path=f'planning/length/{chapter}.json'
    if not support.safe(root,path).is_file():return None
    quota=support.serial()._signed_output(root,path)
    if quota.get('reading_contract_sha256')!=(identity(reading) if reading else None):raise ValueError('本书阅读目标变化，已批准规划须重新审查')
    support.verify(root,quota['stable_sources'])
    current_intent={k:v for k,v in intent(root).items() if k in ('target_word_count','human_intent','world_intent')}
    if quota['author_intent']!=current_intent or quota['authored_selection']!=feedback_layers(root)[2]:
        raise ValueError('作者篇幅或原意见选择变化，旧章节预算不再生效')
    if quota['book_contract_sha256']!=support.archive_store().contract(root,persistent=True):raise ValueError('本书规则契约变化，篇幅预算须重排')
    return quota


def schemas():
    text={'type':'string','minLength':1};integer={'type':'integer','minimum':1,'maximum':200000}
    def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    plan=obj({'request_digest':text,'status':{'enum':['ready','needs_scope']},'reason':text,'minimum':integer,'maximum':integer,
        'segments':{'type':'array','minItems':1,'items':obj({'id':text,'purpose':text,'development':text,'minimum':integer,'maximum':integer})}})
    review=obj({'request_digest':text,'plan_digest':text,'verdict':{'enum':['approve','revise','needs_scope']},
        'scope_preserved':{'type':'boolean'},'length_feasible':{'type':'boolean'},'reason':text,
        'checks':{'type':'array','items':obj({'segment_id':text,'develops_function':{'type':'boolean'},'style_basis':text,'reason':text})}})
    plan['properties']['goal_plans']={'type':'array','items':obj({'goal_id':text,'status':{'enum':['planned','not_applicable']},
        'segment_ids':{'type':'array','items':text},'reader_start':text,'reader_end':text,'basis':text})}
    review['properties']['goal_checks']={'type':'array','items':obj({'goal_id':text,'supported':{'type':'boolean'},'style_basis':text,'reason':text})}
    return plan,review


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','candidate','commit','emit','bypass'])
    parser.add_argument('--chapter',default='0001');parser.add_argument('--target',default='');parser.add_argument('--dir',default='')
    parser.add_argument('--ownership',default='inherit')
    args=parser.parse_args();root=Path.cwd();task=os.environ.get('TASK_ID','');out={}
    if args.action=='prepare':
        request=prepare(root,args.chapter,task,args.target,args.ownership);enabled=request['enabled']
        out={'composition_enabled':'yes' if enabled else 'no','composition_reused':'yes' if request.get('reused') else 'no'}
        if enabled:
            base=folder(task);out.update(composition_dir=base,composition_request_file=base+'/request.json',
                composition_request_model=base+'/request-model.json',composition_review_model=base+'/review-model.json',
                composition_plan_file=base+'/plan.json',composition_review_input=base+'/review-input.json',composition_review_file=base+'/review.json',
                composition_feedback_file=base+'/feedback.md')
            if not support.safe(root,base+'/feedback.md').exists():support.write(root,base+'/feedback.md','')
            support.write(root,base+'/request-model.json',model_packet.composition(request))
    elif args.action=='candidate':
        request=support.load(root,args.dir+'/request.json');plan=support.load(root,args.dir+'/plan.json')
        if request.get('model_transport'):model_packet.verify_composition(support.load(root,args.dir+'/request-model.json'),request)
        if json.loads(sys.stdin.read())!=plan:raise ValueError('规划文件不是本次实际模型输出')
        support.verify(root,request['source_hashes'])
        try:validate_plan(request,plan)
        except ValueError as exc:
            if plan.get('status')=='needs_scope':raise
            support.write(root,args.dir+'/feedback.md',str(exc))
            _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_composition_plan">规划篇幅或来源字段错误，请依冻结资料修正JSON。</WF_REJECT_UPSTREAM>');return
        support.write(root,args.dir+'/review-input.json',{'request':request,'plan':plan,'request_digest':request['request_digest'],'plan_digest':identity(plan)})
        support.write(root,args.dir+'/review-model.json',model_packet.composition(support.load(root,args.dir+'/review-input.json')))
    elif args.action=='commit':
        plan=support.load(root,args.dir+'/plan.json');review=support.load(root,args.dir+'/review.json')
        if json.loads(sys.stdin.read())!=review:raise ValueError('篇幅复查文件不是本次实际模型输出')
        request=support.load(root,args.dir+'/request.json');support.verify(root,request['source_hashes'])
        packet=support.load(root,args.dir+'/review-input.json')
        if request.get('model_transport'):model_packet.verify_composition(support.load(root,args.dir+'/review-model.json'),packet)
        if packet['plan_digest']!=identity(plan):
            try:validate_plan(request,plan)
            except ValueError as exc:
                if plan.get('status')=='needs_scope':raise
                support.write(root,args.dir+'/feedback.md',str(exc))
                _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_composition_plan">变更后的规划字段不一致，请按冻结目标与实际分段修正，不改来源。</WF_REJECT_UPSTREAM>');return
            support.write(root,args.dir+'/review-input.json',{'request':request,'plan':plan,'request_digest':request['request_digest'],'plan_digest':identity(plan)})
            support.write(root,args.dir+'/review-model.json',model_packet.composition(support.load(root,args.dir+'/review-input.json')))
            _guarded_rejection('<WF_REJECT_UPSTREAM target="agent_composition_review">方案变化，已重建输入，请复查当前方案。</WF_REJECT_UPSTREAM>');return
        if review.get('verdict')=='needs_scope':raise ValueError('内容和作者范围冲突，未放宽要求。')
        try:accept(root,task,plan,review)
        except ValueError as exc:
            support.verify(root,request['source_hashes'])
            if book.resolve(root)!=request['book_contract']:raise
            target='agent_composition_plan' if review.get('verdict')=='revise' else 'agent_composition_review'
            support.write(root,args.dir+'/feedback.md',str(exc)+'\n'+json.dumps(review,ensure_ascii=False))
            _guarded_rejection('<WF_REJECT_UPSTREAM target="'+target+'">按冻结来源修正规划或独立复查，不能直接放行。</WF_REJECT_UPSTREAM>');return
    elif args.action=='emit':
        out=effective(root,args.chapter,task)
    for k,v in out.items():print('<WF_VAR>'+k+':'+v+'</WF_VAR>')
    print(json.dumps({'status':'completed','action':args.action},ensure_ascii=False))


if __name__=='__main__':main()
