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


class Retry(ValueError):
    def __init__(self,target,reason):super().__init__(reason);self.target=target


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(data):return sha(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,data):quality.atomic_text(p,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def safe(root,path):return quality.safe_path(root,path)


def state(root):
    p=safe(root,'.novel-project.json');s=read(p) if p.is_file() else {};v=s.get('values',{})
    return {'chapter_number':str(v.get('chapter_number','0001')).zfill(4),
            'author_feedback_file':str(v.get('author_feedback_file') or '').strip(),
            'target_word_count':str(v.get('target_word_count') or '')}


def source_files(root,chapter,context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None):
    paths={safe(root,f'story/{chapter}/chapter.md')}
    for folder in ('meta','outline'):
        paths.update(p for p in safe(root,folder).rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for directory in safe(root,'story').glob('[0-9][0-9][0-9][0-9]'):
        if int(directory.name)<=int(chapter):
            paths.update(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.md','.json'))
    for name in (context_path,f'story/{chapter}/reader_report.json',f'planning/chapters/{chapter}.json',
                 'learning/active_context.md','learning/character_center/preferences.json','learning/prose_policy/policy.json'):
        paths.add(safe(root,name))
    if reference_path:paths.add(safe(root,reference_path))
    feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback:
        p=safe(root,feedback)
        if not p.is_file():raise ValueError('作者意见文件缺失，不能忽略后继续修订')
        paths.add(p)
    result={}
    for p in sorted(paths):
        relative=p.relative_to(Path(root).resolve()).as_posix();p=safe(root,relative)
        result[relative]=sha(p.read_bytes()) if p.is_file() else None
    return result


def locations(folder):
    return {'revision_dir':folder,'revision_source_file':folder+'/source.md','revision_source_input':folder+'/source-input.json',
            'revision_input':folder+'/editor-input.json','revision_patch_path':folder+'/patches.json',
            'revision_review_input':folder+'/review-input.json','revision_review_path':folder+'/review.json',
            'revision_feedback_file':folder+'/feedback.md'}


def prepare(root,chapter,task_id,target='',context_path='cache/story-support/context.md',reference_path='learning/context/polish.md',feedback_path=None):
    root=Path(root).resolve();chapter=quality.chapter_number(chapter)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}',task_id or ''):raise ValueError('局部修订缺少有效任务编号')
    frozen=book.freeze(root,task_id);folder=f'cache/local-revision/{task_id}';out=locations(folder)
    body_path=f'story/{chapter}/chapter.md';raw=safe(root,body_path).read_bytes();body=raw.decode('utf-8')
    if not body.strip():raise ValueError('局部修订需要非空原文')
    bounds=quality.resolve_target(root,target)
    report_path=safe(root,f'story/{chapter}/reader_report.json');report=read(report_path) if report_path.is_file() else None
    if report and report.get('body_sha256')!=sha(raw):report=None
    shared=safe(root,context_path);feedback=state(root)['author_feedback_file'] if feedback_path is None else feedback_path
    if feedback and not safe(root,feedback).is_file():raise ValueError('本次作者意见文件缺失，不能忽略后继续修订')
    confirmed=shared.read_text(encoding='utf-8-sig') if shared.is_file() else ''
    for title,path in (('本书已确认人物对白适配','meta/character_voice_adaptations.md'),('本次已采用抽象参考',reference_path)):
        if path and safe(root,path).is_file():confirmed+='\n\n## '+title+'\n'+book.policy().effective_text(root,path)
    source={'source_body':body,'source_sha256':sha(raw),'paragraphs':patches.paragraphs(body),
            'book_contract':frozen['contract'],'book_contract_sha256':frozen['sha256'],
            'author_feedback':safe(root,feedback).read_text(encoding='utf-8-sig') if feedback else '',
            'confirmed_context':confirmed,
            'reader_report':report,'length':quality.measurement(raw,chapter,bounds)}
    binding={'schema':1,'task_id':task_id,'chapter_number':chapter,'body_path':body_path,'body_sha256':sha(raw),
             'book_contract_sha256':frozen['sha256'],'state':state(root),'context_path':context_path,'reference_path':reference_path,'feedback_path':feedback,
             'files':source_files(root,chapter,context_path,reference_path,feedback),
             'source_digest':digest(source),'bounds':bounds,'outputs':out}
    previous=safe(root,folder+'/source-binding.json')
    if previous.exists() and read(previous)!=binding:raise ValueError('同任务修订来源已有变化，请新建任务')
    save(safe(root,out['revision_source_input']),source);save(safe(root,out['revision_input']),source)
    quality.atomic_text(safe(root,out['revision_source_file']),body);save(previous,binding)
    p=safe(root,out['revision_feedback_file'])
    if not p.exists():quality.atomic_text(p,'')
    return out


def bound(root,folder,accepted_sha=None):
    b=read(safe(root,folder+'/source-binding.json'));source=read(safe(root,b['outputs']['revision_source_input']))
    if digest(source)!=b['source_digest'] or sha(safe(root,b['outputs']['revision_source_file']).read_bytes())!=b['body_sha256']:
        raise ValueError('冻结原文或本书规则上下文已变化，未发布')
    if state(root)!=b['state'] or book.digest(book.resolve(root))!=b['book_contract_sha256']:
        raise ValueError('本书规则、作者意见选择或目标已变化，未发布')
    current=source_files(root,b['chapter_number'],b['context_path'],b['reference_path'],b['feedback_path'])
    if accepted_sha and current.get(b['body_path'])==accepted_sha:current[b['body_path']]=b['body_sha256']
    if current!=b['files']:raise ValueError('正文、作者意见或已确认资料已有变化，未发布')
    book.freeze(root,b['task_id'])
    return b,source


def goals(source,critique):
    rows=[]
    for row in (source.get('reader_report') or {}).get('issues',[]):
        if row.get('priority') in ('medium','high'):
            rows.append({'id':'reader-'+str(row.get('id') or len(rows)),'goal':row.get('goal',''),'excerpts':row.get('excerpts',[])})
    for i in critique.get('blocking_issues',[]):
        row=critique['issues'][i];rows.append({'id':f'critic-{i}','goal':row.get('suggestion') or row.get('description',''),
            'excerpts':row.get('evidence',[])})
    return rows


def writer_input(root,folder,critique_path):
    b,source=bound(root,folder);p=safe(root,critique_path);critique=read(p)
    data={**source,'critique':critique,'goals':goals(source,critique)}
    receipt={'critique_path':critique_path,'critique_sha256':sha(p.read_bytes()),'input_sha256':digest(data)}
    prior=safe(root,folder+'/editor-binding.json')
    if prior.exists() and read(prior)!=receipt:raise ValueError('本轮自审或编辑输入已有变化，请新建任务')
    save(safe(root,b['outputs']['revision_input']),data);save(prior,receipt)
    return b['outputs']


def editor_bound(root,b):
    folder=b['outputs']['revision_dir'];receipt=read(safe(root,folder+'/editor-binding.json'))
    data=read(safe(root,b['outputs']['revision_input']))
    if digest(data)!=receipt['input_sha256'] or sha(safe(root,receipt['critique_path']).read_bytes())!=receipt['critique_sha256']:
        raise ValueError('自审或冻结编辑输入已有变化，未发布')
    return data


def compose(root,b,source):
    data=editor_bound(root,b);payload=read(safe(root,b['outputs']['revision_patch_path']))
    candidate=patches.apply_patches(source['source_body'],payload,protected_phrases=source['book_contract']['protected_phrases'])
    measured=quality.measurement(candidate.encode(),b['chapter_number'],b['bounds'])
    if measured['status'] not in ('pass','unconfigured'):raise ValueError('候选篇幅未达作者目标：'+json.dumps(measured,ensure_ascii=False))
    context={'task_id':b['task_id'],'source_body':source['source_body'],'source_sha256':b['body_sha256'],'candidate':candidate,
             'candidate_sha256':sha(candidate.encode()),'book_contract':source['book_contract'],
             'book_contract_sha256':b['book_contract_sha256'],'confirmed_context':source['confirmed_context'],
             'author_feedback':source['author_feedback'],'goals':data['goals'],'edits':payload['edits'],
             'patch_digest':digest(payload),'evidence_catalog':evidence.catalog(candidate),'length':measured}
    context['review_input_sha256']=digest(context)
    return context


def candidate(root,folder):
    b,source=bound(root,folder)
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:raise Retry('agent_pl',str(exc)) from exc
    save(safe(root,b['outputs']['revision_review_input']),context)
    return b['outputs']


def review_decision(report,context):
    for key in ('candidate_sha256','book_contract_sha256','review_input_sha256'):
        if report.get(key)!=context[key]:raise ValueError('独立复查与当前候选或本书规则不匹配：'+key)
    report=evidence.resolve_report(report,context['candidate'])
    if type(report.get('compatible')) is not bool or not isinstance(report.get('issues'),list):raise ValueError('独立复查缺少事实结论')
    reasons=[];source=context['source_body']+'\n'+context['confirmed_context']+'\n'+context['author_feedback']+'\n'+book.prompt(context['book_contract'])
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
    return reasons


def commit(root,folder,expected_review):
    b=read(safe(root,folder+'/source-binding.json'));saved=read(safe(root,b['outputs']['revision_review_input']))
    b,source=bound(root,folder,accepted_sha=saved['candidate_sha256'])
    editor_bound(root,b)
    try:context=compose(root,b,source)
    except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:raise Retry('agent_pl',str(exc)) from exc
    if context!=saved:
        # The host retries the writer without resetting intermediate completed
        # nodes. Rebuild here and force a fresh reviewer before publication.
        if saved.get('review_input_sha256')!=digest({k:v for k,v in saved.items() if k!='review_input_sha256'}):
            raise ValueError('冻结复查输入已有变化，未发布')
        save(safe(root,b['outputs']['revision_review_input']),context)
        raise Retry('agent_local_review','候选补丁已有变化，已重建复查输入；请独立复查新候选，旧报告不能发布')
    report=read(safe(root,b['outputs']['revision_review_path']))
    try:
        if not isinstance(expected_review,str) or json.loads(expected_review)!=report:raise ValueError('复查文件与本任务实际模型输出不一致')
        reasons=review_decision(report,context)
    except (ValueError,KeyError,TypeError) as exc:raise Retry('agent_local_review',str(exc)) from exc
    if reasons:raise Retry('agent_pl','；'.join(reasons))
    receipt={'schema':1,'task_id':b['task_id'],'before_sha256':b['body_sha256'],'after_sha256':context['candidate_sha256'],
             'book_contract_sha256':b['book_contract_sha256'],'review_digest':digest(report),'patch_digest':context['patch_digest'],
             'changed_spans':len(context['edits']),'length':context['length'],'accepted':True}
    save(safe(root,folder+'/commit-intent.json'),receipt)
    current=safe(root,b['body_path']).read_bytes()
    if sha(current)!=context['candidate_sha256']:
        # Validate once more after the temporary file is fully written.
        p=safe(root,b['body_path'])
        import tempfile
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
                temporary=Path(f.name);f.write(context['candidate'].encode());f.flush()
            bound(root,folder);os.replace(temporary,p)
        finally:
            if temporary is not None and temporary.exists():temporary.unlink()
    save(safe(root,folder+'/receipt.json'),receipt)
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
    report=read(safe(root,b['outputs']['revision_review_path']))
    if (context!=read(safe(root,b['outputs']['revision_review_input'])) or digest(report)!=receipt['review_digest']
            or context['patch_digest']!=receipt['patch_digest'] or not isinstance(values.get('revision_review_result'),str)
            or json.loads(values['revision_review_result'])!=report or review_decision(report,context)):
        raise ValueError('局部修订完成凭据或复查与当前候选不符')
    return receipt


def retry_feedback(root,folder,error):
    text=str(error)+'\n保持冻结原文和本书文风，仅纠正本轮问题。\n'
    if error.target!='agent_pl':return text
    path=safe(root,folder+'/review-input.json')
    if not path.is_file():return text
    context=read(path);binding=read(safe(root,folder+'/source-binding.json'))
    if context.get('task_id')!=binding['task_id'] or context.get('source_sha256')!=binding['body_sha256']:return text
    # A fresh writer session has no previous assistant turn. Hand back the
    # actual rejected edits, while keeping its source/input immutable.
    packet={'source_sha256':binding['body_sha256'],'rejected_edits':context['edits']}
    return text+('\n【上一轮未通过补丁；仅供诊断，未发布、未采用为事实或写法】\n'+
        json.dumps(packet,ensure_ascii=False,indent=2)+
        '\n继续对冻结原文提交新补丁，不能把这份候选当作新底稿；核对上一轮具体替换，避免再次写回同义说明。\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','writer-input','candidate','commit'])
    parser.add_argument('--chapter',default='0001');parser.add_argument('--target',default='');parser.add_argument('--dir',default='')
    parser.add_argument('--context',default='cache/story-support/context.md')
    parser.add_argument('--learning-context',default='learning/context/polish.md')
    parser.add_argument('--feedback',default=None)
    parser.add_argument('--critique',default='cache/sc/critique.json');parser.add_argument('--review-stdin',action='store_true')
    args=parser.parse_args();root=Path.cwd()
    try:
        if args.action=='prepare':out=prepare(root,args.chapter,os.environ.get('TASK_ID',''),args.target,args.context,args.learning_context,args.feedback)
        elif args.action=='writer-input':out=writer_input(root,args.dir,args.critique)
        elif args.action=='candidate':out=candidate(root,args.dir)
        else:commit(root,args.dir,sys.stdin.read() if args.review_stdin else None);out={}
    except Retry as exc:
        out=locations(args.dir);quality.atomic_text(safe(root,out['revision_feedback_file']),retry_feedback(root,args.dir,exc))
        print('<WF_REJECT_UPSTREAM target="'+exc.target+'">'+escape(str(exc))+'</WF_REJECT_UPSTREAM>');return
    for key,value in out.items():print('<WF_VAR>'+key+':'+value+'</WF_VAR>')
    print(json.dumps({'status':'completed','action':args.action},ensure_ascii=False))


if __name__=='__main__':main()
