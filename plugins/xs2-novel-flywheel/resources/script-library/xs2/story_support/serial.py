"""Book-owned volume coordination and evidence-bound rolling plans.

Plans are never history. Publication reuses the P0 journal and writes only
future planning files; neither manuscripts nor global book intent are rewritten.
"""
import argparse
from contextlib import closing
from functools import lru_cache
import importlib.util
import json
import os
import html
import hashlib
from pathlib import Path
import re


def _guarded_rejection(message):
    spec=importlib.util.spec_from_file_location('plugin_rejection_transport',Path(__file__).resolve().parents[1]/'production_guard/rejections.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value.emit(message)

@lru_cache(maxsize=1)
def support():
    spec=importlib.util.spec_from_file_location('serial_story_support',Path(__file__).with_name('story_support.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def contract(root):
    value=support().load(root,'meta/serial_contract.json')
    if value is None:return None
    if not isinstance(value,dict) or value.get('schema')!=1 or not isinstance(value.get('volumes'),list) or not value['volumes']:
        raise ValueError('长篇契约须包含有序的卷级范围')
    seen=set();end=0
    for volume in value['volumes']:
        if (not isinstance(volume,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(volume.get('id','')))
                or volume['id'] in seen or type(volume.get('start')) is not int or volume['start']!=end+1):
            raise ValueError('卷级编号或范围无效、重叠或不连续')
        finish=volume.get('end')
        if finish is not None and (type(finish) is not int or finish<volume['start'] or finish>9999):
            raise ValueError('卷末章节范围无效')
        if finish is None and volume is not value['volumes'][-1]:raise ValueError('开放卷必须位于最后')
        seen.add(volume['id']);end=finish or 9999
    planning=value.get('planning',{})
    if not isinstance(planning,dict) or planning.get('authority','bounded') not in ('bounded','review') or type(planning.get('horizon',6)) is not int or not 1<=planning.get('horizon',6)<=24:
        raise ValueError('滚动规划权限或窗口无效')
    if type(planning.get('max_input_chars',120000)) is not int or planning.get('max_input_chars',120000)<1:
        raise ValueError('滚动规划输入预算无效')
    threads=value.get('threads',[])
    if not isinstance(threads,list) or any(not isinstance(t,dict) or not isinstance(t.get('id'),str) or not t['id'] for t in threads) or len({t['id'] for t in threads})!=len(threads):
        raise ValueError('长线须有独立编号')
    if not isinstance(value.get('run_limits',{}),dict):raise ValueError('连续运行预算无效')
    for key,limit in value.get('run_limits',{}).items():
        if key not in {'max_dispatches','max_chapters','max_stage_attempts','max_elapsed_seconds'} or type(limit) is not int or limit<1:
            raise ValueError('连续运行预算无效')
    for volume in value['volumes']:
        for condition in volume.get('exit_conditions',[]):
            if condition.get('thread_id') not in {t['id'] for t in threads} or condition.get('status') not in ('advanced','resolved','intentionally_open'):
                raise ValueError('卷级承接条件须指向本书长线状态')
    return value


def bootstrap(root, state=None):
    s=support()
    if contract(root):return contract(root)
    project=state or s.load(root,'.novel-project.json',{})
    if project.get('mode')!='serial':return None
    if s.safe(root,'archive/longform.sqlite3').is_file():
        with closing(s.archive_store().connect(root)) as db:
            if db.execute("SELECT name FROM sqlite_master WHERE name='serial_runs'").fetchone() and db.execute('SELECT count(*) FROM serial_runs').fetchone()[0]:
                raise ValueError('本书已有连续运行记录但长篇契约缺失，请恢复契约，未自动重置范围或预算')
    values=project.get('values',{})
    # Existing VO is a planning hint, not author confirmation of a hard ending.
    vo=s.load(root,'cache/vo/volume.json',{})
    value={'schema':1,'volumes':[{'id':'v1','title':vo.get('title') or '当前卷','start':1,'end':None}],
        'threads':[],'planning':{'horizon':int(values.get('rolling_horizon') or 6),
                              'authority':values.get('serial_planning_authority') or 'bounded'},
        'run_limits':{'max_dispatches':10000,'max_chapters':9999,'max_stage_attempts':8},
        'origin':'existing_book_direction; volume end remains open until declared'}
    def build(write):write(root,'meta/serial_contract.json',value)
    s.archive_store().publish_views(root,build,lambda:s.source_hashes(root,include_outline=False))
    contract(root)
    return value


def history(root,chapter):
    s=support();states,stale=s.confirmed(root,before=int(chapter))
    missing=[p.parent.name for p in s.bodies(root) if int(p.parent.name)<int(chapter) and p.parent.name not in {x['chapter'] for x in states}]
    if stale or missing:raise ValueError('前文档案缺失或失效，请先复核归档再规划后续')
    return states


def status(root,chapter,states=None):
    config=contract(root)
    if not config:return {'enabled':False,'ready':True}
    s=support();chapter=s.chapter_id(chapter)
    if states is None:states=history(root,chapter)
    states=[x for x in states if int(x['chapter'])<int(chapter)]
    volume=next((v for v in config['volumes'] if v['start']<=int(chapter)<= (v.get('end') or 9999)),None)
    progress={t['id']:{'status':'unconfirmed','intent':t.get('intent','')} for t in config.get('threads',[])}
    for snapshot in states:
        for item in snapshot.get('serial_progress',[]):
            if item['thread_id'] in progress:progress[item['thread_id']]={**progress[item['thread_id']],**item,'chapter':snapshot['chapter']}
    latest=states[-1] if states else {}
    prior=[v for v in config['volumes'] if v.get('end') is not None and v['end']<int(chapter)]
    unmet=[]
    for previous in prior:
        # Evaluate at its actual closing chapter, not a later repaired outcome.
        at_end={}
        for snapshot in states:
            if int(snapshot['chapter'])>previous['end']:break
            for item in snapshot.get('serial_progress',[]):at_end[item['thread_id']]=item['status']
        unmet.extend({'volume':previous['id'],**c} for c in previous.get('exit_conditions',[]) if at_end.get(c['thread_id'])!=c['status'])
    return {'enabled':True,'ready':bool(volume) and not unmet,'reason_code':'volume_handoff_review' if unmet else ('ready' if volume else 'volume_scope_missing'),
        'volume':volume,'threads':progress,'unmet_exit_conditions':unmet,
        'entry':{'chapter':latest.get('chapter',''),'body_sha256':latest.get('body_sha256',''),
                 'archive_commit_id':latest.get('archive_commit_id',''),'characters':latest.get('characters',[]),
                 'world':latest.get('world',{}),'indexes':latest.get('indexes',{})},
        'boundary':'卷纲与滚动计划是待写意图；承接只用实际归档。悬置长线可保留，不统一要求回收或制造高潮。'}


def validate_progress(root,chapter,items,body):
    if not isinstance(items,list):raise ValueError('长线进度须为列表')
    config=contract(root);known={t['id'] for t in (config or {}).get('threads',[])}
    result=[]
    for item in items:
        if not isinstance(item,dict) or item.get('thread_id') not in known or item.get('status') not in ('advanced','resolved','intentionally_open'):
            raise ValueError('长线进度须指向本书已声明的编号和状态')
        quote=support().validated_evidence(item.get('evidence'),body,'长线进度缺少真实正文依据')
        if 'requires_replan' in item and type(item['requires_replan']) is not bool:raise ValueError('重规划标志无效')
        result.append({**item,'evidence':quote,'chapter':chapter})
    return result


def _signed_output(root,relative):
    s=support();journal=s.archive_store();actual=s.read(root,relative)
    with closing(journal.connect(root)) as db:
        rows=db.execute("SELECT content FROM publications WHERE status='complete' AND chapter='' AND instr(content,?)>0 ORDER BY rowid DESC",(relative,))
        for row in rows:
            expected=json.loads(row['content'])['outputs'].get(relative)
            if expected is not None and expected==actual:return json.loads(actual)
    raise ValueError('滚动计划缺少有效发布凭据，或文件已有变化')


def need_plan(root,chapter):
    s=support();state=status(root,chapter)
    if not state['enabled']:return {'ready':True,'enabled':False}
    if not state['ready']:return state
    number=s.chapter_id(chapter);plan=s.load(root,f'planning/chapters/{number}.json')
    if plan:
        if plan.get('origin')!='rolling':
            try:s.verify(root,plan.get('source_hashes',{}))
            except ValueError:return {'ready':False,'reason_code':'author_plan_stale','requires_author':True}
            return {'ready':True,'origin':'author'}
        try:
            _signed_output(root,f'planning/chapters/{number}.json')
            s.verify(root,plan['source_hashes'])
            if plan['book_contract_sha256']!=s.archive_store().contract(root,persistent=True):raise ValueError('契约变化')
            states=history(root,chapter);latest=states[-1] if states else {}
            for condition in plan.get('expected_state',[]):
                subject=next((c for c in latest.get('characters',[]) if c.get('entity_id')==condition.get('entity_id')),None)
                exists,value=state_value(subject,condition.get('path',''))
                if not exists or value!=condition.get('equals'):raise ValueError('实际人物状态与计划假设不同')
            base=int(plan.get('base_chapter') or 0)
            if any(p.get('requires_replan') for snap in states if int(snap['chapter'])>base for p in snap.get('serial_progress',[])):
                raise ValueError('实际发展触发重规划')
            return {'ready':True,'origin':'rolling'}
        except ValueError:return {'ready':False,'reason_code':'rolling_plan_stale'}
    return {'ready':False,'reason_code':'rolling_window_missing'}


def state_value(subject,path):
    value=subject
    for key in path.split('.'):
        if not isinstance(value,dict) or key not in value:return False,None
        value=value[key]
    return True,value


def task_path(task,name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',task):raise ValueError('滚动任务编号无效')
    return f'cache/serial/{task}/{name}'


def prepare(root,chapter,task):
    s=support();s.archive_store().recover(root);chapter=s.chapter_id(chapter)
    file=task_path(task,'request.json')
    old=s.load(root,file)
    if old:
        old=_signed_output(root,file)
        if old['chapter']!=chapter:raise ValueError('任务已绑定其他章节')
        if not s.load(root,f'planning/serial/receipts/{task}.json'):
            s.verify(root,old['source_hashes'])
            if old.get('review_contract_sha256')!=s.archive_store().contract(root):raise ValueError('本次规划要求已有变化')
        return old
    config=contract(root) or bootstrap(root)
    if not config:raise ValueError('请先建立本书长篇契约')
    states=history(root,chapter);current=status(root,chapter,states)
    if not current['ready']:raise ValueError('跨卷范围或承接条件尚待复核，未擅自扩写新卷')
    if s.read(root,f'story/{chapter}/chapter.md').strip():raise ValueError('不能重规划已写章节')
    finish=min(int(chapter)+config.get('planning',{}).get('horizon',6)-1,current['volume'].get('end') or 9999)
    for number in range(int(chapter),finish+1):
        old=s.load(root,f'planning/chapters/{number:04d}.json',{})
        if s.read(root,f'story/{number:04d}/chapter.md').strip() or (old and old.get('origin')!='rolling'):
            if number==int(chapter):raise ValueError('本章已有正文或作者采用计划，不能自动覆盖')
            finish=number-1;break
    query=current['volume'].get('intent','')+' '+current['volume'].get('title','')+' '+ ' '.join(t.get('intent','') for t in config.get('threads',[]))
    context=s.context(root,chapter,query+' 核对本卷承接、人物与未解决长线，再规划后续')
    hashes={**context['source_hashes'],'meta/serial_contract.json':s.digest(root,'meta/serial_contract.json')}
    hashes.update({relative:s.digest(root,relative) for relative in context['evidence_texts']})
    hashes.update({f"story/{x['chapter']}/confirmed_state.json":s.digest(root,f"story/{x['chapter']}/confirmed_state.json") for x in states})
    for i in range(int(chapter),finish+1):
        for input_path in (f'story/{i:04d}/chapter.md',f'planning/chapters/{i:04d}.json'):hashes[input_path]=s.digest(root,input_path)
    value={'schema':1,'task_id':task,'chapter':chapter,'finish':finish,'contract':config,
        'book_contract_sha256':s.archive_store().contract(root,persistent=True),'source_hashes':hashes,
        'review_contract_sha256':s.archive_store().contract(root),
        'base_chapter':states[-1]['chapter'] if states else '', 'serial':current,'context':context}
    spec=importlib.util.spec_from_file_location('serial_book_contract',s.HERE.parent/'prose_policy/book_contract.py')
    book=importlib.util.module_from_spec(spec);spec.loader.exec_module(book)
    prompt={'window':{'start':chapter,'end':f'{finish:04d}'},'book_contract':book.resolve(root),
        'volume':current['volume'],'threads':current['threads'],
        'entry_archive':{k:v for k,v in current['entry'].items() if k not in ('characters','world')},
        'active_state':context['state_text'],'sources':context['sources'],'memory':context['memory'],
        'boundary':current['boundary']+' 场景认知还须遵循本书时间与叙述权限。缺少依据时提出待核实项，不编造补足。'}
    if len(json.dumps(prompt,ensure_ascii=False))>config.get('planning',{}).get('max_input_chars',120000):
        raise ValueError('本次规划资料超出输入预算，请核对范围或本书规划预算，未静默截断关键资料')
    value['prompt_sha256']=s.archive_store().identity(prompt)
    prompt_file=task_path(task,'prompt.json')
    prompt_bytes=(json.dumps(prompt,ensure_ascii=False,indent=2).rstrip()+'\n').encode('utf-8')
    value['source_hashes'][prompt_file]=hashlib.sha256(prompt_bytes).hexdigest()
    publication_guards={p:h for p,h in hashes.items() if p!=prompt_file}
    def build(write):
        s.verify(root,publication_guards)
        if value['review_contract_sha256']!=s.archive_store().contract(root):raise ValueError('本次规划要求已有变化')
        write(root,file,value);write(root,prompt_file,prompt)
    s.archive_store().publish_views(root,build,lambda:publication_guards)
    return value


def normalize(root,task):
    s=support();request=_signed_output(root,task_path(task,'request.json'))
    if not request:raise ValueError('滚动规划输入缺失')
    s.verify(root,request['source_hashes'])
    if request.get('review_contract_sha256')!=s.archive_store().contract(root):raise ValueError('本次规划要求已有变化')
    candidate=s.load(root,task_path(task,'candidate.json'))
    expected=[f'{n:04d}' for n in range(int(request['chapter']),request['finish']+1)]
    if not isinstance(candidate,dict) or not isinstance(candidate.get('chapters'),list):raise ValueError('候选计划须包含 chapters')
    rows=candidate['chapters']
    if [str(p.get('chapter','')).zfill(4) for p in rows]!=expected:raise ValueError('滚动计划范围不符、重复或跨出已声明卷界')
    evidence=request['context']['evidence_texts']
    states=history(root,request['chapter']);latest=states[-1] if states else {}
    for row in rows:
        if not isinstance(row.get('intent'),str) or not row['intent'].strip():raise ValueError('章节意图缺失')
        if not isinstance(row.get('setup'),list) or not row['setup']:raise ValueError('滚动计划须有实际来源依据')
        for anchor in row['setup']:
            if anchor.get('source_id') not in evidence or not isinstance(anchor.get('quote'),str) or len(anchor['quote'].strip())<2 or anchor['quote'] not in evidence[anchor['source_id']] or anchor['quote'] not in s.read(root,anchor['source_id']):
                raise ValueError('滚动计划的原文依据无法核实')
        for condition in row.get('expected_state',[]):
            if not isinstance(condition,dict) or not condition.get('entity_id') or not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*',condition.get('path','')) or 'equals' not in condition:
                raise ValueError('状态假设须有明确人物、字段与期望值')
            subject=next((c for c in latest.get('characters',[]) if c.get('entity_id')==condition['entity_id']),None)
            exists,value=state_value(subject,condition['path'])
            if not exists:
                raise ValueError('状态假设的人物或字段路径不存在；请按真实档案完整路径，例如 snapshot.location，不使用 location 简写')
            if str(row['chapter']).zfill(4)==request['chapter'] and value!=condition['equals']:
                raise ValueError('本次起始章节的状态假设与当前可信档案不符，不能发布后立即触发重复规划')
    s.verify(root,request['source_hashes'])
    result={'candidate_sha256':s.archive_store().identity(candidate),
        'request_sha256':s.archive_store().identity(request),'candidate':candidate}
    s.write(root,task_path(task,'normalized.json'),result)
    return result


def commit(root,task,approve=False):
    s=support();journal=s.archive_store();journal.recover(root)
    receipt_path=f'planning/serial/receipts/{task}.json'
    prior=s.load(root,receipt_path)
    if prior and prior.get('status')=='accepted':return _signed_output(root,receipt_path)
    normalized=normalize(root,task);request=s.load(root,task_path(task,'request.json'))
    review=s.load(root,task_path(task,'review.json'),{})
    if review.get('candidate_sha256')!=normalized['candidate_sha256'] or review.get('request_sha256')!=normalized['request_sha256'] or review.get('verdict')!='pass' or type(review.get('scope_change')) is not bool:
        raise ValueError('独立规划验收未通过或候选版本不符')
    if request['book_contract_sha256']!=journal.contract(root,persistent=True):raise ValueError('本书契约已有变化')
    needs_author=request['contract'].get('planning',{}).get('authority','bounded')=='review' or review['scope_change']
    if needs_author and not approve:
        receipt={'task_id':task,'status':'awaiting_author',**{k:normalized[k] for k in ('candidate_sha256','request_sha256')}}
        receipt['review_sha256']=journal.identity(review)
        journal.publish_views(root,lambda write:write(root,task_path(task,'awaiting-author.json'),receipt),lambda:request['source_hashes'])
        return receipt
    pending=s.load(root,task_path(task,'awaiting-author.json'))
    if approve and pending:
        pending=_signed_output(root,task_path(task,'awaiting-author.json'))
        if any(pending.get(key)!=normalized[key] for key in ('candidate_sha256','request_sha256')) or pending.get('review_sha256')!=journal.identity(review):
            raise ValueError('待采用候选版本已有变化，请重新预览后采用')
    rows=normalized['candidate']['chapters'];targets={f"planning/chapters/{str(row['chapter']).zfill(4)}.json" for row in rows}
    for row in rows:
        number=str(row['chapter']).zfill(4)
        if s.read(root,f'story/{number}/chapter.md').strip():raise ValueError('不能覆盖已经写出的章节')
        old=s.load(root,f'planning/chapters/{number}.json',{})
        if old and old.get('origin')!='rolling':raise ValueError('不能覆盖作者已采用的未来计划')
    hashes={p:h for p,h in request['source_hashes'].items() if p not in targets and not p.startswith('cache/') and p!='outline/near_term_outline.md'
            and not (re.fullmatch(r'story/[0-9]{4}/chapter.md',p) and int(p.split('/')[1])>=int(request['chapter']))}
    publication_guards={p:h for p,h in request['source_hashes'].items() if p not in targets and p!='outline/near_term_outline.md'}
    outline=s.read(root,'outline/near_term_outline.md');old_outline=outline;blocks={}
    for row in rows:
        number=str(row['chapter']).zfill(4)
        marker=f'<!-- rolling-plan:{number} -->';end=f'<!-- /rolling-plan:{number} -->'
        pattern=re.escape(marker)+r'[\s\S]*?'+re.escape(end)
        old=s.load(root,f'planning/chapters/{number}.json',{})
        match=re.search(pattern,outline)
        if match and (old.get('origin')!='rolling' or old.get('outline_block_sha256')!=journal.identity(match.group(0))):
            raise ValueError('作者已编辑滚动规划段落，请先复核，不自动覆盖')
        outline=re.sub(pattern,'',outline)
        block=f"{marker}\n{s.render_plan({**row,'chapter':number,'goal':row['intent']})}\n{end}"
        blocks[number]=block;outline+='\n\n'+block
    outline=outline.rstrip()+'\n'
    hashes['outline/near_term_outline.md']=hashlib.sha256(outline.encode('utf-8')).hexdigest()
    receipt={'task_id':task,'status':'accepted','chapter':request['chapter'],'finish':request['finish'],
        'candidate_sha256':normalized['candidate_sha256'],'request_sha256':normalized['request_sha256'],
        'review_sha256':journal.identity(review),'book_contract_sha256':request['book_contract_sha256']}
    def build(write):
        s.verify(root,request['source_hashes'])
        if request['book_contract_sha256']!=journal.contract(root,persistent=True):raise ValueError('本书契约已有变化')
        for row in rows:
            number=str(row['chapter']).zfill(4);file=f'planning/chapters/{number}.json'
            old=s.load(root,file)
            if old:write(root,f'planning/serial/history/{task}/{number}.json',old)
            plan={**row,'chapter':number,'goal':row['intent'],'origin':'rolling','base_chapter':request['base_chapter'],
                'source_hashes':hashes,'book_contract_sha256':request['book_contract_sha256'],'serial_receipt':receipt_path,
                'outline_block_sha256':journal.identity(blocks[number])}
            write(root,file,plan)
        write(root,f'planning/serial/history/{task}/near_term_outline.md',old_outline)
        write(root,'outline/near_term_outline.md',outline)
        write(root,'planning/serial/window.json',{'task_id':task,'chapters':[str(p['chapter']).zfill(4) for p in rows]})
        for name,value in [('request.json',request),('candidate.json',normalized['candidate']),('review.json',review),('prompt.json',s.load(root,task_path(task,'prompt.json')))]:
            write(root,f'planning/serial/audit/{task}/{name}',value)
        write(root,receipt_path,receipt)
    journal.publish_views(root,build,lambda:publication_guards)
    return receipt


def verify_task(root,task):
    s=support();relative=f'planning/serial/receipts/{task}.json'
    if s.load(root,relative):
        receipt=_signed_output(root,relative)
        candidate=_signed_output(root,f'planning/serial/audit/{task}/candidate.json')
        review=_signed_output(root,f'planning/serial/audit/{task}/review.json')
        if s.archive_store().identity(candidate)!=receipt['candidate_sha256'] or s.archive_store().identity(review)!=receipt['review_sha256']:
            raise ValueError('规划验收审计版本不符')
        for number in range(int(receipt['chapter']),receipt['finish']+1):
            plan=_signed_output(root,f'planning/chapters/{number:04d}.json')
            s.verify(root,plan['source_hashes'])
        if receipt['book_contract_sha256']!=s.archive_store().contract(root,persistent=True):raise ValueError('本书契约已有变化')
        return receipt
    pending=s.load(root,task_path(task,'awaiting-author.json'))
    if pending:
        pending=_signed_output(root,task_path(task,'awaiting-author.json'))
        normalized=normalize(root,task)
        if pending.get('status')!='awaiting_author' or any(pending[key]!=normalized[key] for key in ('candidate_sha256','request_sha256')):raise ValueError('待确认计划已有变化')
        return pending
    raise ValueError('本次滚动规划缺少发布凭据')


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['bootstrap','prepare','normalize','commit','approve','status'])
    parser.add_argument('--chapter',default='0001');args=parser.parse_args(argv);root=Path.cwd();task=os.environ.get('TASK_ID','')
    if args.action=='bootstrap':result=bootstrap(root)
    elif args.action=='status':result=status(root,args.chapter)
    elif args.action=='prepare':
        result=prepare(root,args.chapter,task)
        for key,name in [('rolling_request_file','prompt.json'),('rolling_candidate_file','candidate.json'),('rolling_review_file','review.json')]:
            print(f'<WF_VAR>{key}:{task_path(task,name)}</WF_VAR>')
        for key,name in [('rolling_candidate_path','candidate.json'),('rolling_review_path','review.json')]:
            print(f'<WF_VAR>{key}:{task_path(task,name)}</WF_VAR>')
    elif args.action=='normalize':
        request=support().load(root,task_path(task,'request.json'))
        support().verify(root,request['source_hashes'])
        try:result=normalize(root,task)
        except ValueError as error:
            _guarded_rejection(f'<WF_REJECT_UPSTREAM target="agent_rolling_plan">{html.escape(str(error))}</WF_REJECT_UPSTREAM>');return
        for key in ('candidate_sha256','request_sha256'):print(f'<WF_VAR>rolling_{key}:{result[key]}</WF_VAR>')
    else:
        support().archive_store().recover(root)
        if support().load(root,f'planning/serial/receipts/{task}.json'):
            print(json.dumps(commit(root,task,approve=args.action=='approve'),ensure_ascii=False));return
        request=support().load(root,task_path(task,'request.json'))
        support().verify(root,request['source_hashes'])
        try:result=commit(root,task,approve=args.action=='approve')
        except ValueError as error:
            findings=support().load(root,task_path(task,'review.json'),{}).get('findings',[])
            detail=html.escape(str(error)+' '+json.dumps(findings,ensure_ascii=False)[:2000])
            _guarded_rejection(f'<WF_REJECT_UPSTREAM target="agent_rolling_plan">{detail}</WF_REJECT_UPSTREAM>');return
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
