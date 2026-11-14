"""Task-bound local content revision; only reviewed exact patches publish prose."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape

HERE=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
quality=load('local_revision_length',HERE/'console_service/length_quality.py')
book=load('local_revision_book',HERE/'prose_policy/book_contract.py')
patches=load('local_revision_patch',HERE/'draft_guard/revision_patch.py')
expression=load('local_revision_expression',HERE/'prose_policy/expression_review.py')
evidence=load('local_revision_evidence',HERE/'multi_scene/audit_evidence.py')
packet=load('local_revision_model_view',HERE/'prose_policy/context_packet.py')
wire=load('local_revision_wire',HERE/'prose_policy/review_wire.py')
pending=load('local_revision_pending',HERE/'local_revision/pending_revision.py')
guard=load('local_revision_execution_guard',HERE/'production_guard/production_guard.py')
report_repair=load('local_revision_report_repair',HERE/'prose_policy/report_repair.py')


class Retry(ValueError):
    def __init__(self,target,reason):super().__init__(reason);self.target=target


class CompositionConflict(ValueError):pass


def refresh_retry_budget(root,target):
    if os.environ.get('TASK_ID') and os.environ.get('WORKFLOW_ID'):
        guard.request_budget(root,target)


def conflict_packet(b,source,payload,reason,quotes,measured=None):
    if payload.get('source_sha256')!=b['body_sha256'] or not isinstance(reason,str) or not reason.strip():
        raise ValueError('重规划冲突缺少冻结原文和逐字证据')
    quotes=patches.exact_evidence(source['source_body'],quotes)
    return {'schema':1,'kind':'content_length_conflict','task_id':b['task_id'],'chapter':b['chapter_number'],
        'source_sha256':b['body_sha256'],'binding_digest':digest(b),'patch_digest':digest(payload),
        'reason':reason,'evidence':quotes,'measurement':measured,'no_publication':True}


def raise_conflict(root,b,source,payload,reason,quotes,measured=None,extras=None):
    packet=conflict_packet(b,source,payload,reason,quotes,measured)
    if extras:packet.update(extras)
    save(safe(root,b['outputs']['revision_dir']+'/composition-conflict.json'),packet)
    raise CompositionConflict('CONTENT_LENGTH_CONFLICT：已保留来源，须重新规划阅读作用与篇幅，不能向同一写手要求补字。')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(data):return sha(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,data):quality.atomic_text(p,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def save_model(p,data,role):
    view=packet.local(data,role)
    if (data.get('writer_view_version')==packet.FOCUSED_WRITER_VERSION
            or data.get('critic_view_version')==packet.COMPACT_CRITIC_VERSION):
        quality.atomic_text(p,json.dumps(view,ensure_ascii=False,separators=(',',':'))+'\n')
    else:
        save(p,view)
def safe(root,path):return quality.safe_path(root,path)


def state(root):
    p=safe(root,'.novel-project.json');s=read(p) if p.is_file() else {};v=s.get('values',{})
    return {'chapter_number':str(v.get('chapter_number','0001')).zfill(4),
            'author_feedback_file':str(v.get('author_feedback_file') or '').strip(),
            'target_word_count':str(v.get('target_word_count') or '')}


def feedback_layers(root,path):
    if not path:return '', '', {}
    raw=safe(root,path).read_bytes();text=raw.decode('utf-8-sig')
    origin_path=(Path(path).parent/'automatic-origin.json').as_posix();p=safe(root,origin_path)
    origin=read(p) if p.is_file() else {}
    if origin.get('origin')!='automatic' or origin.get('feedback_sha256')!=sha(raw):return text,'',{}
    rows=origin.get('retained_feedback_sources')
    if not isinstance(rows,list):raise ValueError('自动建议缺少原作者意见来源')
    guards={origin_path:sha(p.read_bytes())}
    for row in rows:
        file=safe(root,row['source_id'])
        if not file.is_file() or sha(file.read_bytes())!=row['sha256'] or file.read_text(encoding='utf-8-sig')!=row['text']:
            raise ValueError('原作者意见来源已经变化')
        guards[row['source_id']]=row['sha256']
    return '\n\n'.join(row['text'] for row in rows),text,guards


def retained_feedback_sources(root,path):
    _,_,sources=feedback_layers(root,path)
    paths=[source for source in sources if not source.endswith('/automatic-origin.json')] if sources else ([path] if path else [])
    return [{'source_id':source,'sha256':sha(safe(root,source).read_bytes()),'text':safe(root,source).read_text(encoding='utf-8-sig')}
            for source in paths]


def source_files(root,chapter,context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None):
    paths={safe(root,f'story/{chapter}/chapter.md')}
    for folder in ('meta','outline'):
        paths.update(p for p in safe(root,folder).rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for directory in safe(root,'story').glob('[0-9][0-9][0-9][0-9]'):
        if int(directory.name)<=int(chapter):
            paths.update(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for name in (context_path,f'story/{chapter}/reader_report.json',f'planning/chapters/{chapter}.json',
                 f'planning/length/{chapter}.json','meta/length_policy.json',
                 'learning/active_context.md','learning/character_center/preferences.json','learning/prose_policy/policy.json'):
        paths.add(safe(root,name))
    if reference_path:paths.add(safe(root,reference_path))
    feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback:
        p=safe(root,feedback)
        if not p.is_file():raise ValueError('作者意见文件缺失，不能忽略后继续修订')
        paths.add(p)
        for relative in feedback_layers(root,feedback)[2]:paths.add(safe(root,relative))
    result={}
    for p in sorted(paths):
        relative=p.relative_to(Path(root).resolve()).as_posix();p=safe(root,relative)
        result[relative]=sha(p.read_bytes()) if p.is_file() else None
    return result


def locations(folder):
    return {'revision_dir':folder,'revision_source_file':folder+'/source.md','revision_source_input':folder+'/source-input.json',
            'revision_input':folder+'/editor-input.json','revision_patch_path':folder+'/patches.json',
            'revision_review_input':folder+'/review-input.json','revision_review_path':folder+'/review.json',
            'revision_feedback_file':folder+'/feedback.md','revision_source_model':folder+'/source-model.json',
            'revision_editor_model':folder+'/editor-model.json','revision_review_model':folder+'/review-model.json',
            'revision_review_expanded':folder+'/review-expanded.json','revision_review_repair':folder+'/review-repair.json'}


def prepare(root,chapter,task_id,target='',context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None,*,dialogue_check=False,dialogue_check_version=1):
    root=Path(root).resolve();chapter=quality.chapter_number(chapter)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',task_id or ''):raise ValueError('局部修订缺少有效任务编号')
    frozen=book.freeze(root,task_id);folder=f'cache/local-revision/{task_id}';out=locations(folder)
    body_path=f'story/{chapter}/chapter.md';raw=safe(root,body_path).read_bytes();body=raw.decode('utf-8')
    if not body.strip():raise ValueError('局部修订需要非空原文')
    planner=load('local_composition',HERE/'composition_plan/composition_plan.py')
    fixed=planner.fixed_edit(root,chapter,task_id)
    bounds=tuple(fixed['edit']['bounds']) if fixed else quality.resolve_target(root,target)
    report_path=safe(root,f'story/{chapter}/reader_report.json');report=read(report_path) if report_path.is_file() else None
    if report and report.get('body_sha256')!=sha(raw):report=None
    shared=safe(root,context_path);feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback and not safe(root,feedback).is_file():raise ValueError('本次作者意见文件缺失，不能忽略后继续修订')
    if fixed and feedback!=fixed['feedback_path']:raise ValueError('本轮作者意见与单句删除的篇幅凭据不同')
    confirmed=shared.read_text(encoding='utf-8-sig') if shared.is_file() else ''
    for title,path in (('本书已确认人物对白适配','meta/character_voice_adaptations.md'),('本次已采用抽象参考',reference_path)):
        if path and safe(root,path).is_file():confirmed+='\n\n## '+title+'\n'+book.policy().effective_text(root,path)
    authored,automatic,_=feedback_layers(root,feedback)
    composition=None if fixed else planner.current(root,chapter)
    prior=(composition or {}).get('prior_revision')
    if prior and (prior.get('source_sha256')!=sha(raw) or prior.get('book_contract_sha256')!=frozen['sha256']):prior=None
    if composition:composition={k:v for k,v in composition.items() if k!='prior_revision'}
    source={'source_body':body,'source_sha256':sha(raw),'paragraphs':patches.paragraphs(body),
            'book_contract':frozen['contract'],'book_contract_sha256':frozen['sha256'],
            'author_feedback':authored,'automatic_revision_advice':automatic,'composition_plan':composition,'prior_revision':prior,
            'confirmed_context':confirmed,
            'reader_report':report,'length':quality.measurement(raw,chapter,bounds)}
    previous=safe(root,folder+'/source-binding.json')
    previous_source=read(safe(root,out['revision_source_input'])) if previous.exists() else None
    if dialogue_check and not fixed and (previous_source is None or previous_source.get('dialogue_check')):
        source['dialogue_check']=True
        version=dialogue_check_version if previous_source is None else previous_source.get('dialogue_check_version',1)
        if version>1:source['dialogue_check_version']=version
    if not previous.exists() or read(safe(root,out['revision_source_input'])).get('critic_view_version')==packet.COMPACT_CRITIC_VERSION:
        source['critic_view_version']=packet.COMPACT_CRITIC_VERSION
    if fixed:source['fixed_edit']=fixed['edit']
    elif previous_source is None or previous_source.get('precision_review_version')==2:
        candidates=packet.precision().review_candidates(body, source['paragraphs'])
        source['precision_review_version']=2
        if candidates:source['precision_candidates']=candidates
    elif 'precision_candidates' in previous_source:
        source['precision_candidates']=previous_source['precision_candidates']
    binding={'schema':1,'task_id':task_id,'chapter_number':chapter,'body_path':body_path,'body_sha256':sha(raw),
             'book_contract_sha256':frozen['sha256'],'state':state(root),'context_path':context_path,'reference_path':reference_path,'feedback_path':feedback,
             'files':source_files(root,chapter,context_path,reference_path,feedback),
             'source_digest':digest(source),'bounds':bounds,'outputs':out}
    if previous.exists() and read(previous)!=binding:raise ValueError('同任务修订来源已有变化，请新建任务')
    save(safe(root,out['revision_source_input']),source);save(safe(root,out['revision_input']),source)
    save_model(safe(root,out['revision_source_model']),source,'critic')
    quality.atomic_text(safe(root,out['revision_source_file']),body);save(previous,binding)
    p=safe(root,out['revision_feedback_file'])
    if not p.exists():quality.atomic_text(p,'')
    if not safe(root,out['revision_review_repair']).exists():save(safe(root,out['revision_review_repair']),{})
    return out


def bound(root,folder,accepted_sha=None):
    b=read(safe(root,folder+'/source-binding.json'));source=read(safe(root,b['outputs']['revision_source_input']))
    if digest(source)!=b['source_digest'] or sha(safe(root,b['outputs']['revision_source_file']).read_bytes())!=b['body_sha256']:
        raise ValueError('冻结原文或本书规则上下文已变化，未发布')
    if b['outputs'].get('revision_source_model'):
        packet.verify(read(safe(root,b['outputs']['revision_source_model'])),source,'critic')
    if state(root)!=b['state'] or book.digest(book.resolve(root))!=b['book_contract_sha256']:
        raise ValueError('本书规则、作者意见选择或目标已变化，未发布')
    current=source_files(root,b['chapter_number'],b['context_path'],b['reference_path'],b['feedback_path'])
    if accepted_sha and current.get(b['body_path'])==accepted_sha:current[b['body_path']]=b['body_sha256']
    if current!=b['files']:raise ValueError('正文、作者意见或已确认资料已有变化，未发布')
    if source.get('fixed_edit'):
        planner=load('local_composition',HERE/'composition_plan/composition_plan.py')
        fixed=planner.fixed_edit(root,b['chapter_number'],b['task_id'],accepted_sha)
        if not fixed or fixed['edit']!=source['fixed_edit']:raise ValueError('作者指定删句的篇幅凭据已有变化')
    book.freeze(root,b['task_id'])
    return b,source


def goals(source,critique):
    rows=[]
    for row in (source.get('reader_report') or {}).get('issues',[]):
        if row.get('priority') in ('medium','high'):
            rows.append({'id':'reader-'+str(row.get('id') or len(rows)),'goal':row.get('goal',''),'excerpts':row.get('excerpts',[])})
    indices=set(critique.get('blocking_issues',[]))
    indices.update(i for i,r in enumerate(critique.get('issues',[])) if r.get('severity') in ('medium','high'))
    for i in sorted(indices):
        row=critique['issues'][i];rows.append({'id':f'critic-{i}','goal':row.get('suggestion') or row.get('description',''),
            'excerpts':row.get('evidence',[])})
    prior=source.get('prior_revision') or {}
    for i,row in enumerate(prior.get('remaining_issues',[])):
        excerpts=[q for q in row.get('excerpts',[]) if isinstance(q,str) and q and q in source.get('source_body','')]
        if excerpts and row.get('goal'):
            rows.append({'id':f'prior-{i}','goal':row['goal'],'excerpts':excerpts})
    return rows


def precision_goals(source,checks):
    expected={row['paragraph_id']:row['details'] for row in source['precision_candidates']}
    paragraphs={row['id']:row for row in source['paragraphs']}
    if not isinstance(checks,list) or any(not isinstance(row,dict) for row in checks):
        raise ValueError('报数候选须逐项提交判断')
    ids=[row.get('paragraph_id') for row in checks]
    if any(not isinstance(key,str) for key in ids) or len(ids)!=len(set(ids)) or not expected.keys()<=set(ids):
        raise ValueError('报数候选须逐项提交判断：'+', '.join(expected))
    result=[]
    for row in checks:
        key=row['paragraph_id'];action=row.get('action');remove=row.get('remove');reason=row.get('reason')
        if (key not in paragraphs or action not in ('keep','revise','outside_scope') or not isinstance(reason,str) or not reason.strip()
                or not isinstance(remove,list) or any(not isinstance(item,str) or item not in paragraphs[key]['text']
                    or not packet.precision().detail_keys(item) for item in remove)
                or (action=='revise')!=bool(remove)):
            raise ValueError('报数候选判断不完整：'+key)
        if (source.get('precision_review_version')==2 and action=='outside_scope'
                and not (source.get('author_feedback') or '').strip()):
            raise ValueError('本轮没有范围限制，不能跳过数字验收：'+key)
        if action=='revise':
            paragraph=paragraphs[key]
            result.append({'id':'precision-'+key,'goal':'省去可替代的精确值 '+ '、'.join(remove)+'。'+reason,
                           'excerpts':[paragraph['text']],'paragraph_id':key,'remove':remove})
    return result


def check_precision_goals(source,edits,goals):
    rows={row['id']:row['text'] for row in source['paragraphs']}
    precision=packet.precision()
    removed=[]
    for goal in goals:
        if not goal['id'].startswith('precision-'):continue
        key=goal['paragraph_id']
        paragraph=rows[key]
        # Apply only the edits that belong to the frozen source paragraph. Other
        # speakers and unrelated scenes may legitimately use the same values.
        scoped=[{**edit,'paragraph_id':'p0001'} for edit in edits if edit['paragraph_id']==key]
        if scoped and not (len(scoped)==1 and scoped[0]['old']==paragraph and not scoped[0]['replacement'].strip()):
            paragraph=patches.apply_patches(paragraph,{'source_sha256':sha(paragraph.encode()),'edits':scoped})
        elif scoped:
            paragraph=''
        keys=precision.detail_keys(' '.join(goal['remove']))
        if keys & precision.detail_keys(paragraph):
            raise ValueError('返修目标 '+goal['id']+' 的确数仍在：'+'、'.join(goal['remove'])+'。'+goal['goal'])
        removed.append((rows[key],goal['remove']))
    if removed and source.get('precision_review_version')==2:
        body=source['source_body']
        after=patches.apply_patches(body,{'source_sha256':sha(body.encode()),'edits':edits})
        precision.check_removed(body,after,removed)


def dialogue_goals(source, checks):
    if not isinstance(checks,list) or not checks or any(not isinstance(row,dict) for row in checks):
        raise ValueError('须提交对白验收结论，有对白时逐字引出接话，有范围限制时说明')
    version=source.get('dialogue_check_version',1)
    focused=version>=2
    required={'literal_echo','situational_speech'}
    new_checks={'checklist_exchange','scripted_delivery'}
    if version>=4:new_checks.add('voice_contrast')
    if version>=3:required.update(new_checks)
    if focused:
        labels=[row.get('focus') for row in checks]
        if (any(label not in (*required,'other') for label in labels)
                or any(labels.count(label)!=1 for label in required)):
            raise ValueError('须逐项提交对白验收：'+', '.join(sorted(required)))
    paragraphs=source['paragraphs']
    indices={row['id']:index for index,row in enumerate(paragraphs)}
    targets=[]
    seen=set()
    for number,check in enumerate(checks,1):
        status,reason,goal,turns=(check.get(key) for key in ('status','reason','goal','turns'))
        focus=check.get('focus')
        if (status not in ('pass','revise','not_applicable') or not isinstance(reason,str) or not reason.strip()
                or not isinstance(goal,str) or not isinstance(turns,list) or (status=='revise')!=bool(goal.strip())):
            raise ValueError('对白验收须有判断与具体理由，返修项须给出可执行目标')
        if status=='not_applicable':
            if turns or (not focused and len(checks)!=1):raise ValueError('不适用仅用于当前范围没有可核对的对白')
            continue
        minimum=1 if version>=3 and focus=='scripted_delivery' else 2
        if not minimum<=len(turns)<=3 or any(not isinstance(turn,dict) for turn in turns):
            raise ValueError('须引用当前对白；单向讲话可引用一段原话，其余须对照两到三处。')
        offsets=[];quotes=[];scope=[]
        for turn in turns:
            key,quote=turn.get('paragraph_id'),turn.get('quote')
            if not isinstance(key,str) or key not in indices or not isinstance(quote,str) or not quote.strip():
                raise ValueError('对白引文须绑定冻结原文段落')
            index=indices[key];row=paragraphs[index]
            speech=re.finditer(r'“[^”]+”|「[^」]+」|『[^』]+』|"[^"\r\n]+"|(?m:^\s*[—–-]+[^\r\n]+)',row['text'])
            positions=[match.start()+match[0].find(quote) for match in speech if quote in match[0]]
            start=next((row['start']+pos for pos in positions if not offsets or row['start']+pos>=offsets[-1]),None)
            if not positions:raise ValueError('对白引文须逐字出自指定段落的台词')
            if start is None:raise ValueError('对白引文须按正文顺序，且不可重叠')
            offsets.append(start+len(quote));quotes.append(quote);scope.append(index)
        identity=(focus,tuple(offsets)) if version>=3 else tuple(offsets)
        if not expression._distinct_quotes(quotes) or identity in seen:
            raise ValueError('对白验收须使用不同原句，同一组只提交一次')
        seen.add(identity)
        if status=='revise':
            target={'id':f'dialogue-{number}','goal':goal,'excerpts':quotes,
                    'paragraph_ids':[row['id'] for row in paragraphs[scope[0]:scope[-1]+1]],'turns':turns}
            if focused:
                index=check.get('target_turn')
                if type(index) is not int or not 0<=index<len(turns):raise ValueError('对白返修须标明要改的目标原话')
                target.update(focus=focus,target=turns[index])
            if version>=3 and focus in new_checks:
                preserve=check.get('preserve')
                if not isinstance(preserve,list) or not preserve or any(not isinstance(s,str) or not s.strip() for s in preserve):
                    raise ValueError('新对白返修目标须说明需要保留的信息、交际用途或有效口气。')
                target['preserve']=preserve
            targets.append(target)
    return targets


def check_dialogue_goals(edits, goals, source):
    paragraphs={row['id']:row['text'] for row in source['paragraphs']}
    for goal in goals:
        if not goal['id'].startswith('dialogue-'):continue
        if 'target' in goal:
            key,quote=(goal['target'][name] for name in ('paragraph_id','quote'))
            original=paragraphs[key]
            scoped=[{**edit,'paragraph_id':'p0001'} for edit in edits if edit['paragraph_id']==key]
            if not scoped:
                revised=original
            elif len(scoped)==1 and scoped[0]['old']==original and not scoped[0]['replacement'].strip():
                revised=''
            else:
                revised=patches.apply_patches(original,{'source_sha256':sha(original.encode()),'edits':scoped})
            if revised.count(quote)>=original.count(quote):
                raise ValueError('对白返修目标 '+goal['id']+' 仍保留目标原话：'+quote+'。'+goal['goal'])
            continue
        if not any(edit['paragraph_id'] in goal['paragraph_ids'] and edit['old']!=edit['replacement'] for edit in edits):
            raise ValueError('对白返修目标 '+goal['id']+' 尚未修改原对话：'+goal['goal'])


def writer_input(root,folder,critique_path):
    b,source=bound(root,folder);p=safe(root,critique_path);critique=read(p)
    targets=goals(source,critique)
    if source.get('precision_candidates'):
        try:targets+=precision_goals(source,critique.get('precision_checks',[]))
        except ValueError as exc:
            reason='precision_review_format: '+str(exc)
            guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
            raise Retry('agent_sc',reason) from exc
    if source.get('dialogue_check'):
        try:targets+=dialogue_goals(source,critique.get('dialogue_checks'))
        except ValueError as exc:
            reason='dialogue_review_format: '+str(exc)
            guard.retry(root,'local-revision/'+b['task_id'],'agent_sc',reason)
            raise Retry('agent_sc',reason) from exc
    data={**source,'critique':critique,'goals':targets,
          'length_edit_budget':patches.length_edit_budget(quality.count_prose(source['source_body']),b['bounds'])}
    prior=safe(root,folder+'/editor-binding.json')
    previous=read(prior) if prior.is_file() else None
    if previous is None or previous['input_sha256']!=digest(data):
        data['writer_view_version']=packet.FOCUSED_WRITER_VERSION
        references=('meta/story_plan.md','meta/character_profiles.md','meta/character_voice_adaptations.md',b['reference_path'])
        data['writer_references']={path:book.policy().effective_text(root,path) for path in dict.fromkeys(references)
                                   if path and safe(root,path).is_file()}
    review_version=packet.COMPACT_REVIEW_VERSION if previous is None else previous.get('reviewer_view_version')
    if review_version is not None:data['reviewer_view_version']=review_version
    receipt={'critique_path':critique_path,'critique_sha256':sha(p.read_bytes()),'input_sha256':digest(data)}
    if 'reviewer_view_version' in data:receipt['reviewer_view_version']=data['reviewer_view_version']
    if previous is not None and previous!=receipt:raise ValueError('本轮自审或编辑输入已有变化，请新建任务')
    save(safe(root,b['outputs']['revision_input']),data);save(prior,receipt)
    if b['outputs'].get('revision_editor_model'):save_model(safe(root,b['outputs']['revision_editor_model']),data,'writer')
    return b['outputs']


def editor_bound(root,b):
    folder=b['outputs']['revision_dir'];receipt=read(safe(root,folder+'/editor-binding.json'))
    data=read(safe(root,b['outputs']['revision_input']))
    if digest(data)!=receipt['input_sha256'] or sha(safe(root,receipt['critique_path']).read_bytes())!=receipt['critique_sha256']:
        raise ValueError('自审或冻结编辑输入已有变化，未发布')
    if b['outputs'].get('revision_editor_model'):
        packet.verify(read(safe(root,b['outputs']['revision_editor_model'])),data,'writer')
    return data


def compose(root,b,source):
    data=editor_bound(root,b);payload=read(safe(root,b['outputs']['revision_patch_path']))
    if payload.get('status')=='needs_replan':
        if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:
            raise ValueError('冲突响应不能夹带未审核正文补丁')
        raise_conflict(root,b,source,payload,payload.get('reason'),payload.get('evidence'))
    working=pending.current(root,b,digest)
    merged=pending.merge(source['source_body'],(working or {}).get('edits',[]),payload['edits'],patches)
    # A prior equivalent judgment grants only removal, never publication. The
    # native append-only event binds the exact proposals and original review.
    for event in guard.store().events(root):
        pruning=event['data']
        if (event['kind']=='equivalent_prune' and pruning.get('task_id')==b['task_id']
                and pruning.get('binding_digest')==digest(b) and pruning.get('merged_digest')==digest(merged)):
            old=pruning['review_context'];raw=pruning['review_report']
            reasons=review_decision(raw,old);expanded=wire.expand(raw,old)
            removable=equivalent_indices(expanded,old,reasons)
            if removable!=pruning['indices']:raise ValueError('等价撤回凭据与原始判断不符')
            merged=[edit for index,edit in enumerate(merged) if index not in removable]
    candidate=patches.apply_patches(source['source_body'],{'source_sha256':payload['source_sha256'],'edits':merged},protected_phrases=source['book_contract']['protected_phrases'])
    if any(row['id'].startswith('precision-') for row in data['goals']):check_precision_goals(source,merged,data['goals'])
    check_dialogue_goals(merged,data['goals'],source)
    if source.get('fixed_edit') and sha(candidate.encode())!=source['fixed_edit']['candidate_sha256']:
        raise ValueError('候选超出作者指定的单句删除范围')
    measured=quality.measurement(candidate.encode(),b['chapter_number'],b['bounds'])
    if measured['status'] not in ('pass','unconfigured'):
        path=safe(root,b['outputs']['revision_dir']+'/length-candidates.json');history=read(path) if path.is_file() else []
        key=sha((digest(payload)+':'+str(safe(root,b['outputs']['revision_patch_path']).stat().st_mtime_ns)).encode())
        if key not in [r['key'] for r in history]:history.append({'key':key,'patch_digest':digest(payload),'measurement':measured})
        save(path,history)
        # Repeated measurements do not prove a reading-function/scope conflict.
        # The caller retains the hard length gate and bounded classified retry.
        raise ValueError('候选篇幅未达作者目标：'+json.dumps(measured,ensure_ascii=False))
    context={'task_id':b['task_id'],'source_body':source['source_body'],'source_sha256':b['body_sha256'],'candidate':candidate,
             'candidate_sha256':sha(candidate.encode()),'book_contract':source['book_contract'],
             'book_contract_sha256':b['book_contract_sha256'],'confirmed_context':source['confirmed_context'],
             'author_feedback':source['author_feedback'],'goals':data['goals'],'edits':merged,
             'patch_digest':digest(payload),'evidence_catalog':evidence.catalog(candidate),'length':measured}
    if data.get('writer_view_version')==packet.FOCUSED_WRITER_VERSION:
        context.update(writer_view_version=packet.FOCUSED_WRITER_VERSION,reader_report=source['reader_report'],
                       critique=data['critique'])
    if source.get('precision_review_version')==2:context['precision_review_version']=2
    if 'reviewer_view_version' in data:context['reviewer_view_version']=data['reviewer_view_version']
    context['review_input_sha256']=digest(context)
    return context


def candidate(root,folder):
    b,source=bound(root,folder)
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except CompositionConflict:raise
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',str(exc))
        raise Retry('agent_pl',str(exc)) from exc
    save(safe(root,b['outputs']['revision_review_input']),context)
    if b['outputs'].get('revision_review_repair'):
        active=repair_record(root,b,context)
        save(safe(root,b['outputs']['revision_review_repair']),active or {})
    if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),context,'reviewer')
    return b['outputs']


def repair_record(root,b,context):
    rows=[r['data'] for r in guard.store().events(root) if r['kind']=='local_report_repair'
          and r['data'].get('task_id')==b['task_id'] and r['data'].get('binding_digest')==digest(b)
          and r['data'].get('review_input_sha256')==context['review_input_sha256']]
    return rows[-1]['repair'] if rows else None


def save_repair(root,b,context,repair):
    guard.store().event(root,'local_report_repair',{'task_id':b['task_id'],'binding_digest':digest(b),
        'review_input_sha256':context['review_input_sha256'],'repair':repair,
        'ordinal':len(guard.store().events(root))})
    if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),repair or {})


def review_decision(report,context):
    report=wire.expand(report,context)
    for key in ('candidate_sha256','book_contract_sha256','review_input_sha256'):
        if report.get(key)!=context[key]:raise ValueError('独立复查与当前候选或本书规则不匹配：'+key)
    report=evidence.resolve_report(report,context['candidate'])
    if type(report.get('compatible')) is not bool or not isinstance(report.get('issues'),list):raise ValueError('独立复查缺少事实结论')
    reasons=[];source=context['source_body']+'\n'+context['confirmed_context']+'\n'+context['author_feedback']+'\n'+book.prompt(context['book_contract'])
    reading_issues=book.reading().validate_checks(report,context['candidate'],context['book_contract'].get('reading_contract',{}))
    reasons += [r['impact']+'；'+r['goal'] for r in reading_issues if r['priority'] in ('medium','high')]
    for issue in report['issues']:
        if (not isinstance(issue,dict) or any(not isinstance(issue.get(k),str) or not issue[k].strip() for k in ('id','candidate_quote','source_quote','reason'))
                or issue['candidate_quote'] not in context['candidate'] or issue['source_quote'] not in source):raise ValueError('事实复查缺少候选与冻结来源的逐字依据')
        reasons.append(issue['reason'])
    if report['compatible']!= (not report['issues']):raise ValueError('事实结论与问题列表不一致')
    temp={'verdict':'pass','issues':[],'fact_review':{'verdict':'pass','summary':'独立事实复查'},'expression_review':copy.deepcopy(report.get('expression_review'))}
    quality.expression_gate(temp,context['candidate']);expression.validate_checks(report,context['candidate'],required=True)
    reasons += [r['impact']+'；'+r['goal'] for r in temp['issues'] if r['priority'] in ('medium','high')]
    changes=report.get('change_reviews')
    if not isinstance(changes,list) or len(changes)!=len(context['edits']):raise ValueError('每项局部改动都须独立核对净效果')
    seen=set()
    for row in changes:
        index=row.get('edit_index')
        if type(index) is not int or not 0<=index<len(context['edits']) or index in seen:raise ValueError('改动复核编号缺失或重复')
        seen.add(index);edit=context['edits'][index]
        if (row.get('effect') not in ('improved','equivalent','regressed') or not isinstance(row.get('reason'),str) or not row['reason'].strip()
                or not isinstance(row.get('before_excerpt'),str) or not row['before_excerpt'] or row['before_excerpt'] not in edit['old']
                or not isinstance(row.get('after_excerpt'),str) or (edit['replacement'] and (not row['after_excerpt'] or row['after_excerpt'] not in edit['replacement']))
                or (not edit['replacement'] and row['after_excerpt'])):raise ValueError('改动净效果缺少原句与替换文本依据')
        if row['effect']!='improved':reasons.append('改动未改善或损害原表达：'+row['reason'])
    outcomes=report.get('issue_outcomes');expected={r['id'] for r in context['goals']}
    if not isinstance(outcomes,list) or {r.get('id') for r in outcomes}!=expected or len(outcomes)!=len(expected):raise ValueError('原有实质问题未逐项复核')
    for row in outcomes:
        if (row.get('status') not in ('resolved','remaining','not_applicable') or not isinstance(row.get('reason'),str) or not row['reason'].strip()
                or not isinstance(row.get('excerpts'),list) or not row['excerpts']
                or any(not isinstance(q,str) or not q or q not in context['candidate'] for q in row['excerpts'])):raise ValueError('问题解决情况缺少当前候选原文依据')
        if row['status']=='remaining':reasons.append('原有问题仍未解决：'+row['reason'])
        if row['id'].startswith('dialogue-') and row['status']=='not_applicable':
            reasons.append('已定位的对白目标须用候选原文说明解决效果：'+row['reason'])
    return reasons


def equivalent_indices(report,context,reasons):
    rows=report['change_reviews']
    equivalent=[r for r in rows if r['effect']=='equivalent']
    # Other defects or a grouped/moved/dependent edit require writer attention.
    if not equivalent or len(reasons)!=len(equivalent):return []
    if any(r['effect']=='regressed' for r in rows):return []
    if any(context['edits'][r['edit_index']].get('independent') is not True
           or context['edits'][r['edit_index']].get('group_id') for r in equivalent):return []
    return sorted(r['edit_index'] for r in equivalent)


def commit(root,folder,expected_review):
    execution_fence=guard.assert_current(root)
    b=read(safe(root,folder+'/source-binding.json'));saved=read(safe(root,b['outputs']['revision_review_input']))
    b,source=bound(root,folder,accepted_sha=saved['candidate_sha256'])
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except CompositionConflict:raise
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl',str(exc))
        raise Retry('agent_pl',str(exc)) from exc
    if context!=saved:
        # The host retries the writer without resetting intermediate completed
        # nodes. Rebuild here and force a fresh reviewer before publication.
        if saved.get('review_input_sha256')!=digest({k:v for k,v in saved.items() if k!='review_input_sha256'}):
            raise ValueError('冻结复查输入已有变化，未发布')
        save(safe(root,b['outputs']['revision_review_input']),context)
        if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),context,'reviewer')
        if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),repair_record(root,b,context) or {})
        refresh_retry_budget(root,'agent_local_review')
        raise Retry('agent_local_review','候选补丁已有变化，已重建复查输入；请独立复查新候选，旧报告不能发布')
    if b['outputs'].get('revision_review_model'):
        packet.verify(read(safe(root,b['outputs']['revision_review_model'])),context,'reviewer')
    report=read(safe(root,b['outputs']['revision_review_path']))
    actual_matches=False
    try:actual_matches=isinstance(expected_review,str) and json.loads(expected_review)==report
    except (ValueError,TypeError):pass
    try:
        if not actual_matches:raise ValueError('复查文件与本任务实际模型输出不一致')
        active=repair_record(root,b,context)
        if b['outputs'].get('revision_review_repair') and read(safe(root,b['outputs']['revision_review_repair']))!=(active or {}):
            raise ValueError('局部补审资料与可信运行凭据不一致')
        if active:report_repair.verify(report,active,context)
        reasons=review_decision(report,context)
        expanded=wire.expand(report,context)
    except (ValueError,KeyError,TypeError) as exc:
        if actual_matches:
            targeted=report_repair.request(report,context,str(exc))
            if targeted:save_repair(root,b,context,targeted)
            elif '需要完整独立复审' in str(exc):save_repair(root,b,context,None)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_local_review',str(exc))
        raise Retry('agent_local_review',str(exc)) from exc
    if b['outputs'].get('revision_review_expanded'):save(safe(root,b['outputs']['revision_review_expanded']),expanded)
    removable=equivalent_indices(expanded,context,reasons)
    if removable:
        guard.store().event(root,'equivalent_prune',{'task_id':b['task_id'],'binding_digest':digest(b),
            'merged_digest':digest(context['edits']),'indices':removable,'review_context':context,'review_report':report})
        fresh=compose(root,b,source)
        save(safe(root,b['outputs']['revision_review_input']),fresh)
        if b['outputs'].get('revision_review_model'):save_model(safe(root,b['outputs']['revision_review_model']),fresh,'reviewer')
        if b['outputs'].get('revision_review_repair'):save(safe(root,b['outputs']['revision_review_repair']),{})
        refresh_retry_budget(root,'agent_local_review')
        raise Retry('agent_local_review','已撤回无依赖的等价改动，重新组装并检查篇幅；须独立复查新候选，原结论未改写')
    if reasons:
        pending.retain(root,b,source,context,report,expanded,digest,patches)
        path=safe(root,folder+'/content-rejections.json');history=read(path) if path.is_file() else []
        payload=read(safe(root,b['outputs']['revision_patch_path']))
        key=sha((context['candidate_sha256']+digest(report)+str(safe(root,b['outputs']['revision_review_path']).stat().st_mtime_ns)).encode())
        if key not in history:history.append(key)
        save(path,history)
        guard.retry(root,'local-revision/'+b['task_id'],'agent_pl','；'.join(reasons))
        raise Retry('agent_pl','；'.join(reasons))
    receipt={'schema':1,'task_id':b['task_id'],'before_sha256':b['body_sha256'],'after_sha256':context['candidate_sha256'],
             'book_contract_sha256':b['book_contract_sha256'],'review_digest':digest(report),'patch_digest':context['patch_digest'],
             'changed_spans':len(context['edits']),'length':context['length'],'accepted':True,
             'expanded_review_digest':digest(expanded)}
    # Prepare bytes outside the database lock, then keep epoch verification,
    # final source validation, canonical replacement and receipt in one lock.
    p=safe(root,b['body_path'])
    import tempfile
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
            temporary=Path(f.name);f.write(context['candidate'].encode());f.flush();os.fsync(f.fileno())
        with guard.publication(root,proof=execution_fence) as proof:
            bound(root,folder,accepted_sha=context['candidate_sha256'])
            editor_bound(root,b)
            if proof:receipt['execution_fence']=proof
            save(safe(root,folder+'/commit-intent.json'),receipt)
            if sha(p.read_bytes())!=context['candidate_sha256']:os.replace(temporary,p)
            save(safe(root,folder+'/receipt.json'),receipt)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
    return receipt


def verify_attempt(root,task):
    values=task.get('parameter_values') or {};folder=values.get('revision_dir','')
    if not folder:raise ValueError('局部修订完成记录缺少本任务凭据')
    receipt=read(safe(root,folder+'/receipt.json'));b=read(safe(root,folder+'/source-binding.json'))
    if receipt.get('task_id')!=task.get('task_id') or b['task_id']!=task.get('task_id'):
        raise ValueError('局部修订完成记录不属于本任务')
    if sha(safe(root,b['body_path']).read_bytes())!=receipt.get('after_sha256'):
        raise ValueError('局部修订发布后正文已有变化，不能沿用旧完成记录')
    b,source=bound(root,folder,accepted_sha=receipt['after_sha256']);context=compose(root,b,source)
    if b['outputs'].get('revision_review_model'):
        packet.verify(read(safe(root,b['outputs']['revision_review_model'])),context,'reviewer')
    report=read(safe(root,b['outputs']['revision_review_path']))
    if receipt.get('expanded_review_digest'):
        expanded=wire.expand(report,context)
        if (digest(expanded)!=receipt['expanded_review_digest'] or
                read(safe(root,b['outputs']['revision_review_expanded']))!=expanded):raise ValueError('展开审查凭据与实际回复不符')
    if (context!=read(safe(root,b['outputs']['revision_review_input'])) or digest(report)!=receipt['review_digest']
            or context['patch_digest']!=receipt['patch_digest'] or not isinstance(values.get('revision_review_result'),str)
            or json.loads(values['revision_review_result'])!=report or review_decision(report,context)):
        raise ValueError('局部修订完成凭据或复查与当前候选不符')
    return receipt


def writer_retry_had_review(task):
    writer=(task.get('node_states') or {}).get('agent_pl') or {}
    attempt=writer.get('attempt_count',0)
    interrupted=(writer.get('status') in {'failed','stopped','retry_waiting'}
                 or (task.get('status')=='stopped' and writer.get('status')=='running'))
    return (interrupted and type(attempt) is int
            and any(row.get('status')=='failed' and type(row.get('attempt_number')) is int
                    and row['attempt_number']<attempt
                    and '来自节点 script_local_commit' in str(row.get('error') or '')
                    for row in writer.get('attempt_history',[])))


def recover_rejected_review(root, task, *, interrupted_writer=False):
    """Carry genuine feedback into one fresh polish run without adopting the edits."""
    values=task.get('parameter_values') or {};nodes=task.get('node_states') or {}
    identity=task['task_id'];folder=f'cache/local-revision/{identity}'
    writer_verified=(writer_retry_had_review(task) if interrupted_writer
                     else nodes.get('agent_pl',{}).get('status')=='completed')
    allowed_status={'failed','stopped'} if interrupted_writer else {'failed'}
    if (task.get('status') not in allowed_status or not task.get('workspace_override')
            or Path(task['workspace_override']).resolve()!=Path(root).resolve()
            or values.get('revision_dir')!=folder or not writer_verified
            or nodes.get('agent_local_review',{}).get('status')!='completed' or safe(root,folder+'/receipt.json').exists()):
        raise ValueError('润色恢复缺少同一作品的独立复核记录')
    b,source=bound(root,folder);editor_bound(root,b)
    out=b['outputs']
    context=read(safe(root,out['revision_review_input']));report=read(safe(root,out['revision_review_path']))
    if interrupted_writer:
        historical=pending.recorded(root,b,digest)
        if not historical or historical['review_input']!=context or historical['raw_review']!=report:
            raise ValueError('润色恢复缺少已签名的待验收工作稿及复核')
    else:
        payload=read(safe(root,out['revision_patch_path']))
        if context['patch_digest']!=digest(payload) or json.loads(values.get('revision_patch_result','null'))!=payload:
            raise ValueError('润色补丁和原任务不一致')
    body=patches.apply_patches(source['source_body'],{'source_sha256':b['body_sha256'],'edits':context['edits']},
                               protected_phrases=source['book_contract']['protected_phrases'])
    if (b['task_id']!=identity or context.get('task_id')!=identity or context['source_body']!=source['source_body']
            or context['source_sha256']!=b['body_sha256'] or context['book_contract_sha256']!=b['book_contract_sha256']
            or context['candidate']!=body or context['candidate_sha256']!=sha(body.encode())
            or context['review_input_sha256']!=digest({k:v for k,v in context.items() if k!='review_input_sha256'})
            or json.loads(values.get('revision_review_result','null'))!=report):
        raise ValueError('润色补丁、候选或独立复核和原任务不一致')
    if out.get('revision_review_model'):
        packet.verify(read(safe(root,out['revision_review_model'])),context,'reviewer')
    reasons=review_decision(report,context)
    if not reasons:
        raise ValueError('没有需要继续处理的独立润色意见')
    retained=retained_feedback_sources(root,b['state']['author_feedback_file'])
    text=('# 上一次润色的独立复核意见\n\n'+'\n'.join('- '+item for item in dict.fromkeys(reasons))+
          '\n\n以当前已发布正文为底稿，集中解决有原文依据的问题。保留作者的篇幅、人物声线、叙述权限和情节范围，'
          '提交必要的局部补丁并重新接受独立复核。\n')
    relative=f"quality/repairs/{b['chapter_number']}/polish-{identity}/instructions.md"
    origin=relative.rsplit('/',1)[0]+'/automatic-origin.json'
    record={'origin':'automatic','feedback_sha256':sha(text.encode()),'retained_feedback_sources':retained,
            'source_task_id':identity,'source_body_sha256':b['body_sha256'],'review_digest':digest(report)}
    if safe(root,relative).is_file() or safe(root,origin).is_file():
        if safe(root,relative).read_text(encoding='utf-8')!=text or read(safe(root,origin))!=record:
            raise ValueError('润色续跑意见已有变化')
    else:
        def save_feedback(write):
            write(root,relative,text)
            write(root,origin,record)
        guards={path:value or '' for path,value in b['files'].items()}
        guards.update({row['source_id']:row['sha256'] for row in retained})
        guard.store().publish_views(root,save_feedback,lambda:guards)
    return relative


def verify_conflict(root,task,*,recover_evidence=False):
    values=task.get('parameter_values',{});folder=values.get('revision_dir','')
    if (not folder or task.get('status')!='failed' or task.get('node_states',{}).get('agent_pl',{}).get('status')!='completed'
            or not any(task.get('node_states',{}).get(k,{}).get('status')=='failed' for k in ('script_local_candidate','script_local_commit'))):
        raise ValueError('缺少原生重规划失败节点凭据')
    b,source=bound(root,folder);editor_bound(root,b)
    payload=read(safe(root,b['outputs']['revision_patch_path']))
    if b['task_id']!=task.get('task_id') or json.loads(values.get('revision_patch_result','null'))!=payload:
        raise ValueError('冲突补丁与本任务真实模型输出不一致')
    path=safe(root,folder+'/composition-conflict.json')
    if recover_evidence and not path.is_file():
        failed=(task.get('node_states') or {}).get('script_local_candidate') or {}
        if (failed.get('status')!='failed' or 'RETRY_STOP: evidence：重规划冲突缺少冻结原文和逐字证据' not in str(failed.get('error') or '')
                or set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['status']!='needs_replan' or payload['edits']!=[]):
            raise ValueError('未找到可恢复的原生重规划意见')
        save(path,conflict_packet(b,source,payload,payload['reason'],payload['evidence']))
    packet=read(path)
    measured=None;extras={}
    if 'review_digest' in packet:
        context=compose(root,b,source);report=read(safe(root,b['outputs']['revision_review_path']))
        if (task.get('node_states',{}).get('agent_local_review',{}).get('status')!='completed'
                or json.loads(values.get('revision_review_result','null'))!=report
                or len(read(safe(root,folder+'/content-rejections.json')))<2 or not review_decision(report,context)):
            raise ValueError('缺少连续实质返修的真实独立复查')
        measured=context['length'];reason='连续有原文依据的实质修订仍未解决问题，须回到阅读作用与篇幅规划。';quotes=[source['paragraphs'][0]['text']]
        extras={'review_digest':digest(report),'review_report':wire.expand(report,context),'rejected_candidate':context['candidate']}
    elif payload.get('status')=='needs_replan':
        if set(payload)!={'status','source_sha256','edits','reason','evidence'} or payload['edits']!=[]:raise ValueError('冲突响应不合规')
        reason,quotes=payload.get('reason'),payload.get('evidence')
    else:
        working=pending.current(root,b,digest)
        edits=pending.merge(source['source_body'],(working or {}).get('edits',[]),payload['edits'],patches)
        body=patches.apply_patches(source['source_body'],{'source_sha256':payload['source_sha256'],'edits':edits},protected_phrases=source['book_contract']['protected_phrases'])
        measured=quality.measurement(body.encode(),b['chapter_number'],b['bounds'])
        if measured['status'] not in ('short','long') or len(read(safe(root,folder+'/length-candidates.json')))<2:
            raise ValueError('没有连续篇幅冲突的实测来源')
        reason='内容修订连续出现篇幅冲突，应重新规划，不能用重复解释或动作填充。';quotes=[source['paragraphs'][0]['text']]
    if packet!={**conflict_packet(b,source,payload,reason,quotes,measured),**extras}:raise ValueError('冲突凭据已变化')
    return packet


def retry_feedback(root,folder,error):
    text=str(error)+'\n保持冻结原文和本书文风，仅纠正本轮问题。\n'
    if error.target!='agent_pl':return text
    binding,source=bound(root,folder)
    working=pending.current(root,binding,digest)
    if working:
        body=patches.apply_patches(source['source_body'],{'source_sha256':binding['body_sha256'],'edits':working['edits']})
        if sha(body.encode())!=working['candidate_sha256']:raise ValueError('待验收工作稿与保留补丁不一致')
        return text+'\n【待验收工作稿；有效改动由程序保留，未发布】\n'+json.dumps({
            'source_sha256':binding['body_sha256'],'retained_edits':working['edits'],
            'working_candidate_sha256':working['candidate_sha256'],
            'length_edit_budget':patches.length_edit_budget(quality.count_prose(body),binding['bounds'])},ensure_ascii=False,indent=2)+(
            '\n完整冻结原文见主输入；待验收工作稿等于该原文应用上述保留补丁。只提交剩余问题的新增或更新edits，仍以冻结原文的段落id、old、source_sha256为锚点。未重交的保留改动继续存在；'
            '更新保留改动须使用其完整old范围，不能部分重叠。不得把工作稿新句当old。原始事实与全部目标不变，最终仍完整复核所有累计改动。\n')
    text+=('本轮整组edits仍应用于冻结原文，不累计上一版候选的改动；整组净增删按以下源预算计算，'
           '不能只补候选剩余缺口。不把候选新增句当作old；若问题来自replacement，只修该replacement并完整重交补丁。\n'+
           json.dumps(patches.length_edit_budget(quality.count_prose(source['source_body']),binding['bounds']),ensure_ascii=False,indent=2)+'\n')
    patch_path=safe(root,binding['outputs']['revision_patch_path'])
    if patch_path.is_file():
        try:
            payload=read(patch_path)
            candidate=patches.apply_patches(source['source_body'],payload,protected_phrases=source['book_contract']['protected_phrases'])
        except (ValueError,KeyError,TypeError):pass
        else:
            diagnostic={'task_id':binding['task_id'],'source_sha256':binding['body_sha256'],
                'rejected_edits':payload['edits'],'candidate_length':quality.measurement(candidate.encode(),binding['chapter_number'],binding['bounds'])}
            save(safe(root,folder+'/last-rejected-patch.json'),diagnostic)
            return text+'\n【最新未通过补丁；未发布，仅用于修订其replacement】\n'+json.dumps(diagnostic,ensure_ascii=False,indent=2)
    path=safe(root,folder+'/review-input.json')
    if not path.is_file():return text
    context=read(path);binding=read(safe(root,folder+'/source-binding.json'))
    if context.get('task_id')!=binding['task_id'] or context.get('source_sha256')!=binding['body_sha256']:return text
    # A fresh writer session has no previous assistant turn. Hand back the
    # actual rejected edits, while keeping its source/input immutable.
    diagnostic={'source_sha256':binding['body_sha256'],'rejected_edits':context['edits']}
    return text+('\n【上一轮未通过补丁；仅供诊断，未发布、未采用为事实或写法】\n'+
        json.dumps(diagnostic,ensure_ascii=False,indent=2)+
        '\n继续对冻结原文提交新补丁，不能把这份候选当作新底稿；核对上一轮具体替换，避免再次写回同义说明。\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','writer-input','candidate','commit'])
    parser.add_argument('--chapter',default='0001');parser.add_argument('--target',default='');parser.add_argument('--dir',default='')
    parser.add_argument('--context',default='cache/story-support/context.md')
    parser.add_argument('--learning-context',default='learning/context/polish.md')
    parser.add_argument('--feedback',default=None)
    parser.add_argument('--dialogue-check',action='store_true')
    parser.add_argument('--dialogue-check-version',type=int,choices=(1,2,3,4),default=1)
    parser.add_argument('--critique',default='cache/sc/critique.json');parser.add_argument('--review-stdin',action='store_true')
    args=parser.parse_args();root=Path.cwd()
    try:
        if args.action=='prepare':out=prepare(root,args.chapter,os.environ.get('TASK_ID',''),args.target,args.context,args.learning_context,args.feedback,
                                             dialogue_check=args.dialogue_check,dialogue_check_version=args.dialogue_check_version)
        elif args.action=='writer-input':out=writer_input(root,args.dir,args.critique)
        elif args.action=='candidate':out=candidate(root,args.dir)
        else:commit(root,args.dir,sys.stdin.read() if args.review_stdin else None);out={}
    except Retry as exc:
        out=locations(args.dir);quality.atomic_text(safe(root,out['revision_feedback_file']),retry_feedback(root,args.dir,exc))
        print('<WF_REJECT_UPSTREAM target="'+exc.target+'">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>');return
    for key,value in out.items():print('<WF_VAR>'+key+':'+value+'</WF_VAR>')
    print(json.dumps({'status':'completed','action':args.action},ensure_ascii=False))


if __name__=='__main__':main()
